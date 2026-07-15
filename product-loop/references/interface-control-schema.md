# Interface Control Schema

Use `interface-control.v2.json` as the shared mechanical/electrical geometry contract. Store dimensions in millimeters and angles in degrees.

The authoritative JSON Schema is `../schemas/interface-control.v2.schema.json`.

The root `freeze_decision_id` is null until the user freezes this exact revision. A `verified` Interface Control requires that decision and cross-document validation against Run State. Its decision scope explicitly lists `constraint:pcb_geometry` plus every confirmed mounting hole, interface feature, keep-out, height zone, and cable/battery volume; a generic artifact freeze cannot hide an omitted connector or mechanical interface choice.

## Required content

- coordinate system, origin, axis directions, and datum references
- product envelope and tolerance/uncertainty notes
- PCB outline, thickness, mounting holes, and board datum
- connector, switch, button, indicator, sensor, and opening locations
- antenna, RF, thermal, fastener, and service keep-outs
- component height zones
- battery, FPC, harness, and cable volumes
- source artifact revisions and evidence

Every collection item needs a stable ID; every geometry value carries a status and sources. The coordinate system is the declared public convention, not a measured part location. If the datum convention itself is undecided, open a Decision Gate before populating downstream geometry.

Status and canonical-value rules are fail-closed:

- `confirmed`: complete canonical geometry and at least one source.
- `assumed`: complete canonical geometry and at least one source, but it cannot enter a verified Interface Control until the user resolves it.
- `missing`: required JSON fields remain present, while unknown vectors/poses/sizes are `null`, PCB outline is empty, and no guessed `[0,0,0]` is inserted.
- `conflict`: canonical geometry stays null/empty and at least two conflicting sources are recorded. Candidate values and downstream impact belong in the pending Decision Gate until the user resolves the conflict.

Only the user may approve an assumption or choose between conflicting values when it materially affects CAD or PCB.

## Cross-domain rule

Fusion and PCB plans must reference the same interface-control revision. Before cross-domain review, compare shared IDs rather than visually estimating alignment.

## Change behavior

Create a new revision when a shared interface changes. Run State invalidates only descendant artifacts that declare a dependency on that Interface Control revision; use separate artifacts for independently rebuildable branches so an unrelated schematic branch is not needlessly marked stale. Record the changed interface IDs in the invalidation reason for human review. For example, changing a connector opening invalidates the PCB placement and enclosure opening artifacts that consume it, but not a schematic artifact with no Interface Control dependency.
