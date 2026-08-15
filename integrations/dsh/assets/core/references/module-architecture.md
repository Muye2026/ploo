# Module Architecture

Use this reference when key module or component architecture is still open and the unresolved choice would materially change the downstream product definition.

## Why this phase exists

Some hardware ideas are not ready for industrial-design direction exploration until a few architecture-level choices are frozen.

Examples:

- no display vs. round display vs. slim bar display
- no camera vs. centered camera vs. offset vision sensor
- desktop stand vs. monitor-top clip vs. magnetic attach
- wired-only vs. battery-assisted
- passive cooling vs. vented cooling
- one main board vs. split board topology

These are not small implementation details. They can change:

- silhouette
- thickness
- front-face layout
- port placement
- stability
- mounting strategy
- internal stacking
- service access

## Trigger test

Open the architecture decision node only when the unresolved architecture would change the product in a first-order way.

Good trigger examples:

- The user has not decided whether the device is desktop or monitor-mounted.
- The user has not decided whether the product has a screen, only LEDs, or no visual module.
- The user has not decided whether sensing is camera-based, microphone-only, or sensor-free.
- The user has not decided whether there is a battery.

Do not trigger this phase when:

- the user already chose the module strategy
- only exact vendor part numbers are unknown
- the difference is too minor to affect product direction

## Output shape

When triggered, emit `Module Options` grouped by unresolved dimension.

Each dimension should include 2-4 viable options.

For each option, include:

- option name
- physical meaning
- impact on appearance
- impact on structure
- main risk
- what kinds of directions it supports

## Example dimensions

### Display Strategy

- no display
- tiny round display
- slim horizontal display
- shared front-glass status window

### Sensor Strategy

- no sensor
- centered single camera
- offset vision sensor
- camera plus privacy indicator

### Audio Strategy

- no speaker, mic only
- mic plus small speaker
- speaker only
- no audio module

### Mounting Strategy

- freestanding desktop base
- monitor-top passive clip
- magnetic attachment
- wall or dock mount

### Power Strategy

- wired USB-C only
- USB-C with internal battery
- dock-powered

### Thermal Strategy

- sealed passive enclosure
- hidden vent path
- explicit vented enclosure

## Selection behavior

Stop after module options and require the user to select every critical unresolved dimension or explicitly approve a named provisional option. The agent may recommend an architecture set, but no interaction or execution cadence authorizes autonomous selection.

Record the decision and affected downstream branches. If a later component or interface conflicts with the chosen architecture, open a conflict gate instead of silently substituting another option.

## Practical limit

Do not overwhelm the user with a full morphological chart unless the product genuinely needs it.

Prefer selecting 1-3 critical unresolved dimensions rather than exploding every possible variable.

The purpose of this phase is to stabilize the product definition enough that the later direction exploration is meaningful.
