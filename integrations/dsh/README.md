# dsh-ploo — DeepSeek Harness 插件 / Plugin

[English](#english) · [中文](#中文)

## English

DeepSeek Harness bundle plugin for the Ploo hardware product workflow. It turns the repository into a packaged harness-level integration:

- **Runtime skill**: registers `ploo` via `ctx.skills.register` (rank: runtime), so the workflow appears in the skill catalog even without any filesystem skill installation.
- **Host tools**: registers eight `ploo_*` tools that wrap the stdlib-only core scripts — `ploo_validate`, `ploo_validate_bundle`, `ploo_run_state`, `ploo_migrate`, `ploo_normalize`, `ploo_review_matrix`, `ploo_handoff`, `ploo_evaluate_behavior`.
- **Self-contained**: a snapshot of `core/` ships inside the package under `assets/core/`, so an installed profile runs without the repository checkout. `config.coreDir` overrides the snapshot with a live checkout when developing the core.

Verified against `@deepseek-ai/dsh` 0.1.0-rc.6.

### Install (local path)

```bash
dsh plugin --profile web add /path/to/ploo/integrations/dsh
# restart the profile afterwards; the plugin row is cached per boot
```

For a dedicated agent profile, copy the preset and install the plugin into it:

```bash
mkdir -p "$HOME/.dsh/profiles/ploo"
cp integrations/dsh/profile/ploo/package.json "$HOME/.dsh/profiles/ploo/package.json"
dsh plugin --profile ploo add /path/to/ploo/integrations/dsh
dsh --profile ploo          # boots the web app with Ploo mounted
```

Swap `@deepseek-ai/dsh-web-app` for `@deepseek-ai/dsh-headless` in the preset's `bundles` to make a job-style headless profile instead.

### Optional config

In the profile's `cordis.patch.yml`, extend the inserted row:

```yaml
- insert:
    - id: ploo
      name: dsh-ploo
      config:
        coreDir: /absolute/path/to/ploo/core   # live checkout override
        pythonPath: python3                            # interpreter for core scripts
```

### Development

```bash
node scripts/sync-core.mjs   # re-snapshot ../../core into assets/core (run after core changes)
node scripts/verify.mjs      # offline smoke: package shape, asset sync, mock apply, tool execution
```

`sync-core.mjs` must run (and its result be committed) whenever `core/` changes; CI rejects a stale snapshot.

### Safety boundary

The plugin only wraps the core's deterministic validators and state helpers. It cannot grant routes, freeze decisions, or provider writes on its own — every material decision still goes through the user gates defined in `core/SKILL.md`. Non-zero script exits are reported, not raised, mirroring the shipped bash tool.

## 中文

Ploo 硬件产品工作流的 DeepSeek Harness 打包插件,把仓库变成 Harness 级集成:

- **运行时 Skill**:通过 `ctx.skills.register` 注册 `ploo`,不装任何文件系统 Skill 也能出现在 Skill 目录里。
- **宿主工具**:注册 8 个 `ploo_*` 工具,封装仅依赖标准库的核心脚本 —— `ploo_validate`、`ploo_validate_bundle`、`ploo_run_state`、`ploo_migrate`、`ploo_normalize`、`ploo_review_matrix`、`ploo_handoff`、`ploo_evaluate_behavior`。
- **自包含**:`core/` 快照随包分发(`assets/core/`),装好后不依赖仓库 checkout;开发核心时可用 `config.coreDir` 指向实时 checkout。

已按 `@deepseek-ai/dsh` 0.1.0-rc.6 验证。

### 安装(本地路径)

```bash
dsh plugin --profile web add /path/to/ploo/integrations/dsh
# 装完重启该 profile
```

专用 Agent profile:

```bash
mkdir -p "$HOME/.dsh/profiles/ploo"
cp integrations/dsh/profile/ploo/package.json "$HOME/.dsh/profiles/ploo/package.json"
dsh plugin --profile ploo add /path/to/ploo/integrations/dsh
dsh --profile ploo
```

### 开发

```bash
node scripts/sync-core.mjs   # core/ 变更后重新同步快照并提交
node scripts/verify.mjs      # 离线冒烟:包形态、快照同步、mock 注册、工具执行
```

### 安全边界

插件只封装核心的确定性校验器与状态助手,不能自行授予路线、冻结决策或供应商写权限——所有关键决策仍走 `core/SKILL.md` 定义的用户门禁。脚本非零退出按"报告"处理而非抛错,与官方 bash 工具一致。
