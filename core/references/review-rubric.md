# Review Rubric

Use `pass`, `partial`, `fail`, or `not_applicable`. Every status needs evidence, a blocking issue when applicable, and a next action.

`Brief fit`, `Decision traceability`, `Structure plausibility`, `Component credibility`, and `Execution readiness` are mandatory and must be `pass`; they cannot be marked `not_applicable`. An optional category may be `not_applicable` only with reliable evidence showing why that domain is outside the user-approved routes or product scope. This prevents a nine-category empty review from crossing a freeze gate.

## Categories

1. Brief fit: goal, user, scenario, and required functions.
2. Decision traceability: route, architecture, components, candidates, freezes, and exceptions are user-owned and recorded.
3. Visual coherence: silhouette, hierarchy, CMF, and multi-view consistency.
4. Structure plausibility: envelope, mounting, service, stability, and assembly.
5. Component credibility: package, interface, mounting, power, thermal, sourcing, and evidence.
6. Electrical readiness: power domains, interfaces, pin roles, critical networks, protection, DRC, and open risks.
7. Packaging feasibility: board, battery, connector, cable, antenna, thermal, service, and keep-out volumes.
8. Cross-domain consistency: shared IDs and interface-control revision agree across CAD and PCB.
9. Execution readiness: preconditions, operation cards, rollback, acceptance checks, and evidence paths exist.

## Freeze rule

A candidate may cross a freeze gate only when required categories pass. The user may accept a named provisional exception only where the domain gate marks it waivable; strict safety, connectivity, DRC, and evidence failures remain conditional or blocked. `partial` or `fail` never silently becomes verified permission to continue.

For V2 Design Pack freeze, store the strict external `review_results` object as a verified Run State artifact whose content hash is the canonical full-document digest and whose dependency binds the current Design Pack revision/hash. The user freeze decision must include `review:<artifact_id>@<revision>` in scope and bind that review artifact in `dependency_revisions`. `validate_bundle.py` blocks freeze and all downstream schematic/PCB work when the review result is absent, stale, not verified, contains a non-passing category, or leaves a `must` acceptance check non-passing.

## Completion rule

End an implementation loop when all approved acceptance checks pass with adequate evidence and the user freezes the candidate. Otherwise report the exact remaining delta or blocked condition.
