# V1 Interaction-Mode Migration

V2 replaces autonomous decision modes with user-owned material decisions.

## `checkpointed`

Migrate to:

```json
{
  "decision_authority": "user",
  "confirmation_policy": "material_decisions",
  "execution_cadence": "stepwise"
}
```

Preserve unresolved checkpoints as `waiting_user_decision` gates.

## `auto`

Migrate to:

```json
{
  "decision_authority": "user",
  "confirmation_policy": "material_decisions",
  "execution_cadence": "continuous_within_approved_route"
}
```

`auto` never authorizes route selection, architecture, critical components, design direction, freezes, conflicts, constraint relaxation, PCB layer/stack-up, critical footprints, connector orientation, or destructive actions.

If the V1 run lacks explicit route choices, migration must set `pending_decision_gate` to Route Gate 0 and status to `waiting_user_decision`.

## Override rule

The user's latest explicit constraint or selection controls subsequent work. Record it as a decision; do not repeatedly reopen it unless a conflict, changed input, or new safety issue makes reconsideration necessary.
