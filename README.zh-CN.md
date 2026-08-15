# product-loop

**语言: 简体中文 | [English](README.md)**

`product-loop` 是一个开放、可跨 Agent 移植的 Skill,用于编排小型硬件产品的概念视觉、工业设计、机械建模、原理图与 PCB、用户跟画以及下游交接。

它的核心规则很简单:Agent 可以在用户已批准的路线内检查、推荐并执行可逆步骤,但每条路线是否执行、由谁执行,始终由用户决定。

## 无需 Fusion、EasyEDA 或生成类插件即可使用

核心 Skill 是一个与供应商无关的规划与决策编排器。Fusion 360 MCP、EasyEDA API/Skill,以及图片或视频生成器都是可选集成,不是安装依赖。

| 可用工具 | Product Loop 仍可完成 |
| --- | --- |
| 没有任何 MCP 或插件 | 需求、架构、Design Pack、Electrical Pack、Interface Control、验收计划、跟画步骤和外部交接 |
| 图片/视频供应商 | 同样的核心工作流,外加经用户批准的概念视觉 |
| CAD 供应商 | 同样的核心工作流,外加经用户批准的直接机械执行 |
| EasyEDA 供应商 | 同样的核心工作流,外加经用户批准的直接或混合原理图/PCB 执行 |

缺少工具只会改变当前哪些路线可选。Product Loop 不得在未经用户重新决策的情况下安装可选供应商、自行选择降级方案,或把规划变成写操作。辅助脚本仅使用 Python 3 标准库。

## V2.1 新增

- 面向 Codex、Claude Code、Cursor 和 OpenClaw 的原生 Agent Skills 安装指引。
- 为能读取目录但不支持原生 Skill 发现的 Agent 提供手动入口。
- 严格分离工作流可移植性与可选的 CAD、EDA、图片、视频或 MCP 能力。
- 当前 Codex 个人安装路径,以及旧版 `~/.codex/skills` 用户的安全迁移路径。

V2.1 不改变 V2 的产物 Schema。合法的 `schema_version: 2.0` 文件保持兼容。

## V2 引入

- 只读能力探测之后的强制用户路线门禁(Route Gate)。
- 相互独立的视觉、机械、原理图和 PCB 路线。
- 直接、跟画、混合、仅规格说明和交接五种执行路径。
- 与供应商无关的 Design Pack、Electrical Pack、Interface Control 和 Run State 契约。
- 带读回、证据和恢复能力的 Fusion 360 MCP 与 EasyEDA 适配器协议。
- 冲突门禁、依赖感知失效、可恢复状态和带证据的声明。

Product Loop 产出的是设计候选方案和 EVT 输入。它不对 DFM、模具、公差链、合规性或量产发布作认证。

## 仓库结构

```text
product-loop/
├── core/
│   ├── SKILL.md
│   ├── agents/
│   ├── references/
│   ├── schemas/
│   └── scripts/
├── tests/
├── examples/
└── assets/diagrams/
```

可安装的 Skill 是内层 `core/` 目录。示例是公开的合成数据,不随 Skill 安装。

## 核心产物

- `design-pack.v2.json`:产品、器件、外观、结构和验收真相。
- `electrical-pack.v2.json`:电气架构、引脚、网络、封装、原理图和 PCB 约束。
- `interface-control.v2.json`:外壳与电路板共享的毫米级几何接口。
- `run-state.v2.json`:路线、决策、能力、产物、依赖、证据和执行状态。

## 路线选择

- 视觉:跳过、图片、视频或图片+视频。
- 机械:跳过、仅规格说明、直接 MCP、跟画或交接。
- 原理图:跳过、直接、跟画、混合或交接。
- PCB:跳过、直接、跟画、混合或交接。

能力不可用时绝不静默降级。Product Loop 会暂停并请用户选择新路线。

## 辅助脚本

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
python3 core/scripts/evaluate_behavior_contracts.py --cases core/evals/product-loop-v2.jsonl --responses CAPTURED_RESPONSES.jsonl
```

`adapter_contracts.py` 提供纯安全校验:Fusion/EasyEDA 单元边界、写恢复分类、每次调用的危险工具授权、EasyEDA 身份/哈希预检,以及 CAD–PCB 共享几何比对。供应商写操作必须通过同进程的主机事务完成:授权确切的 bundle、执行只读预检、调用 `reserve_execution(...)`、对预留快照重新授权、消费一次性租约、单次调用供应商并记录回读。CLI 有意不暴露预留机制,因为它无法保存密封令牌,也无法保证预检确实发生过。决策引用是溯源指针,不是加密认证:主机必须提供从真实用户消息或审批记录中取得的稳定引用。合成的黄金 bundle 位于 `examples/v2-orchestrator-demo/`。行为用例和黄金捕获结果位于 `core/evals/`;评估器接受来自真实 Skill 运行捕获的结果,缺少保护措施或出现被禁止行为时判定失败。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 安装

克隆仓库,然后安装内层 `core/` 目录。推荐使用符号链接,因为之后 `git pull --ff-only` 拉取的更新对所有链接的主机立即可见。

当前 Codex 个人发现路径:

```bash
git clone https://github.com/Muye2026/product-loop.git
cd product-loop
skills_root="$HOME/.agents/skills"
mkdir -p "$skills_root"
ln -s "$(pwd)/core" "$skills_root/product-loop"
```

Codex、Claude Code、Cursor、OpenClaw、复制式安装、旧版 Codex 路径、更新、回滚和主机能力边界,详见 [AGENT_PORTABILITY.md](AGENT_PORTABILITY.md)。基于复制的当前 Codex 安装,请仅在目标目录尚不存在时,从仓库根目录执行:

```bash
skills_root="$HOME/.agents/skills"
mkdir -p "$skills_root"
if [ -e "$skills_root/product-loop" ]; then
  echo "product-loop already exists; follow UPGRADING.md"
else
  cp -R core "$skills_root/product-loop"
fi
```

安装或更新后,如果主机缓存了 Skill 发现结果,请启动新的 Agent 任务。V1 或 V2 用户应遵循 [UPGRADING.md](UPGRADING.md),其中涵盖符号链接与复制安装、安全备份、V1 数据迁移、V2.1 路径兼容、验证和回滚。发布变更摘要见 [CHANGELOG.md](CHANGELOG.md)。

## 维护者规则

- 保持 `SKILL.md` 精简,详细规则通过一级引用下放。
- 只使用合成示例;不得嵌入私人项目数据、本机路径、凭据或真实文档 ID。
- 提交前检查 `.gitignore`、`git status --short`、未跟踪文件、生成产物、缓存、日志、临时文件和机密信息。
