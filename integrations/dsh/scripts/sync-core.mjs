#!/usr/bin/env node
/**
 * Sync the repository core/ snapshot into assets/core/ so the published or
 * locally installed plugin package is fully self-contained.
 *
 * Usage:
 *   node integrations/dsh/scripts/sync-core.mjs          # (re)write the snapshot
 *   node integrations/dsh/scripts/sync-core.mjs --check  # verify only, write nothing
 *
 * Run the plain form after any change to core/ and commit the result; CI
 * refuses a stale snapshot via scripts/verify.mjs. --check (or --dry-run)
 * only compares content hashes and exits non-zero when the snapshot is stale.
 */
import { cpSync, mkdirSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { ENTRIES, snapshotFiles } from './snapshot.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const repoCore = join(here, '..', '..', '..', 'core')
const target = join(here, '..', 'assets', 'core')

const USAGE = 'usage: node integrations/dsh/scripts/sync-core.mjs [--check]'

const args = process.argv.slice(2)
if (args.includes('--help') || args.includes('-h')) {
  console.log(USAGE)
  process.exit(0)
}
const checkOnly = args.includes('--check') || args.includes('--dry-run')
const unknown = args.filter((arg) => !['--check', '--dry-run'].includes(arg))
if (unknown.length > 0) {
  console.error(`sync-core: unknown argument(s): ${unknown.join(' ')}`)
  console.error(USAGE)
  process.exit(2)
}

if (checkOnly) {
  const repoFiles = snapshotFiles(repoCore)
  const assetFiles = snapshotFiles(target)
  const stale = []
  for (const [file, digest] of repoFiles) {
    if (assetFiles.get(file) !== digest) stale.push(file)
  }
  for (const file of assetFiles.keys()) {
    if (!repoFiles.has(file)) stale.push(`${file} (only in assets)`)
  }
  if (stale.length > 0) {
    console.error(
      `stale: assets/core differs for: ${stale.slice(0, 10).join(', ')}${stale.length > 10 ? '…' : ''}`,
    )
    console.error('run: node integrations/dsh/scripts/sync-core.mjs')
    process.exit(1)
  }
  console.log(`in sync: assets/core matches repository core/ (${repoFiles.size} files)`)
  process.exit(0)
}

rmSync(target, { recursive: true, force: true })
mkdirSync(target, { recursive: true })
for (const entry of ENTRIES) {
  cpSync(join(repoCore, entry), join(target, entry), {
    recursive: true,
    filter: (source) => !source.includes('__pycache__') && !source.endsWith('.pyc'),
  })
}
console.log(`synced ${repoCore} -> ${target}`)
