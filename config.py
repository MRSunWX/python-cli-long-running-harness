# -*- coding: utf-8 -*-
"""
配置文件 (config.py)
====================

本文件包含项目的全局配置信息，包括：
- LLM 模型配置（OpenAI 兼容服务地址、模型名称等）
- 项目默认设置
- 安全相关配置
- Agent 行为参数

使用方式：
    from config import Config
    print(Config.OPENAI_BASE_URL)
"""

from dataclasses import dataclass, field
from typing import List
import os


@dataclass
class Config:
    """
    项目配置类

    使用 dataclass 装饰器自动生成 __init__、__repr__ 等方法。
    所有配置项都集中在这个类中管理，便于维护和修改。

    属性:
        OPENAI_BASE_URL: OpenAI 兼容服务的 API 地址
        MODEL_NAME: 使用的模型名称
        TEMPERATURE: 生成文本的温度参数，控制随机性
        MAX_TOKENS: 单次生成的最大 token 数量
        PROJECT_DIR: 项目工作目录
        ALLOWED_COMMANDS: 允许执行的 Bash 命令白名单
        BLOCKED_COMMANDS: 禁止执行的 Bash 命令黑名单
        MAX_ITERATIONS: Agent 单次运行的最大迭代次数
    """

    # OpenAI 兼容服务的 API 端点地址
    # 推荐使用带 /v1 路径的兼容接口
    OPENAI_BASE_URL: str = "http://10.33.101.35:11434/v1"

    # 使用的 Qwen3-Coder 模型名称
    # 这是一个 30B 参数的代码专用模型
    MODEL_NAME: str = "qwen3-coder:30b"

    # 生成温度参数 (0.0 - 1.0)
    # 较低的值使输出更确定，较高的值使输出更随机
    # 代码生成建议使用较低的温度
    TEMPERATURE: float = 0.1

    # 单次生成的最大 token 数量
    # 根据所接入模型服务的限制设置
    MAX_TOKENS: int = 4096

    # 允许执行的 Bash 命令白名单
    # 留空表示允许所有不在黑名单中的命令
    ALLOWED_COMMANDS: List[str] = field(default_factory=list)

    # 禁止执行的 Bash 命令黑名单
    # 这些命令可能造成系统损坏或数据丢失
    BLOCKED_COMMANDS: List[str] = field(default_factory=lambda: [
        "rm -rf /",           # 禁止删除根目录
        "rm -rf /*",          # 禁止删除根目录下所有文件
        "mkfs",               # 禁止格式化磁盘
        "dd if=",             # 禁止直接磁盘操作
        "> /dev/sd",          # 禁止写入磁盘设备
        "chmod -R 777 /",     # 禁止递归修改根目录权限
        "chown -R",           # 禁止递归修改所有者
        ":(){ :|:& };:",      # 禁止 fork bomb
        "shutdown",           # 禁止关机
        "reboot",             # 禁止重启
        "init 0",             # 禁止关机
        "init 6",             # 禁止重启
        "halt",               # 禁止停机
        "poweroff",           # 禁止关机
    ])

    # Agent 单次运行的最大迭代次数
    # 我们设置为 200，适合单次会话
    MAX_ITERATIONS: int = 200

    # 上下文窗口中保留的历史消息数量
    # 用于控制 prompt 长度
    MAX_HISTORY_MESSAGES: int = 20

    # 会话之间的自动继续延迟（秒）
    AUTO_CONTINUE_DELAY: float = 3.0

    # 命令执行默认超时时间（秒）
    # 用于 run_bash 等通用命令执行场景
    COMMAND_TIMEOUT: int = 60

    # 会话前检查（如 init.sh）超时时间（秒）
    SESSION_PRECHECK_TIMEOUT: int = 120

    # 功能验收测试命令超时时间（秒）
    VERIFICATION_TIMEOUT: int = 300

    # 功能连续失败后的冷却秒数（用于避免 in_progress 永久霸占）
    FEATURE_FAILURE_COOLDOWN_SECONDS: int = 300

    # 功能连续失败达到阈值后，自动转为 blocked
    FEATURE_MAX_CONSECUTIVE_FAILURES: int = 3

    # 迭代运行日志文件名
    RUN_LOG_FILE: str = "run_logs.jsonl"

    # 事件日志文件名（终端事件的结构化落盘）
    EVENT_LOG_FILE: str = "events.jsonl"

    # 会话前检查脚本文件名
    INIT_SCRIPT_NAME: str = "init.sh"

    # 事件日志默认开关（True 表示默认输出详细事件）
    VERBOSE_EVENTS_DEFAULT: bool = True

    # 事件日志文本预览长度
    EVENT_PREVIEW_LENGTH: int = 300

    # 上下文压缩相关阈值（按字符数近似控制 token）
    CONTEXT_TOTAL_MAX_CHARS: int = 12000
    CONTEXT_PROGRESS_MAX_CHARS: int = 4000
    CONTEXT_GIT_MAX_CHARS: int = 1500
    CONTEXT_INIT_MAX_CHARS: int = 2500
    CONTEXT_INIT_MAX_LINES: int = 60
    CONTEXT_RECENT_PROGRESS_SECTIONS: int = 3


# 创建全局配置实例
# 其他模块可以直接导入使用
config = Config()


def get_project_dir() -> str:
    """
    获取当前项目工作目录

    返回:
        str: 项目目录的绝对路径

    说明:
        优先从环境变量 PROJECT_DIR 获取，
        如果未设置则返回当前工作目录。
    """
    return os.environ.get("PROJECT_DIR", os.getcwd())


def set_project_dir(path: str) -> None:
    """
    设置项目工作目录

    参数:
        path: 要设置的项目目录路径

    说明:
        将项目目录路径保存到环境变量中，
        供其他模块使用。
    """
    abs_path = os.path.abspath(path)
    os.environ["PROJECT_DIR"] = abs_path


# 模型配置说明
MODEL_CONFIG = {
    "model": Config.MODEL_NAME,
    "temperature": Config.TEMPERATURE,
    "max_tokens": Config.MAX_TOKENS,
    "base_url": Config.OPENAI_BASE_URL,
}
"""
模型配置字典

包含创建 LLM 实例所需的配置参数。
可直接传递给 LangChain 的 ChatOpenAI 类。

使用示例:
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(**MODEL_CONFIG)
"""
