# Decision Gates

Use decision gates to preserve user authority without interrupting every low-risk implementation step.

## Gate record

Record every gate with:

```json
{
  "decision_id": "route-001",
  "decision_type": "route_selection",
  "scope": ["track:mechanical"],
  "status": "pending",
  "question": "Which mechanical path should this run use?",
  "options": [
    {
      "id": "direct",
      "label": "Direct MCP",
      "description": "Use the selected verified CAD adapter.",
      "impact": "Requires a writable target and recovery checkpoint."
    }
  ],
  "recommendation": null,
  "recommendation_rationale": null,
  "impact": [],
  "selected_option": null,
  "decided_by": null,
  "decided_at": null,
  "decision_evidence": [],
  "dependency_revisions": []
}
```

`scope` names the affected track, artifact revision, interface, operation, or constraint. Recommendations must identify an option and explain the rationale and trade-offs, but must not fill `selected_option`. A resolved gate also needs `decision_evidence` that points to the explicit user message or equivalent source; `decided_by: user` alone is not proof of authorization. Use a host-originated stable reference such as `chat-message:<stable-id>`, `codex-message:<stable-id>`, or `approval-record:<stable-id>`. This reference provides traceability, not cryptographic identity; do not synthesize it in an adapter or migration.

Create and resolve non-route gates through `scripts/manage_run_state.py open-decision` and `resolve-decision`. The open command clears any pre-filled selection/evidence and binds the gate to current artifact hashes. Only one gate may be pending. Route decisions continue to use `resolve-routes` because every track has its own route decision ID.

When an already selected route fails, open a `route_change` gate scoped to the affected track, let the user choose, resolve it, then apply it with `manage_run_state.py change-route`. The command changes only that track and marks its old Operation Cards stale; it does not infer a fallback or invalidate provider-neutral design truth. Stale artifacts are never cleared in place: recovery creates a new revision with fresh evidence and dependency hashes, preserving the old record.

## Required material gates

Stop for the user at:

1. Route selection for visualization, mechanical modeling, schematic, and PCB.
2. Product architecture and critical component set.
3. Design direction, render variant, and appearance freeze.
4. Structure, CAD target, schematic, PCB, and shared-interface freeze.
5. Board outline, layer count, stack-up, critical footprint, connector, polarity, Pin 1, and FPC orientation.
6. Conflicting source values or proposed relaxation of a hard constraint.
7. Ownership changes in a hybrid route.
8. Destructive, externally visible, non-reversible, or weakly recoverable writes.
9. Resolving or provisionally accepting an Electrical Pack open item.

An instruction to implement an approved plan authorizes only choices already fixed in that plan. It does not authorize missing design decisions.

## Continuous execution boundary

With `confirmation_policy: material_decisions`, continue without another pause only when all are true:

- the step stays within an approved route and scope
- the step is reversible or has a verified recovery path
- no source conflict or constraint change appears
- target identifiers and expected delta are explicit
- the operation card has objective acceptance checks

Otherwise open a new gate.

## Capability loss

If a route becomes unavailable, keep the affected branch paused and present feasible choices. Never write a fallback selection into state until the user chooses it.

## Conflict gate

Present:

- each conflicting value and source revision
- what would become stale under each choice
- safety, schedule, appearance, electrical, and mechanical impact
- a recommendation with rationale

After the user decides, store the decision and invalidate only descendants whose dependency hashes changed.

## Freeze gate

A freeze decision must name the artifact revision and unresolved exceptions. A user may accept a provisional exception, but cannot relabel a failed non-waivable safety, connectivity, strict-DRC, or evidence gate as verified. In that case keep the artifact conditional or blocked and restrict downstream work. Changing a frozen input creates a new revision and marks affected descendants `stale`.

For cross-document validation, use `decision_type: freeze` with `selected_option: freeze` and scope `artifact:<id>@<revision>`. A PCB candidate uses `decision_type: candidate_selection` with `selected_option: accept_candidate`. The decision dependencies must contain that same artifact revision and current contract hash.

For provisional Design Pack items accepted at freeze, add `exception:hard_constraint:<id>` or `exception:component_envelope:<id>` to the freeze scope. A generic freeze scope does not silently convert an assumption into a confirmed fact.

A Design Pack freeze also binds the verified passing review artifact: add `review:<artifact_id>@<revision>` to scope and include its exact digest in `dependency_revisions`. Resolving an Electrical Pack open item uses `decision_type: open_item_resolution`, scope `open_item:<id>`, and `selected_option: resolve | accept_provisional`; the latter is rejected unless the item explicitly declares `waivable: true`.

For a `high` or `destructive` Operation Card, the one-call decision scope additionally includes `operation:<material_digest>` alongside run, step, call, attempt, parameter digest, and capability choice. The operation digest binds target objects, expected delta, protected objects, rollback, checks, required evidence, and dependency revisions so an approval cannot survive a material card rewrite.
