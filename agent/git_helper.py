# -*- coding: utf-8 -*-
"""
Git 辅助模块 (git_helper.py)
============================

本模块提供 Git 操作的辅助函数，用于：
- 初始化 Git 仓库
- 创建自动提交
- 读取提交历史
- 检查工作区状态
- 代码回滚和变更暂存

这些操作帮助 Agent 实现增量开发，确保进度可追溯。
通过 Git 的版本控制能力，Agent 可以在遇到问题时回滚到工作状态。

使用示例:
    from agent.git_helper import GitHelper

    git = GitHelper("./my_project")
    git.init_repo()
    git.commit("初始化项目")
    logs = git.get_recent_commits(5)

    # 如果需要回滚
    git.revert_last_commit()  # 软回滚，保留变更
    git.revert_to_commit("abc123")  # 回滚到指定提交
"""

import os
import subprocess
from typing import List, Dict, Optional
from datetime import datetime


class GitHelper:
    """
    Git 操作辅助类

    封装了常用的 Git 操作，为 Agent 提供版本控制能力。

    主要功能:
    - 初始化 Git 仓库
    - 创建提交（自动添加变更文件）
    - 读取提交历史
    - 获取工作区状态

    使用示例:
        git = GitHelper("./my_project")

        # 初始化仓库
        if not git.is_repo():
            git.init_repo()

        # 创建提交
        git.commit("实现用户登录功能")

        # 查看历史
        commits = git.get_recent_commits(5)
        for commit in commits:
            print(f"{commit['hash']}: {commit['message']}")
    """

    def __init__(self, project_dir: str):
        """
        初始化 Git 辅助类

        参数:
            project_dir: 项目目录路径
        """
        self.project_dir = os.path.abspath(project_dir)

    def _run_git_command(
        self,
        args: List[str],
        capture_output: bool = True
    ) -> subprocess.CompletedProcess:
        """
        执行 Git 命令

        参数:
            args: Git 命令参数列表
            capture_output: 是否捕获输出

        返回:
            subprocess.CompletedProcess: 命令执行结果
        """
        cmd = ["git"] + args
        return subprocess.run(
            cmd,
            cwd=self.project_dir,
            capture_output=capture_output,
            text=True
        )

    def is_repo(self) -> bool:
        """
        检查是否是 Git 仓库

        返回:
            bool: 是否是 Git 仓库
        """
        result = self._run_git_command(["rev-parse", "--git-dir"])
        return result.returncode == 0

    def init_repo(self) -> bool:
        """
        初始化 Git 仓库

        返回:
            bool: 是否成功

        说明:
            如果已经是 Git 仓库，不会重复初始化。
            会创建 .gitignore 文件（如果不存在）。
        """
        if self.is_repo():
            return True

        result = self._run_git_command(["init"])
        if result.returncode != 0:
            print(f"Git 初始化失败: {result.stderr}")
            return False

        # 创建默认的 .gitignore
        gitignore_path = os.path.join(self.project_dir, ".gitignore")
        if not os.path.exists(gitignore_path):
            default_gitignore = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual Environment
venv/
ENV/
env/
.venv/

# IDE
.idea/
.vscode/
*.swp
*.swo

# Environment variables
.env
.env.local

# Logs
*.log

# OS
.DS_Store
Thumbs.db
"""
            with open(gitignore_path, 'w', encoding='utf-8') as f:
                f.write(default_gitignore)

        return True

    def get_status(self) -> Dict[str, List[str]]:
        """
        获取工作区状态

        返回:
            Dict[str, List[str]]: 包含 staged、modified、untracked 的文件列表

        说明:
            返回格式:
            {
                "staged": ["file1.py", "file2.py"],
                "modified": ["file3.py"],
                "untracked": ["new_file.py"]
            }
        """
        status = {
            "staged": [],
            "modified": [],
            "untracked": []
        }

        result = self._run_git_command(["status", "--porcelain"])
        if result.returncode != 0:
            return status

        for line in result.stdout.strip().split('\n'):
            if not line:
                continue

            status_code = line[:2]
            filepath = line[3:]

            # X Y 文件名
            # X 表示暂存区状态，Y 表示工作区状态
            # M = 修改, A = 新增, D = 删除, ? = 未跟踪
            if status_code[0] in ('M', 'A', 'D', 'R'):
                status["staged"].append(filepath)
            elif status_code[1] == 'M':
                status["modified"].append(filepath)
            elif status_code.strip() == '??':
                status["untracked"].append(filepath)

        return status

    def has_changes(self) -> bool:
        """
        检查是否有未提交的变更

        返回:
            bool: 是否有变更
        """
        status = self.get_status()
        return bool(status["staged"] or status["modified"] or status["untracked"])

    def add_all(self) -> bool:
        """
        添加所有变更到暂存区

        返回:
            bool: 是否成功
        """
        result = self._run_git_command(["add", "-A"])
        return result.returncode == 0

    def commit(
        self,
        message: str,
        auto_add: bool = True
    ) -> bool:
        """
        创建提交

        参数:
            message: 提交信息
            auto_add: 是否自动添加所有变更（默认 True）

        返回:
            bool: 是否成功

        说明:
            如果 auto_add 为 True，会自动执行 git add -A。
            提交信息会自动添加时间戳。
        """
        if not self.is_repo():
            print("不是 Git 仓库")
            return False

        # 自动添加变更
        if auto_add:
            self.add_all()

        # 检查是否有变更
        status = self.get_status()
        if not (status["staged"] or status["modified"] or status["untracked"]):
            print("没有变更需要提交")
            return True

        # 添加未暂存的修改
        if status["modified"] or status["untracked"]:
            self.add_all()

        # 添加时间戳
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"{message}\n\n时间: {timestamp}"

        result = self._run_git_command(["commit", "-m", full_message])
        if result.returncode != 0:
            print(f"提交失败: {result.stderr}")
            return False

        return True

    def get_recent_commits(self, count: int = 10) -> List[Dict[str, str]]:
        """
        获取最近的提交历史

        参数:
            count: 获取的提交数量

        返回:
            List[Dict[str, str]]: 提交列表，每个元素包含 hash、message、date、author

        说明:
            返回格式:
            [
                {
                    "hash": "abc1234",
                    "message": "实现用户登录",
                    "date": "2024-01-01 12:00:00",
                    "author": "Agent"
                },
                ...
            ]
        """
        commits = []

        if not self.is_repo():
            return commits

        # 格式: hash|date|author|message
        format_str = "%h|%ci|%an|%s"
        result = self._run_git_command([
            "log",
            f"-{count}",
            f"--format={format_str}"
        ])

        if result.returncode != 0:
            return commits

        for line in result.stdout.strip().split('\n'):
            if not line:
                continue

            parts = line.split('|', 3)
            if len(parts) >= 4:
                commits.append({
                    "hash": parts[0],
                    "date": parts[1],
                    "author": parts[2],
                    "message": parts[3]
                })

        return commits

    def get_commit_diff(self, commit_hash: str) -> str:
        """
        获取指定提交的变更内容

        参数:
            commit_hash: 提交哈希

        返回:
            str: 变更的 diff 内容
        """
        result = self._run_git_command([
            "show",
            "--stat",
            commit_hash
        ])

        if result.returncode != 0:
            return ""

        return result.stdout

    def get_last_commit_message(self) -> Optional[str]:
        """
        获取最近一次提交的信息

        返回:
            Optional[str]: 提交信息，没有提交则返回 None
        """
        commits = self.get_recent_commits(1)
        if commits:
            return commits[0]["message"]
        return None

    def create_branch(self, branch_name: str) -> bool:
        """
        创建新分支

        参数:
            branch_name: 分支名称

        返回:
            bool: 是否成功
        """
        result = self._run_git_command(["checkout", "-b", branch_name])
        return result.returncode == 0

    def get_current_branch(self) -> str:
        """
        获取当前分支名称

        返回:
            str: 分支名称
        """
        result = self._run_git_command(["branch", "--show-current"])
        if result.returncode == 0:
            return result.stdout.strip()
        return "main"

    def revert_to_commit(self, commit_hash: str, hard: bool = False) -> bool:
        """
        回滚到指定提交

        参数:
            commit_hash: 目标提交哈希
            hard: 是否使用 --hard 模式（会丢失未提交的变更）

        返回:
            bool: 是否成功

        说明:
            默认使用 --soft 模式，保留工作区变更。
            使用 --hard 会完全重置到目标提交，慎用！
        """
        args = ["reset"]
        if hard:
            args.append("--hard")
        else:
            args.append("--soft")
        args.append(commit_hash)

        result = self._run_git_command(args)
        if result.returncode != 0:
            print(f"回滚失败: {result.stderr}")
            return False
        return True

    def revert_last_commit(self, hard: bool = False) -> bool:
        """
        回滚最近一次提交

        参数:
            hard: 是否使用 --hard 模式

        返回:
            bool: 是否成功
        """
        return self.revert_to_commit("HEAD~1", hard=hard)

    def stash_changes(self, message: str = "") -> bool:
        """
        暂存当前变更

        参数:
            message: 暂存说明

        返回:
            bool: 是否成功
        """
        args = ["stash"]
        if message:
            args.extend(["-m", message])
        else:
            args.append("push")

        result = self._run_git_command(args)
        return result.returncode == 0

    def stash_pop(self) -> bool:
        """
        恢复最近暂存的变更

        返回:
            bool: 是否成功
        """
        result = self._run_git_command(["stash", "pop"])
        return result.returncode == 0

    def get_stash_list(self) -> List[Dict[str, str]]:
        """
        获取暂存列表

        返回:
            List[Dict[str, str]]: 暂存列表
        """
        stashes = []
        result = self._run_git_command(["stash", "list"])

        if result.returncode != 0 or not result.stdout.strip():
            return stashes

        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            # 格式: stash@{0}: On branch: message
            parts = line.split(': ', 2)
            if len(parts) >= 2:
                stashes.append({
                    "ref": parts[0],
                    "branch": parts[1].replace("On ", "") if len(parts) > 1 else "",
                    "message": parts[2] if len(parts) > 2 else ""
                })

        return stashes


def format_commits_for_prompt(commits: List[Dict[str, str]]) -> str:
    """
    格式化提交历史用于提示词

    参数:
        commits: 提交列表

    返回:
        str: 格式化的字符串

    说明:
        将提交历史转换为易读的格式，用于 Agent 理解进度。
    """
    if not commits:
        return "（暂无提交历史）"

    lines = ["## 最近的 Git 提交记录\n"]
    for commit in commits:
        lines.append(f"- [{commit['hash']}] {commit['message']}")
        lines.append(f"  时间: {commit['date']}, 作者: {commit['author']}")

    return "\n".join(lines)
