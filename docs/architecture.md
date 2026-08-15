# Ploo 架构:一个核心,多套宿主外壳 / Architecture

[English](#english) · [中文](#中文)

## English

### Layers

```text
┌─────────────────────────────────────────────────────────────┐
│ Hosts: Codex · Claude Code · Cursor · OpenClaw ·            │
│        DeepSeek Harness · WorkBuddy · terminal              │
└──────────────▲───────────────────────────────┬──────────────┘
               │ Agent Skills format            │ host-specific adapters
┌──────────────┴───────────────────────────────▼──────────────┐
│ integrations/  (thin shells — reference or snapshot,        │
│  cli/ · dsh/ · workbuddy/     never duplicate rules)        │
└──────────────────────────────▲──────────────────────────────┘
                               │ single source of truth
┌──────────────────────────────┴──────────────────────────────┐
│ core/  SKILL.md + references/ + schemas/ + scripts/ + evals │
│        (provider-neutral, Python 3 stdlib only)             │
└─────────────────────────────────────────────────────────────┘
```

### The one rule

`core/` is the only place workflow rules, contracts, and deterministic helpers live. Every integration is a **thin shell**: it either points the host at `core/` (Agent Skills symlink, WorkBuddy entrypoint) or ships a byte-identical snapshot of it (the DSH plugin's `assets/core/`, refreshed by `integrations/dsh/scripts/sync-core.mjs` and enforced in CI by `verify.mjs` plus `tests/test_integrations.py`). No adapter may restate, translate, or soften a workflow rule.

### Per-integration decisions

- **Agent Skills hosts** — no adapter needed; `core/` already is the open Agent Skills folder. Install = symlink `core/` into the host's skill root. See [AGENT_PORTABILITY.md](../AGENT_PORTABILITY.md).
- **`ploo` CLI** (`integrations/cli/`) — a stdlib-only argparse dispatcher. It resolves the core via `--core`, `$PLOO_CORE`, the installing checkout, then cwd ancestors, and forwards every subcommand to the matching script. Passthrough subcommands bypass argparse so `--flags` reach the scripts verbatim.
- **DeepSeek Harness** (`integrations/dsh/`) — a bundle plugin with **zero runtime dependencies**: tool definitions are hand-written against the registry's raw-definition contract instead of importing helper packages. It registers the runtime `ploo` skill (content = core `SKILL.md` body + a pointer to the on-disk core) and eight `ploo_*` tools that spawn the core scripts with cooperative cancellation. Non-zero exits are reported, not raised. The `profile/ploo/` preset boots a dedicated agent; install from a local path today, publish to npm later.
- **WorkBuddy** (`integrations/workbuddy/`) — a WorkBuddy-frontmatter `SKILL.md` that defers to `core/SKILL.md`; install = symlink into `~/.workbuddy/connectors/skills/`.

### Safety boundary

Adapters never widen authority. Route selection, freezes, conflict resolution, and provider writes stay behind the user gates in `core/SKILL.md`; the DSH tools and `ploo` subcommands only wrap the deterministic validators and state helpers. A capability that disappears mid-run must surface as `waiting_user_decision`, never a silent fallback.

### Verification matrix

| Layer | Offline check | Live check |
| --- | --- | --- |
| core | `python3 -m unittest discover -s tests -v` | smoke prompt in any host |
| cli | `python3 -m unittest discover -s integrations/cli/tests -v` | `ploo validate design-pack examples/v2-orchestrator-demo/design-pack.v2.json` |
| dsh | `node integrations/dsh/scripts/verify.mjs` | `dsh --profile ploo` boots; all eight `ploo_*` tools visible |
| workbuddy | `tests/test_integrations.py` frontmatter checks | skill discovered after linking into `~/.workbuddy/connectors/skills/` |

## 中文

### 分层

```text
┌─────────────────────────────────────────────────────────────┐
│ 宿主:Codex · Claude Code · Cursor · OpenClaw ·              │
│       DeepSeek Harness · WorkBuddy · 终端                   │
└──────────────▲───────────────────────────────┬──────────────┘
               │ Agent Skills 格式              │ 各宿主专用适配器
┌──────────────┴───────────────────────────────▼──────────────┐
│ integrations/  薄外壳(引用或快照,绝不复制规则)            │
│  cli/ · dsh/ · workbuddy/                                    │
└──────────────────────────────▲──────────────────────────────┘
                               │ 唯一真相来源
┌──────────────────────────────┴──────────────────────────────┐
│ core/  SKILL.md + references/ + schemas/ + scripts/ + evals │
│        (供应商中立,仅 Python 3 标准库)                     │
└─────────────────────────────────────────────────────────────┘
```

### 一条铁律

工作流规则、契约和确定性工具只存在于 `core/`。每个接入层都是**薄外壳**:要么把宿主指向 `core/`(Agent Skills 软链、WorkBuddy 入口),要么携带逐字节一致的快照(DSH 插件的 `assets/core/`,由 `sync-core.mjs` 刷新,CI 用 `verify.mjs` + `tests/test_integrations.py` 防止漂移)。任何适配层都不得复述、翻译或放宽工作流规则。

### 各接入层的设计决策

- **Agent Skills 宿主** —— 无需适配层;`core/` 本身就是开放的 Agent Skills 目录,软链安装即可。
- **`ploo` CLI** —— 仅标准库的 argparse 分发器;核心目录解析顺序:`--core` → `$PLOO_CORE` → 安装它的 checkout → 向上遍历当前目录;透传类子命令绕过 argparse,保证 `--flags` 原样到达脚本。
- **DeepSeek Harness** —— **零运行时依赖**的 bundle 插件:工具定义直接按注册表的原始定义契约手写,不 import 任何辅助包;注册运行时 `ploo` Skill(内容 = core 的 SKILL.md 正文 + 磁盘上核心目录指针)和 8 个 `ploo_*` 工具(以协作式取消 spawn 核心脚本);非零退出按报告处理;`profile/ploo/` 预设可一键启动专用 Agent;当前本地路径安装,后续可发 npm。
- **WorkBuddy** —— WorkBuddy 专用 frontmatter 的 `SKILL.md`,正文把权威工作流指回 `core/SKILL.md`。

### 安全边界

适配层永不扩大权限。路线选择、冻结、冲突裁决和供应商写操作仍由 `core/SKILL.md` 的用户门禁控制;DSH 工具和 `ploo` 子命令只封装确定性校验器与状态助手。能力在运行中消失时必须回到 `waiting_user_decision`,绝不静默降级。
