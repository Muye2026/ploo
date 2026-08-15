# Ploo Validation Results

Date: 2026-08-15 (V3.0 — project renamed from product-loop to ploo)

## Validated scope

- The installable `SKILL.md` is a lean router and state-machine entrypoint whose rules live one reference deep.
- The same inner Agent Skills folder is documented for Codex, Claude Code, Cursor, OpenClaw, DeepSeek Harness, WorkBuddy, and manual host loading without making any provider a core dependency.
- The single `core/` plus thin host adapters (`integrations/cli`, `integrations/dsh`, `integrations/workbuddy`) keep the core as the only source of workflow rules; the DSH plugin ships a byte-identical snapshot enforced by `sync-core.mjs --check`, `verify.mjs`, and CI.
- All four V2 JSON documents pass strict structural and semantic validation.
- The synthetic four-document planned bundle and strict frozen-schematic, PCB-candidate, and waiting-EVT bundles pass cross-document hash, freeze, dependency, review, and evidence checks.
- V1 migration leaves every missing route at a user decision gate.
- Fusion and EasyEDA adapter contracts bind one Operation Card attempt to one runtime-probed provider operation, capability ID, risk class, canonical parameter digest, full material Operation Card digest, execution reservation, and readback result.
- V2 review and handoff data are external, strict, hash-bound contracts; Design Pack freeze cannot bypass a failing or missing review.
- Behavior evaluation covers route authority, independent EDA routes, capability loss, source conflicts, resume, evidence, partial writes, target identity, high-risk calls, cross-domain mismatch, the EVT boundary, and planning with zero optional providers.
- Run-state mutating actions reject same-path input/output, and malformed execution-recovery decisions fail with a clear validation error instead of an uncaught crash.

## Automated results

```text
python3 -m unittest discover -s tests -v
116 tests passed

validate_v2.py
design-pack: valid
electrical-pack: valid
interface-control: valid
run-state: valid

validate_bundle.py
synthetic V2 bundle: valid

evaluate_behavior_contracts.py
12 behavior contracts: passed

integrations/dsh/scripts/verify.mjs
package shape, snapshot sync, lib parse, mock apply, end-to-end: passed

skill frontmatter
official quick_validate.py: passed
```

## Safety properties exercised

- No image, video, CAD, schematic, or PCB route is inferred without a user selection.
- The provider-neutral planning layer remains usable without Fusion, EasyEDA, image, or video integrations; optional tools are never required or installed implicitly.
- V1 migration refuses same-path or pre-existing outputs, publishes new files via exclusive create, and avoids embedding an absolute input path by default.
- Run-state mutating actions never overwrite their input, even when input and output paths point at the same file.
- An unavailable MCP or API never silently changes the route.
- Conflicting source values cannot be hidden by status or document order.
- A pending decision, stale or unverified dependency, mismatched content/provenance hash, changed parameter or material Operation Card, reused attempt, or ambiguous provider binding blocks execution.
- The reserved write lease rechecks input/output readiness, preventing a time-of-check/time-of-use status change from crossing the provider boundary.
- Dangerous or destructively named tools cannot be down-classified; high-risk calls require one exact scoped user decision.
- Fusion timeout, no-change, partial-write, rollback, unit conversion, and external export paths are handled fail-closed.
- EasyEDA window/document identity, permission, schematic/PCB units, D+/D-, Pin 1, FPC direction, pin-pad mapping, and DRC conditions are checked.
- Frozen schematics require non-empty requirements, power/interface contracts, device/binding/net truth, rules, library revisions, and evidence-complete critical checks; empty contracts cannot pass vacuously.
- CAD/PCB board thickness, holes, connectors, height zones, and antenna keep-outs require an evidence-backed cross-domain match.
- PCB output is bounded to `PCB design candidate / waiting EVT`, never manufacturing release.

## Boundary

These tests validate the orchestration contracts and pure adapter guards. They do not claim that a live Fusion 360 or EasyEDA backend was modified or exercised; backend changes are intentionally outside this phase.
