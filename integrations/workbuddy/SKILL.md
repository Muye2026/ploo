---
name: ploo
description: Orchestrate a small hardware product from brief to evidence-backed design artifacts, with every material route decided by the user.
description_zh: 编排小型硬件产品从需求简报到证据支撑的设计产物(概念视觉、工业设计、机械建模、原理图/PCB、跟画、交接),所有关键路线由用户决策。
description_en: Orchestrate a small hardware product from brief to evidence-backed design artifacts, with every material route decided by the user.
version: 1.0.0
allowed-tools: Read,Write,Bash
---

# Ploo(WorkBuddy 入口)

本 Skill 是 Ploo 的 WorkBuddy 入口。权威工作流在 Ploo 仓库的 `core/SKILL.md`,本文件只做入口与边界声明。

## 启动步骤(必须按序执行)

1. 用 Read 加载权威工作流:相对本文件的路径是 `../../core/SKILL.md`(经符号链接安装时按其真实路径解析);若用户另行提供了仓库位置,以该位置的 `core/SKILL.md` 为准。
2. 把 `references/`、`schemas/`、`scripts/`、`evals/` 等所有相对路径解析到 `core/` 目录。
3. 严格遵循其中的工作流:先只读能力探测,再在 Route Gate 0 呈现全部相关路线选项并等待用户选择。
4. 未经用户明确决策,不得生成图片/视频、建模、画原理图/PCB、安装供应商,也不得静默更换路线。推荐不等于授权。

## 核心脚本(可选,用于确定性校验)

`core/scripts/` 下的脚本仅依赖 Python 3 标准库,可用于产物校验(`validate_v2.py`、`validate_bundle.py`)、V1→V2 迁移(`migrate_v1_to_v2.py`)、运行状态管理(`manage_run_state.py`)等;任何校验失败都视为阻塞,不得猜测修补关键值。

## 可选供应商

Fusion 360 MCP、EasyEDA、图片/视频生成器都是可选适配器,通过 `~/.workbuddy/mcp.json` 等宿主配置接入;一个都没有时,需求、架构、四份 V2 契约、验收计划、跟画说明和外部交接工作流仍然完全可用。缺少工具只会让对应的直接执行路线暂时不可用,不得自动安装或自动降级。

## English summary

This skill is the WorkBuddy entrypoint for Ploo. Load `core/SKILL.md` from the Ploo repository (relative to this file: `../../core/SKILL.md`) as the authoritative workflow, resolve every relative reference against `core/`, run read-only capability discovery first, present all relevant routes at Route Gate 0, and wait for the user's decision at every gate. Optional providers (Fusion 360 MCP, EasyEDA, image/video) attach through host configuration such as `~/.workbuddy/mcp.json`; the planning layer is fully usable without them. A recommendation is never authorization.
