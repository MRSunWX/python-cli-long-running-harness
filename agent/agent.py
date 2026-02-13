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

import os
import sys
import time
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
from .tools import get_all_tools


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


class CodingAgent:
    """
    自主编程 Agent 主类。

    主要职责：
    - 初始化模型、工具、进度和 Git 管理器
    - 初始化项目上下文
    - 按功能粒度执行任务
    - 提供状态查询与对话能力
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

        self.model_name = model_name or Config.MODEL_NAME
        self.base_url = base_url or Config.OLLAMA_BASE_URL
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
                return {"output": self._extract_langgraph_output(result)}
            except Exception:
                self._use_langgraph = False

        return self._fallback_executor.invoke(
            {"input": prompt, "chat_history": history}
        )

    def initialize(self, requirements: str, project_name: Optional[str] = None) -> bool:
        """初始化项目进度文件、基础功能和初始 Git 提交。"""
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
                )

            init_prompt = prompt_loader.get_initializer_prompt(
                requirements=requirements,
                project_name=project_name,
                project_dir=self.project_dir,
                current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            init_result = self._invoke_agent(init_prompt, [])
            init_output = init_result.get("output", "").strip()
            if init_output:
                self.progress_manager.append_to_progress(
                    "## 初始化分析\n\n" + init_output
                )

            if not self.git_helper.is_repo():
                self.git_helper.init_repo()

            if self.git_helper.has_changes():
                self.git_helper.commit("chore: 项目初始化")

            return True
        except Exception as exc:
            print(f"[Agent] 初始化失败: {exc}")
            return False

    def run(
        self,
        max_iterations: Optional[int] = None,
        on_iteration: Optional[Callable[[int, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """执行单次任务循环并处理一个可执行功能。"""
        _ = max_iterations or Config.MAX_ITERATIONS

        feature_list = self.progress_manager.load_feature_list(force_reload=True)
        if feature_list is None:
            return {"success": False, "error": "未找到 feature_list.json，请先执行 init"}

        next_feature = self.progress_manager.get_next_feature()
        if next_feature is None:
            stats = self.progress_manager.get_progress_stats()
            if stats.get("completion_rate") == 100:
                return {"success": True, "message": "所有功能已完成"}
            return {"success": False, "error": "没有可执行的功能（可能被依赖阻塞）"}

        self.progress_manager.update_feature_status(next_feature.id, "in_progress")

        progress_content = self.progress_manager.load_progress() or ""
        git_history = format_commits_for_prompt(self.git_helper.get_recent_commits(5))
        init_sh_path = os.path.join(self.project_dir, "init.sh")
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

            completion_keywords = ["完成", "completed", "done", "finished", "成功"]
            lowered = output_text.lower()
            is_completed = any(word in lowered for word in completion_keywords)
            if not output_text.strip():
                is_completed = False

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if is_completed:
                self.progress_manager.update_feature_status(
                    next_feature.id,
                    "completed",
                    f"完成于 {now_str}",
                )
                summary_title = "## 功能执行记录（完成）"
            else:
                self.progress_manager.update_feature_status(
                    next_feature.id,
                    "in_progress",
                    f"会话结束于 {now_str}，需要继续执行",
                )
                summary_title = "## 功能执行记录（进行中）"

            if output_text.strip():
                self.progress_manager.append_to_progress(
                    f"{summary_title}\n\n- 功能: {next_feature.id} {next_feature.name}\n\n{output_text}"
                )

            if self.git_helper.has_changes():
                if is_completed:
                    commit_msg = f"feat: 完成 {next_feature.name} ({next_feature.id})"
                else:
                    commit_msg = f"wip: {next_feature.name} 进行中 ({next_feature.id})"
                self.git_helper.commit(commit_msg)

            payload = {
                "success": is_completed,
                "feature_id": next_feature.id,
                "output": output_text,
                "status": "completed" if is_completed else "in_progress",
            }
            if on_iteration is not None:
                on_iteration(self._iteration_count, payload)
            return payload

        except Exception as exc:
            self.progress_manager.update_feature_status(
                next_feature.id,
                "blocked",
                f"错误: {exc}",
            )
            return {"success": False, "error": str(exc), "feature_id": next_feature.id}

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
    ) -> str:
        """构建包含进度、Git 历史和启动脚本的会话上下文。"""
        stats = self.progress_manager.get_progress_stats()
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
            "### 进度文件内容",
            progress_content or "（无进度记录）",
            "",
            git_history,
        ]

        if init_sh:
            context_parts.extend(["", "### init.sh 内容", "```bash", init_sh, "```"])

        return "\n".join(context_parts)

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

        if feature.test_command:
            lines.append(f"**测试命令**: `{feature.test_command}`")
            lines.append("")

        lines.extend(
            [
                "**重要提醒**:",
                "- 完成功能后运行测试并更新状态",
                "- 确认符合验收标准后再标记 completed",
                "- 会话结束前记录进度并创建提交",
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
    ) -> bool:
        """向功能列表添加新功能项。"""
        return self.progress_manager.add_feature(
            feature_id=feature_id,
            name=name,
            description=description,
            priority=priority,
            dependencies=dependencies,
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
