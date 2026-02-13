# 自主编程助手 Agent

这是一个 Python CLI 项目，用于实现可持续运行的编程 Agent（初始化项目、按功能迭代开发、记录进度、自动 Git 管理）。

## 主要能力

- `init`：初始化项目目录、创建进度文件、生成功能清单。
- `run`：执行单次任务循环，处理下一个可执行功能。
- `run --continuous`：连续执行多个功能直到完成或达到上限。
- `status`：查看项目统计信息和功能状态。
- `chat`：与 Agent 进行交互式对话。
- `add-feature`：手动向功能列表添加新功能。
- `add-feature --verify`：为功能设置一个或多个验收命令（测试门禁）。

## 项目结构

```text
.
├── main.py                  # CLI 入口
├── config.py                # 全局配置
├── agent/
│   ├── agent.py             # Agent 核心逻辑
│   ├── tools.py             # 文件/命令工具
│   ├── security.py          # 命令安全校验
│   ├── progress.py          # 进度和 feature 管理
│   ├── git_helper.py        # Git 操作封装
│   ├── prompts.py           # 提示词加载与格式化
│   ├── event_logger.py      # 事件日志（终端+JSONL）
│   └── __init__.py
├── prompts/                 # 提示词模板（.md）
└── requirements.txt
```

## 环境准备

使用 conda 环境 `demo`，推荐如下：

```bash
conda activate demo
pip install -r requirements.txt
```

## 命令示例

```bash
# 查看帮助
python main.py --help

# 默认详细事件日志（中文前缀）
python main.py init ./demo_project --spec "创建一个 Flask 应用"

# 关闭详细事件日志（仅保留简洁输出）
python main.py --quiet-events init ./demo_project --spec "创建一个 Flask 应用"

# 初始化一个项目目录
python main.py init ./demo_project --spec "创建一个 Flask 应用"

# 执行一次任务
python main.py run ./demo_project

# 连续执行
python main.py run ./demo_project --continuous --iterations 20

# 查看状态
python main.py status ./demo_project
python main.py status ./demo_project --json

# 对话模式
python main.py chat ./demo_project

# 添加功能
python main.py add-feature ./demo_project --id feat-002 --name "用户登录" --priority high

# 添加功能并设置验收命令（可重复 --verify）
python main.py add-feature ./demo_project --id feat-003 --name "导出报告" --verify "python -m pytest -q"
```

## 强化机制

- 会话前检查：每轮 `run` 前会先执行项目内 `init.sh`（存在时）。
- 测试门禁：只有功能的验收命令全部通过，状态才会变为 `completed`。
- 运行日志：每轮执行会写入 `run_logs.jsonl`，用于复盘。
- 事件日志：默认详细输出中文前缀事件，并写入 `events.jsonl`。
- 降级初始化：模型不可达时仍可完成本地初始化，不阻断项目启动。

## 事件日志说明

默认情况下（`--verbose-events`），终端会输出以下中文前缀：

- `[会话]`：会话开始、结束、阶段状态
- `[助手]`：模型回复摘要
- `[工具调用]`：工具名称与输入摘要
- `[工具结果]`：执行状态（完成/错误/拦截）、返回码、耗时

并且会同步写入项目目录下的 `events.jsonl`（JSONL 结构化日志）：

- `timestamp`：时间戳
- `session_id`：会话标识
- `iteration`：迭代编号
- `phase`：阶段（init/run/chat/status）
- `event_type`：事件类型
- `component`：组件来源（cli/agent/tool/security/git）
- `name`：事件名称
- `payload`：事件内容
- `ok`：是否成功

示例输出：

```text
[会话] 开始执行命令: init
[会话] Agent 实例初始化
[助手] 已完成初始化分析...
[工具调用] <run_bash - python -m pytest -q>
[工具结果] [完成] run_bash 返回码=0 耗时=0.2s
[会话] 项目初始化完成
```

## 测试与校验

```bash
# 语法检查
python -m py_compile main.py config.py agent/*.py

# CLI 基础检查
python main.py --help

# smoke test
python main.py init ./demo_smoke --spec "创建一个命令行应用"
python main.py status ./demo_smoke --json
```

## Git 管理建议

```bash
git status
git add -A
git commit -m "feat: 完善 Agent 与中文文档"
```

建议遵循 Conventional Commits：`feat:`、`fix:`、`docs:`、`refactor:`。
