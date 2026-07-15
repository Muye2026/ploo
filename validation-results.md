# Product Loop V2 Validation Results

Date: 2026-07-15

## Validated scope

- The installable `SKILL.md` is a 152-line router and state-machine entrypoint.
- All four V2 JSON documents pass strict structural and semantic validation.
- The synthetic four-document planned bundle and strict frozen-schematic, PCB-candidate, and waiting-EVT bundles pass cross-document hash, freeze, dependency, review, and evidence checks.
- V1 migration leaves every missing route at a user decision gate.
- Fusion and EasyEDA adapter contracts bind one Operation Card attempt to one runtime-probed provider operation, capability ID, risk class, canonical parameter digest, full material Operation Card digest, execution reservation, and readback result.
- V2 review and handoff data are external, strict, hash-bound contracts; Design Pack freeze cannot bypass a failing or missing review.
- Behavior evaluation covers route authority, independent EDA routes, capability loss, source conflicts, resume, evidence, partial writes, target identity, high-risk calls, cross-domain mismatch, the EVT boundary, and planning with zero optional providers.

## Automated results

```text
python3 -m unittest discover -s tests -v
105 tests passed

validate_v2.py
design-pack: valid
electrical-pack: valid
interface-control: valid
run-state: valid

validate_bundle.py
synthetic V2 bundle: valid

evaluate_behavior_contracts.py
12 behavior contracts: passed

skill frontmatter
Ruby YAML equivalent validation: passed
official quick_validate.py: unavailable because PyYAML is not installed in this workspace runtime
```

## Safety properties exercised

- No image, video, CAD, schematic, or PCB route is inferred without a user selection.
- The provider-neutral planning layer remains usable without Fusion, EasyEDA, image, or video integrations; optional tools are never required or installed implicitly.
- V1 migration refuses same-path or pre-existing outputs, publishes new files atomically, and avoids embedding an absolute input path by default.
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
