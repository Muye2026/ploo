# EasyEDA Adapter

本规范定义 `ploo` 如何通过可插拔 adapter 把 provider-neutral 的 `electrical-pack.v2.json` 落实到 EasyEDA，同时兼容 API 直控、用户陪画和两者混合执行。它只定义执行边界、能力探测、证据和验收规则，不改变 Design Pack、电气真值或共享接口真值，也不替代器件数据手册、电气设计评审、制板厂叠层计算、样机测试或生产放行。

## 目录

- [适用范围与路线](#scope-and-routes)
- [按操作能力探测](#capability-probe)
- [写入、快照与 readback](#write-and-readback)
- [DRC、网络、封装与单位](#design-verification)
- [操作失败与用户重新选路](#failure-and-route)
- [最终状态与产物](#final-status-and-artifacts)

<a id="scope-and-routes"></a>

## 1. 适用范围

当目标产物包含原理图或 PCB 时使用本适配器。原理图与 PCB 必须分别选择执行路线，因为两者可能拥有不同的文档状态、API 覆盖、权限和用户协作偏好。

适配器必须消费 [electrical-pack-schema.md](electrical-pack-schema.md) 定义的 V2 电气契约，并引用与电气包相同 revision 的 `interface-control.v2.json`。路线、能力报告、操作卡、执行 journal 和失败状态属于 `run-state.v2.json` 及其 evidence artifacts；不得写入电气设计真值。验证结论通过 evidence 引用回填到新 revision 的电气包，不能根据聊天描述、一次 API 返回或用户口头确认直接宣称设计已完成。

本适配器的成功边界仅为：

- `pcb_candidate`：已满足契约内的静态设计检查，可作为打样候选。
- `waiting_evt`：打样候选已冻结，等待 EVT 制板、装配和实测。

不得输出 `production_ready`、`manufacturing_released`、`validated_hardware` 或同义结论。

## 2. 路线模型

### 2.1 原理图与 PCB 独立决策

原理图和 PCB 是 `run-state.v2.json` 中两个独立 track：

- `schematic`
- `pcb`

两个 track 必须分别打开 route-selection gate、分别记录 route 与逐操作 ownership。不得把总体产品路线、原理图路线和 PCB 路线混为一个授权。

允许的组合包括但不限于：

- 原理图由用户陪画，PCB 由 API 直控。
- 原理图由 API 读取和 DRC、用户完成写入，PCB 全程陪画。
- 原理图已有冻结清单，仅对 PCB 重新选择路线。
- 原理图和 PCB 都只生成交接包。

不得用“EasyEDA 已连接”推导原理图和 PCB 都能直控，也不得因其中一条路线失败而自动改变另一条路线。

### 2.2 路线枚举

每个阶段向用户展示以下路线：

- `skip`：不运行该 track。
- `direct`：Agent 通过已验证的 API 执行写入，并通过 API 或等价结构化来源读回验证。
- `guided`：用户在 EasyEDA 中执行操作，Agent 每次只给一个可验收的操作卡，并根据截图、导出或报告验收。
- `hybrid`：同一领域内按操作拆分；通常由 API 负责读取、核网和 DRC，由用户执行没有可靠 API 的写入。run-state 中用逐操作 ownership 表示，不把 `hybrid` 伪装成单一执行者能力。
- `handoff`：当前会话不操作 EasyEDA，只输出明确的下游输入、步骤、阻塞项和验收标准。

`direct` 表示写入能力已经对当前操作验证，不表示所有 EasyEDA API 都可用。能力必须按操作探测。`handoff` 不执行 live mutation。

### 2.3 路线可行性与用户选择

初次 route-selection gate 按以下顺序生成选项：

1. 先读取用户已经表达的协作偏好。用户要求“我动手画”时，只把 `guided` 或 `hybrid` 列为符合该偏好的候选。
2. 运行只读能力探测，不得用正式文档上的试写探测权限。
3. 对计划中的每个操作记录 API 能力和替代执行选项。
4. 只有所有即将执行的写操作均满足直控门禁时，才把 `direct` 标记为当前可执行。
5. 文档表明可能支持直控但写权限尚未验证时，可把 `direct` 标记为“条件可选”；用户选中后，先在其明确授权的临时文档完成可回滚 probe，仍不得写正式目标。
6. 任一操作只能读取、不能可靠写入时，把 `hybrid` 或 `guided` 标记为可行候选，并说明用户需要承担的操作。
7. 输入、环境或证据渠道不足以安全继续时，把 `handoff` 或 `skip` 标记为可行候选，并说明直接实施为何不可用。

能力报告只决定某个路线能否展示为当前可执行、需先修复或不可用，并提供理由和影响；它不能填写 route decision。适配器可以给推荐但必须保持 decision gate 未选择，最终路线只能由用户在 gate 中明确选择。连续执行节奏也不授权 adapter 代替用户选路。

路线决定写入 decision ledger 后不得静默切换。运行期发生连接、权限、签名、文档状态或验证失败时，必须把受影响 track 置为 `waiting_user_decision` 或 `blocked`、打开新的 route-selection gate，并让用户重新选择以下之一：

- 修复条件后重试当前路线。
- 改为 `guided`。
- 改为 `hybrid`。
- 改为 `handoff`。
- 改为 `skip`。

用户明确选择前，不得继续下一项写操作。

### 2.4 Provider-neutral adapter interface

EasyEDA adapter 实现以下语义接口：

```text
probe(context) -> CapabilityReport
plan(pack, artifacts) -> RunPlan
execute_step(step, session) -> StepResult
verify(step, result, checks) -> VerificationResult
rollback(checkpoint) -> RollbackResult
export(formats, artifact_root) -> ArtifactManifest
```

`pack` 传入 Electrical Pack，`artifacts` 传入 Interface Control、用户决策和已批准的上游产物。`RunPlan` 只能使用 provider-neutral 意图，例如“验证关键网络端点”“放置结构约束器件”“应用已确认的网络规则”。EasyEDA 类名、方法名、窗口 ID、文档 UUID 和 bridge 端口只存在于 adapter resolution、capability report、operation journal 或 evidence 中。

<a id="capability-probe"></a>

## 3. 按操作能力探测

能力探测输出到独立的 `eda-capability-report.json`，并由 run-state 的 artifact/evidence 记录引用。每项能力使用：

- `available`：当前目标和当前会话已验证可用。
- `unavailable`：文档、连接、权限或上下文明确不支持。
- `unknown`：尚未安全验证，不能当作可用。

每项还必须记录真实 `provider_operation`、provider-neutral `capability_id`、`risk_class`、参数 schema digest、`evidence`、`limitations`、`route_options_if_unavailable` 和探测时间。真实 API 方法与 capability 必须一一绑定；无法分类或无法唯一映射的写操作保持 unavailable。`route_options_if_unavailable` 只用于下一个用户 gate 的选项展示，不是自动 fallback 指令。

### 3.1 Bridge 探测

1. 扫描端口 `49620-49629`。
2. 校验健康检查或握手中的 `service` 必须等于 `easyeda-bridge`。
3. 记录 bridge 端口和连接状态。
4. bridge 不存在或 EasyEDA 未连接时，只能把 API 能力标记为 `unavailable`，不能据此自动切换路线。

### 3.2 Window 探测

1. 查询所有已连接窗口。
2. 无窗口时阻断 API 操作。
3. 一个窗口时可以设为候选活动窗口，但仍需核对工程和文档。
4. 多个窗口时必须展示窗口 ID 并让用户明确选择。
5. 记录 `window_id`；后续每个写前门禁必须再次核对该窗口仍然连接。

### 3.3 Project 与 Document 探测

对每个领域分别记录：

- 当前工程名称与 UUID。
- 当前活动文档名称、UUID 和类型。
- 目标原理图页或 PCB 文档的 UUID。
- 当前文档是否与操作领域匹配。

PCB API 只能在活动 PCB 文档上执行，原理图 API 只能在活动原理图页上执行。切换工程可能丢弃未保存内容；在无法只读确认保存状态时，必须让用户确认后才能切换。

### 3.4 API 方法探测

每个计划操作都必须单独探测，例如：

- 读取工程和文档。
- 读取原理图器件、引脚、导线和网络。
- 创建或修改原理图图元。
- 读取 PCB 器件、焊盘、网络和图元。
- 同步原理图到 PCB。
- 创建或修改 PCB 图元。
- 设置层、网络类或设计规则。
- 运行 DRC。
- 读取封装与器件库信息。
- 导出结构化源或检查报告。

探测时必须：

1. 阅读对应类文档的完整签名、返回类型和备注。
2. 对 `Promise` 返回使用 `await`。
3. 查阅枚举定义，不得猜测裸数字或字符串。
4. 核对坐标、尺寸和角度单位。
5. 核对方法需要的活动文档类型。
6. 将持续返回错误或 `null` 的已正确调用视为权限或能力问题。

API 文档中不存在的方法视为 `unavailable`。不得根据方法名风格臆造接口。写权限只有在用户先选择条件直控路线、再授权临时文档 probe，并完成可回滚验证后，才能标为 `available`；否则保持 `unknown`。

<a id="write-and-readback"></a>

## 4. 写前门禁

每个 API 写入批次必须生成 `prewrite_gate`，结果只能为 `pass`、`block` 或 `provisional`。`provisional` 只允许用户明确接受的临时板框或粗布局，不允许关键网络布线、最终阻抗规则或候选冻结。

写前门禁先取得 `authorize_execute_step(...)` 返回的全 bundle 执行授权，并核对 token 中的 capability、真实 provider operation、risk class、call、attempt、参数 digest 和 `operation:<material_digest>`；再直接比对已验证操作卡中的 `route_decision_id`、`operation_step_id`、工程/文档 UUID 和输入 artifact hash，与 bridge/API 独立 readback 的实际值。Operation digest 覆盖目标对象、预期变化、禁止触碰项、回滚、验收、所需证据和依赖版本；任一字段变化都会使旧授权失效。不得让调用方用 `route_authorized: true`、`schematic_frozen: true` 或 `hash_matches: true` 之类二手布尔值代替原始 ID/hash。PCB 写入还要精确比对原理图与 Interface Control 的 freeze-decision ID 和当前 hash；任何一个缺失或不一致都应 fail closed。

### 4.1 目标身份

- window、工程、文档 UUID 与已批准操作卡一致。
- 活动文档类型正确。
- 源原理图冻结 hash 与操作卡引用一致。
- 目标对象 ID 存在且唯一。

### 4.2 写前快照

直控写入前必须存在可恢复或可比对的快照。快照优先级为：

1. EasyEDA 版本副本或可恢复工程导出。
2. 目标文档结构化源导出。
3. 与本批相关的图元、网络、封装、坐标和 DRC 基线。

快照记录至少包含：

- `snapshot_id`、时间和证据类型。
- 工程与文档 UUID。
- 相关对象 ID 和状态摘要。
- 关键网络摘要或 hash。
- 当前 DRC 摘要。
- 已验证的回滚方法。

没有足够快照且写入不可可靠撤销时，`direct` 门禁必须失败。

### 4.3 电气和封装检查

- 原理图已经通过严格 DRC，或本批正处于原理图修复阶段。
- 关键网络端点与冻结清单一致。
- 进入 PCB 的每个器件都有已确认封装。
- 符号引脚集合、PCB 焊盘集合和 pin-pad 映射一致。
- Pin 1、极性、二极管方向、LED 方向和连接器方向有证据。
- FPC 额外核对触点面、正反面、插入方向和实物 Pin 1。
- 电池连接器额外核对实际线序和丝印正负极。
- 封装或引脚编号变化后，原理图冻结必须先失效并重新 DRC。

### 4.4 机械和规则检查

- 板框、层数、孔位、限高和结构器件位置已确认，或明确标为临时。
- 叠层、铜厚和介质参数有来源后，才能写入阻抗相关规则。
- 禁布区、天线净空、测试点和装配方向已进入约束契约。
- 写入坐标必须落在合理板框范围内。

### 4.5 Dry Run

执行前必须列出：

- 将创建、删除、移动或修改的对象及数量。
- 每个对象的旧值和目标值。
- 可能受影响的网络、层和规则。
- 明确的 `do_not_touch` 范围。
- 预期读回差异和回滚动作。

用户批准的是带 hash 的具体操作卡；计划变化后必须重新批准。

## 5. 原子执行与 Readback

一个批次只能完成一个语义目标，例如“移动一个接口器件组”或“设置一个网络类”，不能把同步、布局、布线和铺铜混在同一批次。

直控执行顺序固定为：

1. 用完整 bundle 的 `authorized` token 做只读写前门禁，独立回读窗口、工程、文档、输入 hash 和真实 API schema。
2. 读取并保存本批基线。
3. 原子写入本 attempt 的 `execution_reservations`；高风险卡同时预留唯一一次授权。
4. 对更新后的完整 bundle 取得一次性 `reserved` lease；用真实 API 方法和真实参数通过 guard。
5. guard 消费 lease 后，立即只执行 `execution_capability_id` 绑定的一个 API 写入。
6. 校验 API 返回值。
7. 重新读取目标对象、关联网络和必要规则，以 fingerprint 完结 reservation。
8. 比较实际差异与 `expected_delta`。
9. 运行本阶段适用的定向检查或 DRC。
10. 保存证据；验收检查记为 `pass` 或 `fail`，Operation Card 随后按证据进入 `verified`、`implemented-unverified` 或 `blocked`。

一次 API 返回成功不能替代 readback。超时、断线或 `null` 返回时，必须先查询实际文档状态，确认是否已经部分写入；禁止直接重试，以免重复创建或重复移动。

## 6. 用户陪画与混合执行

`guided` 和 `hybrid` 使用与直控完全相同的操作卡和验收条件，只替换执行者。

每次只向用户提供一个操作卡，至少包括：

- 本步目标。
- 精确目标文档和对象。
- EasyEDA 中的操作路径或动作。
- 要输入的值及单位。
- 本步禁止触碰的对象。
- 预期可见结果。
- 撤销方法。
- 用户需要提交的截图、导出或 DRC 报告。

用户完成后，优先用 API 只读核对；API 不可用时使用结构化导出，其次使用清晰截图。只有用户文字回复而无可检查证据时，结果只能标为 `user_self_report`，不能标为已验证。

<a id="design-verification"></a>

## 7. 严格 DRC 与冻结

### 7.1 原理图冻结

原理图只有同时满足以下条件才能标为 `frozen`：

- 严格 DRC：fatal 0、error 0、warning 0。
- 关键网络的端点集合验证通过。
- 未使用引脚具有明确 NC 清单。
- 所有进入 PCB 的器件有封装绑定。
- pin-pad、Pin 1、极性和关键连接器方向通过检查。
- 冻结结果绑定工程、页面、规则集和源 hash。

存在警告豁免时，只能标为 `conditional`，不能标为严格冻结。

### 7.2 PCB 检查节点

至少在以下节点运行适用的 DRC 或结构化检查：

- 原理图同步到 PCB 后。
- 结构器件和板框确认后。
- 关键器件布局后。
- 关键网络布线后。
- 铺铜和最终候选生成后。

最终 `pcb_candidate` 默认要求 fatal 0、error 0、warning 0，并且所有关键网络、封装、Pin 1、极性、单位和机械检查通过。DRC 不覆盖回流路径、天线净空、热设计、实物连接器方向和可制造性实测，这些必须作为独立验收项。

如果当前 DRC API 只能返回布尔值，适配器不得据此伪造 fatal/error/warning 计数。应通过结构化报告、导出或用户在 UI 中运行严格 DRC 的证据补齐计数；无法补齐时，冻结或 candidate gate 保持未通过。

## 8. 网络、封装与方向验证

### 8.1 网络

- 使用“器件位号/引脚号”与“器件位号/焊盘号”的端点集合比较，而不只比较网络名称。
- 关键差分或成对信号必须逐条核对，不允许只检查其中一条。
- 电源域、地、模拟节点、测试点支线和 NC 必须分别有允许规则。
- PCB 同步后记录缺失网络、额外端点、错误合并、错误拆分和未连接数量。

### 8.2 封装与 pin-pad

- 记录封装库、UUID、版本、焊盘集合、焊盘类型和钻孔。
- 符号 pin 与 PCB pad 必须逐一映射；焊盘数量相同不代表映射正确。
- 关键连接器、开关、二极管、LED、IC 和极性器件不得使用未经确认的占位封装进入最终布线。

### 8.3 Pin 1、极性与 FPC

至少交叉核对：

1. 数据手册或制造商封装图。
2. EasyEDA 封装的 Pin 1/极性标记。
3. PCB 丝印和装配方向。

FPC 还必须核对实际物料是顶接或底接、触点朝向、排线正反面和插入后的引脚顺序。无法确认时必须阻断该接口周围的最终布局和布线。

## 9. 单位规则

V2 电气契约统一使用毫米。适配器只在调用 API 的边界转换成本地域单位：

- PCB：`1 native unit = 1 mil = 0.0254 mm`。
- 原理图：`1 native unit = 0.01 inch = 10 mil = 0.254 mm`。

换算公式：

```text
pcb_native = mm / 0.0254
pcb_mm = pcb_native * 0.0254

schematic_native = mm / 0.254
schematic_mm = schematic_native * 0.254
```

所有坐标、长度、线宽和间距都必须记录 `input_mm`、`native_value`、`native_unit` 和 round-trip 结果。API 参数若要求整数，应按照该方法文档和活动网格规则取整，并以半个本地域网格作为最大 round-trip 误差。

写前必须执行：

- round-trip 误差检查。
- 板框或页面合理范围检查。
- 10 倍尺度异常检查。
- 原理图单位和 PCB 单位混用检查。

角度使用 API 文档规定的度数或枚举，不适用上述长度换算。

## 10. 操作卡

每项执行使用以下最小结构：

```json
{
  "step_id": "pcb-place-001",
  "goal": "Place the approved connector component group.",
  "track": "pcb",
  "route": "direct",
  "adapter_id": "easyeda-api",
  "route_decision_id": "decision-pcb-route",
  "authorization_decision_ids": [],
  "ownership": "agent",
  "risk_level": "low",
  "call_id": "call-pcb-place-001",
  "attempt_id": "attempt-pcb-place-001",
  "parameters": {"component_ids": ["J1", "D1", "D2"], "placement_group": "rear-io"},
  "parameter_digest": "sha256:<canonical-parameters>",
  "status": "planned",
  "required_capabilities": ["pcb.read_components", "pcb.move_components", "pcb.readback_positions"],
  "execution_capability_id": "pcb.move_components",
  "preconditions": ["Schematic and interface revisions match the approved hashes."],
  "target_ids": ["selected-window", "project-uuid", "pcb-document-uuid"],
  "expected_delta": {"moved_components": 3},
  "do_not_touch": ["board-outline", "mounting-holes"],
  "rollback": {
    "method": "restore snapshot or undo the single semantic batch",
    "checkpoint_ref": "snapshot-001",
    "limitations": []
  },
  "acceptance_checks": ["Read back all three component positions."],
  "evidence_required": ["api_readback"],
  "evidence": [],
  "depends_on": [
    {"artifact_id": "schematic-freeze", "revision": 2, "content_hash": "sha256:..."}
  ],
  "produces": [
    {"artifact_id": "pcb-layout", "revision": 1, "content_hash": null}
  ]
}
```

`route` 必须从 `route_decision_id` 指向的、已由用户 resolve 的 decision 复制；adapter 不得自行填入或改写。

`hybrid` 的每张操作卡还必须在 `authorization_decision_ids` 中引用一个 scope 为当前 `step_id` 的用户 ownership 决策。危险写入、不可可靠回滚或约束放宽也通过该数组引用各自的单独授权，不能由路线授权代替。

对外状态使用统一枚举：

```text
planned -> waiting_user_decision
        -> implemented-unverified -> verified
        -> stale
        -> blocked
```

执行中、读回中等瞬时信息写入 journal event，不另造可恢复状态。任何 `stale` 或 `blocked` 都停止后续依赖步骤。

<a id="failure-and-route"></a>

## 11. 失败处理与重新选路线

以下任一事件都会使当前领域路线进入 `route_selection_required`：

- bridge 或目标窗口断开。
- 目标工程、文档或文档类型发生变化。
- API 不存在、签名不确定或权限被拒。
- 写入返回异常、超时、`null` 或 readback 不一致。
- 快照、回滚或证据渠道失效。
- 单位、封装、pin-pad、Pin 1、极性、FPC 或网络检查失败。
- 原理图源 hash 变化。
- DRC 未达到当前门禁要求。

适配器必须输出：

- 已完成与可能部分完成的实际差异。
- 当前证据和不确定项。
- 可恢复方法。
- `direct`、`guided`、`hybrid`、`handoff`、`skip` 中当前可选的路线及影响。

然后停止。不得自动执行降级路线；必须等待用户重新选择。

<a id="final-status-and-artifacts"></a>

## 12. 最终状态与措辞

静态检查全部通过后，输出：

- `pcb_candidate`：可进入打样准备，但仍需制造参数复核。
- `waiting_evt`：候选已冻结，等待 EVT 板的制板、装配、上电、接口、热、射频、续航和整机测试。

最终报告必须明确：

- DRC 和网络核对只验证当前数字设计状态。
- 阻抗、温升、电源瞬态、ESD、无线、机械装配和器件实物方向仍需对应验证。
- EVT 完成前不得把候选称为已验证硬件或量产设计。

## 13. Adapter 产物

只读探测阶段：

- `eda-capability-report.json`
- `eda-adapter-resolution.json`

原理图或 PCB 执行阶段：

- `eda-run-plan.json`
- `eda-operation-cards.json`
- `eda-operation-journal.jsonl`
- `eda-snapshot-manifest.json`
- 原理图/PCB 结构化导出或等价 checkpoint evidence
- `eda-acceptance-results.json`
- `eda-artifact-manifest.json`
- 失败时的 `eda-recovery-report.md`

这些是 run-state 引用的执行 artifacts，不嵌入 Design Pack 或 Electrical Pack。产物不得保存凭据、未脱敏账号信息、私有工程链接、机器本地配置或无必要的绝对路径。
