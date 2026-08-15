import { loadSkillDefinition, resolveCoreDir } from './core.js'
import { buildTools } from './tools.js'

const name = 'ploo'
const inject = ['tools', 'skills']

/**
 * DeepSeek Harness bundle plugin for Ploo.
 *
 * Registers the ploo skill as a runtime skill (no filesystem skill
 * directory required) and the ploo_* tools that wrap the stdlib-only core
 * scripts. `config.coreDir` may point at a live repository checkout; the
 * bundled assets/core snapshot is the default execution target.
 */
function apply(ctx, config = {}) {
  const coreDir = resolveCoreDir(config)
  ctx.skills.register(loadSkillDefinition(coreDir))
  const pythonPath = config && config.pythonPath ? String(config.pythonPath) : 'python3'
  for (const definition of buildTools({ coreDir, pythonPath })) {
    ctx.tools.register(definition)
  }
}

export { apply, inject, name }
