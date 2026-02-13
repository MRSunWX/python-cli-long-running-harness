# -*- coding: utf-8 -*-
"""
工具模块 (tools.py)
===================

本模块定义了 Agent 可以使用的所有工具函数，包括：
- 文件操作工具：读取、写入、编辑、列出文件
- 代码搜索工具：在代码库中搜索内容
- Bash 命令执行工具：在沙箱中执行命令

所有工具都使用 LangChain 的 @tool 装饰器定义，
使其可以被 LangChain Agent 直接调用。

使用示例:
    from agent.tools import get_all_tools
    tools = get_all_tools()
"""

import os
import subprocess
import shlex
import re
import time
import glob as glob_module
from typing import Optional, List, Any, Tuple, Dict
from langchain_core.tools import tool, StructuredTool

# 导入安全模块和配置
from .security import get_validator
from config import get_project_dir, Config
from .event_logger import emit_event


# ============================================
# 文件操作工具
# ============================================

@tool
def read_file(file_path: str) -> str:
    """
    读取文件内容

    参数:
        file_path: 要读取的文件路径（相对或绝对路径）

    返回:
        str: 文件的完整内容

    说明:
        - 支持相对路径和绝对路径
        - 如果是相对路径，会相对于项目目录解析
        - 文件不存在时会返回错误信息
        - 自动处理 UTF-8 编码

    使用示例:
        content = read_file("src/main.py")
    """
    try:
        # 解析文件路径
        # 如果是相对路径，相对于项目目录
        if not os.path.isabs(file_path):
            project_dir = get_project_dir()
            file_path = os.path.join(project_dir, file_path)

        # 安全检查：确保路径在项目目录内
        abs_path = os.path.abspath(file_path)
        project_dir = os.path.abspath(get_project_dir())
        if not abs_path.startswith(project_dir):
            return f"错误: 路径 '{file_path}' 超出项目目录范围"

        # 检查文件是否存在
        if not os.path.exists(abs_path):
            return f"错误: 文件 '{file_path}' 不存在"

        # 检查是否是文件（而非目录）
        if not os.path.isfile(abs_path):
            return f"错误: '{file_path}' 不是文件"

        # 读取文件内容
        with open(abs_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return content

    except UnicodeDecodeError:
        return f"错误: 文件 '{file_path}' 不是有效的 UTF-8 文本文件"
    except PermissionError:
        return f"错误: 没有权限读取文件 '{file_path}'"
    except Exception as e:
        return f"读取文件时发生错误: {str(e)}"


@tool
def write_file(file_path: str, content: str) -> str:
    """
    创建或覆盖文件

    参数:
        file_path: 要写入的文件路径（相对或绝对路径）
        content: 要写入的文件内容

    返回:
        str: 操作结果信息

    说明:
        - 如果文件不存在，会创建新文件
        - 如果文件已存在，会完全覆盖原内容
        - 会自动创建必要的父目录
        - 使用 UTF-8 编码写入

    使用示例:
        result = write_file("src/new_file.py", "# 新文件\\nprint('Hello')")
    """
    try:
        # 解析文件路径
        if not os.path.isabs(file_path):
            project_dir = get_project_dir()
            file_path = os.path.join(project_dir, file_path)

        # 安全检查
        abs_path = os.path.abspath(file_path)
        project_dir = os.path.abspath(get_project_dir())
        if not abs_path.startswith(project_dir):
            return f"错误: 路径 '{file_path}' 超出项目目录范围"

        # 创建父目录（如果不存在）
        parent_dir = os.path.dirname(abs_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        # 写入文件
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return f"成功: 文件 '{file_path}' 已写入 ({len(content)} 字符)"

    except PermissionError:
        return f"错误: 没有权限写入文件 '{file_path}'"
    except Exception as e:
        return f"写入文件时发生错误: {str(e)}"


@tool
def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """
    编辑文件（字符串替换）

    参数:
        file_path: 要编辑的文件路径
        old_string: 要被替换的原始字符串（必须完全匹配）
        new_string: 替换后的新字符串

    返回:
        str: 操作结果信息

    说明:
        - 使用精确字符串匹配，不会进行模糊匹配
        - old_string 在文件中必须唯一，否则会报错
        - 如果 old_string 不存在，会返回错误
        - 适合小范围的精确修改

    使用示例:
        result = edit_file("main.py", "print('hello')", "print('world')")
    """
    try:
        # 解析文件路径
        if not os.path.isabs(file_path):
            project_dir = get_project_dir()
            file_path = os.path.join(project_dir, file_path)

        # 安全检查
        abs_path = os.path.abspath(file_path)
        project_dir = os.path.abspath(get_project_dir())
        if not abs_path.startswith(project_dir):
            return f"错误: 路径 '{file_path}' 超出项目目录范围"

        # 检查文件是否存在
        if not os.path.exists(abs_path):
            return f"错误: 文件 '{file_path}' 不存在"

        # 读取当前内容
        with open(abs_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 检查 old_string 是否存在
        if old_string not in content:
            return f"错误: 未找到要替换的内容 '{old_string[:50]}...'"

        # 检查 old_string 是否唯一
        count = content.count(old_string)
        if count > 1:
            return f"错误: 找到 {count} 处匹配，old_string 必须唯一。请提供更多上下文使匹配唯一。"

        # 执行替换
        new_content = content.replace(old_string, new_string)

        # 写入文件
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return f"成功: 文件 '{file_path}' 已更新"

    except PermissionError:
        return f"错误: 没有权限编辑文件 '{file_path}'"
    except Exception as e:
        return f"编辑文件时发生错误: {str(e)}"


@tool
def list_files(directory: str = ".", pattern: str = "*") -> str:
    """
    列出目录中的文件和子目录

    参数:
        directory: 要列出的目录路径，默认为当前目录
        pattern: 文件匹配模式（glob 格式），默认为 "*" 匹配所有

    返回:
        str: 文件和目录列表，每行一个

    说明:
        - 支持 glob 模式匹配（如 "*.py", "src/**/*.js"）
        - 递归模式使用 "**" （如 "**/*.py"）
        - 结果按修改时间排序（最新的在前）
        - 同时显示文件大小

    使用示例:
        files = list_files("src", "*.py")
        files = list_files(".", "**/*.md")
    """
    try:
        # 解析目录路径
        if not os.path.isabs(directory):
            project_dir = get_project_dir()
            directory = os.path.join(project_dir, directory)

        # 安全检查
        abs_dir = os.path.abspath(directory)
        project_dir = os.path.abspath(get_project_dir())
        if not abs_dir.startswith(project_dir):
            return f"错误: 路径 '{directory}' 超出项目目录范围"

        # 检查目录是否存在
        if not os.path.exists(abs_dir):
            return f"错误: 目录 '{directory}' 不存在"

        if not os.path.isdir(abs_dir):
            return f"错误: '{directory}' 不是目录"

        # 使用 glob 匹配文件
        glob_pattern = os.path.join(abs_dir, pattern)
        matches = glob_module.glob(glob_pattern, recursive=True)

        if not matches:
            return f"在 '{directory}' 中未找到匹配 '{pattern}' 的文件"

        # 收集文件信息并排序
        file_infos = []
        for match in matches:
            try:
                stat = os.stat(match)
                rel_path = os.path.relpath(match, abs_dir)
                is_dir = os.path.isdir(match)
                size = stat.st_size if not is_dir else 0
                file_infos.append((rel_path, is_dir, size, stat.st_mtime))
            except OSError:
                continue

        # 按修改时间排序（最新的在前）
        file_infos.sort(key=lambda x: x[3], reverse=True)

        # 格式化输出
        lines = [f"目录 '{directory}' 中的文件 (模式: {pattern}):\n"]
        for rel_path, is_dir, size, _ in file_infos:
            type_marker = "[DIR] " if is_dir else "      "
            if not is_dir:
                size_str = f"({size} bytes)"
            else:
                size_str = ""
            lines.append(f"  {type_marker}{rel_path} {size_str}")

        return "\n".join(lines)

    except PermissionError:
        return f"错误: 没有权限访问目录 '{directory}'"
    except Exception as e:
        return f"列出文件时发生错误: {str(e)}"


@tool
def create_directory(directory_path: str) -> str:
    """
    创建目录

    参数:
        directory_path: 要创建的目录路径

    返回:
        str: 操作结果信息

    说明:
        - 会递归创建所有父目录
        - 如果目录已存在，不会报错

    使用示例:
        result = create_directory("src/utils/helpers")
    """
    try:
        # 解析路径
        if not os.path.isabs(directory_path):
            project_dir = get_project_dir()
            directory_path = os.path.join(project_dir, directory_path)

        # 安全检查
        abs_path = os.path.abspath(directory_path)
        project_dir = os.path.abspath(get_project_dir())
        if not abs_path.startswith(project_dir):
            return f"错误: 路径 '{directory_path}' 超出项目目录范围"

        # 创建目录
        os.makedirs(abs_path, exist_ok=True)

        return f"成功: 目录 '{directory_path}' 已创建"

    except PermissionError:
        return f"错误: 没有权限创建目录 '{directory_path}'"
    except Exception as e:
        return f"创建目录时发生错误: {str(e)}"


@tool
def delete_file(file_path: str) -> str:
    """
    删除文件

    参数:
        file_path: 要删除的文件路径

    返回:
        str: 操作结果信息

    说明:
        - 只能删除文件，不能删除目录
        - 删除操作不可逆，请谨慎使用

    使用示例:
        result = delete_file("temp.txt")
    """
    try:
        # 解析路径
        if not os.path.isabs(file_path):
            project_dir = get_project_dir()
            file_path = os.path.join(project_dir, file_path)

        # 安全检查
        abs_path = os.path.abspath(file_path)
        project_dir = os.path.abspath(get_project_dir())
        if not abs_path.startswith(project_dir):
            return f"错误: 路径 '{file_path}' 超出项目目录范围"

        # 检查文件是否存在
        if not os.path.exists(abs_path):
            return f"错误: 文件 '{file_path}' 不存在"

        # 检查是否是文件
        if os.path.isdir(abs_path):
            return f"错误: '{file_path}' 是目录，请使用删除目录功能"

        # 删除文件
        os.remove(abs_path)

        return f"成功: 文件 '{file_path}' 已删除"

    except PermissionError:
        return f"错误: 没有权限删除文件 '{file_path}'"
    except Exception as e:
        return f"删除文件时发生错误: {str(e)}"


# ============================================
# 代码搜索工具
# ============================================

@tool
def search_code(query: str, directory: str = ".", file_pattern: str = "*") -> str:
    """
    在代码中搜索内容

    参数:
        query: 要搜索的文本或正则表达式
        directory: 搜索的起始目录，默认为当前目录
        file_pattern: 文件过滤模式，默认为 "*" 搜索所有文件

    返回:
        str: 搜索结果，包含匹配的文件、行号和内容

    说明:
        - 支持基本的文本搜索
        - 递归搜索所有子目录
        - 结果限制为前 50 个匹配

    使用示例:
        results = search_code("def hello", "src", "*.py")
    """
    try:
        # 解析目录路径
        if not os.path.isabs(directory):
            project_dir = get_project_dir()
            directory = os.path.join(project_dir, directory)

        # 安全检查
        abs_dir = os.path.abspath(directory)
        project_dir = os.path.abspath(get_project_dir())
        if not abs_dir.startswith(project_dir):
            return f"错误: 路径 '{directory}' 超出项目目录范围"

        # 检查目录是否存在
        if not os.path.exists(abs_dir):
            return f"错误: 目录 '{directory}' 不存在"

        # 收集匹配的文件
        matches = []
        glob_pattern = os.path.join(abs_dir, "**", file_pattern)

        for file_path in glob_module.glob(glob_pattern, recursive=True):
            if not os.path.isfile(file_path):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

                rel_path = os.path.relpath(file_path, abs_dir)

                for line_num, line in enumerate(lines, 1):
                    if query in line:
                        matches.append((rel_path, line_num, line.rstrip()))
                        if len(matches) >= 50:
                            break

                if len(matches) >= 50:
                    break

            except Exception:
                continue

        if not matches:
            return f"未找到匹配 '{query}' 的内容"

        # 格式化输出
        result_lines = [f"搜索结果 (查询: '{query}'):\n"]
        for rel_path, line_num, line in matches:
            result_lines.append(f"  {rel_path}:{line_num}: {line}")

        if len(matches) >= 50:
            result_lines.append(f"\n  ... 结果已截断，显示前 50 个匹配")

        return "\n".join(result_lines)

    except Exception as e:
        return f"搜索时发生错误: {str(e)}"


# ============================================
# Bash 命令执行工具
# ============================================

def _is_compound_shell_command(command: str) -> bool:
    """
    判断命令是否为复合 Shell 命令。

    参数:
        command: 原始命令字符串

    返回:
        bool: 如果包含控制符（如 &&、||、;、|）则返回 True
    """
    return bool(re.search(r'&&|\|\||;|\|', command))


def _classify_tool_result(result_text: str) -> Tuple[bool, str]:
    """
    根据工具返回文本判断执行状态

    参数:
        result_text: 工具返回的文本

    返回:
        Tuple[bool, str]: (是否成功, 状态码字符串)
    """
    text = str(result_text or "")
    if "命令被拒绝" in text:
        return False, "blocked"
    if text.startswith("错误") or "发生错误" in text:
        return False, "error"
    return True, "done"


def _wrap_tool_invoke(tool_obj: Any) -> Any:
    """
    为 LangChain 工具对象包装 invoke 日志

    参数:
        tool_obj: 由 @tool 生成的工具对象

    返回:
        Any: 包装后的工具对象
    """
    cache_key = f"{getattr(tool_obj, 'name', 'unknown')}::{id(tool_obj)}"
    cached_tool = _WRAPPED_TOOL_CACHE.get(cache_key)
    if cached_tool is not None:
        return cached_tool

    original_func = getattr(tool_obj, "func", None)
    if original_func is None:
        return tool_obj

    def logged_func(*args, **kwargs):
        """
        包装后的工具调用方法

        参数:
            *args: 位置参数
            **kwargs: 关键字参数

        返回:
            Any: 原始工具调用结果
        """
        start_time = time.time()
        if kwargs:
            input_preview = str(kwargs)
        else:
            input_preview = str(args)
        emit_event(
            event_type="tool_use",
            component="tool",
            name=tool_obj.name,
            payload={"tool_name": tool_obj.name, "input_preview": input_preview},
            ok=True,
            phase="run",
        )

        try:
            result = original_func(*args, **kwargs)
        except Exception as exc:
            duration = round(time.time() - start_time, 3)
            emit_event(
                event_type="tool_result",
                component="tool",
                name=tool_obj.name,
                payload={
                    "status": "error",
                    "returncode": 1,
                    "duration_sec": duration,
                    "stderr_preview": str(exc),
                },
                ok=False,
                phase="run",
            )
            raise

        duration = round(time.time() - start_time, 3)
        success, status = _classify_tool_result(str(result))
        emit_event(
            event_type="tool_result",
            component="tool",
            name=tool_obj.name,
            payload={
                "status": status,
                "returncode": 0 if success else 1,
                "duration_sec": duration,
                "stdout_preview": str(result),
            },
            ok=success,
            phase="run",
        )
        return result

    logged_tool = StructuredTool.from_function(
        func=logged_func,
        name=tool_obj.name,
        description=tool_obj.description,
        return_direct=tool_obj.return_direct,
        args_schema=getattr(tool_obj, "args_schema", None),
        infer_schema=False,
        response_format=getattr(tool_obj, "response_format", "content"),
    )
    _WRAPPED_TOOL_CACHE[cache_key] = logged_tool
    return logged_tool


def _get_wrapped_tools(tool_list: List[Any]) -> List[Any]:
    """
    为工具列表批量挂载事件日志包装器

    参数:
        tool_list: 原始工具列表

    返回:
        List[Any]: 包装后的工具列表
    """
    return [_wrap_tool_invoke(tool_obj) for tool_obj in tool_list]


# 工具包装缓存
_WRAPPED_TOOL_CACHE: Dict[str, Any] = {}


@tool
def run_bash(command: str, timeout: int = 60) -> str:
    """
    在沙箱中执行 Bash 命令

    参数:
        command: 要执行的 Bash 命令
        timeout: 命令超时时间（秒），默认 60 秒

    返回:
        str: 命令执行结果（标准输出 + 标准错误）

    说明:
        - 命令在安全沙箱中执行
        - 自动进行安全检查（黑名单、路径限制等）
        - 危险命令会被拒绝执行
        - 超时的命令会被终止

    使用示例:
        result = run_bash("npm install")
        result = run_bash("python test.py", timeout=120)
    """
    try:
        # 安全验证（支持复合命令逐段校验）
        validator = get_validator()
        check_result = validator.validate_with_compound_handling(command)
        if not check_result.allowed:
            return f"命令被拒绝: {check_result.reason}"

        # 获取工作目录
        work_dir = get_project_dir()

        # 执行命令（默认使用 shell=False，避免直接注入风险）
        if _is_compound_shell_command(command):
            # 复合命令在通过验证后，交由 bash -lc 解释执行
            exec_args = ["bash", "-lc", command]
            execution_mode = "复合命令模式"
        else:
            # 单命令模式通过 shlex 安全拆分参数
            exec_args = shlex.split(command)
            execution_mode = "单命令模式"

        if not exec_args:
            return "错误: 命令为空，无法执行"

        result = subprocess.run(
            exec_args,
            shell=False,
            capture_output=True,
            text=True,
            cwd=work_dir,
            timeout=timeout or Config.COMMAND_TIMEOUT
        )

        # 组合输出
        output_parts = []

        if result.stdout:
            output_parts.append(f"标准输出:\n{result.stdout}")

        if result.stderr:
            output_parts.append(f"标准错误:\n{result.stderr}")

        # 添加返回码信息
        output_parts.append(f"执行模式: {execution_mode}")
        output_parts.append(f"返回码: {result.returncode}")

        return "\n\n".join(output_parts)

    except subprocess.TimeoutExpired:
        return f"错误: 命令执行超时（{timeout}秒）"
    except PermissionError:
        return f"错误: 没有权限执行该命令"
    except Exception as e:
        return f"执行命令时发生错误: {str(e)}"


# ============================================
# 工具注册函数
# ============================================

def get_all_tools() -> List:
    """
    获取所有可用工具的列表

    返回:
        List: 包含所有工具函数的列表

    说明:
        返回的列表可以直接传递给 LangChain Agent。
        包括：read_file, write_file, edit_file, list_files,
             create_directory, delete_file, search_code, run_bash
    """
    return _get_wrapped_tools([
        read_file,
        write_file,
        edit_file,
        list_files,
        create_directory,
        delete_file,
        search_code,
        run_bash,
    ])


def get_file_tools() -> List:
    """
    获取文件操作相关的工具

    返回:
        List: 文件操作工具列表

    说明:
        只返回文件操作相关的工具，
        不包括命令执行工具。
    """
    return _get_wrapped_tools([
        read_file,
        write_file,
        edit_file,
        list_files,
        create_directory,
        delete_file,
    ])


def get_safe_tools() -> List:
    """
    获取安全的工具集合（不包括 run_bash）

    返回:
        List: 安全的工具列表

    说明:
        返回不包括 Bash 命令执行的工具，
        适用于需要更高安全性的场景。
    """
    return _get_wrapped_tools([
        read_file,
        write_file,
        edit_file,
        list_files,
        create_directory,
        delete_file,
        search_code,
    ])


# ============================================
# 工具描述（供 Agent 参考）
# ============================================

TOOLS_DESCRIPTION = """
可用工具说明
============

1. read_file(file_path) - 读取文件内容
   用途：查看现有代码或配置文件

2. write_file(file_path, content) - 创建或覆盖文件
   用途：创建新文件或完全重写现有文件

3. edit_file(file_path, old_string, new_string) - 编辑文件
   用途：精确修改文件中的特定内容

4. list_files(directory, pattern) - 列出目录内容
   用途：了解项目结构，查找特定文件

5. create_directory(directory_path) - 创建目录
   用途：组织项目结构

6. delete_file(file_path) - 删除文件
   用途：清理不需要的文件

7. search_code(query, directory, file_pattern) - 搜索代码
   用途：在代码库中查找特定内容

8. run_bash(command, timeout) - 执行 Bash 命令
   用途：运行测试、安装依赖、执行脚本等
"""
