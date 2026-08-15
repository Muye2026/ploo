# ploo

**Languages: English | [简体中文](README.zh-CN.md)**

`ploo` is an open, agent-portable skill for orchestrating a small hardware product across concept visuals, industrial design, mechanical modeling, schematic and PCB work, guided user operation, and downstream handoff.

Its central rule is simple: the agent may inspect, recommend, and execute reversible steps inside an approved route, but the user decides whether each track runs and who performs it.

## Works without Fusion, EasyEDA, or generation plugins

The core skill is a provider-neutral planning and decision orchestrator. Fusion 360 MCP, EasyEDA APIs/skills, and image or video generators are optional integrations, not install dependencies.

| Available tools | Ploo can still do |
| --- | --- |
| No MCP or plugin | Requirements, architecture, Design Pack, Electrical Pack, Interface Control, acceptance planning, guided steps, and external handoff |
| Image/video provider | The same core workflow plus user-approved concept visuals |
| CAD provider | The same core workflow plus user-approved direct mechanical execution |
| EasyEDA provider | The same core workflow plus user-approved direct or hybrid schematic/PCB execution |

Missing tools only change which routes are currently eligible. Ploo must not install an optional provider, choose a fallback, or convert planning into a write operation without a new user decision. The helper scripts use only the Python 3 standard library.

## Capabilities

- A mandatory user Route Gate after read-only capability discovery.
- Independent visual, mechanical, schematic, and PCB tracks.
- Direct, guided, hybrid, specification-only, and handoff execution paths.
- Provider-neutral Design Pack, Electrical Pack, Interface Control, and Run State contracts.
- Optional Fusion 360 MCP and EasyEDA adapter protocols with readback, evidence, and recovery.
- Conflict gates, dependency-aware invalidation, resumable state, and evidence-backed claims.

Ploo produces design candidates and EVT inputs. It does not certify DFM, tooling, tolerance stacks, compliance, or manufacturing release.

V3.0 renamed the project from product-loop to ploo; the artifact contracts remain `schema_version: 2.0`. Release history lives in [CHANGELOG.md](CHANGELOG.md).

## Repository layout

```text
ploo/
├── core/
│   ├── SKILL.md
│   ├── agents/
│   ├── references/
│   ├── schemas/
│   └── scripts/
├── integrations/
│   ├── cli/          # ploo terminal entrypoint
│   ├── dsh/          # DeepSeek Harness bundle plugin + profile preset
│   └── workbuddy/    # WorkBuddy skill entrypoint
├── docs/             # architecture notes
├── tests/
├── examples/
└── assets/diagrams/
```

The installable skill is the `core/` directory. Examples are public synthetic fixtures and are not installed with the skill. Architecture notes live in [docs/architecture.md](docs/architecture.md).

## Integrations

One core, thin host adapters. The core stays the single source of truth; every adapter references or snapshots it and never duplicates its rules.

| Host | Integration | Entry point |
| --- | --- | --- |
| Agent Skills hosts (Codex, Claude Code, Cursor, OpenClaw) | `core/` itself follows the open Agent Skills format | [AGENT_PORTABILITY.md](AGENT_PORTABILITY.md) |
| Terminal | `ploo` CLI dispatching to `core/scripts/` | [integrations/cli/](integrations/cli/) |
| DeepSeek Harness | Bundle plugin: runtime skill, eight `ploo_*` tools, profile preset | [integrations/dsh/](integrations/dsh/) |
| WorkBuddy | WorkBuddy-format skill entrypoint | [integrations/workbuddy/](integrations/workbuddy/) |

## Core artifacts

- `design-pack.v2.json`: product, component, appearance, structure, and acceptance truth.
- `electrical-pack.v2.json`: electrical architecture, pin, net, footprint, schematic, and PCB constraints.
- `interface-control.v2.json`: shared millimeter-based geometry across enclosure and board.
- `run-state.v2.json`: routes, decisions, capabilities, artifacts, dependencies, evidence, and execution state.

## Route choices

- Visualization: skip, image, video, or image+video.
- Mechanical: skip, spec (specification-only), direct MCP, guided, or handoff.
- Schematic: skip, direct, guided, hybrid, or handoff.
- PCB: skip, direct, guided, hybrid, or handoff.

Unavailable capabilities never trigger silent fallback. Ploo pauses and asks the user to choose a new route.

## Helper scripts

```bash
python3 core/scripts/migrate_v1_to_v2.py INPUT --output-dir NEW_DIRECTORY
python3 core/scripts/validate_v2.py design-pack INPUT
python3 core/scripts/validate_bundle.py --run-state RUN_STATE --design-pack DESIGN_PACK --electrical-pack ELECTRICAL_PACK --interface-control INTERFACE_CONTROL --review-results REVIEW_RESULTS
python3 core/scripts/manage_run_state.py validate RUN_STATE
python3 core/scripts/manage_run_state.py resolve-routes RUN_STATE OUTPUT --decision-ref chat-message:route-choice-001 --visualization image --mechanical direct --schematic guided --pcb hybrid
python3 core/scripts/manage_run_state.py open-decision RUN_STATE OUTPUT --gate DECISION_GATE_JSON
python3 core/scripts/manage_run_state.py resolve-decision RUN_STATE OUTPUT --selected-option freeze --decision-ref approval-record:freeze-001
python3 core/scripts/manage_run_state.py record-execution RUN_STATE OUTPUT --step-id STEP --attempt-id ATTEMPT --status completed --result-fingerprint sha256:READBACK
python3 core/scripts/manage_run_state.py change-route RUN_STATE OUTPUT --track mechanical --decision-id DECISION
python3 core/scripts/manage_run_state.py stale RUN_STATE OUTPUT --artifact-id interface-control --revision 3 --reason "Board outline changed"
python3 core/scripts/normalize_design_pack.py INPUT OUTPUT
python3 core/scripts/build_review_matrix.py INPUT OUTPUT --run-state RUN_STATE --review-results REVIEW_RESULTS
python3 core/scripts/emit_handoff_brief.py INPUT OUTPUT --run-state RUN_STATE --handoff-data HANDOFF_DATA
python3 core/scripts/evaluate_behavior_contracts.py --cases core/evals/ploo-v2.jsonl --responses CAPTURED_RESPONSES.jsonl
```

`adapter_contracts.py` supplies pure safety checks for Fusion/EasyEDA unit boundaries, write recovery classification, per-call dangerous-tool authorization, EasyEDA identity/hash preflight, and CAD–PCB shared-geometry comparison. Provider writes must run through the reserved-write sequence documented in [core/references/workflow-state-schema.md](core/references/workflow-state-schema.md). The CLI intentionally does not expose reservation because it cannot preserve the sealed token or guarantee that preflight occurred. Decision references are provenance pointers, not cryptographic authentication: the host must supply a stable reference obtained from the real user message or approval record. The synthetic golden bundle is in `examples/v2-orchestrator-demo/`. Behavior cases and golden captured outcomes live in `core/evals/`; the evaluator accepts outcomes captured from real skill runs and fails on missing safeguards or prohibited actions.

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Install

Clone the repository, then install the inner `core/` directory. A symlink is recommended because future `git pull --ff-only` updates are immediately visible to every linked host.

For current Codex personal discovery:

```bash
git clone https://github.com/Muye2026/ploo.git
cd ploo
skills_root="$HOME/.agents/skills"
mkdir -p "$skills_root"
ln -s "$(pwd)/core" "$skills_root/ploo"
```

Codex, Claude Code, Cursor, OpenClaw, copied installs, legacy Codex paths, updates, rollback, and host capability boundaries are documented in [AGENT_PORTABILITY.md](AGENT_PORTABILITY.md). For a copy-based current Codex install, run this from the repository root only when the destination does not already exist:

```bash
skills_root="$HOME/.agents/skills"
mkdir -p "$skills_root"
if [ -e "$skills_root/ploo" ]; then
  echo "ploo already exists; follow UPGRADING.md"
else
  cp -R core "$skills_root/ploo"
fi
```

After installing or updating, start a new agent task if the host caches skill discovery. Existing V1 or V2 users should follow [UPGRADING.md](UPGRADING.md); it covers symlink and copied installs, safe backup, V1 data migration, legacy path compatibility, verification, and rollback. Release changes are summarized in [CHANGELOG.md](CHANGELOG.md).

## Maintainer rules

- Keep `SKILL.md` concise and route detailed rules through one-level references.
- Use synthetic examples; do not embed private project data, local paths, credentials, or live document IDs.
- Before committing, inspect `.gitignore`, `git status --short`, untracked files, generated artifacts, caches, logs, temporary files, and secrets.
