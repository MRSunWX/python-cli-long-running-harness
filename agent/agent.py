# -*- coding: utf-8 -*-
"""
Agent 核心模块 (agent.py)
========================

本模块实现了自主编程 Agent 的核心逻辑，包括：
- CodingAgent：项目主执行类
- SimpleAgentExecutor：基础回退执行器
- 初始化、任务执行、状态查询与对话接口

说明：
- 优先尝试使用 LangGraph 的 `create_react_agent`
- 如果 LangGraph 不可用或初始化失败，自动回退到简单执行器
"""

import json
import os
import shlex
import subprocess
import sys
import time
import hashlib
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

try:
    from langgraph.prebuilt import create_react_agent

    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

# 项目内部导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config, set_project_dir
from .git_helper import GitHelper, format_commits_for_prompt
from .progress import Feature, ProgressManager
from .prompts import get_system_prompt, loader as prompt_loader
from .security import get_validator
from .tools import get_all_tools
from .event_logger import emit_event, get_event_logger, setup_event_logger, update_event_context


class SimpleAgentExecutor:
    """
    简易 Agent 执行器。

    该执行器不做工具规划，仅把系统提示词、历史消息和用户输入
    发送给 LLM，作为 LangGraph 不可用时的回退方案。
    """

    def __init__(self, llm: ChatOpenAI, tools: List[Any]):
        """初始化回退执行器。"""
        self.llm = llm
        self.tools = tools

    @staticmethod
    def _normalize_chat_history(chat_history: List[Any]) -> List[Any]:
        """将多种历史消息格式标准化为 LangChain 消息对象列表。"""
        normalized: List[Any] = []
        for item in chat_history or []:
            if isinstance(item, (HumanMessage, AIMessage, SystemMessage)):
                normalized.append(item)
                continue

            if isinstance(item, tuple) and len(item) == 2:
                role, content = item
                role_str = str(role).lower()
                if role_str in {"human", "user"}:
                    normalized.append(HumanMessage(content=str(content)))
                elif role_str in {"ai", "assistant"}:
                    normalized.append(AIMessage(content=str(content)))
                else:
                    normalized.append(SystemMessage(content=str(content)))
                continue

            if isinstance(item, dict):
                role_str = str(item.get("role", "")).lower()
                content = str(item.get("content", ""))
                if role_str in {"human", "user"}:
                    normalized.append(HumanMessage(content=content))
                elif role_str in {"ai", "assistant"}:
                    normalized.append(AIMessage(content=content))
                else:
                    normalized.append(SystemMessage(content=content))

        return normalized

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """执行一次 LLM 调用并返回统一的输出结构。"""
        input_text = str(inputs.get("input", ""))
        chat_history = self._normalize_chat_history(inputs.get("chat_history", []))

        messages: List[Any] = [SystemMessage(content=get_system_prompt())]
        messages.extend(chat_history)
        messages.append(HumanMessage(content=input_text))

        response = self.llm.invoke(messages)
        content = getattr(response, "content", str(response))
        return {"output": str(content)}


def _is_compound_shell_command(command: str) -> bool:
    """判断命令是否包含复合控制符（&&、||、;、|）。"""
    return any(token in command for token in ["&&", "||", ";", "|"])


class CodingAgent:
    """
    自主编程 Agent 主类。

    主要职责：
    - 初始化模型、工具、进度和 Git 管理器
    - 初始化项目上下文
    - 按功能粒度执行任务
    - 通过测试门禁决定功能完成状态
    - 记录迭代运行日志
    """

    def __init__(
        self,
        project_dir: str,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
    ):
        """初始化 CodingAgent 及其依赖组件。"""
        self.project_dir = os.path.abspath(project_dir)
        set_project_dir(self.project_dir)
        os.makedirs(self.project_dir, exist_ok=True)

        # 若外部尚未初始化事件日志器，则使用默认配置兜底
        if get_event_logger() is None:
            setup_event_logger(
                project_dir=self.project_dir,
                verbose_events=Config.VERBOSE_EVENTS_DEFAULT,
                persist_file=True,
                phase="agent",
            )
        else:
            update_event_context(project_dir=self.project_dir)

        emit_event(
            event_type="session_start",
            component="agent",
            name="agent_init",
            payload={"message": "Agent 实例初始化", "project_dir": self.project_dir},
            ok=True,
            phase="agent",
        )

        self.model_name = model_name or Config.MODEL_NAME
        self.base_url = base_url or Config.OPENAI_BASE_URL
        self.temperature = (
            temperature if temperature is not None else Config.TEMPERATURE
        )

        self.llm: Optional[ChatOpenAI] = None
        self.tools: List[Any] = []
        self.agent_executor: Optional[Any] = None
        self._fallback_executor: Optional[SimpleAgentExecutor] = None
        self._use_langgraph = False

        self._iteration_count = 0
        self._last_action: Optional[str] = None

        self._init_llm()
        self._init_tools()
        self._init_agent()
        self._init_progress_manager()
        self._init_git_helper()

    def _init_llm(self) -> None:
        """初始化 ChatOpenAI 客户端。"""
        self.llm = ChatOpenAI(
            model=self.model_name,
            base_url=self.base_url,
            api_key="not-needed",
            temperature=self.temperature,
            max_tokens=Config.MAX_TOKENS,
        )

    def _init_tools(self) -> None:
        """加载可供 Agent 调用的工具列表。"""
        self.tools = get_all_tools()

    def _init_agent(self) -> None:
        """初始化 Agent 执行器并按可用能力选择运行模式。"""
        self._fallback_executor = SimpleAgentExecutor(self.llm, self.tools)

        if not LANGGRAPH_AVAILABLE:
            self.agent_executor = self._fallback_executor
            self._use_langgraph = False
            return

        try:
            graph_or_runnable = create_react_agent(self.llm, self.tools)
            self.agent_executor = graph_or_runnable
            self._use_langgraph = True
        except Exception:
            self.agent_executor = self._fallback_executor
            self._use_langgraph = False

    def _init_progress_manager(self) -> None:
        """初始化项目进度管理器。"""
        self.progress_manager = ProgressManager(self.project_dir)

    def _init_git_helper(self) -> None:
        """初始化 Git 辅助操作器。"""
        self.git_helper = GitHelper(self.project_dir)

    @staticmethod
    def _extract_langgraph_output(result: Any) -> str:
        """从 LangGraph 调用结果中提取最终文本输出。"""
        if result is None:
            return ""

        if isinstance(result, str):
            return result

        if isinstance(result, dict):
            if "output" in result:
                return str(result.get("output", ""))
            messages = result.get("messages", [])
            if isinstance(messages, list) and messages:
                last_msg = messages[-1]
                return str(getattr(last_msg, "content", str(last_msg)))
            return str(result)

        return str(result)

    @staticmethod
    def _truncate_text(text: str, max_len: int = 2000) -> str:
        """截断过长文本，避免日志体积过大。"""
        if len(text) <= max_len:
            return text
        return text[:max_len] + "\n...(已截断)"

    def _compress_progress_content(self, progress_content: str) -> str:
        """
        压缩 progress.md 内容，保留项目头部与最近关键章节。

        参数:
            progress_content: 原始进度文件全文

        返回:
            str: 压缩后的进度摘要
        """
        if not progress_content.strip():
            return "（无进度记录）"

        lines = progress_content.splitlines()
        head_part = "\n".join(lines[:30]).strip()

        # 以二级标题切分，优先保留最近几个章节（通常包含最新执行结果与问题）。
        blocks = progress_content.split("\n## ")
        normalized_blocks: List[str] = []
        for index, block in enumerate(blocks):
            block = block.strip()
            if not block:
                continue
            if index == 0:
                normalized_blocks.append(block)
            else:
                normalized_blocks.append("## " + block)

        tail_count = max(1, Config.CONTEXT_RECENT_PROGRESS_SECTIONS)
        recent_blocks = normalized_blocks[-tail_count:]
        recent_part = "\n\n".join(recent_blocks).strip()

        compressed = (
            "### 进度头部摘要\n"
            f"{head_part}\n\n"
            "### 最近进展章节\n"
            f"{recent_part}"
        )
        return self._truncate_text(compressed, Config.CONTEXT_PROGRESS_MAX_CHARS)

    def _compress_git_history(self, git_history: str) -> str:
        """
        压缩 Git 历史文本。

        参数:
            git_history: 原始 Git 历史文本

        返回:
            str: 压缩后的历史摘要
        """
        if not git_history.strip():
            return "（无 Git 历史）"
        return self._truncate_text(git_history, Config.CONTEXT_GIT_MAX_CHARS)

    def _compress_init_script(self, init_sh: str) -> str:
        """
        压缩 init.sh 内容，保留前几行与摘要元信息。

        参数:
            init_sh: init.sh 原始内容

        返回:
            str: 压缩后的 init.sh 文本（含元信息）
        """
        if not init_sh.strip():
            return ""

        lines = init_sh.splitlines()
        max_lines = max(1, Config.CONTEXT_INIT_MAX_LINES)
        preview_lines = lines[:max_lines]
        preview = "\n".join(preview_lines)
        if len(lines) > max_lines:
            preview += "\n# ...(已截断)"

        digest = hashlib.sha1(init_sh.encode("utf-8")).hexdigest()[:12]
        preview = self._truncate_text(preview, Config.CONTEXT_INIT_MAX_CHARS)
        return (
            f"- 总行数: {len(lines)}\n"
            f"- SHA1: {digest}\n"
            "```bash\n"
            f"{preview}\n"
            "```"
        )

    @property
    def _run_log_path(self) -> str:
        """获取迭代日志文件路径。"""
        return os.path.join(self.project_dir, Config.RUN_LOG_FILE)

    def _append_run_log(self, record: Dict[str, Any]) -> None:
        """将一次迭代记录追加写入 JSONL 日志文件。"""
        try:
            with open(self._run_log_path, "a", encoding="utf-8") as file_obj:
                file_obj.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # 日志写入失败不应阻断主流程
            pass

    def _runtime_log_files(self) -> List[str]:
        """返回需要长期忽略 Git 跟踪的运行日志文件名列表。"""
        return [Config.EVENT_LOG_FILE, Config.RUN_LOG_FILE]

    def _ensure_runtime_logs_ignored(self) -> None:
        """确保目标项目 .gitignore 包含运行日志忽略规则。"""
        gitignore_path = os.path.join(self.project_dir, ".gitignore")
        required_entries = self._runtime_log_files()

        existing_lines: List[str] = []
        if os.path.exists(gitignore_path):
            with open(gitignore_path, "r", encoding="utf-8") as file_obj:
                existing_lines = file_obj.read().splitlines()

        normalized = {
            line.strip()
            for line in existing_lines
            if line.strip() and not line.strip().startswith("#")
        }
        missing_entries = [entry for entry in required_entries if entry not in normalized]
        if not missing_entries:
            emit_event(
                event_type="git_status",
                component="git",
                name="ensure_runtime_logs_ignored",
                payload={"message": "运行日志忽略规则已存在", "files": required_entries},
                ok=True,
                phase="init",
            )
            return

        output_lines = list(existing_lines)
        if output_lines and output_lines[-1].strip():
            output_lines.append("")
        output_lines.append("# Agent runtime logs")
        output_lines.extend(missing_entries)
        output_content = "\n".join(output_lines) + "\n"
        with open(gitignore_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(output_content)

        emit_event(
            event_type="git_status",
            component="git",
            name="ensure_runtime_logs_ignored",
            payload={
                "message": "已更新 .gitignore 运行日志忽略规则",
                "path": gitignore_path,
                "added": missing_entries,
            },
            ok=True,
            phase="init",
        )

    def _untrack_runtime_logs_if_needed(self) -> None:
        """若运行日志已被 Git 跟踪，则取消跟踪并保留本地文件。"""
        if not self.git_helper.is_repo():
            emit_event(
                event_type="git_status",
                component="git",
                name="untrack_runtime_logs",
                payload={"message": "非 Git 仓库，跳过取消跟踪"},
                ok=True,
                phase="init",
            )
            return

        runtime_logs = self._runtime_log_files()
        ls_result = subprocess.run(
            ["git", "ls-files", "--"] + runtime_logs,
            cwd=self.project_dir,
            capture_output=True,
            text=True,
        )
        if ls_result.returncode != 0:
            emit_event(
                event_type="error",
                component="git",
                name="untrack_runtime_logs",
                payload={"message": ls_result.stderr.strip()},
                ok=False,
                phase="init",
            )
            return

        tracked_files = [line.strip() for line in ls_result.stdout.splitlines() if line.strip()]
        if not tracked_files:
            emit_event(
                event_type="git_status",
                component="git",
                name="untrack_runtime_logs",
                payload={"message": "运行日志未被跟踪，无需处理"},
                ok=True,
                phase="init",
            )
            return

        untrack_result = subprocess.run(
            ["git", "rm", "--cached", "--ignore-unmatch", "--"] + tracked_files,
            cwd=self.project_dir,
            capture_output=True,
            text=True,
        )
        if untrack_result.returncode != 0:
            emit_event(
                event_type="error",
                component="git",
                name="untrack_runtime_logs",
                payload={"message": untrack_result.stderr.strip(), "files": tracked_files},
                ok=False,
                phase="init",
            )
            return

        emit_event(
            event_type="git_status",
            component="git",
            name="untrack_runtime_logs",
            payload={"message": "已取消跟踪运行日志文件", "files": tracked_files},
            ok=True,
            phase="init",
        )

    def _build_scaffold_init_summary(self, project_name: str, requirements: str) -> str:
        """生成 scaffold-only 模式的初始化摘要并写入 progress.md。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        requirement_preview = self._truncate_text(requirements.strip(), 500)
        summary_lines = [
            "## 初始化分析（scaffold-only）",
            "",
            f"- 时间: {now}",
            "- 模式: scaffold-only（仅脚手架，不进入功能实现）",
            f"- 项目名称: {project_name}",
            "- 已完成项:",
            "  - 创建/更新 progress.md",
            "  - 创建/更新 feature_list.json",
            "  - 写入 .gitignore 运行日志忽略规则",
            "  - 确保 init.sh 可执行",
            "  - 初始化 Git 并准备初始提交",
            "",
            "- 需求摘要:",
            requirement_preview or "（空）",
            "",
            "- 下一步: 使用 `python main.py run <project_dir>` 进入功能开发迭代",
        ]
        return "\n".join(summary_lines)

    def _execute_validated_command(self, command: str, timeout: int) -> Dict[str, Any]:
        """执行经过安全校验的命令并返回结构化结果。"""
        emit_event(
            event_type="tool_use",
            component="agent",
            name="command_exec",
            payload={"tool_name": "bash", "input_preview": command},
            ok=True,
            iteration=self._iteration_count,
            phase="run",
        )
        validator = get_validator()
        check_result = validator.validate_with_compound_handling(command)
        if not check_result.allowed:
            rejected = {
                "ok": False,
                "command": command,
                "returncode": 126,
                "stdout": "",
                "stderr": check_result.reason,
                "mode": "rejected",
                "duration_sec": 0.0,
            }
            emit_event(
                event_type="tool_result",
                component="agent",
                name="command_exec",
                payload={
                    "status": "blocked",
                    "returncode": rejected["returncode"],
                    "duration_sec": rejected["duration_sec"],
                    "stderr_preview": rejected["stderr"],
                },
                ok=False,
                iteration=self._iteration_count,
                phase="run",
            )
            return rejected

        start_time = time.time()
        try:
            if _is_compound_shell_command(command):
                # 复合命令使用 bash -lc 解释执行，但不启用 shell=True
                exec_args = ["bash", "-lc", command]
                mode = "compound"
            else:
                # 单命令模式使用 shlex 拆分参数，避免注入风险
                exec_args = shlex.split(command)
                mode = "single"

            if not exec_args:
                return {
                    "ok": False,
                    "command": command,
                    "returncode": 2,
                    "stdout": "",
                    "stderr": "命令为空",
                    "mode": "invalid",
                    "duration_sec": round(time.time() - start_time, 3),
                }

            completed = subprocess.run(
                exec_args,
                shell=False,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            success = {
                "ok": completed.returncode == 0,
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "mode": mode,
                "duration_sec": round(time.time() - start_time, 3),
            }
            emit_event(
                event_type="tool_result",
                component="agent",
                name="command_exec",
                payload={
                    "status": "done" if success["ok"] else "error",
                    "returncode": success["returncode"],
                    "duration_sec": success["duration_sec"],
                    "stdout_preview": self._truncate_text(success["stdout"], 200),
                    "stderr_preview": self._truncate_text(success["stderr"], 200),
                },
                ok=success["ok"],
                iteration=self._iteration_count,
                phase="run",
            )
            return success

        except subprocess.TimeoutExpired:
            timeout_result = {
                "ok": False,
                "command": command,
                "returncode": 124,
                "stdout": "",
                "stderr": f"命令执行超时（{timeout}秒）",
                "mode": "timeout",
                "duration_sec": round(time.time() - start_time, 3),
            }
            emit_event(
                event_type="tool_result",
                component="agent",
                name="command_exec",
                payload={
                    "status": "error",
                    "returncode": timeout_result["returncode"],
                    "duration_sec": timeout_result["duration_sec"],
                    "stderr_preview": timeout_result["stderr"],
                },
                ok=False,
                iteration=self._iteration_count,
                phase="run",
            )
            return timeout_result
        except ValueError as exc:
            invalid = {
                "ok": False,
                "command": command,
                "returncode": 2,
                "stdout": "",
                "stderr": f"命令解析失败: {exc}",
                "mode": "invalid",
                "duration_sec": round(time.time() - start_time, 3),
            }
            emit_event(
                event_type="tool_result",
                component="agent",
                name="command_exec",
                payload={
                    "status": "error",
                    "returncode": invalid["returncode"],
                    "duration_sec": invalid["duration_sec"],
                    "stderr_preview": invalid["stderr"],
                },
                ok=False,
                iteration=self._iteration_count,
                phase="run",
            )
            return invalid
        except Exception as exc:
            failed = {
                "ok": False,
                "command": command,
                "returncode": 1,
                "stdout": "",
                "stderr": str(exc),
                "mode": "error",
                "duration_sec": round(time.time() - start_time, 3),
            }
            emit_event(
                event_type="tool_result",
                component="agent",
                name="command_exec",
                payload={
                    "status": "error",
                    "returncode": failed["returncode"],
                    "duration_sec": failed["duration_sec"],
                    "stderr_preview": failed["stderr"],
                },
                ok=False,
                iteration=self._iteration_count,
                phase="run",
            )
            return failed

    def _ensure_init_script(self) -> None:
        """确保项目目录存在最小可用的 init.sh 脚本。"""
        init_path = os.path.join(self.project_dir, Config.INIT_SCRIPT_NAME)
        if os.path.exists(init_path):
            emit_event(
                event_type="precheck",
                component="agent",
                name="ensure_init_script",
                payload={"message": "init.sh 已存在，跳过创建"},
                ok=True,
                phase="init",
            )
            return

        init_content = """#!/usr/bin/env bash
# 最小初始化脚本：用于会话前健康检查
set -e

# 可在此添加依赖安装、环境检查等步骤
echo \"[init.sh] 初始化检查通过\"
"""
        with open(init_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(init_content)
        os.chmod(init_path, 0o755)
        emit_event(
            event_type="precheck",
            component="agent",
            name="ensure_init_script",
            payload={"message": "已创建最小 init.sh", "path": init_path},
            ok=True,
            phase="init",
        )

    def _run_session_precheck(self) -> Dict[str, Any]:
        """执行会话前检查（优先运行 init.sh）。"""
        init_path = os.path.join(self.project_dir, Config.INIT_SCRIPT_NAME)
        if not os.path.exists(init_path):
            skipped = {
                "ok": True,
                "skipped": True,
                "message": f"未找到 {Config.INIT_SCRIPT_NAME}，跳过会话前检查",
            }
            emit_event(
                event_type="precheck",
                component="agent",
                name="session_precheck",
                payload={"message": skipped["message"]},
                ok=True,
                iteration=self._iteration_count,
                phase="run",
            )
            return skipped

        result = self._execute_validated_command(
            command=f"bash ./{Config.INIT_SCRIPT_NAME}",
            timeout=Config.SESSION_PRECHECK_TIMEOUT,
        )
        result["skipped"] = False
        emit_event(
            event_type="precheck",
            component="agent",
            name="session_precheck",
            payload={
                "message": "会话前检查完成",
                "returncode": result.get("returncode"),
                "stderr_preview": self._truncate_text(result.get("stderr", ""), 200),
            },
            ok=result.get("ok", False),
            iteration=self._iteration_count,
            phase="run",
        )
        return result

    @staticmethod
    def _get_feature_verify_commands(feature: Feature) -> List[str]:
        """获取功能的验收命令列表，兼容旧的 test_command 字段。"""
        if getattr(feature, "verify_commands", None):
            return [cmd.strip() for cmd in feature.verify_commands if cmd.strip()]

        if feature.test_command:
            return [line.strip() for line in feature.test_command.splitlines() if line.strip()]

        return []

    def _run_feature_verification(self, feature: Feature) -> Dict[str, Any]:
        """执行功能验收命令并返回验证结果。"""
        commands = self._get_feature_verify_commands(feature)
        if not commands:
            no_verify = {
                "passed": False,
                "reason": "未配置验收命令，无法自动标记完成",
                "results": [],
            }
            emit_event(
                event_type="verification",
                component="agent",
                name="feature_verification",
                payload={"feature_id": feature.id, "reason": no_verify["reason"]},
                ok=False,
                iteration=self._iteration_count,
                phase="run",
            )
            return no_verify

        command_results: List[Dict[str, Any]] = []
        for command in commands:
            result = self._execute_validated_command(
                command=command,
                timeout=Config.VERIFICATION_TIMEOUT,
            )
            command_results.append(result)
            if not result.get("ok"):
                failed = {
                    "passed": False,
                    "reason": f"验收失败: {command}",
                    "results": command_results,
                }
                emit_event(
                    event_type="verification",
                    component="agent",
                    name="feature_verification",
                    payload={
                        "feature_id": feature.id,
                        "reason": failed["reason"],
                        "commands": commands,
                    },
                    ok=False,
                    iteration=self._iteration_count,
                    phase="run",
                )
                return failed

        verification_ok = {
            "passed": True,
            "reason": "所有验收命令通过",
            "results": command_results,
        }
        emit_event(
            event_type="verification",
            component="agent",
            name="feature_verification",
            payload={
                "feature_id": feature.id,
                "reason": verification_ok["reason"],
                "commands": commands,
            },
            ok=True,
            iteration=self._iteration_count,
            phase="run",
        )
        return verification_ok

    def _invoke_agent(self, prompt: str, chat_history: Optional[List[Any]] = None) -> Dict[str, Any]:
        """统一封装 Agent 调用，优先 LangGraph，失败回退到简易执行器。"""
        history = chat_history or []
        self._last_action = "invoke_agent"

        if self._use_langgraph and self.agent_executor is not None:
            try:
                messages: List[Any] = [SystemMessage(content=get_system_prompt())]
                messages.extend(SimpleAgentExecutor._normalize_chat_history(history))
                messages.append(HumanMessage(content=prompt))
                result = self.agent_executor.invoke({"messages": messages})
                output_text = self._extract_langgraph_output(result)
                emit_event(
                    event_type="assistant_text",
                    component="agent",
                    name="assistant_response",
                    payload={"text_preview": self._truncate_text(output_text, 500)},
                    ok=True,
                    iteration=self._iteration_count,
                    phase="run",
                )
                return {"output": output_text}
            except Exception:
                self._use_langgraph = False

        fallback_result = self._fallback_executor.invoke({"input": prompt, "chat_history": history})
        emit_event(
            event_type="assistant_text",
            component="agent",
            name="assistant_response",
            payload={"text_preview": self._truncate_text(fallback_result.get("output", ""), 500)},
            ok=True,
            iteration=self._iteration_count,
            phase="run",
        )
        return fallback_result

    def initialize(
        self,
        requirements: str,
        project_name: Optional[str] = None,
        init_mode: str = "scaffold-only",
    ) -> bool:
        """初始化项目进度文件、基础结构和初始 Git 提交。"""
        normalized_mode = (init_mode or "scaffold-only").strip().lower()
        if normalized_mode not in {"scaffold-only", "open"}:
            normalized_mode = "scaffold-only"

        update_event_context(phase="init", project_dir=self.project_dir)
        emit_event(
            event_type="session_start",
            component="agent",
            name="initialize",
            payload={"message": "开始执行初始化流程", "init_mode": normalized_mode},
            ok=True,
            phase="init",
        )
        if project_name is None:
            project_name = os.path.basename(self.project_dir)

        try:
            ok = self.progress_manager.initialize(project_name, requirements)
            if not ok:
                return False

            feature_list = self.progress_manager.load_feature_list(force_reload=True)
            if feature_list and not feature_list.features:
                self.progress_manager.add_feature(
                    feature_id="feat-001",
                    name="项目初始化与基础结构",
                    description=requirements,
                    priority="high",
                    verify_commands=["ls -la"],
                )

            # 先确保运行日志不纳入版本控制，避免初始化阶段循环提交日志文件
            self._ensure_runtime_logs_ignored()

            # 无论模型是否可用，都先确保 init.sh 存在，保证后续 run 可执行
            self._ensure_init_script()

            if not self.git_helper.is_repo():
                self.git_helper.init_repo()

            # 历史项目可能已经把运行日志纳入了索引，这里统一取消跟踪但保留本地文件
            self._untrack_runtime_logs_if_needed()

            if normalized_mode == "open":
                # 初始化分析阶段：模型失败时降级为提示信息，不阻断初始化成功
                try:
                    init_prompt = prompt_loader.get_initializer_prompt(
                        requirements=requirements,
                        project_name=project_name,
                        project_dir=self.project_dir,
                        current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        init_mode=normalized_mode,
                    )
                    init_result = self._invoke_agent(init_prompt, [])
                    init_output = init_result.get("output", "").strip()
                    if init_output:
                        self.progress_manager.append_to_progress("## 初始化分析\n\n" + init_output)
                except Exception as exc:
                    self.progress_manager.append_to_progress(
                        "## 初始化分析\n\n"
                        f"- 模型初始化分析失败，已降级继续。\n"
                        f"- 原因: {exc}"
                    )
            else:
                scaffold_summary = self._build_scaffold_init_summary(
                    project_name=project_name,
                    requirements=requirements,
                )
                self.progress_manager.append_to_progress(scaffold_summary)
                emit_event(
                    event_type="assistant_text",
                    component="agent",
                    name="initialize_summary",
                    payload={"text_preview": self._truncate_text(scaffold_summary, 500)},
                    ok=True,
                    phase="init",
                )

            if self.git_helper.has_changes():
                self.git_helper.commit("chore: 项目初始化")
                emit_event(
                    event_type="git_commit",
                    component="git",
                    name="initialize_commit",
                    payload={"message": "chore: 项目初始化", "init_mode": normalized_mode},
                    ok=True,
                    phase="init",
                )

            emit_event(
                event_type="session_end",
                component="agent",
                name="initialize",
                payload={"message": "初始化流程结束"},
                ok=True,
                phase="init",
            )
            return True
        except Exception as exc:
            print(f"[Agent] 初始化失败: {exc}")
            emit_event(
                event_type="error",
                component="agent",
                name="initialize",
                payload={"message": str(exc)},
                ok=False,
                phase="init",
            )
            return False

    def run(
        self,
        max_iterations: Optional[int] = None,
        on_iteration: Optional[Callable[[int, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """执行单次任务循环并处理一个可执行功能。"""
        update_event_context(phase="run", project_dir=self.project_dir)
        emit_event(
            event_type="session_start",
            component="agent",
            name="run",
            payload={"message": "开始执行单次运行"},
            ok=True,
            iteration=self._iteration_count,
            phase="run",
        )
        _ = max_iterations or Config.MAX_ITERATIONS

        feature_list = self.progress_manager.load_feature_list(force_reload=True)
        if feature_list is None:
            payload = {"success": False, "error": "未找到 feature_list.json，请先执行 init"}
            emit_event(
                event_type="session_end",
                component="agent",
                name="run",
                payload={"message": payload["error"]},
                ok=False,
                iteration=self._iteration_count,
                phase="run",
            )
            return payload

        precheck_result = self._run_session_precheck()
        if not precheck_result.get("ok"):
            payload = {
                "success": False,
                "error": f"会话前检查失败: {precheck_result.get('stderr', '')}",
                "status": "blocked",
                "precheck": precheck_result,
            }
            self._append_run_log(
                {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "iteration": self._iteration_count,
                    "event": "session_precheck_failed",
                    "payload": payload,
                }
            )
            emit_event(
                event_type="session_end",
                component="agent",
                name="run",
                payload={"message": payload["error"], "status": payload["status"]},
                ok=False,
                iteration=self._iteration_count,
                phase="run",
            )
            return payload

        scheduling = self.progress_manager.get_next_feature_with_reason()
        next_feature = scheduling.get("feature")
        if next_feature is None:
            stats = self.progress_manager.get_progress_stats()
            if stats.get("completion_rate") == 100:
                payload = {"success": True, "message": "所有功能已完成"}
                emit_event(
                    event_type="session_end",
                    component="agent",
                    name="run",
                    payload={"message": payload["message"]},
                    ok=True,
                    iteration=self._iteration_count,
                    phase="run",
                )
                return payload

            reason_parts: List[str] = []
            dependency_blocked = scheduling.get("dependency_blocked", [])
            cooldown_blocked = scheduling.get("cooldown_blocked", [])
            if dependency_blocked:
                blocked_ids = ",".join(item.get("id", "") for item in dependency_blocked[:5])
                reason_parts.append(f"依赖未满足({blocked_ids})")
            if cooldown_blocked:
                cooldown_ids = ",".join(item.get("id", "") for item in cooldown_blocked[:5])
                reason_parts.append(f"冷却中({cooldown_ids})")

            detail = "；".join(reason_parts) if reason_parts else "可能被依赖阻塞"
            payload = {"success": False, "error": f"没有可执行的功能（{detail}）"}
            emit_event(
                event_type="session_end",
                component="agent",
                name="run",
                payload={
                    "message": payload["error"],
                    "dependency_blocked_count": len(dependency_blocked),
                    "cooldown_blocked_count": len(cooldown_blocked),
                },
                ok=False,
                iteration=self._iteration_count,
                phase="run",
            )
            return payload

        self.progress_manager.update_feature_status(next_feature.id, "in_progress")

        progress_content = self.progress_manager.load_progress() or ""
        git_history = format_commits_for_prompt(self.git_helper.get_recent_commits(5))
        init_sh_path = os.path.join(self.project_dir, Config.INIT_SCRIPT_NAME)
        init_sh_content = ""
        if os.path.exists(init_sh_path):
            try:
                with open(init_sh_path, "r", encoding="utf-8") as file_obj:
                    init_sh_content = file_obj.read()
            except Exception:
                init_sh_content = ""

        session_context = self._build_session_context(
            progress_content=progress_content,
            git_history=git_history,
            init_sh=init_sh_content,
            feature_list=feature_list,
            precheck_result=precheck_result,
        )
        task_prompt = prompt_loader.get_coding_prompt(
            progress_summary=session_context,
            pending_features=self._format_pending_features(),
            current_task=self._format_current_task(next_feature),
        )

        try:
            self._iteration_count += 1
            result = self._invoke_agent(task_prompt, [])
            output_text = result.get("output", "")

            # 关键门禁：只有验收命令全部通过才标记 completed
            verification = self._run_feature_verification(next_feature)
            is_completed = verification.get("passed", False)

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            run_status = "completed" if is_completed else "in_progress"
            if is_completed:
                self.progress_manager.record_feature_attempt(
                    feature_id=next_feature.id,
                    success=True,
                    cooldown_seconds=0,
                )
                self.progress_manager.update_feature_status(
                    next_feature.id,
                    "completed",
                    f"完成于 {now_str}；{verification.get('reason', '')}",
                )
                summary_title = "## 功能执行记录（完成）"
            else:
                updated_feature = self.progress_manager.record_feature_attempt(
                    feature_id=next_feature.id,
                    success=False,
                    cooldown_seconds=Config.FEATURE_FAILURE_COOLDOWN_SECONDS,
                )
                fail_count = (updated_feature.consecutive_failures if updated_feature else 1)
                cooldown_info = ""
                if updated_feature and updated_feature.cooldown_until:
                    cooldown_info = f"；冷却至 {updated_feature.cooldown_until}"

                if fail_count >= Config.FEATURE_MAX_CONSECUTIVE_FAILURES:
                    run_status = "blocked"
                    self.progress_manager.update_feature_status(
                        next_feature.id,
                        "blocked",
                        (
                            f"会话结束于 {now_str}；{verification.get('reason', '验收未通过')}"
                            f"；连续失败 {fail_count} 次，已转 blocked"
                        ),
                    )
                    summary_title = "## 功能执行记录（阻塞）"
                else:
                    self.progress_manager.update_feature_status(
                        next_feature.id,
                        "in_progress",
                        (
                            f"会话结束于 {now_str}；{verification.get('reason', '验收未通过')}"
                            f"；连续失败 {fail_count} 次{cooldown_info}"
                        ),
                    )
                    summary_title = "## 功能执行记录（进行中）"

            verification_lines = ["### 验收结果", f"- 结论: {verification.get('reason', '')}"]
            for item in verification.get("results", []):
                verification_lines.append(
                    f"- 命令: `{item.get('command', '')}`，返回码: {item.get('returncode', '')}"
                )
                if item.get("stderr"):
                    verification_lines.append(f"  - 错误: {self._truncate_text(item['stderr'], 300)}")

            if output_text.strip() or verification_lines:
                self.progress_manager.append_to_progress(
                    f"{summary_title}\n\n"
                    f"- 功能: {next_feature.id} {next_feature.name}\n\n"
                    f"### Agent 输出\n{self._truncate_text(output_text, 1500)}\n\n"
                    + "\n".join(verification_lines)
                )

            if self.git_helper.has_changes():
                if is_completed:
                    commit_msg = f"feat: 完成 {next_feature.name} ({next_feature.id})"
                else:
                    commit_msg = f"wip: {next_feature.name} 验收未通过 ({next_feature.id})"
                commit_ok = self.git_helper.commit(commit_msg)
                if commit_ok:
                    emit_event(
                        event_type="git_commit",
                        component="git",
                        name="run_commit",
                        payload={
                            "message": commit_msg,
                            "feature_id": next_feature.id,
                            "status": "completed" if is_completed else "in_progress",
                        },
                        ok=True,
                        iteration=self._iteration_count,
                        phase="run",
                    )
                else:
                    emit_event(
                        event_type="error",
                        component="git",
                        name="run_commit",
                        payload={
                            "message": f"提交失败: {commit_msg}",
                            "feature_id": next_feature.id,
                        },
                        ok=False,
                        iteration=self._iteration_count,
                        phase="run",
                    )

            payload = {
                "success": is_completed,
                "feature_id": next_feature.id,
                "output": output_text,
                "status": run_status,
                "verification": verification,
            }

            self._append_run_log(
                {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "iteration": self._iteration_count,
                    "event": "run_iteration",
                    "feature_id": next_feature.id,
                    "status": payload["status"],
                    "verification": verification,
                    "precheck": {
                        "ok": precheck_result.get("ok", False),
                        "stderr": self._truncate_text(precheck_result.get("stderr", ""), 300),
                    },
                    "output_preview": self._truncate_text(output_text, 300),
                }
            )

            if on_iteration is not None:
                on_iteration(self._iteration_count, payload)
            emit_event(
                event_type="session_end",
                component="agent",
                name="run",
                payload={"message": "单次运行结束", "status": payload["status"]},
                ok=payload["success"],
                iteration=self._iteration_count,
                phase="run",
            )
            return payload

        except Exception as exc:
            updated_feature = self.progress_manager.record_feature_attempt(
                feature_id=next_feature.id,
                success=False,
                cooldown_seconds=Config.FEATURE_FAILURE_COOLDOWN_SECONDS,
            )
            fail_count = (updated_feature.consecutive_failures if updated_feature else 1)
            if fail_count >= Config.FEATURE_MAX_CONSECUTIVE_FAILURES:
                final_status = "blocked"
                final_note = f"错误: {exc}；连续失败 {fail_count} 次，已转 blocked"
            else:
                final_status = "in_progress"
                cooldown_info = ""
                if updated_feature and updated_feature.cooldown_until:
                    cooldown_info = f"；冷却至 {updated_feature.cooldown_until}"
                final_note = f"错误: {exc}；连续失败 {fail_count} 次{cooldown_info}"

            self.progress_manager.update_feature_status(
                next_feature.id,
                final_status,
                final_note,
            )
            payload = {
                "success": False,
                "error": str(exc),
                "feature_id": next_feature.id,
                "status": final_status,
            }
            self._append_run_log(
                {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "iteration": self._iteration_count,
                    "event": "run_exception",
                    "payload": payload,
                }
            )
            emit_event(
                event_type="error",
                component="agent",
                name="run",
                payload={"message": str(exc)},
                ok=False,
                iteration=self._iteration_count,
                phase="run",
            )
            emit_event(
                event_type="session_end",
                component="agent",
                name="run",
                payload={"message": f"运行异常: {exc}", "status": payload["status"]},
                ok=False,
                iteration=self._iteration_count,
                phase="run",
            )
            return payload

    def run_continuous(
        self,
        max_total_iterations: int = 100,
        pause_between_tasks: float = 1.0,
    ) -> Dict[str, Any]:
        """连续执行任务直到完成、阻塞或达到最大轮次。"""
        results = {
            "completed_features": [],
            "failed_features": [],
            "total_iterations": 0,
        }

        for _ in range(max_total_iterations):
            next_feature = self.progress_manager.get_next_feature()
            if next_feature is None:
                break

            result = self.run(max_iterations=Config.MAX_ITERATIONS)
            results["total_iterations"] += 1

            feature_id = next_feature.id
            if result.get("success"):
                results["completed_features"].append(feature_id)
            else:
                results["failed_features"].append(feature_id)

            if pause_between_tasks > 0:
                time.sleep(pause_between_tasks)

        return results

    def _build_context(self, progress_content: str, feature_list: Any) -> str:
        """构建简要上下文摘要。"""
        stats = self.progress_manager.get_progress_stats()
        context_parts = [
            "## 项目信息",
            f"- 名称: {feature_list.project_name}",
            f"- 总功能数: {stats['total']}",
            f"- 已完成: {stats['completed']}",
            f"- 完成率: {stats['completion_rate']}%",
            "",
            "## 当前进度",
            progress_content or "（无进度记录）",
        ]
        return "\n".join(context_parts)

    def _format_pending_features(self) -> str:
        """格式化待处理功能列表供提示词使用。"""
        pending = self.progress_manager.get_pending_features()
        if not pending:
            return "（无待完成功能）"

        status_map = {
            "pending": "⏳",
            "in_progress": "🔄",
            "completed": "✅",
            "blocked": "❌",
        }
        priority_map = {"high": "高", "medium": "中", "low": "低"}

        lines: List[str] = []
        for feature in pending:
            status_icon = status_map.get(feature.status, "❓")
            priority = priority_map.get(feature.priority, "中")
            lines.append(
                f"{status_icon} [{feature.id}] {feature.name} "
                f"(优先级: {priority}, 状态: {feature.status})"
            )

        return "\n".join(lines)

    def _build_session_context(
        self,
        progress_content: str,
        git_history: str,
        init_sh: str,
        feature_list: Any,
        precheck_result: Optional[Dict[str, Any]] = None,
    ) -> str:
        """构建包含进度、Git 历史和启动脚本的会话上下文。"""
        stats = self.progress_manager.get_progress_stats()
        compressed_progress = self._compress_progress_content(progress_content)
        compressed_git_history = self._compress_git_history(git_history)
        compressed_init_sh = self._compress_init_script(init_sh)

        context_parts = [
            "## 会话上下文",
            "",
            "### 项目信息",
            f"- 名称: {feature_list.project_name}",
            f"- 技术栈: {feature_list.tech_stack or '未指定'}",
            f"- 启动命令: {feature_list.init_command}",
            f"- 总功能数: {stats['total']}",
            f"- 已完成: {stats['completed']}",
            f"- 完成率: {stats['completion_rate']}%",
            "",
            "### 会话前检查",
        ]

        if precheck_result is None:
            context_parts.append("- 本轮未执行会话前检查")
        elif precheck_result.get("ok"):
            context_parts.append("- 会话前检查通过")
        else:
            context_parts.append(f"- 会话前检查失败: {precheck_result.get('stderr', '')}")

        context_parts.extend(
            [
                "",
                "### 进度文件摘要（压缩）",
                compressed_progress,
                "",
                "### 最近 Git 历史（压缩）",
                compressed_git_history,
            ]
        )

        if compressed_init_sh:
            context_parts.extend(["", "### init.sh 摘要（压缩）", compressed_init_sh])

        context_text = "\n".join(context_parts)
        return self._truncate_text(context_text, Config.CONTEXT_TOTAL_MAX_CHARS)

    def _format_current_task(self, feature: Feature) -> str:
        """格式化当前执行任务的描述文本。"""
        lines = [
            f"## 当前任务: [{feature.id}] {feature.name}",
            "",
            f"**描述**: {feature.description or '无描述'}",
            "",
        ]

        if feature.acceptance_criteria:
            lines.append("**验收标准**:")
            for index, criteria in enumerate(feature.acceptance_criteria, 1):
                lines.append(f"{index}. {criteria}")
            lines.append("")

        verify_commands = self._get_feature_verify_commands(feature)
        if verify_commands:
            lines.append("**验收命令**:")
            for index, command in enumerate(verify_commands, 1):
                lines.append(f"{index}. `{command}`")
            lines.append("")

        lines.extend(
            [
                "**重要提醒**:",
                "- 完成功能后必须执行验收命令",
                "- 只有验收通过才允许标记 completed",
                "- 会话结束前更新进度并创建提交",
            ]
        )
        return "\n".join(lines)

    def get_status(self) -> Dict[str, Any]:
        """返回当前 Agent 状态、统计信息与下一任务。"""
        feature_list = self.progress_manager.load_feature_list(force_reload=True)
        stats = self.progress_manager.get_progress_stats()
        next_feature = self.progress_manager.get_next_feature()

        return {
            "project_dir": self.project_dir,
            "model": self.model_name,
            "project_name": feature_list.project_name if feature_list else "未知",
            "stats": stats,
            "next_feature": (
                {
                    "id": next_feature.id,
                    "name": next_feature.name,
                    "status": next_feature.status,
                }
                if next_feature
                else None
            ),
            "progress_report": self.progress_manager.get_progress_report(),
            "run_log_path": self._run_log_path,
        }

    def chat(self, message: str, chat_history: Optional[List[Any]] = None) -> str:
        """执行一次对话请求并返回文本回复。"""
        result = self._invoke_agent(message, chat_history or [])
        return result.get("output", "")

    def add_feature(
        self,
        feature_id: str,
        name: str,
        description: str = "",
        priority: str = "medium",
        dependencies: Optional[List[str]] = None,
        verify_commands: Optional[List[str]] = None,
    ) -> bool:
        """向功能列表添加新功能项。"""
        return self.progress_manager.add_feature(
            feature_id=feature_id,
            name=name,
            description=description,
            priority=priority,
            dependencies=dependencies,
            verify_commands=verify_commands,
        )

    def reset_feature(self, feature_id: str) -> bool:
        """将指定功能状态重置为 pending。"""
        return self.progress_manager.update_feature_status(
            feature_id=feature_id,
            status="pending",
            notes="状态已重置",
        )


def create_agent(
    project_dir: str,
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
) -> CodingAgent:
    """创建 CodingAgent 实例的工厂函数。"""
    return CodingAgent(project_dir=project_dir, model_name=model_name, base_url=base_url)


def quick_init(project_dir: str, requirements: str) -> CodingAgent:
    """快速完成 Agent 创建与项目初始化。"""
    agent = CodingAgent(project_dir)
    agent.initialize(requirements)
    return agent


def quick_run(project_dir: str) -> Dict[str, Any]:
    """快速创建 Agent 并执行一次任务循环。"""
    agent = CodingAgent(project_dir)
    return agent.run()
