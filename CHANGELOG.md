# Changelog

## V3.0 — 2026-08-15

- Renamed the project from product-loop to ploo: skill name, CLI package (`ploo-cli`), DeepSeek Harness plugin (`dsh-ploo`), WorkBuddy skill, documentation, and the GitHub repository (`Muye2026/ploo`; the old URL redirects).
- Updated the golden bundle's contract hash chain after the rename. Artifact contracts remain `schema_version: 2.0`; no run-data migration is required.

## V2.2 — 2026-08-15

- Restructured the repository into a single `core/` skill plus thin host adapters under `integrations/`; the inner `ploo/` directory is now `core/`.
- Added the `ploo` terminal CLI (`integrations/cli`), a stdlib-only dispatcher over the core scripts.
- Added the DeepSeek Harness bundle plugin (`integrations/dsh`): a runtime-registered skill, eight `ploo_*` host tools, a synced core snapshot, and a `ploo` profile preset.
- Added the WorkBuddy entrypoint (`integrations/workbuddy`) and host contract tests for every integration.
- Documented DeepSeek Harness and WorkBuddy installation in AGENT_PORTABILITY.md. Artifact contracts remain `schema_version: 2.0`; no run-data migration is required.

## V2.1 — 2026-07-15

- Documented native Agent Skills installation for Codex, Claude Code, Cursor, and OpenClaw, plus a manual entrypoint for other agents.
- Generalized the Skill trigger language from Codex-only to agent-portable without weakening the user decision gates.
- Separated workflow portability from optional CAD, EDA, image, video, MCP, and provider capabilities.
- Updated the preferred Codex personal skill path to `~/.agents/skills` while preserving a safe path for legacy `~/.codex/skills` installations.
- Kept the V2 artifact contracts at `schema_version: 2.0`; V2.1 requires no run-data migration.

## V2 — 2026-07-15

- Made all visual, mechanical, schematic, and PCB routes explicit user decisions.
- Added provider-neutral Design Pack, Electrical Pack, Interface Control, and Run State V2 contracts.
- Added optional Fusion 360 and EasyEDA adapter safety contracts without making either provider an install dependency.
- Added strict validation, non-overwriting and path-portable V1 migration, dependency invalidation, review/handoff binding, behavior evaluations, and CI.
- Added safe upgrade instructions for symlink, copied, and installer-managed V1 installations.

## V1

- Initial product-design workflow and Design Pack helpers.
