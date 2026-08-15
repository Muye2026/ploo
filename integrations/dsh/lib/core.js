import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const PKG_ROOT = dirname(dirname(fileURLToPath(import.meta.url)))

/** Bundled snapshot of the repository's core/ directory (kept in sync by scripts/sync-core.mjs). */
export const BUNDLED_CORE = join(PKG_ROOT, 'assets', 'core')

/**
 * Resolve the core directory the plugin executes against.
 * `config.coreDir` points at a live checkout; the bundled snapshot is the default.
 */
export function resolveCoreDir(config = {}) {
  const cfg = config || {}
  if (cfg.coreDir) {
    const dir = String(cfg.coreDir)
    if (!existsSync(join(dir, 'scripts'))) {
      throw new Error(`dsh-product-loop: config.coreDir ${dir} does not contain scripts/`)
    }
    return dir
  }
  return BUNDLED_CORE
}

/**
 * Build the runtime skill registration from the resolved core directory.
 * The body keeps the verbatim SKILL.md instructions; a footer tells the agent
 * where references/, schemas/, scripts/, and evals/ live on disk.
 */
export function loadSkillDefinition(coreDir) {
  const skillPath = join(coreDir, 'SKILL.md')
  const raw = readFileSync(skillPath, 'utf8')
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/)
  let name = 'product-loop'
  let description =
    'Orchestrate a small hardware product from brief to evidence-backed design artifacts.'
  let body = raw
  if (match) {
    const frontmatter = match[1]
    body = match[2]
    const nameMatch = frontmatter.match(/^name:\s*(.+)$/m)
    const descMatch = frontmatter.match(/^description:\s*(.+)$/m)
    if (nameMatch) name = nameMatch[1].trim()
    if (descMatch) description = descMatch[1].trim()
  }
  const content = `${body.trimEnd()}

---

Harness runtime note: this skill is embedded by the dsh-product-loop plugin. The core files for this session live at:

    ${coreDir}

Resolve relative paths such as \`references/\`, \`schemas/\`, \`scripts/\`, and \`evals/\` against that directory. Prefer the ploo_* tools for validation, migration, run-state management, review, handoff, and behavior evaluation instead of invoking the scripts by hand.
`
  return {
    name,
    description,
    source: 'runtime',
    provider: 'product-loop',
    resourceBase: { kind: 'directory', path: coreDir },
    path: skillPath,
    content,
  }
}
