# Use Cases

## Good fits

- Explore several physical product directions and let the user select one.
- Generate only images/video, only a design pack, or both, after route selection.
- Turn approved product constraints into a Fusion 360 MCP modeling plan or guided CAD steps.
- Produce or review an EasyEDA schematic through direct, guided, hybrid, or handoff work.
- Move a frozen schematic and shared interface into PCB planning and incremental verification.
- Resume a mixed CAD/EDA workflow without confusing planned work with implemented work.
- Detect a conflict between a render, structure document, schematic, PCB, and enclosure, then ask the user to resolve it.

## Expected decision behavior

- “Give me options first” stops at the relevant gate.
- “Run end to end” permits continuous low-risk execution only after routes and material decisions are explicit.
- “You teach me; I draw it” selects `guided` for that track and requires step-by-step acceptance.
- “Use the MCP directly” selects `direct` only for the named track; it does not authorize destructive tools or unrelated branches.
- A supplied render, schematic, or model shortens discovery but does not waive missing contracts or freezes.

## Resume examples

- Existing render: validate brief, components, views, and structure before CAD.
- Frozen schematic: verify the freeze manifest and shared mechanical inputs before PCB.
- Draft PCB: compare source hashes and interface revision before continuing layout or routing.
- Draft CAD: validate the design-pack and interface-control revisions before editing.

## Non-goals

Do not use this skill as the primary path for production tooling, tolerance stacks, final manufacturing release, large architectural systems, or certification. Product Loop may produce design candidates and EVT plans; it does not certify production readiness.
