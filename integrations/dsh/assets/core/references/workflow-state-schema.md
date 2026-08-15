# Workflow State Schema

Use `run-state.v2.json` for orchestration state. Do not store design truth here.

## Required domains

- `schema_version`, `run_id`, and one unified run `status`
- `decision_authority: user`
- `confirmation_policy: material_decisions`
- selected route and resolved user decision ID for each track
- `route_decision_ids` linking every selected route to a resolved user decision
- at most one currently presented pending decision gate; other resolved or superseded decisions live in the ledger
- decision ledger with `decision_type`, machine-readable `scope`, candidates, recommendation rationale, user selection, timestamp, impact, and dependency revisions
- capability reports binding each provider operation name to one provider-neutral capability ID, risk class, and tool-schema digest
- artifact IDs, revisions, hashes, producers, dependencies, and evidence
- operation-card references, one exact execution capability, execution reservations, authorization consumptions, and readback status
- targeted invalidation reasons on affected artifact records

The authoritative JSON Schema is `../schemas/run-state.v2.schema.json`.

Single-document validation checks internal structure. Before a freeze or implementation step, run `../scripts/validate_bundle.py` so freeze decisions, artifact status, revisions, and content hashes are resolved across Run State, Design Pack, Electrical Pack, and Interface Control.

`content_hash` uses the validator's canonical `contract_hash`: provider-neutral contract truth is serialized with stable key ordering while root `provenance`, root `evidence`, migration notes, workflow `status`, and the root freeze-decision pointer are excluded. This avoids a circular freeze in which approving a candidate changes the very hash that was approved. A new screenshot, timestamp, or state transition therefore does not invalidate design descendants, while any actual contract-value change does. The document's `provenance.hash`, its Run State artifact record, and every dependency reference must agree.

Run status uses the same six values as artifacts: `planned`, `waiting_user_decision`, `implemented-unverified`, `verified`, `stale`, or `blocked`. A missing route requires `waiting_user_decision`; a `verified` run cannot contain unresolved routes, a pending gate, or an unverified operation card.

## Artifact record

```json
{
  "artifact_id": "interface-control",
  "artifact_type": "interface_control",
  "revision": 3,
  "status": "verified",
  "path": "interface-control.v2.json",
  "content_hash": "sha256:...",
  "source_hashes": {"design-pack": "sha256:..."},
  "provenance": {
    "source": "approved product contracts",
    "producer": "product-loop",
    "time": "2026-01-01T00:00:00Z",
    "hash": "sha256:..."
  },
  "depends_on": [
    {"artifact_id": "design-pack", "revision": 2, "content_hash": "sha256:..."}
  ],
  "invalidation_reasons": [],
  "evidence": [
    {
      "evidence_id": "evidence-interface-export-001",
      "type": "source_export",
      "source": "interface-control.v2.json",
      "captured_at": "2026-01-01T00:00:00Z",
      "ref": "sha256:...",
      "note": "Validated source export"
    }
  ]
}
```

## Invalidation rules

- Component envelope changes invalidate affected directions, renders, interfaces, CAD, and PCB placement.
- Style-only changes invalidate appearance outputs but not schematic truth.
- Schematic net or footprint changes invalidate schematic freeze and PCB descendants.
- Board outline, mounting, or connector changes invalidate PCB placement and the relevant enclosure interfaces; schematic truth remains valid unless pins or nets changed.
- Layer count or stack-up changes invalidate PCB rules, routing, and DRC; CAD changes only if shared board thickness changes.
- Route changes invalidate execution plans and journals, not design truth.

Never overwrite a verified record in place. Create a new revision and retain lineage.

## Operation Card integrity

Every card describes one semantic goal and one provider call. It includes a unique attempt, the exact canonical parameter object and its recomputed SHA-256 digest, `execution_capability_id`, non-empty inputs, outputs, targets, expected delta, protected objects, checks, and at least one reliable evidence requirement. The execution capability must resolve to exactly one runtime-probed `provider_operation` and `risk_class`. A card may list readback or verification prerequisites, but it may bind only one mutating provider operation. `depends_on` and `produces` must reference different revisions, and every produced artifact must declare exactly the card inputs as its direct lineage.

For `high` or `destructive` risk, record a stable `call_id` and `attempt_id`. The execution capability needs exactly one resolved decision whose scope includes `run:<run_id>`, `step:<step_id>`, `call:<call_id>`, `attempt:<attempt_id>`, `parameters:<digest>`, and `operation:<material_digest>`. The material digest covers the full Operation Card contract, including goal, route, ownership, risk, capability, dependencies, targets, expected delta, protected objects, rollback, checks, and required evidence; changing any of them invalidates the approval. One approval cannot cover a second capability, changed parameters or target, retry, or later run.

All Fusion and EasyEDA writes, including low-risk writes, use this exact order:

1. `authorize_execute_step(...)` validates the complete bundle and issues a sealed `authorized` token bound to the exact state snapshot, attempt, provider operation, parameters, targets, and inputs.
2. The adapter performs only read-only identity, capability, scene/document, and hash preflight with that token.
3. The same-process host calls `reserve_execution(...)` with the sealed authorization and the same state digest to atomically append one `execution_reservations` entry and, when required, reserve the exact high-risk decision in `authorization_consumptions`. This is deliberately not a standalone CLI command because the read-only preflight and sealed token must remain in the same transaction.
4. `authorize_reserved_execute_step(...)` revalidates the updated bundle and issues a sealed, single-use `reserved` lease for that reservation.
5. The adapter guard compares the actual provider operation and canonical parameters to the lease, consumes it once, and immediately invokes that one operation.
6. Query provider state, then call `record-execution` with `completed`, `failed`, or `unknown` plus the readback fingerprint.

Never invoke or run a write guard before reservation. A crash, timeout, failed or unknown result opens a user recovery gate; retry or route change requires an explicit choice and a new Operation Card attempt. The old reservation and authorization consumption remain immutable, mirrored audit history. The in-process seal prevents callers from hand-constructing a token; the host must additionally keep the authoritative Run State behind a single-writer lock or compare-and-swap boundary across processes.

`cross_domain_checks` records the Interface Control, optional CAD, and PCB artifact revisions plus five mandatory comparison groups: board thickness, mounting holes, connectors, height zones, and antenna keep-outs. A verified check needs reliable evidence, all groups `match`, verified source artifacts, and no stale dependency.

A `verified` or `implemented-unverified` artifact may depend only on `verified` parent artifacts. Artifact `provenance.hash` must equal `content_hash`; this prevents a status-only mutation or mismatched journal record from masquerading as the approved source. Design freeze additionally requires one verified `review_results` artifact bound to the current Design Pack, and the freeze decision must bind that exact review digest.

Use `manage_run_state.py open-decision` and `resolve-decision` for architecture, freeze, conflict, ownership, adapter, candidate, and high-risk gates. `decision-ref` must be a stable host-provided message or approval pointer. The JSON validator proves shape, scope, and dependency binding; it is not an identity or signature service, so callers must never fabricate the reference from free text.
