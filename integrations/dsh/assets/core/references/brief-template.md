# Brief Template

Use this template to normalize a hardware brief before direction work starts.

## Required

- `Product goal`: What job should the product do?
- `Target user`: Who uses it most often?
- `Use scenario`: Where and when is it used?
- `Primary functions`: What must it do every time?
- `Core modules`: What boards, sensors, displays, batteries, or mechanisms are already assumed?
- `Envelope constraints`: What overall size, weight, or thickness limits are known?
- `Mounting or placement`: How does it attach, stand, hang, or sit?
- `Power and I/O`: What power source, ports, charging, wireless, or service access is required?
- `Interaction model`: What buttons, indicators, touchpoints, or sound outputs are required?

## Strongly Recommended

- `Style intent`: What product family, mood, or visual references should guide the design?
- `Priority tradeoffs`: What matters more if tradeoffs appear: compactness, friendliness, serviceability, manufacturability, cost, or stability?
- `Known risks`: What already looks hard or uncertain?
- `Forbidden moves`: What should the design avoid?

## Output Shape

Emit a normalized brief with these headings:

1. Goal
2. Audience
3. Scenario
4. Functions
5. Modules and assumptions
6. Hard constraints
7. Soft preferences
8. Unknowns

## Resume Rule

If the user already provides a render, sketch, model, schematic, PCB, or partial spec, extract the same fields and record the artifact revision. Do not let a downstream artifact bypass missing upstream constraints; open a decision gate for any missing material choice.
