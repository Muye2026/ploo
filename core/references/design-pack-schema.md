# Design Pack V2

Use `design-pack.v2.json` as provider-neutral product and industrial-design truth. Keep orchestration state in `run-state.v2.json`, electrical truth in `electrical-pack.v2.json`, and shared geometry in `interface-control.v2.json`.

The authoritative JSON Schema is `../schemas/design-pack.v2.schema.json`.

## Required V2 fields

- `schema_version`: `2.0`, and `document_type`: `design_pack`
- `artifact_id`, `revision`, `status`, nullable `architecture_decision_id`, and nullable `freeze_decision_id`
- `product_goal`
- `hard_constraints`
- `component_envelopes`
- `reference_cases`
- `component_requirements`
- `component_candidates`
- `selected_components`
- `packaging_constraints`
- `sourcing_risks`
- `layout_zones`
- `mounting_strategy`
- `style_features`
- `manufacturing_risks`
- `forbidden_features`
- `acceptance_checks`
- `provenance` and `evidence`

Optional references may point to the electrical pack and interface-control artifact (`artifact_refs`), and migrations may carry a `migration` block. Do not embed provider tool names, local paths, credentials, or live session IDs.

## Structured-item pattern

Use stable IDs and explicit units:

```json
{
  "id": "hc-envelope",
  "category": "envelope",
  "rule": "Keep the main body within the approved bounding box.",
  "priority": "must",
  "value": [140, 38, 20],
  "unit": "mm",
  "status": "confirmed",
  "source": "decision-envelope-001"
}
```

Acceptance checks need an ID, method, pass condition, and priority. Use optional `evidence_required` when the check needs a specific evidence class. Images may be referenced as appearance evidence, but not used as geometry truth.

## Decision-sensitive values

Geometry-driving source status uses `confirmed`, `assumed`, `missing`, or `conflict`. Component selections use `user_confirmed`, `user_approved_provisional`, or `needs_user_confirmation`, and every confirmed/provisional selection carries its own `decision_id`. A verified pack separately links the approved architecture and the final freeze. A provisional value may continue only when the user explicitly approves its scope and downstream risk. Missing, conflicting, or migration-unconfirmed material values open a decision gate.

## V1 compatibility

Retain all V1 product fields. Add V2 metadata and references without changing their meaning. Preserve old `execution_mode` only as migration provenance; never turn it into a route choice or permission to execute. Mark legacy component selections without explicit decision metadata as `needs_user_confirmation`. Invalid V1 modes are errors, not silent `spec-only` fallbacks.

## Rules

- Use millimeters for lengths and degrees for angles.
- Keep keys stable across revisions.
- Prefer structured objects over loose prose.
- Attach source and evidence to geometry-driving claims.
- Create a new revision instead of overwriting a frozen artifact.
