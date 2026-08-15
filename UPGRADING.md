# Upgrading Ploo

Updating the skill never modifies CAD/EDA documents or migrates project data automatically. V3.0 renamed the project from product-loop to ploo: the skill is named `ploo`, the CLI package is `ploo-cli`, the DeepSeek Harness plugin is `dsh-ploo`, the WorkBuddy skill is `ploo`, and the repository is `Muye2026/ploo` (the old URL redirects). The workflow, contracts, and `schema_version: 2.0` artifacts are unchanged. Release history is in [CHANGELOG.md](CHANGELOG.md).

## 1. Rename and layout migration (pre-V3.0 installs)

Since V3.0, the installable unit is the repository's `core/` directory. Older releases installed an inner `ploo/` directory from a repository that was then named product-loop.

For symlink installs, re-point the link to `core/` and remove any old product-loop link:

```bash
ln -sfn /path/to/ploo/core "$HOME/.agents/skills/ploo"
rm -f "$HOME/.agents/skills/product-loop"
```

For copied installs, back up the old skill folder, install the new `core/` as `ploo`, verify the smoke test in [AGENT_PORTABILITY.md](AGENT_PORTABILITY.md), then remove the backup. Hosts that cache skill discovery need a new task or restart.

Older releases documented `${CODEX_HOME:-$HOME/.codex}/skills/ploo` for personal discovery; current hosts prefer `~/.agents/skills/ploo`. If the old location is still discovered it may remain, but do not keep two visible copies. To migrate discovery paths: confirm the old target with `readlink`, create a link under `~/.agents/skills` to the repository's `core/`, start a new task and pass the smoke test, and only then remove or disable the legacy entry.

## 2. Identify the installation type

```bash
for skill_dir in \
  "$HOME/.agents/skills/ploo" \
  "${CODEX_HOME:-$HOME/.codex}/skills/ploo"
do
  if [ -e "$skill_dir" ] || [ -L "$skill_dir" ]; then
    ls -ld "$skill_dir"
    readlink "$skill_dir" || true
  fi
done
```

- If `readlink` prints the repository's `core/` path, this is a symlink install.
- If it prints nothing and `SKILL.md` is inside the directory, this is usually a copied install.
- If another installer manages the directory, use its update flow after making a backup. Do not copy a second `ploo/` directory inside the existing one.

## 3A. Update a symlink install

Pull the repository that the link points to:

```bash
git -C /path/to/ploo pull --ff-only
```

No reinstall is needed. The installed skill points at the updated files. Start a new task or restart the host to reload skill discovery.

## 3B. Update a copied install

First update or freshly clone the repository, then move the old installed directory to a timestamped backup and copy the new `core/` directory into its place:

```bash
git -C /path/to/ploo pull --ff-only   # or: git clone https://github.com/Muye2026/ploo.git /path/to/ploo
skills_root="$HOME/.agents/skills"
backup="$skills_root/ploo.v3-backup-$(date +%Y%m%d-%H%M%S)"
mv "$skills_root/ploo" "$backup"
cp -R /path/to/ploo/core "$skills_root/ploo"
```

Installers that refuse to overwrite an existing skill should be handled the same way: back up or rename the existing destination, install from the same GitHub source, verify it, and only then remove the backup.

## 4. Verify the update

From the repository root:

```bash
python3 -m unittest discover -s tests -v
python3 core/scripts/migrate_v1_to_v2.py --help
```

Confirm the installed entrypoint exists (adjust `skills_root` if you use the legacy Codex path):

```bash
skills_root="$HOME/.agents/skills"
test -f "$skills_root/ploo/SKILL.md"
test -f "$skills_root/ploo/scripts/migrate_v1_to_v2.py"
grep -q "waiting_user_decision" "$skills_root/ploo/SKILL.md"
```

Discovery should present four independent route choices and state that recommendations are not authorization. It must also work in planning-only mode when no optional provider is installed.

## 5. Migrate V1 run data only when needed

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

Both forms refuse to overwrite an existing file or directory and reject identical input/output paths. Writes use an exclusive-create publish path. By default, provenance records only the input filename; use `--source-ref LOGICAL_REFERENCE` if the project has a portable source identifier.

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

## 6. Compatibility and rollback

V2.1 and later change distribution guidance, not the V2 JSON contracts. Do not rewrite a valid V2 run merely to relabel it.

| V1 behavior | V2 behavior |
| --- | --- |
| One broad execution mode | Independent visual, mechanical, schematic, and PCB routes |
| `auto` could be read broadly | Cadence only; it grants no design or route authority |
| Missing provider could imply a fallback | The user chooses retry, guided, hybrid, handoff, skip, or pause |
| Loose state/artifact fields | Strict V2 schemas and hash-bound dependencies |
| Provider-specific workflow | Provider-neutral core with optional adapters |

To roll back the installed skill, move the current directory aside and restore the timestamped backup. This does not roll back V2 run data or external CAD/EDA changes. Provider writes require their own recorded checkpoint and recovery path.

## Security note

Before publishing an issue, fixture, or migration sample, remove `.env` files, API tokens, passwords, certificates, machine paths, real account data, private project names, and live document identifiers. Public examples in this repository use synthetic data only.
