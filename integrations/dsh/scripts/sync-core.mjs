#!/usr/bin/env node
/**
 * Sync the repository core/ snapshot into assets/core/ so the published or
 * locally installed plugin package is fully self-contained.
 *
 * Run this after any change to core/ and commit the result; CI refuses a
 * stale snapshot via scripts/verify.mjs.
 */
import { cpSync, mkdirSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repoCore = join(here, '..', '..', '..', 'core')
const target = join(here, '..', 'assets', 'core')

const ENTRIES = ['SKILL.md', 'agents', 'references', 'schemas', 'scripts', 'evals']

rmSync(target, { recursive: true, force: true })
mkdirSync(target, { recursive: true })
for (const entry of ENTRIES) {
  cpSync(join(repoCore, entry), join(target, entry), {
    recursive: true,
    filter: (source) => !source.includes('__pycache__') && !source.endsWith('.pyc'),
  })
}
console.log(`synced ${repoCore} -> ${target}`)
