# Fusion 360 Adapter V2

本规范定义 `product-loop` 如何通过可插拔 adapter 使用 Fusion 360 MCP。它只负责把 mechanical implementation plan 映射为具体工具调用，不改变 provider-neutral 设计合同，也不负责安装 Fusion、启动 Add-in 或写入用户的 MCP 客户端配置。

## 1. 用户先选择 CAD 路线

在 Phase 0 报告环境能力后，必须让用户明确选择 mechanical 路线：

- `direct`：使用用户选定的 Fusion 360 MCP 或其他可用 adapter
- `guided`：由用户在 CAD 中操作，Agent 提供操作卡并验收
- `spec`：只生成 CAD-ready 规格
- `handoff`：生成外部建模交接包
- `skip`：不运行机械分支

runtime probe 只回答“当前路线是否可用”，不能替用户选择路线。即使 `execution_cadence` 允许连续执行，也不得把 Fusion 不可用自动解释为允许切换 adapter、`guided`、`spec` 或 `handoff`。

如果用户已选择 Fusion，但 probe 未通过，应暂停并给出以下可选动作：

1. 修复连接或打开正确的 Fusion 文档后重试
2. 改选另一个 CAD adapter
3. 明确改为 `guided` 或 `spec`
4. 明确改为 `handoff` 或 `skip`

未经用户重新选择，不得静默改变 mechanical route 或继续产生看似完成的 CAD 产物。

## 2. 阶段入口与前置产物

### Phase 0

仅执行 adapter 发现和只读 probe，产出 `CAD Capability Report`。不要在 probe 中创建、修改或删除几何。

### Mechanical implementation node

仅在以下条件全部满足时进入真实 CAD 执行：

- 用户已明确选择 Fusion 360 MCP 路线
- `Design Pack` 已通过当前 schema 校验
- `Appearance Spec`、`Structure Spec`、`Review Report` 已存在
- 已从 Design Pack 生成 provider-neutral `CAD Iteration Inputs`
- 当前 Fusion 文档已由用户确认是目标文档
- runtime probe 状态为 `ready`
- 用户已选择 `mechanical: direct`、已选定目标 adapter，并授权开始本轮模型变更

Design Pack、Appearance Spec、Structure Spec 和同一 revision 的 Interface Control 共同构成几何约束源；发生冲突时必须打开用户决策门。Fusion 工具名、MCP server 名称、文件系统路径和单位换算不得写入这些设计真值。

## 3. Provider-neutral Adapter Interface

所有 CAD adapter 应实现同一语义接口：

```text
probe(context) -> CapabilityReport
plan(pack, artifacts) -> CadRunPlan
execute_step(step, session) -> StepResult
verify(step, result, checks) -> VerificationResult
rollback(checkpoint) -> RollbackResult
export(formats, artifact_root) -> ArtifactManifest
```

`CadRunPlan` 使用 provider-neutral 操作和验收意图，例如“创建参数化主壳体”“切除端口避让区”“检查包络尺寸”。只有 adapter 内部可以把这些意图映射为 `create_sketch`、`extrude`、`shell` 等 Fusion 工具。

`context` 由宿主注入，至少包含：

- MCP tool discovery 与调用器
- 逻辑 `server_ref`
- `artifact_root`
- `run_id`
- 当前用户授权范围
- timeout 与重试上限

不得在 adapter 中写死本机仓库路径、用户主目录、Fusion 安装路径或输出目录。MCP server 应按逻辑引用或能力发现绑定；存在多个匹配 server 时必须让用户选择。

## 4. Runtime Probe

Probe 必须以 MCP 实时发现结果为准，不以 README 中的工具总数或固定版本号为准。

按顺序执行：

1. 枚举 MCP tools，校验必需工具名称及其 input schema
2. 调用 `ping`，确认 MCP server 可响应
3. 检查返回中是否存在 `mode: mock`
4. 调用 `get_scene_info`，确认 Fusion Add-in、活动设计和场景可访问
5. 调用 `get_design_type`，确认设计处于 `parametric`
6. 比对本次 `CadRunPlan` 所需的任务级能力
7. 保存工具 schema digest，供执行前复核接口是否漂移

`ping` 不访问 Fusion API，因此不能单独证明 CAD 路径可用。

每个发现到的 operation 必须同时固化真实 `provider_operation`、provider-neutral `capability_id`、`risk_class` 和该工具参数 schema digest。未能分类或无法建立唯一映射的写工具不得进入可执行 Capability Report；delete/remove/CAM 等即使名称不在旧名单中也归为 destructive write。

### Full 模式最低能力

- 场景读取：`get_scene_info`、`get_object_info`
- 设计类型：`get_design_type`
- 参数读取与修改：`get_parameters`、`create_parameter`、`set_parameter`
- 回滚：`undo`
- 原生 checkpoint：`export_f3d`
- 视觉复核：`render_view` 或 `export_view_sheet` 至少一个
- 当前 `CadRunPlan` 实际需要的建模与验收工具

不得为了通过 probe 要求所有 Fusion 工具都存在；也不得只因工具同名就判定兼容。required 字段、枚举或语义不兼容时，状态应为 `incompatible`。若多个 adapter 或 MCP endpoint 同时满足条件，必须让用户选择目标。

Mock mode 只能用于 adapter 合同测试和 dry-run，不得产出或宣称产出了真实 `Parametric Draft Model`。

## 5. 单位合同

- Design Pack 的所有长度使用毫米 `mm`
- Fusion 几何工具的原生长度使用厘米 `cm`
- adapter 在唯一的单位边界集中执行 `mm * 0.1 -> cm`
- Fusion 的 bbox、距离等读回结果必须转换回 `mm` 后再写入报告
- 角度保持 `deg`
- `create_parameter` 可显式传入 `unit: mm`，但其他几何参数仍按各工具 schema 的原生单位处理

每条 journal 记录都应同时保留源值、源单位、传入值和原生单位，防止重复换算或漏换算。

## 6. 执行、验证与回滚

### 6.1 Baseline

每轮真实变更前必须：

1. 用 `get_scene_info`、`get_design_type`、`get_parameters` 记录 readback baseline
2. 记录目标文档名称和场景指纹
3. 将当前设计导出为本轮 `baseline.f3d`
4. 把 baseline 路径、hash 和 Design Pack hash 写入 artifact manifest

如果当前文档已有对象且与预期 baseline 不符，停止并让用户确认。工具集没有可靠的新建或打开文档事务，adapter 不得假设当前活动设计为空。

### 6.2 原子步骤

一个原子步骤只能包含一个变更型 MCP tool call。多步骤 feature 必须拆成有序 recipe。

每步按以下协议执行：

1. **Before**：记录设计类型、目标对象 readback、参数旧值和预期 delta。
2. **Authorize and preflight**：对完整 V2 bundle 调用 `authorize_execute_step`，使用 `authorized` token 只读核对真实工具 schema、场景、对象、参数与输入 hash。
3. **Reserve and lease**：原子预留 attempt 与高风险授权，再对更新后的完整 bundle 调用 `authorize_reserved_execute_step`，取得该 reservation 的一次性 `reserved` lease。
4. **Guard and execute**：guard 用真实工具名和真实参数核对 lease 的 capability、provider operation、risk class 和 digest；消费 lease 后立即只调用这一个工具。对象必须使用稳定名称，优先 `body_name`，避免 `body_index`。
5. **Check result**：同时检查 MCP `isError`、业务返回 `ok`、结构化 `error_kind` 和 `deltas`。
6. **Readback**：调用只读工具确认真实场景状态，不能把“没有抛异常”视为成功，并用 readback fingerprint 完结 reservation。
7. **Commit**：仅在 readback 通过后把步骤标记为 committed，并写入 operation journal。

推荐验证映射：

- 参数：`get_parameters`
- body、sketch、feature：`get_object_info` + `get_scene_info`
- boolean：检查 delta；零变化时先 `check_interference`
- assembly：`list_components` + `check_interference`
- 尺寸：bbox 或 `measure_distance`
- 物理属性：`get_physical_properties`
- 外观：在逻辑 checkpoint 使用 `render_view` 或 `export_view_sheet`
- 导出：校验文件位于 `artifact_root` 内，并记录存在性、大小和 hash

`render_view` 只在完成一个逻辑 feature、准备验收或准备导出时使用，不应在每个原子步骤后调用。

### 6.3 失败与回滚

任意错误后必须先重新读取场景，因为 timeout 或失败响应可能伴随部分生效。

- 未发生变更：记录失败，修正计划后才可重试
- 已部分生效：按 journal 反向逐次调用 `undo`
- 每次 undo 后：重新检查场景指纹和 `get_design_type`
- 恢复到 checkpoint：状态记为 `recovered`，由用户决定是否继续
- 无法恢复：状态记为 `recovery_failed`，停止所有变更并输出恢复报告

`baseline.f3d` 是人工恢复点，不代表 MCP 具备自动重新打开或恢复文件的能力。不得使用 `delete_all` 模拟回滚，也不得在恢复失败后继续堆叠新操作。

只有在确认没有部分生效，或已经完整回滚到已知 checkpoint 后，才允许重试。

## 7. 危险工具单独授权

以下工具默认禁止，不能由“开始本轮 CAD”这一通用授权覆盖：

- `execute_code`
- `delete_all`
- `delete_parameter`
- `set_design_type`
- 所有 CAM、toolpath 和 post-process 工具
- 写入 `artifact_root` 之外路径的导出调用

确需使用时，必须在调用前单独向用户说明：工具名、provider-neutral capability、完整参数、影响范围、验证方法和回滚限制，并取得针对该次调用的明确授权。
该授权必须写入 decision ledger，并由对应 Operation Card 的 `authorization_decision_ids` 引用；scope 必须同时绑定 `run`、`step`、单次 `call_id`、`attempt_id`、canonical `parameter_digest` 与 `operation:<material_digest>`。Operation digest 覆盖目标对象、预期变化、禁止触碰项、回滚、验收、证据和输入版本；任一材料字段变化都会让旧授权失效。每张卡只允许一个执行 capability，并且恰好一条匹配该次调用的危险授权；同进程 host 在只读 preflight 后调用 `reserve_execution(...)`，原子写入 call reservation 和 authorization consumption，更新后的 bundle 再签发一次性 write lease。guard 从真实 parameters 自行重算 digest，不能信任调用方复用旧摘要。参数、目标、影响范围、超时重试或 run 改变都必须重新确认。adapter 必须使用 probe 固化的真实工具名映射，例如 `execute_code -> cad.execute_code`、`cam_generate_toolpath -> cad.cam.generate_toolpath`，不得一边按工具名授权、一边按 capability 验证。所有 delete/remove/purge/clear/destroy/wipe/erase/reset 与未分类破坏性工具 fail closed。

导出工具必须同时提交 `artifact_root` 和实际输出路径。路径归一化后处于 root 内才是常规导出；缺少路径信息或越界写出必须把该次导出卡提升为高风险，并在其唯一 capability 授权 scope 中加入规范化后的 `output:<path>`。

即使用户授权 `execute_code`，仍应优先使用专用工具；代码不得包含循环，建议控制在 15 行以内。危险工具的授权不得跨 run 复用。

## 8. 产物

Read-only discovery：

- `cad-capability-report.json`
- `cad-adapter-resolution.json`

Mechanical implementation：

- `cad-run-plan.json`
- `cad-operation-journal.jsonl`
- `baseline.f3d`
- `iteration-N.f3d`
- `iteration-N.step`，能力存在时
- checkpoint 视图 PNG 或 view sheet HTML
- `cad-acceptance-results.json`
- `cad-iteration-report.md`
- `cad-artifact-manifest.json`
- 失败时的 `cad-recovery-report.md`

`Parametric Draft Model` 至少对应可追溯的 F3D 文件；STEP 是中性格式补充，不能替代参数化源模型。

`CAD Iteration Report` 只记录可执行差异：

- appearance delta
- layout delta
- structure delta
- manufacturing-risk delta

报告和 journal 默认不保存未脱敏 traceback、本机日志路径、账号信息或其他机器本地配置。

## 9. 状态与用户决策

Run State 和产物只使用统一状态：`planned`、`waiting_user_decision`、`implemented-unverified`、`verified`、`stale`、`blocked`。以下 Fusion 细分状态只写入 capability report 或 operation journal，不替代统一状态：

- `awaiting_user_route`：等待用户选择 CAD 路线
- `probing`：正在只读探测
- `ready`：当前 Fusion 路线可执行
- `mock`：仅可 dry-run
- `unavailable`：server 或 Add-in 不可用
- `no_active_design`：没有可访问的活动设计
- `wrong_design`：当前文档未获用户确认
- `direct_mode`：当前设计不是 parametric
- `incompatible`：工具或 schema 不满足本次任务
- `executing`：正在执行已授权步骤
- `verification_failed`：调用完成但 readback 或 acceptance check 未通过
- `rollback_required`：检测到部分生效，需要回滚
- `recovered`：已回到已知 checkpoint
- `recovery_failed`：无法确认恢复，必须人工处理
- `completed`：模型、验收和交付产物均已生成

映射规则：等待选路映射为 `waiting_user_decision`；写入返回成功但尚未获得可靠 readback 时不升级产物状态，并在 journal 中记录可能的部分生效；readback 证明确有变化但完整验收尚未通过时映射为 `implemented-unverified`；完成且验收通过映射为 `verified`；接口漂移映射为 `stale`；不可用、验证失败或恢复失败映射为 `blocked`。

任何 `mock`、`unavailable`、`no_active_design`、`wrong_design`、`direct_mode`、`incompatible` 或 `recovery_failed` 状态都必须停止自动推进，并回到用户决策。不得把缺失工具、断连或验收失败包装成成功，也不得自动切换 mechanical route。
