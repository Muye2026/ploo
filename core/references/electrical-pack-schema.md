# Electrical Pack V2

Use `electrical-pack.v2.json` as the provider-neutral electrical design contract. The authoritative machine contract is `../schemas/electrical-pack.v2.schema.json`; examples in this reference use exactly those field names and enums.

EasyEDA window IDs, bridge ports, document UUIDs, API signatures, retries, ownership, and routes belong in Run State, capability reports, operation journals, or evidence. They are not electrical design truth.

## Root contract

Required root fields are:

```json
{
  "schema_version": "2.0",
  "document_type": "electrical_pack",
  "artifact_id": "electrical-pack-001",
  "revision": 1,
  "status": "planned",
  "provenance": {
    "source": "approved brief",
    "producer": "ploo",
    "time": "2026-01-01T00:00:00Z",
    "hash": "sha256:..."
  },
  "evidence": [],
  "dependencies": [],
  "electrical_requirements": {
    "functional_blocks": [],
    "supply_inputs": [],
    "power_budget": [],
    "environmental_constraints": [],
    "safety_constraints": [],
    "assumptions": []
  },
  "power_domains": [],
  "interfaces": [],
  "selected_devices": [],
  "schematic": {
    "artifact_id": null,
    "revision": null,
    "status": "not_started",
    "freeze_decision_id": null,
    "source_hash": null,
    "strict_drc": {
      "ruleset_ref": null,
      "fatal": null,
      "error": null,
      "warning": null,
      "exemptions": [],
      "evidence_refs": []
    },
    "critical_net_result_ids": [],
    "nc_whitelist": [],
    "library_revisions": [],
    "evidence_refs": []
  },
  "pcb": {
    "artifact_id": null,
    "revision": null,
    "status": "not_started",
    "candidate_decision_id": null,
    "source_hash": null,
    "schematic_source_hash": null,
    "board_constraint_ref": null,
    "layer_count": null,
    "layer_count_decision_id": null,
    "stackup_source": null,
    "stackup_decision_id": null,
    "evt_plan_ref": null,
    "drc": {
      "ruleset_ref": null,
      "fatal": null,
      "error": null,
      "warning": null,
      "exemptions": [],
      "evidence_refs": []
    },
    "evidence_refs": []
  },
  "component_bindings": [],
  "net_contracts": [],
  "rule_requirements": [],
  "verification_requirements": [],
  "verification_results": [],
  "open_items": []
}
```

Root status uses only `planned`, `waiting_user_decision`, `implemented-unverified`, `verified`, `stale`, or `blocked`. It describes this contract revision, not hardware maturity.

The nested schematic and PCB statuses express implementation maturity. Therefore a verified Electrical Pack may still describe a frozen schematic before PCB work begins; it must not be interpreted as a verified PCB. `pcb.evt_plan_ref` is null unless PCB status is exactly `waiting_evt`.

Each dependency records `artifact_id`, `revision`, `content_hash`, affected `facets`, and the `on_change` policy (`ignore | review | rebuild`). Run State owns the downstream invalidation reason and affected descendants. Create a new revision rather than overwriting frozen truth.

## Requirements, sources, and quantities

Every requirement record contains:

```json
{
  "id": "req-input-5v",
  "statement": "Accept a regulated 5 V input.",
  "status": "confirmed",
  "source_refs": ["decision-power-input-001"]
}
```

Source status is `confirmed | assumed | missing | conflict`. Do not convert `missing` or `conflict` into an assumption. If it changes architecture, pin roles, safety, power, interfaces, or a critical component, open a user decision gate.

Quantities always include `value`, `unit`, `status`, and `source_refs`:

```json
{
  "value": 3.3,
  "unit": "V",
  "status": "confirmed",
  "source_refs": ["datasheet-controller-rev-a"]
}
```

Lengths use millimeters. Other physical quantities use explicit engineering units.

## Power domains and interfaces

A power domain records its source domains, sink devices, nominal voltage, current requirement, sequencing, protection, source status, and evidence references. Keep input power, converted rails, grounds, and analog references distinct unless a user-approved electrical contract explicitly joins them.

An interface records logical endpoints and signals, while `shared_interface_ids` link to connector/opening geometry in Interface Control:

```json
{
  "id": "if-usb",
  "type": "usb",
  "endpoint_a": "external-usb-c",
  "endpoint_b": "controller",
  "signals": ["USB_DP", "USB_DM"],
  "electrical_constraints": ["Keep D+ and D- as a named pair."],
  "shared_interface_ids": ["connector-usb", "opening-usb"],
  "status": "confirmed",
  "source_refs": ["decision-interface-001"]
}
```

Changing connector position usually invalidates PCB placement and enclosure geometry. Changing connector pinout invalidates both schematic and PCB descendants.

## Selected devices

Selected devices use `selection_status: user_confirmed | user_approved_provisional`. Agent recommendations never populate this field.

```json
{
  "id": "device-controller",
  "role": "controller",
  "manufacturer_part": "Synthetic MCU A",
  "selection_status": "user_confirmed",
  "decision_id": "decision-controller-001",
  "electrical_constraints": ["3.3 V I/O"],
  "package_requirement": "Verified QFN footprint",
  "source_refs": ["decision-controller-001"]
}
```

## Schematic contract and freeze

The schematic object uses:

```json
{
  "artifact_id": "schematic-001",
  "revision": 2,
  "status": "frozen",
  "freeze_decision_id": "decision-schematic-freeze-001",
  "source_hash": "sha256:...",
  "strict_drc": {
    "ruleset_ref": "rules-schematic-strict-001",
    "fatal": 0,
    "error": 0,
    "warning": 0,
    "exemptions": [],
    "evidence_refs": ["evidence-schematic-drc-001"]
  },
  "critical_net_result_ids": ["result-usb-dp", "result-usb-dm"],
  "nc_whitelist": ["U1.7"],
  "library_revisions": ["controller-symbol@3"],
  "evidence_refs": ["evidence-schematic-export-001"]
}
```

Schematic status is `not_started | draft | conditional | frozen | blocked`. Freeze requires:

- a user freeze decision tied to the exact revision and source hash
- strict DRC counts of zero for fatal, error, and warning, with reliable evidence
- matching critical-net endpoint sets and an explicit NC whitelist
- confirmed symbol-to-footprint bindings, Pin 1, polarity, connector, and FPC orientation
- recorded library revisions
- at least one confirmed electrical requirement, power domain, interface contract, rule, and `schematic_freeze` `must` verification result; empty arrays cannot prove a frozen design

Warnings or accepted exceptions remain `conditional`; they are not strict freeze. If a frozen source changes, update the root artifact status to `stale`, create a new revision, and block PCB work that references the old hash.

## Component bindings

Bindings use flat, provider-neutral symbol pins and footprint pads:

```json
{
  "id": "binding-j1",
  "refdes": "J1",
  "device_id": "device-usb-c",
  "symbol_pins": ["A6", "A7"],
  "footprint": {
    "id": "usb-c-footprint",
    "version": "2",
    "pads": ["A6", "A7"],
    "pin1_marker": "A1 triangle"
  },
  "pin_pad_map": [
    {"symbol_pin": "A6", "pcb_pad": "A6"},
    {"symbol_pin": "A7", "pcb_pad": "A7"}
  ],
  "polarity": "not_applicable",
  "fpc_orientation": null,
  "status": "confirmed",
  "decision_id": "decision-binding-j1-001",
  "evidence_refs": ["evidence-binding-j1"]
}
```

Binding status is `confirmed | provisional | blocked`. Every symbol pin must map once to a real pad. Equal pin and pad counts do not prove correctness. A confirmed binding needs a footprint version, a usable Pin 1 marker, non-conflicting polarity, and reliable evidence.

For FPC connectors, `fpc_orientation` records `contact_side`, `insertion_direction`, and `pin1_direction`. `contact_side: unknown`, an unverified physical Pin 1, or an uncertain top/bottom contact blocks final placement and routing.

## Net contracts

```json
{
  "id": "net-usb-dp",
  "name": "USB_DP",
  "net_class": "differential_signal",
  "expected_endpoints": ["J1.A6", "U1.10"],
  "actual_endpoints": ["J1.A6", "U1.10"],
  "allow_branches": false,
  "layout_constraints": ["Pair with USB_DM"],
  "compare_status": "match",
  "evidence_refs": ["evidence-net-usb-dp"]
}
```

Compare endpoint sets, not just names. `compare_status` is `pending | match | mismatch | blocked`; a `match` result must have identical expected and actual endpoint sets. Check each side of D+/D- and other paired signals independently.

## PCB contract and candidate gate

```json
{
  "artifact_id": "pcb-001",
  "revision": 1,
  "status": "pcb_candidate",
  "candidate_decision_id": "decision-pcb-candidate-001",
  "source_hash": "sha256:...",
  "schematic_source_hash": "sha256:...",
  "board_constraint_ref": {
    "artifact_id": "interface-control-001",
    "revision": 3,
    "content_hash": "sha256:..."
  },
  "layer_count": 2,
  "layer_count_decision_id": "decision-pcb-layer-count-001",
  "stackup_source": "approved-fabricator-stackup-001",
  "stackup_decision_id": "decision-pcb-stackup-001",
  "evt_plan_ref": null,
  "drc": {
    "ruleset_ref": "rules-pcb-strict-001",
    "fatal": 0,
    "error": 0,
    "warning": 0,
    "exemptions": [],
    "evidence_refs": ["evidence-pcb-drc-001"]
  },
  "evidence_refs": ["evidence-pcb-source-export-001"]
}
```

PCB status is `not_started | draft | pcb_candidate | waiting_evt | blocked`. There is no production-ready status.

Before `pcb_candidate` or `waiting_evt`, require:

- the current schematic is `frozen`
- the same approved Interface Control revision is used by PCB and CAD consumers
- user-decided board outline, layer count, stack-up, holes, connectors, FPC direction, keep-outs, and height zones
- confirmed component bindings and matching critical net contracts
- strict final DRC with zero fatal, error, and warning and reliable evidence
- all pre-EVT `must` verification requirements have passing evidence
- a user candidate decision referencing current hashes
- a verified cross-domain check whose evidence matches PCB thickness, holes, connectors, height zones, and antenna keep-outs against the same Interface Control revision (and CAD revision when mechanical work is selected)

Device selection, confirmed footprint/Pin 1/FPC binding, layer count, and stack-up each carry a dedicated Decision Gate ID. The final schematic freeze or PCB candidate selection does not retroactively prove those earlier material choices.

## Rules and verification

`rule_requirements[]` contains `id`, `category`, textual `rule`, `source`, and source `status`. Categories are `power`, `signal`, `layout`, `thermal`, `rf`, `safety`, `service`, or `manufacturing`. Keep computed trace geometry tied to a real stack-up source; do not infer it from an impedance target.

`verification_requirements[]` contains `id`, `stage`, `method`, `pass_condition`, `priority`, and allowed `evidence_required`. Stage is `schematic_freeze | pcb_candidate | evt`. `verification_results[]` links to a requirement and uses `pending | pass | fail | waived`. A `pass` must include every evidence type listed by the requirement and at least one reliable source; a user self-report alone is not sufficient. EVT-stage items may remain pending at `pcb_candidate` and `waiting_evt`, because those states explicitly precede physical validation.

`open_items[]` records `question`, `status`, `blocking_stage`, `impact`, `waivable`, and its decision ID. `resolved` and `accepted_provisional` both require a resolved user `open_item_resolution` Decision Gate bound to the current Electrical Pack. `accepted_provisional` is legal only when `waivable: true`; a still-open item with a blocking stage prevents the corresponding freeze or candidate gate.

## EasyEDA unit boundary

The public contract uses millimeters. Convert only at the adapter boundary:

```text
PCB:       1 mil = 0.0254 mm
Schematic: 0.01 inch = 0.254 mm
```

Record the source value, native value, round-trip value, and error. Before writing, reject mixed-domain conversion, out-of-board coordinates, and suspicious 10x scale changes.

## Invalidation and EVT boundary

- Device, pin, net, or binding changes invalidate schematic freeze and PCB descendants.
- Board outline, holes, connector position, battery/FPC volume, or height-zone changes invalidate affected PCB placement and enclosure descendants, not unrelated schematic networks.
- Layer count or stack-up changes invalidate PCB rules, routing, DRC, and candidate status.
- Route changes invalidate execution plans and journals, not already verified electrical truth.
- EasyEDA connection or permission failure opens a new user route gate; it does not rewrite the Electrical Pack.

Static design checks end at `pcb_candidate`. `waiting_evt` requires `evt_plan_ref` to resolve to a verified Run State `evt_plan` artifact whose exact dependency is the current PCB candidate. It still awaits physical fabrication, assembly, power, interface, signal, thermal, RF, ESD, and mechanical validation.
