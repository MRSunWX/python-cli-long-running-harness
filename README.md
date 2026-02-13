# 自主编程助手 Agent

## 项目简介

这是一个基于 Python CLI 的 long-running harness 项目，用于驱动可持续运行的编程 Agent。  
核心命令包括：`init`、`run`、`status`、`chat`、`add-feature`。

项目目标不是“一次性生成全部代码”，而是通过可迭代、可验证、可回滚的流程持续推进：
- 用 `feature_list.json` 管理任务与状态
- 用 `progress.md` 记录跨会话进展
- 用 `init.sh` 做每轮会话前检查
- 用 Git 保证可追溯与可回滚
- 用 `run_logs.jsonl` / `events.jsonl` 提供可观测性

## 快速开始（conda demo）

```bash
# 1) 激活已有 conda 环境
conda activate demo

# 2) 安装依赖
pip install -r requirements.txt

# 3) 查看 CLI 总帮助
python main.py --help

# 4) 初始化项目（会在目标目录创建 progress.md / feature_list.json / init.sh）
python main.py init ./my_project --spec "创建一个命令行应用"

# 5) 执行一次任务循环
python main.py run ./my_project

# 6) 查看状态
python main.py status ./my_project --json
```

如果你更偏好单命令调用（不手动激活环境）：

```bash
conda run -n demo python main.py init ./my_project --spec "创建一个命令行应用"
conda run -n demo python main.py run ./my_project
conda run -n demo python main.py status ./my_project --json
```

## 运行前置条件

1. Python 3 环境可用（建议使用 `demo` conda 环境）。
2. 依赖已安装：`pip install -r requirements.txt`。
3. 模型服务可访问：
- 默认模型地址来自 `config.py`（`Config.OLLAMA_BASE_URL`）。
- 默认模型名来自 `config.py`（`Config.MODEL_NAME`）。
- 可通过 CLI 覆盖：`--url` 与 `--model`。

示例：

```bash
python main.py --url "http://127.0.0.1:11434/v1" --model "qwen3-coder:30b" run ./my_project
```

## 命令总览（与当前实现对齐）

### 全局参数

```bash
python main.py [--model MODEL] [--url URL] [-v|--verbose] [--verbose-events|--quiet-events] <command> ...
```

- `--verbose-events/--quiet-events`：控制终端是否输出详细事件流（默认开启详细事件）。

### `init`

```bash
python main.py init <project_dir> --spec "需求描述" [--name 项目名] [--template 模板名]
```

作用：初始化目标项目目录，生成基础工件并尝试创建初始化提交。

### `run`

```bash
python main.py run <project_dir> [--iterations N] [--continuous] [--task feat-xxx]
```

作用：执行单次或连续迭代。
- 单次模式：处理一个“下一个可执行”功能。
- 连续模式：循环执行直到完成、阻塞或达到最大轮数。

### `status`

```bash
python main.py status <project_dir> [--json]
```

作用：查看项目统计和功能状态。

### `chat`

```bash
python main.py chat <project_dir>
```

作用：进入交互式问答（输入 `exit`/`quit` 退出）。

### `add-feature`

```bash
python main.py add-feature <project_dir> \
  --id feat-002 \
  --name "用户登录" \
  [--desc "功能描述"] \
  [--priority high|medium|low] \
  [--verify "python -m pytest -q"]
```

作用：向 `feature_list.json` 追加功能项，`--verify` 可重复传入多条验收命令。

## 运行生命周期（从 `init.sh` 开始）

### 1) 定位工作目录

`CodingAgent` 初始化时会将 `project_dir` 绝对化，并设置为全局工作目录上下文。后续命令执行与文件读写围绕该目录进行。

### 2) 初始化阶段（`init`）

`python main.py init ...` 的核心动作：
1. 创建 `progress.md` 与 `feature_list.json`
2. 若功能清单为空，写入一个可跑通的默认功能
3. 确保 `init.sh` 存在且可执行
4. 尝试生成初始化分析（模型失败时降级，不阻断初始化）
5. 若不是 Git 仓库则初始化，并在有变更时提交 `chore: 项目初始化`

### 3) 运行阶段（`run`）

每轮执行流程：
1. 会话前检查：优先执行 `bash ./init.sh`
2. 选择下一个可执行功能
3. 组装会话上下文并调用 Agent
4. 执行 `verify_commands` 验收
5. 更新 feature 状态与 `progress.md`
6. 有代码改动则自动提交（`feat:` 或 `wip:`）
7. 追加 `run_logs.jsonl`

## `feature_list.json` 结构与调度规则

### 结构（当前实现）

每个 feature 的核心字段：
- `id`: 功能 ID（如 `feat-001`）
- `name`: 功能名
- `description`: 描述
- `priority`: `high|medium|low`
- `status`: `pending|in_progress|completed|blocked`
- `dependencies`: 依赖功能 ID 列表
- `verify_commands`: 验收命令列表（推荐）
- `test_command`: 旧字段（兼容）
- `acceptance_criteria`、`notes`、`created_at`、`updated_at`

兼容规则：若 `verify_commands` 为空但有 `test_command`，会自动将其视作一条验收命令。

### 下一个可执行功能选择规则

当前实现的调度顺序：
1. 从 `pending + in_progress` 中按优先级排序（`high > medium > low`）
2. 优先返回 `in_progress` 功能
3. 再返回满足依赖已完成的 `pending` 功能
4. 若都不可执行，返回 `None`（可能是依赖阻塞）

## Prompt 上下文拼装与 token 现实

当前 `run` 阶段会把这些信息拼到会话上下文中：
1. 项目统计信息 + precheck 结果
2. `progress.md` 内容
3. 最近 Git 提交历史
4. `init.sh` 内容（若存在）
5. 当前任务描述（含验收命令）

说明：
- 当前实现未做“严格 token 预算分配”和分段裁剪策略。  
- 对长 `progress.md` / 长 git 历史 / 长脚本场景，后续建议再补充上下文裁剪机制。

## 验收门禁（`verify_commands`）

### 判定规则（当前实现）

1. 按顺序执行 feature 的验收命令。
2. 任一命令失败，则本轮验收失败。
3. 全部命令成功，才允许将功能标记为 `completed`。
4. 验收失败时通常保持 `in_progress`（异常情况下可能转 `blocked`）。

### 当前不做的事

- 不做关键字匹配判定（例如不要求输出包含特定文案）。
- 不自动生成复杂测试报告模板。

核心依据是命令执行结果（`ok` / 返回码语义）。

## 日志与可观测性

### `run_logs.jsonl`

定位：迭代级运行日志，用于复盘每轮执行。  
典型包含：轮次、功能 ID、状态、验收结果、precheck 摘要、输出预览。

### `events.jsonl`

定位：结构化事件流日志（JSONL）。  
事件结构字段固定为：
- `timestamp`
- `session_id`
- `iteration`
- `phase`
- `event_type`
- `component`
- `name`
- `payload`
- `ok`

### 终端中文前缀

详细事件模式下，常见输出前缀：
- `[会话]`
- `[助手]`
- `[工具调用]`
- `[工具结果]`

工具结果状态示例：`[完成]`、`[错误]`、`[拦截]`。

### 事件流边界（按当前实现真相）

- `init` / `run` / `chat`：有完整事件流能力（终端 + JSONL）。
- `status` / `add-feature`：当前不承诺完整事件流水（文档不做超实现承诺）。

## 故障排查

### 1) 模型不可达 / 初始化分析失败

现象：`init` 期间模型调用报错。  
处理：初始化流程会降级继续，先保证 `progress.md`、`feature_list.json`、`init.sh`、Git 基础可用。

### 2) precheck 失败（`init.sh` 失败）

现象：`run` 返回 `blocked` 或提示会话前检查失败。  
处理：先手动执行并修复：

```bash
cd my_project
bash ./init.sh
```

### 3) 验收命令失败

现象：feature 无法变成 `completed`。  
处理：逐条复现 `verify_commands`，先修命令本身，再修代码实现。

### 4) 没有可执行功能

现象：`run` 提示没有可执行功能。  
处理：检查是否存在依赖阻塞（`dependencies` 未完成），或 feature 状态配置不合理。

## 基础校验命令

```bash
# 语法校验
conda run -n demo python -m py_compile main.py config.py agent/*.py

# CLI 帮助对齐
conda run -n demo python main.py --help
conda run -n demo python main.py add-feature --help

# 基础 smoke
conda run -n demo python main.py init ./demo_smoke --spec "创建一个命令行应用"
conda run -n demo python main.py run ./demo_smoke
conda run -n demo python main.py status ./demo_smoke --json
```

## Git 使用建议

建议使用 Conventional Commits：`feat:`、`fix:`、`docs:`、`refactor:`、`chore:`。

最小提交流程：

```bash
git status
git add README.md
git commit -m "docs: 全面对齐README并补充运行与排障说明"
```
