import { join } from 'node:path'

import { runPython } from './proc.js'

/** Canonical result schema shared by every ploo_* tool. */
const RESULT_SCHEMA = {
  type: 'object',
  properties: {
    exitCode: { type: 'integer', description: 'Process exit code; 0 means success.' },
    stdout: { type: 'string' },
    stderr: { type: 'string' },
    killedBySignal: { oneOf: [{ type: 'string' }, { type: 'null' }] },
    aborted: { type: 'boolean' },
  },
  required: ['exitCode', 'stdout', 'stderr', 'killedBySignal', 'aborted'],
  additionalProperties: false,
}

function renderResult(_args, value) {
  const parts = []
  if (value.stdout) parts.push(value.stdout.trimEnd())
  if (value.stderr) parts.push(`[stderr]\n${value.stderr.trimEnd()}`)
  const markers = []
  if (value.aborted) markers.push('aborted')
  if (value.killedBySignal) markers.push(`signal: ${value.killedBySignal}`)
  markers.push(`exit code: ${value.exitCode}`)
  parts.push(`[${markers.join(', ')}]`)
  return [{ type: 'text', text: parts.join('\n\n') }]
}

function requireString(args, field) {
  const value = args[field]
  if (typeof value !== 'string' || value.trim() === '') {
    throw new Error(`ploo: argument "${field}" must be a non-empty string`)
  }
  return value
}

function optionalString(args, field) {
  const value = args[field]
  if (value === undefined || value === null) return undefined
  return requireString(args, field)
}

function optionalStringArray(args, field) {
  const value = args[field]
  if (value === undefined || value === null) return []
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new Error(`ploo: argument "${field}" must be an array of strings`)
  }
  return value
}

const PATH_HINT = 'Absolute path (or path relative to the current workspace).'

const ABS = (description) => ({ type: 'string', description: `${description} ${PATH_HINT}` })

/**
 * Build the ploo_* tool definitions. Definitions are raw ToolDefinition
 * objects (no external dependencies): the registry enforces the declared
 * output schema, and each body validates its own arguments before spawning
 * the matching stdlib-only core script.
 */
export function buildTools({ coreDir, pythonPath }) {
  const script = (file) => join(coreDir, 'scripts', file)
  const run = (file, args, exec) => runPython(pythonPath, [script(file), ...args], exec)

  const definitions = []

  definitions.push({
    name: 'ploo_validate',
    description:
      'Validate one Ploo V2 artifact (design-pack, electrical-pack, interface-control, or run-state) against its JSON schema. Read-only.',
    parameters: {
      type: 'object',
      properties: {
        kind: {
          type: 'string',
          enum: ['design-pack', 'electrical-pack', 'interface-control', 'run-state'],
          description: 'Artifact kind.',
        },
        path: ABS('Path to the V2 JSON document.'),
      },
      required: ['kind', 'path'],
      additionalProperties: false,
    },
    output: { schema: RESULT_SCHEMA, render: renderResult },
    timeoutMs: 120_000,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      return run('validate_v2.py', [requireString(args, 'kind'), requireString(args, 'path')], exec)
    },
  })

  definitions.push({
    name: 'ploo_validate_bundle',
    description:
      'Cross-document Ploo validation of the four V2 artifacts before a freeze or any execution. Read-only; required before crossing a freeze gate.',
    parameters: {
      type: 'object',
      properties: {
        runState: ABS('Path to run-state.v2.json.'),
        designPack: ABS('Path to design-pack.v2.json.'),
        electricalPack: ABS('Path to electrical-pack.v2.json.'),
        interfaceControl: ABS('Path to interface-control.v2.json.'),
        reviewResults: ABS('Optional path to a review-results document.'),
      },
      required: ['runState', 'designPack', 'electricalPack', 'interfaceControl'],
      additionalProperties: false,
    },
    output: { schema: RESULT_SCHEMA, render: renderResult },
    timeoutMs: 120_000,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const argv = [
        '--run-state',
        requireString(args, 'runState'),
        '--design-pack',
        requireString(args, 'designPack'),
        '--electrical-pack',
        requireString(args, 'electricalPack'),
        '--interface-control',
        requireString(args, 'interfaceControl'),
      ]
      const reviewResults = optionalString(args, 'reviewResults')
      if (reviewResults) argv.push('--review-results', reviewResults)
      return run('validate_bundle.py', argv, exec)
    },
  })

  definitions.push({
    name: 'ploo_run_state',
    description:
      'Inspect or update a Ploo run-state.v2.json: validate, resolve-routes, open-decision, resolve-decision, record-execution, change-route, or stale. Mutating actions write the output file you name; they never overwrite inputs.',
    parameters: {
      type: 'object',
      properties: {
        action: {
          type: 'string',
          enum: [
            'validate',
            'resolve-routes',
            'open-decision',
            'resolve-decision',
            'record-execution',
            'change-route',
            'stale',
          ],
          description: 'run-state action.',
        },
        input: ABS('Path to run-state.v2.json.'),
        output: ABS('Output path for mutating actions (must differ from input).'),
        args: {
          type: 'array',
          items: { type: 'string' },
          description:
            'Extra flags forwarded to the action, e.g. ["--track", "mechanical", "--decision-id", "..."] .',
        },
      },
      required: ['action', 'input'],
      additionalProperties: false,
    },
    output: { schema: RESULT_SCHEMA, render: renderResult },
    timeoutMs: 120_000,
    isConcurrencySafe: (args) => args && args.action === 'validate',
    async execute(args, exec) {
      const argv = [requireString(args, 'action'), requireString(args, 'input')]
      const output = optionalString(args, 'output')
      if (output) argv.push(output)
      argv.push(...optionalStringArray(args, 'args'))
      return run('manage_run_state.py', argv, exec)
    },
  })

  definitions.push({
    name: 'ploo_migrate',
    description:
      'Migrate a V1 Ploo design pack into V2 artifacts. Creates a new output directory (design-pack.v2.json, run-state.v2.json, migration-bundle.v2.json); never overwrites existing files.',
    parameters: {
      type: 'object',
      properties: {
        input: ABS('Path to the V1 design pack JSON.'),
        outputDir: ABS('New directory for the split V2 outputs.'),
        legacyOutput: ABS('Legacy single-file migration-bundle.v2.json output (alternative to outputDir).'),
        sourceRef: {
          type: 'string',
          description: 'Portable logical source identifier recorded in migration provenance.',
        },
      },
      required: ['input'],
      additionalProperties: false,
    },
    output: { schema: RESULT_SCHEMA, render: renderResult },
    timeoutMs: 120_000,
    isConcurrencySafe: () => false,
    async execute(args, exec) {
      const argv = [requireString(args, 'input')]
      const outputDir = optionalString(args, 'outputDir')
      const legacyOutput = optionalString(args, 'legacyOutput')
      if (outputDir && legacyOutput) {
        throw new Error('ploo: pass either outputDir or legacyOutput, not both')
      }
      if (outputDir) argv.push('--output-dir', outputDir)
      else if (legacyOutput) argv.push(legacyOutput)
      const sourceRef = optionalString(args, 'sourceRef')
      if (sourceRef) argv.push('--source-ref', sourceRef)
      return run('migrate_v1_to_v2.py', argv, exec)
    },
  })

  definitions.push({
    name: 'ploo_normalize',
    description: 'Normalize a Ploo design pack into canonical form. Writes the output file you name.',
    parameters: {
      type: 'object',
      properties: {
        input: ABS('Path to the design pack JSON.'),
        output: ABS('Output path for the normalized design pack.'),
      },
      required: ['input', 'output'],
      additionalProperties: false,
    },
    output: { schema: RESULT_SCHEMA, render: renderResult },
    timeoutMs: 120_000,
    isConcurrencySafe: () => false,
    async execute(args, exec) {
      return run('normalize_design_pack.py', [requireString(args, 'input'), requireString(args, 'output')], exec)
    },
  })

  definitions.push({
    name: 'ploo_review_matrix',
    description: 'Build a Ploo review matrix from review results. Writes the output file you name.',
    parameters: {
      type: 'object',
      properties: {
        input: ABS('Path to the review matrix input JSON.'),
        output: ABS('Output path for the review matrix.'),
        runState: ABS('Path to run-state.v2.json for binding.'),
        reviewResults: ABS('Path to the review-results document.'),
      },
      required: ['input', 'output'],
      additionalProperties: false,
    },
    output: { schema: RESULT_SCHEMA, render: renderResult },
    timeoutMs: 120_000,
    isConcurrencySafe: () => false,
    async execute(args, exec) {
      const argv = [requireString(args, 'input'), requireString(args, 'output')]
      const runState = optionalString(args, 'runState')
      if (runState) argv.push('--run-state', runState)
      const reviewResults = optionalString(args, 'reviewResults')
      if (reviewResults) argv.push('--review-results', reviewResults)
      return run('build_review_matrix.py', argv, exec)
    },
  })

  definitions.push({
    name: 'ploo_handoff',
    description:
      'Emit a Ploo handoff brief for spec or handoff routes. Writes the output file you name.',
    parameters: {
      type: 'object',
      properties: {
        input: ABS('Path to the handoff brief input JSON.'),
        output: ABS('Output path for the handoff brief.'),
        runState: ABS('Path to run-state.v2.json for binding.'),
        handoffData: ABS('Path to the handoff data JSON.'),
      },
      required: ['input', 'output'],
      additionalProperties: false,
    },
    output: { schema: RESULT_SCHEMA, render: renderResult },
    timeoutMs: 120_000,
    isConcurrencySafe: () => false,
    async execute(args, exec) {
      const argv = [requireString(args, 'input'), requireString(args, 'output')]
      const runState = optionalString(args, 'runState')
      if (runState) argv.push('--run-state', runState)
      const handoffData = optionalString(args, 'handoffData')
      if (handoffData) argv.push('--handoff-data', handoffData)
      return run('emit_handoff_brief.py', argv, exec)
    },
  })

  definitions.push({
    name: 'ploo_evaluate_behavior',
    description:
      'Score captured Ploo agent responses against the behavior contract cases. Read-only; fails when a safeguard is missing or a prohibited action appears.',
    parameters: {
      type: 'object',
      properties: {
        cases: ABS('Path to the behavior cases JSONL.'),
        responses: ABS('Path to the captured responses JSONL.'),
      },
      required: ['cases', 'responses'],
      additionalProperties: false,
    },
    output: { schema: RESULT_SCHEMA, render: renderResult },
    timeoutMs: 120_000,
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      return run(
        'evaluate_behavior_contracts.py',
        ['--cases', requireString(args, 'cases'), '--responses', requireString(args, 'responses')],
        exec,
      )
    },
  })

  return definitions
}
