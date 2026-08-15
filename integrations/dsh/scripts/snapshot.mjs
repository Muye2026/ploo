/**
 * Shared snapshot helpers for the dsh-ploo bundle: the synced entries of the
 * repository core/ and a content-hash tree over them.
 *
 * Imported by sync-core.mjs (write/check) and verify.mjs (CI freshness
 * check), so the two scripts can never drift apart on what "the snapshot"
 * contains.
 */
import { createHash } from 'node:crypto'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

export const ENTRIES = ['SKILL.md', 'agents', 'references', 'schemas', 'scripts', 'evals']

export const hashTree = (root) => {
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

/** Map of relative path -> sha256 for exactly the synced entries under coreRoot. */
export const snapshotFiles = (coreRoot) => {
  const files = new Map()
  for (const entry of ENTRIES) {
    const full = join(coreRoot, entry)
    if (!existsSync(full)) continue
    const stat = statSync(full)
    const sub = stat.isDirectory()
      ? hashTree
      : (p) => new Map([[entry, createHash('sha256').update(readFileSync(p)).digest('hex')]])
    for (const [key, value] of sub(full)) files.set(entry === key ? key : join(entry, key), value)
  }
  return files
}
