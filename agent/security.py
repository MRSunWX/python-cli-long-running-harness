# -*- coding: utf-8 -*-
"""
安全控制模块 (security.py)
=========================

本模块实现了 Bash 命令执行的安全控制，包括：
- 命令黑名单/白名单检查
- 路径访问限制（沙箱机制）
- 危险操作检测
- 命令注入防护

安全策略：
1. 黑名单优先：所有在黑名单中的命令都会被拒绝
2. 白名单可选：如果配置了白名单，只有白名单中的命令可以执行
3. 路径限制：命令执行被限制在项目目录内
4. 特殊字符过滤：防止命令注入攻击
"""

import os
import re
import shlex
from typing import Tuple, Optional, List
from dataclasses import dataclass

# 导入项目配置
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config, get_project_dir
from .event_logger import emit_event


@dataclass
class SecurityCheckResult:
    """
    安全检查结果类

    用于返回安全检查的结果，包含是否通过、拒绝原因等信息。

    属性:
        allowed: 命令是否被允许执行
        reason: 如果被拒绝，说明拒绝的原因
        sanitized_command: 清理后的安全命令（可选）
        risk_level: 风险等级 (low, medium, high, critical)
    """
    allowed: bool
    reason: str = ""
    sanitized_command: Optional[str] = None
    risk_level: str = "low"


class CommandValidator:
    """
    命令验证器类

    负责验证用户输入的 Bash 命令是否安全可执行。

    主要功能:
    - 检查命令是否在黑名单中
    - 检查命令是否在白名单中（如果启用）
    - 检测危险模式（如命令注入）
    - 验证路径是否在允许范围内

    使用示例:
        validator = CommandValidator()
        result = validator.validate("ls -la")
        if result.allowed:
            # 执行命令
            pass
        else:
            print(f"命令被拒绝: {result.reason}")
    """

    def __init__(
        self,
        allowed_commands: List[str] = None,
        blocked_commands: List[str] = None,
        sandbox_dir: str = None
    ):
        """
        初始化命令验证器

        参数:
            allowed_commands: 允许的命令白名单，为空表示允许所有非黑名单命令
            blocked_commands: 禁止的命令黑名单
            sandbox_dir: 沙箱目录，命令执行被限制在此目录内

        说明:
            如果未提供参数，将使用 Config 中的默认值。
        """
        # 使用配置中的默认值或用户提供的值
        # Config 是 dataclass，需要通过实例获取字段默认值
        cfg = Config()  # 创建配置实例
        self.allowed_commands = allowed_commands or cfg.ALLOWED_COMMANDS
        self.blocked_commands = blocked_commands or cfg.BLOCKED_COMMANDS
        self.sandbox_dir = sandbox_dir or get_project_dir()

        # 编译黑名单命令的正则表达式，用于高效匹配
        self._compile_blocked_patterns()

    def _compile_blocked_patterns(self):
        """
        编译黑名单命令的正则表达式

        将黑名单中的命令模式编译为正则表达式，
        以便快速检测危险命令。

        说明:
            使用 re.IGNORECASE 使匹配不区分大小写，
            防止通过大小写变化绕过检测。
        """
        patterns = []
        for cmd in self.blocked_commands:
            # 转义正则特殊字符，但保留通配符语义
            escaped = re.escape(cmd)
            patterns.append(escaped)

        # 合并所有模式为一个正则表达式
        if patterns:
            self.blocked_pattern = re.compile(
                '|'.join(patterns),
                re.IGNORECASE
            )
        else:
            self.blocked_pattern = None

    @staticmethod
    def _emit_reject_event(command: str, result: "SecurityCheckResult") -> None:
        """
        输出安全拦截事件日志

        参数:
            command: 原始命令
            result: 安全检查结果
        """
        if result.allowed:
            return
        emit_event(
            event_type="tool_result",
            component="security",
            name="command_validation",
            payload={
                "status": "blocked",
                "returncode": 126,
                "duration_sec": 0.0,
                "stderr_preview": result.reason,
                "input_preview": command,
            },
            ok=False,
            phase="run",
        )

    def validate(self, command: str) -> SecurityCheckResult:
        """
        验证命令是否安全可执行

        参数:
            command: 要验证的 Bash 命令字符串

        返回:
            SecurityCheckResult: 包含验证结果的对象

        验证流程:
        1. 检查命令是否为空
        2. 检查命令是否包含危险模式（黑名单）
        3. 检查命令是否在白名单中（如果启用）
        4. 检查路径是否在沙箱范围内
        5. 检测命令注入尝试
        """
        # 步骤 1: 检查空命令
        if not command or not command.strip():
            return SecurityCheckResult(
                allowed=False,
                reason="命令不能为空",
                risk_level="low"
            )

        # 清理命令前后的空白字符
        command = command.strip()

        # 步骤 2: 检查黑名单
        blocked_result = self._check_blocked(command)
        if not blocked_result.allowed:
            self._emit_reject_event(command, blocked_result)
            return blocked_result

        # 步骤 3: 检查白名单（如果启用）
        if self.allowed_commands:
            whitelist_result = self._check_whitelist(command)
            if not whitelist_result.allowed:
                self._emit_reject_event(command, whitelist_result)
                return whitelist_result

        # 步骤 4: 检查路径限制
        path_result = self._check_paths(command)
        if not path_result.allowed:
            self._emit_reject_event(command, path_result)
            return path_result

        # 步骤 5: 检测命令注入
        injection_result = self._check_injection(command)
        if not injection_result.allowed:
            self._emit_reject_event(command, injection_result)
            return injection_result

        # 所有检查通过
        return SecurityCheckResult(
            allowed=True,
            sanitized_command=command,
            risk_level="low"
        )

    def _check_blocked(self, command: str) -> SecurityCheckResult:
        """
        检查命令是否在黑名单中

        参数:
            command: 要检查的命令

        返回:
            SecurityCheckResult: 检查结果

        说明:
            黑名单中的命令被认为是危险的，
            可能造成系统损坏或数据丢失。
        """
        if self.blocked_pattern and self.blocked_pattern.search(command):
            # 找到匹配的危险模式
            matched = self.blocked_pattern.search(command).group()
            return SecurityCheckResult(
                allowed=False,
                reason=f"命令包含危险操作: '{matched}' 在黑名单中",
                risk_level="critical"
            )
        return SecurityCheckResult(allowed=True)

    def _check_whitelist(self, command: str) -> SecurityCheckResult:
        """
        检查命令是否在白名单中

        参数:
            command: 要检查的命令

        返回:
            SecurityCheckResult: 检查结果

        说明:
            如果启用了白名单，只有白名单中的命令可以执行。
            提取命令的第一个词（实际命令名）进行匹配。
        """
        try:
            # 使用 shlex 正确解析命令
            parts = shlex.split(command)
            if not parts:
                return SecurityCheckResult(
                    allowed=False,
                    reason="无法解析命令",
                    risk_level="medium"
                )

            # 获取实际命令名（去除路径）
            cmd_name = os.path.basename(parts[0])

            # 检查是否在白名单中
            if cmd_name not in self.allowed_commands:
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"命令 '{cmd_name}' 不在白名单中",
                    risk_level="medium"
                )

        except ValueError as e:
            # shlex 解析失败，可能有格式问题
            return SecurityCheckResult(
                allowed=False,
                reason=f"命令格式错误: {str(e)}",
                risk_level="medium"
            )

        return SecurityCheckResult(allowed=True)

    def _check_paths(self, command: str) -> SecurityCheckResult:
        """
        检查命令中的路径是否在沙箱范围内

        参数:
            command: 要检查的命令

        返回:
            SecurityCheckResult: 检查结果

        说明:
            提取命令中的所有路径参数，
            检查它们是否在允许的沙箱目录内。
            这防止了访问项目目录外的敏感文件。
        """
        # 获取沙箱目录的绝对路径
        sandbox_abs = os.path.abspath(self.sandbox_dir)

        # 查找命令中可能的路径
        # 匹配以 / 开头的路径或 ./ 开头的相对路径
        path_pattern = r'(?:^|\s)([\./][^\s;|&<>]+)|(?:^|\s)(/[^\s;|&<>]+)'
        paths = re.findall(path_pattern, command)

        for path_tuple in paths:
            # 获取非空的路径
            path = path_tuple[0] or path_tuple[1]
            if not path:
                continue

            try:
                # 解析为绝对路径
                if path.startswith('/'):
                    abs_path = os.path.abspath(path)
                else:
                    abs_path = os.path.abspath(os.path.join(self.sandbox_dir, path))

                # 检查是否在沙箱内
                # 使用 os.path.commonpath 检查路径前缀
                if not abs_path.startswith(sandbox_abs):
                    return SecurityCheckResult(
                        allowed=False,
                        reason=f"路径 '{path}' 超出沙箱范围 '{self.sandbox_dir}'",
                        risk_level="high"
                    )

            except (ValueError, OSError):
                # 路径解析错误，可能是无效路径
                pass

        return SecurityCheckResult(allowed=True)

    def _check_injection(self, command: str) -> SecurityCheckResult:
        """
        检测命令注入尝试

        参数:
            command: 要检查的命令

        返回:
            SecurityCheckResult: 检查结果

        说明:
            检测常见的命令注入模式，如：
            - 命令链式执行 (;, &&, ||)
            - 命令替换 $() 或 ` `
            - 管道符 |
            - 重定向到敏感位置
            - 环境变量注入
        """
        # 危险的模式列表
        dangerous_patterns = [
            # 命令替换
            (r'\$\([^)]*\)', "检测到命令替换 $(...)"),
            (r'`[^`]*`', "检测到命令替换 `...`"),

            # 敏感的环境变量访问
            (r'\$\{?[A-Z_]+\}?', "检测到环境变量引用"),

            # 危险的重定向
            (r'>\s*/dev/', "检测到重定向到设备文件"),
            (r'>\s*/proc/', "检测到重定向到 proc 文件系统"),

            # 网络 相关
            (r'nc\s+-', "检测到 netcat 命令"),
            (r'curl\s+.*\|\s*bash', "检测到从网络下载并执行"),
            (r'wget\s+.*\|\s*bash', "检测到从网络下载并执行"),
        ]

        for pattern, message in dangerous_patterns:
            if re.search(pattern, command):
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"潜在的安全风险: {message}",
                    risk_level="high"
                )

        return SecurityCheckResult(allowed=True)

    def _split_command_segments(self, command_string: str) -> List[str]:
        """
        将复合命令分割为独立的命令段

        处理命令链（&&, ||, ;）但不处理管道（管道是单个命令）。

        参数:
            command_string: 完整的 shell 命令

        返回:
            List[str]: 独立命令段列表

        参考:
            Anthropic autonomous-coding 示例的实现
        """
        # 分割 && 和 ||
        segments = re.split(r'\s*(?:&&|\|\|)\s*', command_string)

        result = []
        for segment in segments:
            # 进一步按分号分割（不在引号内的分号）
            sub_segments = re.split(r'(?<!["\'])\s*;\s*(?!["\'])', segment)
            for sub in sub_segments:
                sub = sub.strip()
                if sub:
                    result.append(sub)

        return result

    def _extract_all_commands(self, command_string: str) -> List[str]:
        """
        从命令字符串中提取所有命令名称

        处理管道、命令链和子 shell。
        使用 shlex 安全解析，避免正则表达式绕过漏洞。

        参数:
            command_string: 完整的 shell 命令

        返回:
            List[str]: 找到的命令名称列表

        参考:
            Anthropic autonomous-coding 示例的 extract_commands 函数
        """
        commands = []
        segments = self._split_command_segments(command_string)

        for segment in segments:
            try:
                tokens = shlex.split(segment)
            except ValueError:
                continue

            if not tokens:
                continue

            # 跟踪何时期望命令 vs 参数
            expect_command = True

            for token in tokens:
                # Shell 操作符表示后面跟新命令
                if token in ("|", "||", "&&", "&"):
                    expect_command = True
                    continue

                # 跳过 shell 关键字
                if token in (
                    "if", "then", "else", "elif", "fi",
                    "for", "while", "until", "do", "done",
                    "case", "esac", "in", "!", "{", "}"
                ):
                    continue

                # 跳过选项/标志
                if token.startswith("-"):
                    continue

                # 跳过变量赋值 (VAR=value)
                if "=" in token and not token.startswith("="):
                    continue

                if expect_command:
                    cmd = os.path.basename(token) if '/' in token else token
                    commands.append(cmd)
                    expect_command = False

        return commands

    def _validate_sensitive_command(self, command: str, cmd_name: str) -> SecurityCheckResult:
        """
        对敏感命令进行额外验证

        某些命令即使在白名单中也需要额外检查。

        参数:
            command: 完整命令字符串
            cmd_name: 命令名称

        返回:
            SecurityCheckResult: 验证结果

        参考:
            Anthropic 示例中的 validate_pkill_command, validate_chmod_command 等
        """
        # 获取包含该命令的段
        segments = self._split_command_segments(command)
        cmd_segment = command
        for segment in segments:
            if cmd_name in self._extract_all_commands(segment):
                cmd_segment = segment
                break

        # pkill 验证 - 只允许终止开发相关进程
        if cmd_name == "pkill":
            allowed_processes = {"node", "npm", "npx", "vite", "next", "python", "python3"}
            try:
                tokens = shlex.split(cmd_segment)
            except ValueError:
                return SecurityCheckResult(
                    allowed=False,
                    reason="无法解析 pkill 命令",
                    risk_level="high"
                )

            args = [t for t in tokens[1:] if not t.startswith("-")]
            if not args:
                return SecurityCheckResult(
                    allowed=False,
                    reason="pkill 需要指定进程名",
                    risk_level="medium"
                )

            target = args[-1]
            if " " in target:
                target = target.split()[0]

            if target not in allowed_processes:
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"pkill 只允许用于开发进程: {allowed_processes}",
                    risk_level="high"
                )

        # chmod 验证 - 只允许 +x 模式
        elif cmd_name == "chmod":
            try:
                tokens = shlex.split(cmd_segment)
            except ValueError:
                return SecurityCheckResult(
                    allowed=False,
                    reason="无法解析 chmod 命令",
                    risk_level="high"
                )

            if len(tokens) < 3:
                return SecurityCheckResult(
                    allowed=False,
                    reason="chmod 需要模式和文件参数",
                    risk_level="medium"
                )

            # 找到模式参数
            mode = None
            for token in tokens[1:]:
                if not token.startswith("-"):
                    mode = token
                    break

            if not mode:
                return SecurityCheckResult(
                    allowed=False,
                    reason="chmod 需要指定模式",
                    risk_level="medium"
                )

            # 只允许 +x 变体
            if not re.match(r'^[ugoa]*\+x$', mode):
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"chmod 只允许 +x 模式，得到: {mode}",
                    risk_level="high"
                )

        # rm 验证 - 阻止危险删除
        elif cmd_name == "rm":
            if re.search(r'rm\s+-.*rf\s+/', cmd_segment):
                return SecurityCheckResult(
                    allowed=False,
                    reason="禁止递归强制删除根目录",
                    risk_level="critical"
                )
            if '/*' in cmd_segment:
                return SecurityCheckResult(
                    allowed=False,
                    reason="禁止删除根目录内容",
                    risk_level="critical"
                )

        return SecurityCheckResult(allowed=True)

    def validate_with_compound_handling(self, command: str) -> SecurityCheckResult:
        """
        支持复合命令的增强验证

        对复合命令（包含 &&, ||, ;）进行逐段验证。

        参数:
            command: 要验证的命令

        返回:
            SecurityCheckResult: 验证结果
        """
        # 首先进行基础验证
        base_result = self.validate(command)
        if not base_result.allowed:
            return base_result

        # 提取所有命令进行逐个检查
        commands = self._extract_all_commands(command)
        if not commands:
            # 解析失败时回退到 shlex 的首命令提取，避免误伤合法命令
            try:
                parts = shlex.split(command)
            except ValueError as exc:
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"无法解析命令进行安全验证: {exc}",
                    risk_level="medium"
                )

            if not parts:
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"无法解析命令进行安全验证: {command}",
                    risk_level="medium"
                )

            commands = [os.path.basename(parts[0])]

        # 需要额外验证的敏感命令
        sensitive_commands = {"pkill", "chmod", "rm"}

        for cmd in commands:
            # 如果有白名单，检查每个命令
            if self.allowed_commands and cmd not in self.allowed_commands:
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"命令 '{cmd}' 不在白名单中",
                    risk_level="medium"
                )

            # 敏感命令额外验证
            if cmd in sensitive_commands:
                result = self._validate_sensitive_command(command, cmd)
                if not result.allowed:
                    return result

        return SecurityCheckResult(
            allowed=True,
            sanitized_command=command,
            risk_level="low"
        )


class SandboxExecutor:
    """
    沙箱执行器类

    提供在安全沙箱环境中执行 Bash 命令的功能。

    主要功能:
    - 使用 CommandValidator 验证命令安全性
    - 在受限环境中执行命令
    - 捕获和处理执行结果

    使用示例:
        executor = SandboxExecutor()
        result = executor.execute("ls -la")
        print(result.stdout)
    """

    def __init__(self, sandbox_dir: str = None):
        """
        初始化沙箱执行器

        参数:
            sandbox_dir: 沙箱目录路径，命令将在此目录下执行
        """
        self.sandbox_dir = sandbox_dir or get_project_dir()
        self.validator = CommandValidator(sandbox_dir=self.sandbox_dir)

    def is_safe(self, command: str) -> Tuple[bool, str]:
        """
        检查命令是否安全

        参数:
            command: 要检查的命令

        返回:
            Tuple[bool, str]: (是否安全, 原因说明)

        说明:
            这是一个便捷方法，直接返回布尔值和原因字符串。
        """
        result = self.validator.validate(command)
        return result.allowed, result.reason

    def get_safe_command(self, command: str) -> Optional[str]:
        """
        获取清理后的安全命令

        参数:
            command: 原始命令

        返回:
            Optional[str]: 清理后的命令，如果不安全则返回 None

        说明:
            返回经过安全验证和清理的命令，
            可直接用于 subprocess 执行。
        """
        result = self.validator.validate(command)
        if result.allowed:
            return result.sanitized_command
        return None


# 创建全局验证器实例
# 可以直接使用，无需创建新实例
_global_validator = None
_global_executor = None


def get_validator() -> CommandValidator:
    """
    获取全局命令验证器实例

    返回:
        CommandValidator: 全局验证器实例

    说明:
        使用单例模式，避免重复创建验证器。
    """
    global _global_validator
    if _global_validator is None:
        _global_validator = CommandValidator()
    return _global_validator


def get_executor() -> SandboxExecutor:
    """
    获取全局沙箱执行器实例

    返回:
        SandboxExecutor: 全局执行器实例

    说明:
        使用单例模式，避免重复创建执行器。
    """
    global _global_executor
    if _global_executor is None:
        _global_executor = SandboxExecutor()
    return _global_executor


def validate_command(command: str) -> SecurityCheckResult:
    """
    便捷函数：验证命令安全性

    参数:
        command: 要验证的命令

    返回:
        SecurityCheckResult: 验证结果

    说明:
        这是一个便捷函数，直接使用全局验证器进行验证。
    """
    return get_validator().validate(command)


def is_command_safe(command: str) -> Tuple[bool, str]:
    """
    便捷函数：检查命令是否安全

    参数:
        command: 要检查的命令

    返回:
        Tuple[bool, str]: (是否安全, 原因说明)
    """
    result = validate_command(command)
    return result.allowed, result.reason
