---
name: product-loop
description: Orchestrate a small hardware product from brief to evidence-backed design artifacts, including planning-only runs with no external execution backend, concept images or video, industrial design, optional Fusion 360 MCP modeling, optional EasyEDA schematic and PCB work, guided user operation, and downstream handoff. Use when Codex must plan, resume, execute, or review a multi-domain hardware workflow while preserving user authority over whether each track runs and whether work is direct, guided, hybrid, specification-only, or handed off. Best for small consumer electronics, desktop hardware, and lightweight robotic accessories; not a production DFM, tooling, tolerance-stack, or manufacturing-release certification skill.
---

# Product Loop

Orchestrate product design as a dependency graph. Keep design truth provider-neutral, make material choices visible, and attach evidence to every implementation claim.

## Non-negotiable authority rule

Set `decision_authority: user` for every run.

Never decide on the user's behalf whether to:

- generate images or video
- create a mechanical model
- use Fusion 360 MCP, guide the user, or hand work off
- create a schematic or PCB
- let EasyEDA APIs write, guide the user, split ownership, or hand work off
- freeze architecture, components, appearance, CAD, schematic, PCB, or shared interfaces

You may inspect, compare, recommend, normalize, and perform reversible steps already inside an approved route. A recommendation is not authorization. If a required selection is missing, set the run to `waiting_user_decision`, present the choices and consequences, then stop.

Read [references/decision-gates.md](references/decision-gates.md) before presenting or crossing any gate.

## Phase 0: read-only discovery

Inspect available inputs and capabilities without modifying CAD, EDA, project files, or external systems. Read [references/environment-check.md](references/environment-check.md).

Probe independently:

- research and supplied references
- image and video generation
- Fusion 360 or other CAD adapters
- EasyEDA schematic operations
- EasyEDA PCB operations
- source export, readback, verification, rollback, and handoff paths

Record evidence in `CapabilityReport`. Do not infer write capability from connectivity alone. Do not choose a route during discovery.

Product Loop has no mandatory execution backend. Fusion 360 MCP, EasyEDA APIs or skills, and image or video providers are optional adapters, not installation dependencies. When none are available, keep the provider-neutral planning layer usable: build the brief, architecture, contracts, interface controls, acceptance plan, guided instructions, and handoff package as authorized. Mark provider-backed routes unavailable; never require installation, invent a provider, select a fallback route, or block unrelated planning work.

## Route Gate 0

Ask the user to select every relevant track. Do not preselect or silently omit an available choice.

| Track | Allowed choices |
| --- | --- |
| `visualization` | `skip`, `image`, `video`, `image+video` |
| `mechanical` | `skip`, `spec`, `direct`, `guided`, `handoff` |
| `schematic` | `skip`, `direct`, `guided`, `hybrid`, `handoff` |
| `pcb` | `skip`, `direct`, `guided`, `hybrid`, `handoff` |

Show available routes and conditionally eligible routes separately; label every unverified prerequisite. Show unavailable routes with reasons. A conditional route may be selected, but must pass its post-selection probe before any live write. The user may combine tracks. Record each selection and its resolved user decision ID in `run-state.v2.json` before implementation.

If an approved route later becomes unavailable, do not auto-degrade. Offer `retry`, `guided`, `hybrid`, `handoff`, or `pause` as applicable and return to `waiting_user_decision`.

## Build the contracts

Normalize the brief, architecture, components, requirements, and acceptance checks into `design-pack.v2.json`. Read:

- [references/brief-template.md](references/brief-template.md)
- [references/module-architecture.md](references/module-architecture.md)
- [references/component-selection.md](references/component-selection.md)
- [references/design-pack-schema.md](references/design-pack-schema.md)
- [references/appearance-spec-template.md](references/appearance-spec-template.md)
- [references/structure-spec-template.md](references/structure-spec-template.md)

For electronic products, create `electrical-pack.v2.json`. For cross-domain geometry, create `interface-control.v2.json`. Read:

- [references/electrical-pack-schema.md](references/electrical-pack-schema.md)
- [references/interface-control-schema.md](references/interface-control-schema.md)

Do not hide missing facts as assumptions when they require a material user choice. Open a decision gate instead.

## Run the dependency graph

Read [references/workflow-v2.md](references/workflow-v2.md) and follow artifact dependencies rather than a rigid phase number.

Core readiness rules:

- Start direction exploration only after material architecture and component choices are user-approved or explicitly marked provisional by the user.
- Start Fusion modeling only after the visual/structure target and required shared interfaces are frozen.
- Start PCB work only after the schematic and required shared interfaces are frozen.
- Converge CAD and PCB through cross-domain checks before emitting an EVT validation plan.
- Never treat a supplied render or draft model as permission to bypass missing upstream contracts.

Use `Appearance Spec`, `Structure Spec`, `Design Pack`, `Electrical Pack`, and `Interface Control` as design truth. Treat images as appearance evidence, not geometry truth.

## Execute through operation cards

Before each direct or guided batch, create an `OperationCard` containing:

- `step_id`, one-call `call_id`, unique `attempt_id`, exact canonical `parameters` and their `parameter_digest`, goal, track, route, selected adapter, resolved route-decision ID, any additional authorization-decision IDs, ownership, risk level, one `execution_capability_id`, supporting capability requirements, and preconditions
- target identifiers and expected delta
- `do_not_touch` boundaries
- rollback or recovery path
- acceptance checks and required evidence

Use the common adapter lifecycle:

```text
probe(context) -> CapabilityReport
plan(pack, artifacts) -> RunPlan
execute_step(step, session) -> StepResult
verify(step, result, checks) -> VerificationResult
rollback(checkpoint) -> RollbackResult
export(formats, artifact_root) -> ArtifactManifest
```

For Fusion 360, read [references/fusion360-adapter.md](references/fusion360-adapter.md). For EasyEDA, read [references/easyeda-adapter.md](references/easyeda-adapter.md). Do not invent provider APIs or silently substitute another backend.

Before every provider write, obtain a full-bundle authorization bound to the exact state, capability, probed provider operation, parameters, targets, and attempt. Use it for read-only preflight, atomically reserve the attempt and any high-risk approval, revalidate the updated bundle for a single-use write lease, guard the actual call, invoke that one provider operation once, then record readback. A pending decision, stale/blocked dependency, changed hash, mismatched attempt, or prior reservation blocks the write.

### Execution boundary

An execution token proves that a previously approved route and exact Operation Card are currently executable; it does not grant a new architecture, component, freeze, conflict, or route decision. If the intended provider operation, parameters, target, or ownership changes, discard the card and return to the relevant user gate.

## Evidence and claims

Use these artifact states:

`planned`, `waiting_user_decision`, `implemented-unverified`, `verified`, `stale`, `blocked`

Use these evidence types:

`api_readback`, `source_export`, `screenshot`, `user_self_report`, `unverified`

Only API readback, source export, or a clear screenshot can support `implemented-unverified` or `verified`. A self-report alone remains unverified. Never describe planned work as implemented.

## Conflict and invalidation protocol

When sources conflict, show both values, revisions, downstream effects, and a recommendation. Do not apply newest-wins or any hidden precedence. Wait for the user to decide, record the resolution, and invalidate only dependent descendants.

Persist run status and dependency hashes using [references/workflow-state-schema.md](references/workflow-state-schema.md). On resume, validate upstream hashes and return to the pending gate; do not merely continue from the earliest missing file.

## Review and stop conditions

Use [references/review-rubric.md](references/review-rubric.md) before every freeze and final handoff. A Design Pack freeze is valid only when its strict passing `review_results` document is stored as a verified Run State artifact and the user's freeze decision binds that exact review digest.

Complete a loop only when all approved acceptance checks have evidence-backed pass results and the user freezes the candidate. Stop without claiming completion when the run becomes blocked or the user pauses it. Do not iterate indefinitely.

Use [references/handoff-brief-template.md](references/handoff-brief-template.md) for `spec` or `handoff` routes. Emit only artifacts for approved tracks. Label PCB output `PCB design candidate / waiting EVT`; never imply production or manufacturing readiness.

## V1 compatibility

Migrate V1 inputs before resuming. Map `checkpointed` to `confirmation_policy: material_decisions`. Map `auto` only to continuous cadence inside approved routes; it never grants route or material-decision authority. Missing routes must enter `waiting_user_decision`.

Use `scripts/migrate_v1_to_v2.py` for migration, `scripts/validate_v2.py` for each document, `scripts/validate_bundle.py` before any cross-document freeze or execution, and `scripts/manage_run_state.py` for route resolution, non-route decision gates, validation, and descendant invalidation. Treat any validator failure as blocking; never repair a material value by guessing.

Read [references/checkpoint-mode.md](references/checkpoint-mode.md) for migration semantics and [references/use-cases.md](references/use-cases.md) for examples and boundaries.
