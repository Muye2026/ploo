# Upgrading Product Loop

V2 keeps the planning layer usable without Fusion 360 MCP, EasyEDA, or image/video plugins. It adds explicit route decisions, strict V2 artifacts, dependency-aware invalidation, and optional provider adapters. V2.1 adds cross-Agent installation guidance and does not change the V2 artifact schemas. Updating the skill does not modify a CAD/EDA document or migrate project data automatically.

## 0. V2.1 to V2.2: repository layout change

V2.2 reorganizes the repository into `core/` plus `integrations/`. The installable skill moved from the inner `product-loop/` directory to `core/`; the workflow, contracts, and `schema_version: 2.0` artifacts are unchanged.

If the installed skill is a symlink into a repository clone, re-point it after `git pull --ff-only`:

```bash
ln -sfn /path/to/product-loop/core "$HOME/.agents/skills/product-loop"
```

For copied installs, replace the destination with the new `core/` directory instead of the old inner directory. New host integrations (terminal CLI, DeepSeek Harness, WorkBuddy) are documented in [AGENT_PORTABILITY.md](AGENT_PORTABILITY.md) and [integrations/](integrations/).

## 1. V2 to V2.1

If the installed skill is a symlink to this repository's inner `core/` directory, `git pull --ff-only` is enough. Valid V2 files remain `schema_version: 2.0` and need no data migration.

Current Codex documentation recommends `~/.agents/skills/product-loop` for personal discovery. Older Product Loop releases documented `${CODEX_HOME:-$HOME/.codex}/skills/product-loop`. If the old location is still discovered, it can remain in place. To migrate discovery paths without touching the repository or run data:

1. Confirm the old installation target with `readlink`.
2. Create a link under `~/.agents/skills` to the same inner repository directory.
3. Start a new Codex task and run the V2.1 smoke test in [AGENT_PORTABILITY.md](AGENT_PORTABILITY.md).
4. Remove or disable the legacy discovery entry only after the new entry is confirmed, so duplicate skills do not remain visible.

Claude Code, Cursor, OpenClaw, and manual host setup are documented in [AGENT_PORTABILITY.md](AGENT_PORTABILITY.md).

## 1. Identify the installation type

```bash
for skill_dir in \
  "$HOME/.agents/skills/product-loop" \
  "${CODEX_HOME:-$HOME/.codex}/skills/product-loop"
do
  if [ -e "$skill_dir" ] || [ -L "$skill_dir" ]; then
    ls -ld "$skill_dir"
    readlink "$skill_dir" || true
  fi
done
```

- If `readlink` prints the repository's inner `core/` path, this is a symlink install.
- If it prints nothing and `SKILL.md` is inside the directory, this is usually a copied install.
- If another installer manages the directory, use its update flow after making a backup. Do not copy a second `product-loop/` directory inside the existing one.

## 2A. Update a symlink install

Pull the repository that the link points to:

```bash
git -C /path/to/product-loop pull --ff-only
```

No reinstall is needed. The installed skill points at the updated files. Start a new Codex task or restart the host to reload skill discovery.

## 2B. Update a copied install

First update or freshly clone the public repository. Then move the old installed directory to a timestamped backup and copy the inner V2.1 directory into its place. Set `skills_root` to the host location you are actually updating; this example preserves the legacy Codex V1 path:

```bash
git -C /path/to/product-loop pull --ff-only
skills_root="${CODEX_HOME:-$HOME/.codex}/skills"
backup="$skills_root/product-loop.v1-backup-$(date +%Y%m%d-%H%M%S)"
mv "$skills_root/product-loop" "$backup"
cp -R /path/to/product-loop/core "$skills_root/product-loop"
```

If the repository is not already present, clone it first:

```bash
git clone https://github.com/Muye2026/product-loop.git /path/to/product-loop
```

Installers that refuse to overwrite an existing skill should be handled the same way: back up or rename the existing destination, install V2 from the same GitHub source, verify it, and only then remove the backup.

## 3. Verify the update

From the repository root:

```bash
python3 -m unittest discover -s tests -v
python3 core/scripts/migrate_v1_to_v2.py --help
```

Confirm the installed entrypoint exists:

```bash
test -f "${CODEX_HOME:-$HOME/.codex}/skills/product-loop/SKILL.md"
test -f "${CODEX_HOME:-$HOME/.codex}/skills/product-loop/scripts/migrate_v1_to_v2.py"
grep -q "waiting_user_decision" "${CODEX_HOME:-$HOME/.codex}/skills/product-loop/SKILL.md"
```

V2.1 discovery should present four independent route choices and state that recommendations are not authorization. It must also work in planning-only mode when no optional provider is installed.

## 4. Migrate V1 run data only when needed

The skill files and project/run data are separate. Existing briefs and V1 Design Packs are not rewritten during installation. The recommended command creates a new directory containing separate standard V2 files plus a migration manifest:

```bash
python3 core/scripts/migrate_v1_to_v2.py \
  /path/to/design-pack.v1.json \
  --output-dir /path/to/v2-migration
```

The new directory contains `design-pack.v2.json`, `run-state.v2.json`, and `migration-bundle.v2.json`. To keep only the nested compatibility bundle, use the legacy two-positional-path form:

```bash
python3 core/scripts/migrate_v1_to_v2.py \
  /path/to/design-pack.v1.json \
  /path/to/migration-bundle.v2.json
```

Both forms refuse to overwrite an existing file or directory and reject identical input/output paths. Writes use a new-file atomic publish path. By default, provenance records only the input filename; use `--source-ref LOGICAL_REFERENCE` if the project has a portable source identifier.

Validate the split outputs before using them:

```bash
python3 core/scripts/validate_v2.py design-pack /path/to/v2-migration/design-pack.v2.json
python3 core/scripts/validate_v2.py run-state /path/to/v2-migration/run-state.v2.json
```

Migration is deliberately conservative:

- `checkpointed` becomes `confirmation_policy: material_decisions` with stepwise cadence.
- `auto` becomes continuous cadence only inside a route the user later approves.
- Old execution modes and route hints do not authorize V2 execution.
- All missing routes stay `null`, and the run enters `waiting_user_decision`.
- Legacy component claims and migration evidence remain unverified until checked.
- Fusion, EasyEDA, image, and video capability reports start unknown and are probed only if relevant.

Keep the original V1 file until the migrated bundle has been reviewed and the user has explicitly selected the four V2 routes.

## 5. Compatibility and rollback

V2.1 changes distribution guidance, not the V2 JSON contracts. Do not rewrite a valid V2 run merely to label it V2.1.

| V1 behavior | V2 behavior |
| --- | --- |
| One broad execution mode | Independent visual, mechanical, schematic, and PCB routes |
| `auto` could be read broadly | Cadence only; it grants no design or route authority |
| Missing provider could imply a fallback | The user chooses retry, guided, hybrid, handoff, skip, or pause |
| Loose state/artifact fields | Strict V2 schemas and hash-bound dependencies |
| Provider-specific workflow | Provider-neutral core with optional adapters |

To roll back the installed skill, move the V2 directory aside and restore the timestamped V1 backup. This does not roll back V2 run data or external CAD/EDA changes. Provider writes require their own recorded checkpoint and recovery path.

## Security note

Before publishing an issue, fixture, or migration sample, remove `.env` files, API tokens, passwords, certificates, machine paths, real account data, private project names, and live document identifiers. Public examples in this repository use synthetic data only.
