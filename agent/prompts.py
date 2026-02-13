# -*- coding: utf-8 -*-
"""
提示词模块 (prompts.py)
======================

本模块负责加载和管理 Agent 使用的各种提示词模板。

提示词存储在 prompts/ 目录下的独立文件中：
- system_prompt.md: 系统提示词，定义 Agent 的角色和行为规范
- initializer_prompt.md: 初始化提示词，用于项目初始化阶段
- coding_prompt.md: 编码提示词，用于日常编码任务
- error_handling_prompt.md: 错误处理提示词
- feature_complete_prompt.md: 功能完成提示词
- task_planning_prompt.md: 任务规划提示词
- progress_report_prompt.md: 进度报告提示词

使用示例:
    from agent.prompts import PromptLoader

    loader = PromptLoader()
    system_prompt = loader.get_system_prompt()
    init_prompt = loader.get_initializer_prompt("创建一个 Flask 应用")
"""

import os
from typing import Optional
from datetime import datetime


# ============================================
# 提示词文件路径配置
# ============================================

# 获取 prompts 目录的路径
# 位于项目根目录下的 prompts/ 文件夹
PROMPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts"
)

# 提示词文件名映射
PROMPT_FILES = {
    "system": "system_prompt.md",
    "initializer": "initializer_prompt.md",
    "coding": "coding_prompt.md",
    "error_handling": "error_handling_prompt.md",
    "feature_complete": "feature_complete_prompt.md",
    "task_planning": "task_planning_prompt.md",
    "progress_report": "progress_report_prompt.md",
}


# ============================================
# 提示词加载器类
# ============================================

class PromptLoader:
    """
    提示词加载器类

    负责从文件系统加载提示词模板，并提供格式化功能。

    主要功能:
    - 从 prompts/ 目录加载 .md 文件
    - 缓存已加载的提示词
    - 提供格式化方法填充变量

    使用示例:
        loader = PromptLoader()
        system = loader.get_system_prompt()
        init = loader.get_initializer_prompt(
            requirements="创建一个 Web 应用",
            project_name="MyApp",
            project_dir="/path/to/project",
            current_time="2024-01-01 12:00:00"
        )
    """

    def __init__(self, prompts_dir: str = None):
        """
        初始化提示词加载器

        参数:
            prompts_dir: 提示词目录路径（可选，默认使用 PROMPTS_DIR）

        说明:
            初始化时清空缓存，提示词将在首次访问时从文件加载。
        """
        self.prompts_dir = prompts_dir or PROMPTS_DIR
        self._cache = {}  # 提示词缓存

    def _load_prompt(self, prompt_name: str) -> str:
        """
        从文件加载提示词

        参数:
            prompt_name: 提示词名称（如 "system", "initializer"）

        返回:
            str: 提示词内容

        说明:
            - 优先从缓存读取
            - 如果缓存未命中，从文件加载并缓存
            - 如果文件不存在，返回空字符串
        """
        # 检查缓存
        if prompt_name in self._cache:
            return self._cache[prompt_name]

        # 获取文件路径
        filename = PROMPT_FILES.get(prompt_name)
        if not filename:
            raise ValueError(f"未知的提示词名称: {prompt_name}")

        filepath = os.path.join(self.prompts_dir, filename)

        # 从文件加载
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            print(f"警告: 提示词文件不存在: {filepath}")
            content = ""
        except Exception as e:
            print(f"错误: 加载提示词文件失败: {str(e)}")
            content = ""

        # 缓存并返回
        self._cache[prompt_name] = content
        return content

    def _format_prompt(self, template: str, **kwargs) -> str:
        """
        格式化提示词模板

        参数:
            template: 提示词模板字符串
            **kwargs: 要填充的变量

        返回:
            str: 格式化后的提示词

        说明:
            使用 Python 的 str.format() 方法进行变量替换。
        """
        try:
            return template.format(**kwargs)
        except KeyError as e:
            print(f"警告: 提示词缺少变量: {e}")
            return template

    # ============================================
    # 各类提示词的获取方法
    # ============================================

    def get_system_prompt(self) -> str:
        """
        获取系统提示词

        返回:
            str: 系统提示词内容

        说明:
            系统提示词定义了 Agent 的基本行为规范和能力说明。
            这个提示词会在每次对话开始时发送给 LLM。
        """
        return self._load_prompt("system")

    def get_initializer_prompt(
        self,
        requirements: str,
        project_name: str = "未命名项目",
        project_dir: str = "",
        current_time: str = None,
        init_mode: str = "scaffold-only",
    ) -> str:
        """
        获取初始化提示词

        参数:
            requirements: 项目需求描述
            project_name: 项目名称
            project_dir: 项目目录路径
            current_time: 当前时间（可选，默认自动生成）
            init_mode: 初始化模式（scaffold-only/open）

        返回:
            str: 格式化后的初始化提示词

        说明:
            初始化提示词用于项目初始化阶段，
            指导 Agent 创建项目结构和规划文档。
        """
        template = self._load_prompt("initializer")

        if current_time is None:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return self._format_prompt(
            template,
            requirements=requirements,
            project_name=project_name,
            project_dir=project_dir,
            current_time=current_time,
            init_mode=init_mode,
        )

    def get_coding_prompt(
        self,
        progress_summary: str,
        pending_features: str,
        current_task: str
    ) -> str:
        """
        获取编码提示词

        参数:
            progress_summary: 当前进度摘要
            pending_features: 待完成功能列表
            current_task: 当前任务描述

        返回:
            str: 格式化后的编码提示词

        说明:
            编码提示词用于日常编码任务，
            告知 Agent 当前状态和待完成的工作。
        """
        template = self._load_prompt("coding")

        return self._format_prompt(
            template,
            progress_summary=progress_summary,
            pending_features=pending_features,
            current_task=current_task
        )

    def get_error_handling_prompt(self, error_message: str) -> str:
        """
        获取错误处理提示词

        参数:
            error_message: 错误信息

        返回:
            str: 格式化后的错误处理提示词

        说明:
            当执行过程中遇到错误时使用此提示词，
            指导 Agent 分析和修复错误。
        """
        template = self._load_prompt("error_handling")

        return self._format_prompt(
            template,
            error_message=error_message
        )

    def get_feature_complete_prompt(self, feature_name: str) -> str:
        """
        获取功能完成提示词

        参数:
            feature_name: 完成的功能名称

        返回:
            str: 格式化后的功能完成提示词

        说明:
            当一个功能完成时使用此提示词，
            指导 Agent 验证功能并更新状态。
        """
        template = self._load_prompt("feature_complete")

        return self._format_prompt(
            template,
            feature_name=feature_name
        )

    def get_task_planning_prompt(
        self,
        requirements: str,
        completed: str
    ) -> str:
        """
        获取任务规划提示词

        参数:
            requirements: 当前需求
            completed: 已完成的工作

        返回:
            str: 格式化后的任务规划提示词

        说明:
            用于规划接下来的工作。
        """
        template = self._load_prompt("task_planning")

        return self._format_prompt(
            template,
            requirements=requirements,
            completed=completed
        )

    def get_progress_report_prompt(
        self,
        project_info: str,
        feature_status: str
    ) -> str:
        """
        获取进度报告提示词

        参数:
            project_info: 项目基本信息
            feature_status: 功能状态列表

        返回:
            str: 格式化后的进度报告提示词

        说明:
            用于生成项目进度报告。
        """
        template = self._load_prompt("progress_report")

        return self._format_prompt(
            template,
            project_info=project_info,
            feature_status=feature_status
        )

    def clear_cache(self):
        """
        清空提示词缓存

        说明:
            当提示词文件被修改后，调用此方法重新加载。
        """
        self._cache.clear()

    def reload_prompt(self, prompt_name: str) -> str:
        """
        重新加载指定的提示词

        参数:
            prompt_name: 提示词名称

        返回:
            str: 重新加载的提示词内容

        说明:
            从缓存中移除后重新从文件加载。
        """
        if prompt_name in self._cache:
            del self._cache[prompt_name]
        return self._load_prompt(prompt_name)


# ============================================
# 全局加载器实例
# ============================================

# 创建全局加载器实例
# 其他模块可以直接使用，无需创建新实例
loader = PromptLoader()


# ============================================
# 便捷函数（向后兼容）
# ============================================

def get_system_prompt() -> str:
    """
    获取系统提示词（便捷函数）

    返回:
        str: 系统提示词内容
    """
    return loader.get_system_prompt()


def get_initializer_prompt(requirements: str, init_mode: str = "scaffold-only") -> str:
    """
    获取初始化提示词（便捷函数）

    参数:
        requirements: 项目需求描述
        init_mode: 初始化模式（scaffold-only/open）

    返回:
        str: 格式化后的初始化提示词
    """
    return loader.get_initializer_prompt(requirements=requirements, init_mode=init_mode)


def get_coding_prompt(
    progress_summary: str,
    pending_features: str,
    current_task: str
) -> str:
    """
    获取编码提示词（便捷函数）

    参数:
        progress_summary: 当前进度摘要
        pending_features: 待完成功能列表
        current_task: 当前任务描述

    返回:
        str: 格式化后的编码提示词
    """
    return loader.get_coding_prompt(
        progress_summary=progress_summary,
        pending_features=pending_features,
        current_task=current_task
    )


def get_error_handling_prompt(error_message: str) -> str:
    """
    获取错误处理提示词（便捷函数）
    """
    return loader.get_error_handling_prompt(error_message)


def get_feature_complete_prompt(feature_name: str) -> str:
    """
    获取功能完成提示词（便捷函数）
    """
    return loader.get_feature_complete_prompt(feature_name)


def get_task_planning_prompt(requirements: str, completed: str) -> str:
    """
    获取任务规划提示词（便捷函数）
    """
    return loader.get_task_planning_prompt(requirements, completed)


# ============================================
# 向后兼容的模板类
# ============================================

class PromptTemplates:
    """
    提示词模板类（向后兼容）

    提供统一的接口访问各种提示词模板。
    实际工作由 PromptLoader 完成。

    使用示例:
        templates = PromptTemplates()
        system = templates.system_prompt
        init = templates.get_initializer("创建一个 Flask 应用")
    """

    def __init__(self):
        """
        初始化提示词模板类

        使用全局 loader 实例。
        """
        self._loader = loader

    @property
    def system_prompt(self) -> str:
        """
        获取系统提示词

        返回:
            str: 系统提示词
        """
        return self._loader.get_system_prompt()

    def get_initializer(self, requirements: str, init_mode: str = "scaffold-only") -> str:
        """
        获取初始化提示词

        参数:
            requirements: 项目需求
            init_mode: 初始化模式（scaffold-only/open）

        返回:
            str: 初始化提示词
        """
        return self._loader.get_initializer_prompt(
            requirements=requirements,
            init_mode=init_mode,
        )

    def get_coding(
        self,
        progress_summary: str,
        pending_features: str,
        current_task: str
    ) -> str:
        """
        获取编码提示词

        参数:
            progress_summary: 进度摘要
            pending_features: 待完成功能
            current_task: 当前任务

        返回:
            str: 编码提示词
        """
        return self._loader.get_coding_prompt(
            progress_summary=progress_summary,
            pending_features=pending_features,
            current_task=current_task
        )

    def get_current_time(self) -> str:
        """
        获取当前时间字符串

        返回:
            str: 格式化的当前时间

        说明:
            用于在提示词中插入时间信息。
        """
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# 创建全局模板实例（向后兼容）
templates = PromptTemplates()
