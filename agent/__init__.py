# -*- coding: utf-8 -*-
"""
Agent 模块初始化文件 (__init__.py)
=================================

本文件定义了 agent 包的公共接口。
从其他模块导入时，可以直接使用：

    from agent import CodingAgent, tools, progress

而不是：
    from agent.agent import CodingAgent
    from agent.tools import *
    from agent.progress import *

导出的模块和类：
- CodingAgent: 核心编程 Agent 类
- tools: 工具函数模块
- progress: 进度管理模块
- security: 安全控制模块
- prompts: 提示词模板模块
- git_helper: Git 操作辅助模块
"""

# 导入核心类和函数，供外部使用
from .agent import CodingAgent
from . import tools
from . import progress
from . import security
from . import prompts
from . import git_helper
from . import event_logger

# 定义公开接口
# 当使用 from agent import * 时，只会导入这些名称
__all__ = [
    "CodingAgent",   # 核心 Agent 类
    "tools",         # 工具模块
    "progress",      # 进度管理模块
    "security",      # 安全控制模块
    "prompts",       # 提示词模块
    "git_helper",    # Git 辅助模块
    "event_logger",  # 事件日志模块
]

# 版本信息
__version__ = "0.1.0"
__author__ = "Autonomous Coding Agent Project"
