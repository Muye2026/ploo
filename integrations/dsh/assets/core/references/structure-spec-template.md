# Structure Spec Template

Write this spec after the visual direction is stable enough to express structure intent.

## Required Sections

1. `Mounting or placement logic`
   - how the product sits, hangs, clips, or stands
   - what keeps it stable
   - what contact points matter

2. `Target envelope`
   - overall size target
   - thickness or depth target
   - critical clearances

3. `Internal zoning`
   - front-facing elements
   - central keep-outs
   - side service zones
   - lower-layer or rear-layer volumes

4. `Component assumptions`
   - board keep-out
   - display package
   - camera or sensor package
   - speaker, battery, antenna, cable, or port assumptions
   - selected or assumed component path
   - fallback envelope if exact parts change

5. `Packaging constraints`
   - thickness drivers from selected components
   - visible windows, tracks, ports, buttons, hinges, clips, magnets, pads, or fasteners
   - required service access
   - environmental constraints from heat, UV, vibration, abrasion, or sealing

6. `Serviceability`
   - access to ports
   - assembly direction
   - replacement or debug assumptions

7. `Structural risks`
   - thin sections
   - support-arm leverage
   - impact-sensitive features
   - cable routing risks

8. `Manufacturing boundary`
   - what this phase does not yet define
   - what must be validated before detailed engineering
   - component availability, price, and exact supplier dimensions if unverified

9. `Shared interface reference`
   - `interface-control.v2.json` artifact ID and revision
   - coordinate origin and datums
   - board outline, holes, connectors, buttons, indicators, openings, keep-outs, and height zones consumed by the structure

## Writing Rule

Keep the spec concrete enough for CAD translation, but do not imply production readiness unless those details were actually validated.
