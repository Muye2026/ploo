# Ploo for WorkBuddy

[English](#english) · [中文](#中文)

## English

WorkBuddy-format entrypoint for Ploo. [`SKILL.md`](SKILL.md) carries the WorkBuddy frontmatter (`description_zh` / `description_en` / `allowed-tools`) and points the agent at `core/SKILL.md` as the authoritative workflow, so no workflow rules are duplicated.

### Install

```bash
repo_root=/path/to/ploo
mkdir -p "$HOME/.workbuddy/connectors/skills"
ln -s "$repo_root/integrations/workbuddy" "$HOME/.workbuddy/connectors/skills/ploo"
```

Restart WorkBuddy (or start a new task) and ask: "用 Ploo 规划一个小型桌面硬件,先只读探测能力,停在路线门禁。" — a passing run discovers the skill, loads the core workflow, and waits for your route choices.

### Optional providers

Attach Fusion 360 or EasyEDA MCP servers through `~/.workbuddy/mcp.json` (the host's MCP configuration). Without them, the planning, contract, acceptance, guided, and handoff tracks remain fully available.

## 中文

Ploo 的 WorkBuddy 格式入口。[`SKILL.md`](SKILL.md) 使用 WorkBuddy 专用 frontmatter(`description_zh` / `description_en` / `allowed-tools`),并指引 Agent 加载 `core/SKILL.md` 作为权威工作流,不复制任何工作流规则。

### 安装

```bash
repo_root=/path/to/ploo
mkdir -p "$HOME/.workbuddy/connectors/skills"
ln -s "$repo_root/integrations/workbuddy" "$HOME/.workbuddy/connectors/skills/ploo"
```

重启 WorkBuddy(或新建任务)后提问:"用 Ploo 规划一个小型桌面硬件,先只读探测能力,停在路线门禁。"——能看到 Skill 被发现、核心工作流被加载、并停在路线选择处即为成功。

### 可选供应商

通过 `~/.workbuddy/mcp.json` 挂载 Fusion 360 或 EasyEDA 的 MCP 服务。没有它们时,规划、契约、验收、跟画和交接路线完全可用。
