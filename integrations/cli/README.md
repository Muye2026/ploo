# Product Loop CLI (`ploo`)

[English](#usage) · [中文](#中文)

`ploo` is the terminal entrypoint for the Product Loop hardware product workflow. It is a **thin dispatcher**: every subcommand forwards to the matching stdlib-only script in [`core/scripts/`](../../core/scripts/), so no workflow logic is duplicated here.

## Install

From the repository root:

```bash
pipx install integrations/cli      # recommended
# or
pip install -e integrations/cli    # development
```

Requirements: Python ≥ 3.8, nothing else. Core scripts are resolved automatically: the `--core` flag wins, then `$PRODUCT_LOOP_CORE`, then the checkout that installed the package, then every ancestor of the working directory — so `ploo` works anywhere inside a clone after `git pull`.

## Usage

```bash
ploo validate design-pack path/to/design-pack.v2.json
ploo validate-bundle --run-state RUN_STATE --design-pack DESIGN_PACK --electrical-pack ELECTRICAL_PACK --interface-control INTERFACE_CONTROL
ploo migrate INPUT --output-dir NEW_DIRECTORY
ploo run-state validate RUN_STATE
ploo run-state resolve-routes RUN_STATE OUTPUT --decision-ref ... --visualization image --mechanical direct --schematic guided --pcb hybrid
ploo run-state open-decision RUN_STATE OUTPUT --gate DECISION_GATE_JSON
ploo run-state resolve-decision RUN_STATE OUTPUT --selected-option freeze --decision-ref ...
ploo run-state record-execution RUN_STATE OUTPUT --step-id STEP --attempt-id ATTEMPT --status completed --result-fingerprint sha256:READBACK
ploo run-state change-route RUN_STATE OUTPUT --track mechanical --decision-id DECISION
ploo run-state stale RUN_STATE OUTPUT --artifact-id interface-control --revision 3 --reason "Board outline changed"
ploo normalize INPUT OUTPUT
ploo review-matrix INPUT OUTPUT --run-state RUN_STATE --review-results REVIEW_RESULTS
ploo handoff INPUT OUTPUT --run-state RUN_STATE --handoff-data HANDOFF_DATA
ploo evaluate-behavior --cases core/evals/product-loop-v2.jsonl --responses CAPTURED.jsonl
```

Every command passes through to the core script, so the core scripts remain the single source of truth for behavior, and this CLI stays version-stable.

## 中文

`ploo` 是 Product Loop 硬件产品工作流的终端入口。它是一个**薄分发器**:每个子命令都转发到 [`core/scripts/`](../../core/scripts/) 中仅依赖标准库的脚本,不复制任何工作流逻辑。

```bash
pipx install integrations/cli   # 推荐
ploo validate design-pack 路径/design-pack.v2.json
ploo run-state validate 路径/run-state.v2.json
ploo --help
```

核心目录自动解析:`--core` 优先,其次是环境变量 `PRODUCT_LOOP_CORE`,再是安装本包的仓库 checkout,最后向上遍历当前工作目录——所以在仓库克隆目录的任何位置都能直接运行 `ploo`。
