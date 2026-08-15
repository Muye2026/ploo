#!/usr/bin/env node
/**
 * Offline smoke verification for the dsh-ploo bundle plugin.
 *
 * Checks, in order:
 *  1. package.json and cordis.patch.yml bundle shape.
 *  2. assets/core is byte-identical to the repository core/ snapshot.
 *  3. lib modules parse (node --check).
 *  4. apply() against mock ctx.tools / ctx.skills registries registers the
 *     runtime skill and every ploo_* tool.
 *  5. If python3 is available, executes ploo_validate against the golden
 *     design pack for an end-to-end check.
 *
 * Exits non-zero on the first failure; safe to run with no DSH installation.
 */
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const pkgDir = join(here, '..')
const repoRoot = join(here, '..', '..', '..')

let failures = 0
const ok = (message) => console.log(`ok: ${message}`)
const fail = (message) => {
  failures += 1
  console.error(`FAIL: ${message}`)
}

// 1. package + patch shape -------------------------------------------------
const pkg = JSON.parse(readFileSync(join(pkgDir, 'package.json'), 'utf8'))
if (pkg.name !== 'dsh-ploo') fail(`package name is ${pkg.name}`)
if (pkg.type !== 'module') fail('package type must be module')
if (pkg.main !== 'lib/index.js') fail('main must be lib/index.js')
if (!pkg.exports || !pkg.exports['./cordis.patch.yml']) fail('exports must expose ./cordis.patch.yml')
if (!pkg.dsh || !pkg.dsh.bundle || pkg.dsh.bundle.patch !== './cordis.patch.yml') {
  fail('dsh.bundle.patch must point at ./cordis.patch.yml')
}
const patch = readFileSync(join(pkgDir, 'cordis.patch.yml'), 'utf8')
if (!patch.includes('name: dsh-ploo')) fail('cordis.patch.yml must name dsh-ploo')
if (!patch.includes('insert:')) fail('cordis.patch.yml must contain an insert row')
if (failures === 0) ok('package.json and cordis.patch.yml bundle shape')

// 2. asset sync ------------------------------------------------------------
const SYNCED = ['SKILL.md', 'agents', 'references', 'schemas', 'scripts', 'evals']
const hashTree = (root) => {
  const files = new Map()
  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry)
      if (entry === '__pycache__' || entry.endsWith('.pyc')) continue
      const stat = statSync(full)
      if (stat.isDirectory()) walk(full)
      else {
        const digest = createHash('sha256').update(readFileSync(full)).digest('hex')
        files.set(relative(root, full), digest)
      }
    }
  }
  walk(root)
  return files
}
{
  const repoFiles = new Map()
  const assetFiles = new Map()
  for (const entry of SYNCED) {
    const repoPath = join(repoRoot, 'core', entry)
    const assetPath = join(pkgDir, 'assets', 'core', entry)
    if (!existsSync(assetPath)) {
      fail(`assets/core/${entry} missing; run node integrations/dsh/scripts/sync-core.mjs`)
      continue
    }
    const sub = statSync(repoPath).isDirectory() ? hashTree : (p) => new Map([[entry, createHash('sha256').update(readFileSync(p)).digest('hex')]])
    for (const [k, v] of sub(repoPath)) repoFiles.set(entry === k ? k : join(entry, k), v)
    for (const [k, v] of sub(assetPath)) assetFiles.set(entry === k ? k : join(entry, k), v)
  }
  const stale = []
  for (const [file, digest] of repoFiles) {
    if (assetFiles.get(file) !== digest) stale.push(file)
  }
  for (const file of assetFiles.keys()) {
    if (!repoFiles.has(file)) stale.push(`${file} (only in assets)`)
  }
  if (stale.length > 0) {
    fail(`assets/core is stale for: ${stale.slice(0, 5).join(', ')}${stale.length > 5 ? '…' : ''}; run node integrations/dsh/scripts/sync-core.mjs`)
  } else {
    ok(`assets/core snapshot matches repository core/ (${repoFiles.size} files)`)
  }
}

// 3. lib parses ------------------------------------------------------------
try {
  for (const file of readdirSync(join(pkgDir, 'lib'))) {
    if (file.endsWith('.js')) {
      execFileSync(process.execPath, ['--check', join(pkgDir, 'lib', file)])
    }
  }
  ok('lib modules parse')
} catch (error) {
  fail(`lib parse: ${error.message}`)
}

// 4. mock apply ------------------------------------------------------------
let registered = null
try {
  const tools = new Map()
  const skills = new Map()
  const ctx = {
    tools: {
      register(definition) {
        tools.set(definition.name, definition)
        return () => tools.delete(definition.name)
      },
    },
    skills: {
      register(definition) {
        skills.set(definition.name, definition)
        return () => skills.delete(definition.name)
      },
    },
  }
  const plugin = await import(join(pkgDir, 'lib', 'index.js'))
  if (plugin.name !== 'ploo') fail(`plugin name is ${plugin.name}`)
  for (const key of ['tools', 'skills']) {
    if (!plugin.inject.includes(key)) fail(`inject must include ${key}`)
  }
  plugin.apply(ctx, {})
  const expectedTools = [
    'ploo_validate',
    'ploo_validate_bundle',
    'ploo_run_state',
    'ploo_migrate',
    'ploo_normalize',
    'ploo_review_matrix',
    'ploo_handoff',
    'ploo_evaluate_behavior',
  ]
  for (const toolName of expectedTools) {
    const def = tools.get(toolName)
    if (!def) {
      fail(`tool not registered: ${toolName}`)
      continue
    }
    if (!def.output || !def.output.schema || typeof def.execute !== 'function') {
      fail(`tool ${toolName} lacks output declaration or execute`)
    }
    // The registry rejects type arrays in schemas; mirror that invariant here.
    const badTypes = []
    const walkSchema = (node, trail) => {
      if (node && typeof node === 'object' && !Array.isArray(node)) {
        if ('type' in node && typeof node.type !== 'string') badTypes.push(trail)
        for (const [key, value] of Object.entries(node)) walkSchema(value, `${trail}.${key}`)
      } else if (Array.isArray(node)) {
        node.forEach((value, index) => walkSchema(value, `${trail}[${index}]`))
      }
    }
    walkSchema(def.output.schema, toolName)
    if (badTypes.length > 0) fail(`tool ${toolName} uses type arrays at ${badTypes.join(', ')}`)
  }
  const skill = skills.get('ploo')
  if (!skill) {
    fail('runtime skill ploo not registered')
  } else {
    if (skill.source !== 'runtime') fail('skill source must be runtime')
    if (!skill.resourceBase || skill.resourceBase.kind !== 'directory') fail('skill resourceBase must be a directory')
    if (typeof skill.content !== 'string' || skill.content.length < 500) fail('skill content looks too short')
    if (!skill.content.includes('waiting_user_decision')) fail('skill content must contain the core workflow')
  }
  registered = { tools, skills }
  if (failures === 0) ok(`mock apply registered 1 skill and ${tools.size} tools`)
} catch (error) {
  fail(`mock apply: ${error.message}`)
}

// 5. end-to-end tool execution (optional) ----------------------------------
try {
  execFileSync('python3', ['--version'], { stdio: 'ignore' })
  const def = registered && registered.tools.get('ploo_validate')
  const golden = join(repoRoot, 'examples', 'v2-orchestrator-demo', 'design-pack.v2.json')
  const exec = { signal: new AbortController().signal }
  const result = await def.execute({ kind: 'design-pack', path: golden }, exec)
  if (result.exitCode !== 0) fail(`ploo_validate exit code ${result.exitCode}: ${result.stderr}`)
  else ok('ploo_validate executed against the golden design pack')
} catch (error) {
  console.log(`skip: end-to-end execution (${error.message})`)
}

if (failures > 0) {
  console.error(`\n${failures} check(s) failed`)
  process.exit(1)
}
console.log('\nall checks passed')
