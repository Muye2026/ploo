# Environment and Capability Check

Run read-only discovery before asking the user to select routes. Do not modify live CAD, EDA, project, browser, or external state during this phase.

## Capability buckets

Probe independently:

1. Research and supplied references.
2. Image generation and image refinement.
3. Video generation and video refinement.
4. Mechanical/CAD providers, including inspection, parameterization, verification, rollback, render, and export.
5. EasyEDA schematic read, write, DRC, export, and evidence capabilities.
6. EasyEDA PCB read, write, DRC, export, and evidence capabilities.
7. Input completeness for each requested branch.

Ploo has no mandatory execution backend. The core planning capability is provider-neutral and must remain available when every optional adapter is absent. Fusion 360 MCP, EasyEDA APIs or skills, and image/video providers are integrations, not Ploo prerequisites. Their absence can make `direct`, `hybrid`, image, or video routes unavailable, but it must not prevent requirements, architecture, Design Pack, Electrical Pack, Interface Control, acceptance planning, guided work, or handoff preparation where those outputs are otherwise supportable.

## Capability report

For each provider or route, record:

- adapter ID and detected version when available
- status: `available`, `unavailable`, or `unknown`
- read, write, verify, export, rollback, and render capabilities separately
- per-operation real `provider_operation`, provider-neutral `capability_id`, and `risk_class`: read, reversible write, destructive write, export, render, verify, or rollback; unknown or non-unique write mappings stay unavailable
- tool-schema digest or equivalent compatibility evidence
- units and limits
- current target/session/document identity when relevant
- probe evidence and known limitations

Connectivity or a successful ping is not write authorization. Documentation claims are not runtime proof. Do not mutate a production document merely to test write access.

## Route presentation

After discovery, present Route Gate 0. Show feasible routes, conditionally eligible routes whose write permission still needs a user-authorized probe, and unavailable routes with reasons. Do not label an unknown write capability ready, and do not select `direct`, `guided`, `hybrid`, `spec`, `handoff`, image, video, or skip on the user's behalf.

If no route is selected, persist `waiting_user_decision`. If a selected capability later fails, return to a user decision instead of silently switching modes.

Do not install or require an optional provider on the user's behalf. With zero providers, still present the complete route gate: identify unavailable provider-backed choices, keep eligible `skip`, `spec`, `guided`, and `handoff` choices visible, and wait for the user to select them.
