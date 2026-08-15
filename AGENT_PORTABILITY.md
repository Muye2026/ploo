# Product Loop V2.1 Agent Portability

Product Loop follows the open [Agent Skills](https://agentskills.io/home) folder format: the installable unit is the inner `core/` directory, with `SKILL.md` as its entrypoint and references, schemas, scripts, and evaluations kept beside it.

The workflow is portable across skills-compatible agents. Tool access is not. A host may run the full planning and decision workflow without Fusion 360, EasyEDA, image generation, video generation, or any MCP server. Direct execution is available only when that host can probe a real provider operation and the user explicitly selects and authorizes that route.

This guide was verified against the linked official documentation on 2026-07-15.

## Compatibility at a glance

| Host | Native Agent Skills support | Recommended discovery path or UI | Typical invocation |
| --- | --- | --- | --- |
| Codex | Yes | Personal: `~/.agents/skills/product-loop`; repository: `.agents/skills/product-loop` | `$product-loop` or automatic matching |
| Claude Code | Yes | Personal: `~/.claude/skills/product-loop`; project: `.claude/skills/product-loop` | `/product-loop` or automatic matching |
| Cursor | Yes in editor and CLI from 2.4 | Add the inner folder from Cursor's Skills/Customize UI at user or workspace scope | `/product-loop` or automatic matching |
| OpenClaw | Yes | Shared: `~/.agents/skills/product-loop`; managed: `~/.openclaw/skills/product-loop`; workspace: `<workspace>/skills/product-loop` | Skill name or slash-command discovery |
| DeepSeek Harness | Yes | Shared: `~/.agents/skills/product-loop`; dsh-only: `~/.dsh/skills/product-loop`; project: `<repo>/.dsh/skills/product-loop` | Session skill catalog or automatic matching |
| WorkBuddy | Yes (variant frontmatter) | Link `~/.workbuddy/connectors/skills/product-loop` to `integrations/workbuddy/` | Automatic matching after restart |
| Other agent | Host-dependent | Give the agent read access to the inner folder and explicitly load `core/SKILL.md` | Manual prompt entrypoint below |

Native discovery means the host can find and progressively load `SKILL.md`. It does not mean the host has the same MCP servers, UI-control tools, permissions, or provider API signatures.

## Clone once

```bash
git clone https://github.com/Muye2026/product-loop.git
cd product-loop
repo_root="$(pwd)"
```

All links below must point to `$repo_root/core`, not the repository root. Keeping one clone and linking each host to the same inner directory makes `git pull --ff-only` update every linked host at once.

## Codex

Current Codex documentation uses `~/.agents/skills` for personal skills and `.agents/skills` for repository-scoped skills:

```bash
mkdir -p "$HOME/.agents/skills"
ln -s "$repo_root/core" "$HOME/.agents/skills/product-loop"
```

Start a new task if the skill does not appear immediately. Existing installations under `${CODEX_HOME:-$HOME/.codex}/skills/product-loop` may continue to work in hosts that still scan the legacy location. Do not create a second visible copy if the old installation is already discovered. See [UPGRADING.md](UPGRADING.md) for a no-data-loss migration path.

Codex-specific UI metadata remains in `core/agents/openai.yaml`; it is optional for other hosts and does not add a provider dependency.

## Claude Code

Claude Code supports personal and project skills and follows symlinked skill directories:

```bash
mkdir -p "$HOME/.claude/skills"
ln -s "$repo_root/core" "$HOME/.claude/skills/product-loop"
```

Use `.claude/skills/product-loop` instead for a project-only installation. Invoke `/product-loop`, or ask Claude to use Product Loop for a hardware-product workflow. Product Loop uses only the standard `name` and `description` frontmatter fields, so it does not depend on Claude-only extensions.

## Cursor

Cursor supports Agent Skills in both the editor and CLI. In current Cursor versions, open the Skills/Customize surface, choose user or workspace scope, and add the inner `$repo_root/core` folder. Confirm that `product-loop` appears in the skills list, then invoke `/product-loop` or describe a matching hardware-planning task.

Cursor's UI and distribution surfaces change more frequently than the open folder format. Prefer the current in-product Skills/Customize flow over copying a path from an older tutorial. If a managed workspace blocks local skills, ask the workspace administrator to distribute the same inner folder at team scope.

## OpenClaw

OpenClaw scans `~/.agents/skills`, so the Codex personal link above can be shared by both hosts. For an OpenClaw-only managed install:

```bash
mkdir -p "$HOME/.openclaw/skills"
ln -s "$repo_root/core" "$HOME/.openclaw/skills/product-loop"
```

For workspace-local installation, OpenClaw can install the inner directory:

```bash
openclaw skills install "$repo_root/core" --as product-loop
```

OpenClaw's Git/local installs and registry-managed installs can have different update behavior. A symlink to a trusted local clone keeps updates explicit and reviewable: inspect the diff, run the tests, then run `git pull --ff-only`.

## DeepSeek Harness

DeepSeek Harness (`dsh`) ships a filesystem skill provider that scans, in rank order: the project `.dsh/skills` directory, the project `.agents/skills` directory, any configured custom roots, the user-level `~/.dsh/skills`, and the shared user-level `~/.agents/skills`. The Codex personal link above is therefore discovered by DeepSeek Harness with no extra setup. A dsh-only install works too:

```bash
mkdir -p "$HOME/.dsh/skills"
ln -s "$repo_root/core" "$HOME/.dsh/skills/product-loop"
```

Project-scoped installs work the same way under `<repo>/.dsh/skills/product-loop` or `<repo>/.agents/skills/product-loop` (the latter doubles as Codex's repository-scoped path).

Verified against `@deepseek-ai/dsh` 0.1.0-rc.6: the skill appears in the session skill catalog and is both model- and user-invocable. For a deeper harness-level integration — host tools wrapping the core scripts, a runtime-embedded skill, and a dedicated `dsh --profile product-loop` preset — see [integrations/dsh/](integrations/dsh/).

## WorkBuddy

WorkBuddy discovers skills from `~/.workbuddy/connectors/skills/<name>/SKILL.md` with a variant frontmatter (`description_zh`, `description_en`, `allowed-tools`, `version`). The [integrations/workbuddy/](integrations/workbuddy/) folder is a ready-made entrypoint in that format; it points the agent at `core/SKILL.md` as the authoritative workflow instead of duplicating rules:

```bash
mkdir -p "$HOME/.workbuddy/connectors/skills"
ln -s "$repo_root/integrations/workbuddy" "$HOME/.workbuddy/connectors/skills/product-loop"
```

MCP providers (Fusion 360, EasyEDA) attach through `~/.workbuddy/mcp.json`; without them the planning layer remains fully usable. See [integrations/workbuddy/README.md](integrations/workbuddy/README.md) for install and verification steps.

## Manual entrypoint for another agent

If an agent can read files but does not natively discover Agent Skills, attach or expose the inner `core/` directory and use this prompt:

```text
Load core/SKILL.md as the authoritative workflow.
Resolve every relative reference from the core directory.
Run read-only capability discovery first.
Present all relevant Route Gate 0 choices and wait for my selection.
Do not generate visuals, model, draw a schematic, draw a PCB, install a provider,
or silently change route without my explicit decision.
```

The agent must be able to read Markdown and JSON. Python 3 is optional for reading the workflow but required to run the deterministic validators and migration helpers.

## Capability tiers

| Available host capability | Allowed Product Loop scope |
| --- | --- |
| File read/write only | Brief, architecture, component comparison, four V2 contracts, acceptance plan, guided steps, and handoff package |
| Image/video provider | The planning scope plus user-approved concept visuals |
| CAD/MCP provider | The planning scope plus user-approved mechanical execution after interface freeze |
| EasyEDA or compatible EDA provider | The planning scope plus user-approved schematic/PCB execution after the required freezes |
| No reliable readback or rollback | Planning, specification, guided, or handoff routes only; direct execution remains unavailable |

Never infer provider support from the host name. A host passes a direct-execution probe only when it exposes the required operation, target identity, permission, expected units, readback, verification, and recovery path at runtime.

## Adapter boundary

Fusion 360 and EasyEDA are optional provider adapters, not universal requirements. Every host integration must preserve the same boundary:

1. Probe real tool names and parameter schemas at runtime.
2. Report eligible, conditional, and unavailable routes without selecting one.
3. Wait for the user's route decision.
4. Bind one Operation Card to one provider operation, target, parameter digest, attempt, and decision record.
5. Perform read-only preflight before a write.
6. Verify with API readback, source export, or a clear screenshot.
7. On failure or lost capability, ask the user to retry, switch route, hand off, or pause; never silently substitute a backend.

An adapter for a different CAD or EDA system may implement the common lifecycle documented in `core/SKILL.md`, but Product Loop must not claim that adapter exists until the host actually exposes and probes it.

## Smoke test

After installation, start a fresh task and ask:

```text
Use Product Loop to plan a small desktop hardware product. Do read-only capability
discovery, explain which direct routes are actually available, and stop at Route Gate 0.
```

A passing result:

- separates visualization, mechanical, schematic, and PCB choices;
- does not assume Fusion, EasyEDA, or generation tools exist;
- does not preselect a route;
- says that a recommendation is not authorization;
- waits for the user before any direct write.

## Update and rollback

For linked installs:

```bash
git -C "$repo_root" pull --ff-only
python3 -m unittest discover -s "$repo_root/tests" -v
```

Start a new host task if discovery is cached. For copied installs, back up the installed folder, replace it with the inner `core/` directory, verify the smoke test, and only then remove the backup. Updating the skill never edits existing CAD/EDA documents or project run data automatically.

V2.1 is a workflow and distribution release. The public artifact contracts remain `schema_version: 2.0`, so valid V2 run files do not require a V2.1 data migration.

## Security

- Review the repository diff before updating a skill that can drive external tools.
- Grant only the filesystem, MCP, browser, or application permissions needed for the selected route.
- Keep `.env`, API tokens, passwords, certificates, private project data, and machine configuration outside the skill folder.
- Treat registry provenance and host discovery as separate from runtime authorization; installation never grants permission to write CAD, EDA, or external systems.

## Official references

- [Agent Skills open standard](https://agentskills.io/home)
- [Codex: Build skills](https://developers.openai.com/codex/skills)
- [Claude Code: Extend Claude with skills](https://code.claude.com/docs/en/skills)
- [Cursor 2.4: Agent Skills in editor and CLI](https://cursor.com/changelog/2-4)
- [Cursor Customize surface](https://cursor.com/changelog)
- [OpenClaw Skills](https://docs.openclaw.ai/skills)
- [DeepSeek Harness](https://github.com/deepseek-ai/DeepSeek-Harness)
