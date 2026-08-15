# Handoff Brief Template

Use this template for `spec` or `handoff` routes and for blocked direct execution.

For a V2 Design Pack, handoff-specific content is external state. Pass a strict
`handoff_data` JSON object with `--handoff-data`; do not add `handoff` or
`selected_routes` to the Design Pack because its schema forbids those root
fields. The object must contain exactly:

- `schema_version: "2.0"`
- `document_type: "handoff_data"`
- `design_pack_ref` with the current `artifact_id`, `revision`, and computed
  Design Pack `contract_hash`
- non-empty `modeling_target` and `expected_fidelity` strings
- list-valued `priority_constraints`, `suggested_work_split`, `open_questions`,
  and `recovery_notes`

The renderer validates V2 Design Pack and Run State inputs before reading them.
It marks a V2 brief `ready` only when hash-bound handoff data is present, the
Run State has no pending gate or unresolved route, and the user explicitly chose
mechanical `spec | handoff`, schematic `handoff`, or PCB `handoff`. Without those
conditions it emits a blocked, draft brief; missing fidelity remains explicitly
unprovided. Route choices and artifact state come only from the validated Run
State.

## Required sections

1. Modeling or EDA target and expected fidelity.
2. User-selected track and route.
3. Source artifact IDs, revisions, and hashes.
4. Critical envelope, interfaces, and hard constraints.
5. Approved components, packages, and unresolved variants.
6. Suggested part, schematic, or PCB work split.
7. Priority constraints: must preserve and user-approved relaxations.
8. Packaging, mounting, service, thermal, antenna, and cable constraints.
9. Acceptance checks and required evidence.
10. Open decisions and questions.
11. Known risks, stale descendants, and recovery notes.

Write the brief so the recipient can start without chat history, while still knowing which decisions remain with the user. Do not claim that planned or unverified work is implemented.
