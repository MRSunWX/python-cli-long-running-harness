# -*- coding: utf-8 -*-
"""
进度管理模块 (progress.py)
=========================

本模块负责管理项目的进度信息，包括：
- 读取和写入 progress.md 进度文件
- 解析和更新 feature_list.json 功能列表
- 生成进度报告
- 统计完成度

进度管理是 Agent 增量开发的核心，确保跨会话保持进度。

使用示例:
    from agent.progress import ProgressManager

    manager = ProgressManager("./my_project")
    manager.initialize("My Project", "创建一个 Flask 应用")
    features = manager.get_pending_features()
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict


# ============================================
# 数据类定义
# ============================================

@dataclass
class Feature:
    """
    功能项数据类

    表示 feature_list.json 中的一个功能项。

    属性:
        id: 功能唯一标识符（如 "feat-001"）
        name: 功能名称
        description: 功能详细描述
        acceptance_criteria: 验收标准列表（用于自验证）
        test_command: 测试命令（用于验证功能）
        verify_commands: 验收命令列表（支持多个命令按顺序执行）
        priority: 优先级（high/medium/low）
        status: 状态（pending/in_progress/completed/blocked）
        dependencies: 依赖的其他功能 ID 列表
        created_at: 创建时间
        updated_at: 更新时间
        notes: 备注信息
    """
    id: str
    name: str
    description: str = ""
    acceptance_criteria: List[str] = None  # 验收标准
    test_command: str = ""  # 测试命令
    verify_commands: List[str] = None  # 验收命令列表
    priority: str = "medium"
    status: str = "pending"
    dependencies: List[str] = None
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""

    def __post_init__(self):
        """
        初始化后处理

        设置默认时间戳和空列表。
        """
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.updated_at:
            self.updated_at = self.created_at
        if self.dependencies is None:
            self.dependencies = []
        if self.acceptance_criteria is None:
            self.acceptance_criteria = []
        if self.verify_commands is None:
            self.verify_commands = []
        # 兼容旧字段：如果未提供 verify_commands，但有 test_command，则自动补齐
        if not self.verify_commands and self.test_command:
            self.verify_commands = [self.test_command]

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式

        返回:
            Dict[str, Any]: 功能项的字典表示

        说明:
            用于 JSON 序列化。
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Feature":
        """
        从字典创建 Feature 实例

        参数:
            data: 包含功能信息的字典

        返回:
            Feature: 新创建的 Feature 实例
        """
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            acceptance_criteria=data.get("acceptance_criteria", []),
            test_command=data.get("test_command", ""),
            verify_commands=data.get("verify_commands", []),
            priority=data.get("priority", "medium"),
            status=data.get("status", "pending"),
            dependencies=data.get("dependencies", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            notes=data.get("notes", "")
        )


@dataclass
class FeatureList:
    """
    功能列表数据类

    表示完整的 feature_list.json 文件结构。

    属性:
        project_name: 项目名称
        tech_stack: 技术栈描述
        init_command: 启动命令（如 ./init.sh）
        created_at: 创建时间
        updated_at: 更新时间
        features: 功能项列表
    """
    project_name: str
    tech_stack: str = ""  # 技术栈
    init_command: str = "./init.sh"  # 启动命令
    created_at: str = ""
    updated_at: str = ""
    features: List[Feature] = None

    def __post_init__(self):
        """
        初始化后处理
        """
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.updated_at:
            self.updated_at = self.created_at
        if self.features is None:
            self.features = []

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式

        返回:
            Dict[str, Any]: 功能列表的字典表示
        """
        return {
            "project_name": self.project_name,
            "tech_stack": self.tech_stack,
            "init_command": self.init_command,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "features": [f.to_dict() for f in self.features]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FeatureList":
        """
        从字典创建 FeatureList 实例

        参数:
            data: 包含功能列表信息的字典

        返回:
            FeatureList: 新创建的 FeatureList 实例
        """
        features = [
            Feature.from_dict(f) for f in data.get("features", [])
        ]
        return cls(
            project_name=data.get("project_name", ""),
            tech_stack=data.get("tech_stack", ""),
            init_command=data.get("init_command", "./init.sh"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            features=features
        )


# ============================================
# 进度管理器类
# ============================================

class ProgressManager:
    """
    进度管理器类

    负责管理项目的进度信息，包括读写进度文件和功能列表。

    主要功能:
    - 初始化项目进度文件
    - 读取/写入 progress.md
    - 读取/写入 feature_list.json
    - 更新功能状态
    - 生成进度报告

    使用示例:
        manager = ProgressManager("./my_project")

        # 初始化新项目
        manager.initialize("My App", "创建一个 Flask 应用")

        # 添加功能
        manager.add_feature("feat-001", "用户登录", "实现用户登录功能")

        # 更新状态
        manager.update_feature_status("feat-001", "completed")

        # 获取进度报告
        report = manager.get_progress_report()
    """

    # 文件名常量
    PROGRESS_FILE = "progress.md"
    FEATURE_LIST_FILE = "feature_list.json"

    def __init__(self, project_dir: str):
        """
        初始化进度管理器

        参数:
            project_dir: 项目目录路径

        说明:
            项目目录是进度文件的存储位置。
        """
        self.project_dir = os.path.abspath(project_dir)
        self._feature_list: Optional[FeatureList] = None

    @property
    def progress_file_path(self) -> str:
        """
        获取进度文件路径

        返回:
            str: progress.md 的完整路径
        """
        return os.path.join(self.project_dir, self.PROGRESS_FILE)

    @property
    def feature_list_path(self) -> str:
        """
        获取功能列表文件路径

        返回:
            str: feature_list.json 的完整路径
        """
        return os.path.join(self.project_dir, self.FEATURE_LIST_FILE)

    def initialize(self, project_name: str, description: str = "") -> bool:
        """
        初始化项目进度文件

        参数:
            project_name: 项目名称
            description: 项目描述（可选）

        返回:
            bool: 初始化是否成功

        说明:
            创建 progress.md 和 feature_list.json 文件。
            如果目录不存在会自动创建。
        """
        try:
            # 确保目录存在
            os.makedirs(self.project_dir, exist_ok=True)

            # 创建 feature_list.json
            self._feature_list = FeatureList(project_name=project_name)
            self._save_feature_list()

            # 创建 progress.md
            progress_content = self._generate_initial_progress(
                project_name, description
            )
            self._save_progress(progress_content)

            return True

        except Exception as e:
            print(f"初始化失败: {str(e)}")
            return False

    def _generate_initial_progress(
        self,
        project_name: str,
        description: str
    ) -> str:
        """
        生成初始进度文件内容

        参数:
            project_name: 项目名称
            description: 项目描述

        返回:
            str: 进度文件内容
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""# 项目进度

## 项目信息

- **名称**: {project_name}
- **描述**: {description}
- **开始时间**: {now}
- **当前阶段**: 初始化

## 已完成

- [x] 项目初始化
- [x] 创建项目结构

## 进行中

（无）

## 待开始

（等待添加功能）

## 问题记录

（无）

## 更新日志

### {now}
- 项目初始化完成
"""

    def _save_progress(self, content: str) -> bool:
        """
        保存进度文件

        参数:
            content: 要保存的内容

        返回:
            bool: 是否成功
        """
        try:
            with open(self.progress_file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"保存进度文件失败: {str(e)}")
            return False

    def _save_feature_list(self) -> bool:
        """
        保存功能列表文件

        返回:
            bool: 是否成功
        """
        try:
            if self._feature_list is None:
                return False

            self._feature_list.updated_at = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            with open(self.feature_list_path, 'w', encoding='utf-8') as f:
                json.dump(
                    self._feature_list.to_dict(),
                    f,
                    ensure_ascii=False,
                    indent=2
                )
            return True

        except Exception as e:
            print(f"保存功能列表失败: {str(e)}")
            return False

    def load_feature_list(self, force_reload: bool = False) -> Optional[FeatureList]:
        """
        加载功能列表

        参数:
            force_reload: 是否强制从文件重新加载（忽略缓存）

        返回:
            Optional[FeatureList]: 功能列表对象，失败返回 None

        说明:
            从 feature_list.json 文件加载功能列表。
            结果会缓存以避免重复读取。
            如果 Agent 通过工具修改了文件，需要设置 force_reload=True。
        """
        if self._feature_list is not None and not force_reload:
            return self._feature_list

        try:
            if not os.path.exists(self.feature_list_path):
                return None

            with open(self.feature_list_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self._feature_list = FeatureList.from_dict(data)
            return self._feature_list

        except Exception as e:
            print(f"加载功能列表失败: {str(e)}")
            return None

    def load_progress(self) -> Optional[str]:
        """
        加载进度文件内容

        返回:
            Optional[str]: 进度文件内容，失败返回 None
        """
        try:
            if not os.path.exists(self.progress_file_path):
                return None

            with open(self.progress_file_path, 'r', encoding='utf-8') as f:
                return f.read()

        except Exception as e:
            print(f"加载进度文件失败: {str(e)}")
            return None

    def add_feature(
        self,
        feature_id: str,
        name: str,
        description: str = "",
        priority: str = "medium",
        dependencies: List[str] = None,
        verify_commands: List[str] = None
    ) -> bool:
        """
        添加新功能

        参数:
            feature_id: 功能 ID（如 "feat-001"）
            name: 功能名称
            description: 功能描述
            priority: 优先级（high/medium/low）
            dependencies: 依赖的其他功能 ID 列表
            verify_commands: 验收命令列表（可选）

        返回:
            bool: 是否成功添加

        说明:
            向功能列表添加新功能项。
        """
        try:
            feature_list = self.load_feature_list()
            if feature_list is None:
                return False

            # 检查 ID 是否已存在
            if any(f.id == feature_id for f in feature_list.features):
                print(f"功能 ID '{feature_id}' 已存在")
                return False

            # 创建新功能
            new_feature = Feature(
                id=feature_id,
                name=name,
                description=description,
                priority=priority,
                dependencies=dependencies or [],
                verify_commands=verify_commands or []
            )

            feature_list.features.append(new_feature)
            self._save_feature_list()

            return True

        except Exception as e:
            print(f"添加功能失败: {str(e)}")
            return False

    def update_feature_status(
        self,
        feature_id: str,
        status: str,
        notes: str = ""
    ) -> bool:
        """
        更新功能状态

        参数:
            feature_id: 功能 ID
            status: 新状态（pending/in_progress/completed/blocked）
            notes: 备注信息（可选）

        返回:
            bool: 是否成功更新
        """
        try:
            feature_list = self.load_feature_list()
            if feature_list is None:
                return False

            # 查找并更新功能
            for feature in feature_list.features:
                if feature.id == feature_id:
                    feature.status = status
                    feature.updated_at = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    if notes:
                        feature.notes = notes
                    break
            else:
                print(f"未找到功能 ID '{feature_id}'")
                return False

            self._save_feature_list()
            return True

        except Exception as e:
            print(f"更新功能状态失败: {str(e)}")
            return False

    def clear_cache(self) -> None:
        """
        清除功能列表缓存

        说明:
            当 Agent 通过工具直接修改了 feature_list.json 文件后，
            应调用此方法清除缓存，以确保后续读取最新数据。
        """
        self._feature_list = None

    def get_feature(self, feature_id: str) -> Optional[Feature]:
        """
        获取指定功能

        参数:
            feature_id: 功能 ID

        返回:
            Optional[Feature]: 功能对象，未找到返回 None
        """
        feature_list = self.load_feature_list()
        if feature_list is None:
            return None

        for feature in feature_list.features:
            if feature.id == feature_id:
                return feature

        return None

    def get_pending_features(self) -> List[Feature]:
        """
        获取所有待完成的功能

        返回:
            List[Feature]: 待完成功能列表

        说明:
            返回状态为 pending 或 in_progress 的功能，
            按优先级排序（high > medium > low）。
        """
        feature_list = self.load_feature_list()
        if feature_list is None:
            return []

        pending = [
            f for f in feature_list.features
            if f.status in ("pending", "in_progress")
        ]

        # 优先级排序
        priority_order = {"high": 0, "medium": 1, "low": 2}
        pending.sort(key=lambda f: priority_order.get(f.priority, 1))

        return pending

    def get_next_feature(self) -> Optional[Feature]:
        """
        获取下一个要处理的功能

        返回:
            Optional[Feature]: 下一个功能，没有返回 None

        说明:
            优先返回 in_progress 状态的功能，
            然后是 pending 状态的高优先级功能。
        """
        pending = self.get_pending_features()

        # 优先处理进行中的任务
        for feature in pending:
            if feature.status == "in_progress":
                return feature

        # 然后处理待开始的
        for feature in pending:
            if feature.status == "pending":
                # 检查依赖是否都已完成
                if self._check_dependencies(feature):
                    return feature

        return None

    def _check_dependencies(self, feature: Feature) -> bool:
        """
        检查功能的依赖是否都已完成

        参数:
            feature: 要检查的功能

        返回:
            bool: 依赖是否都已完成
        """
        if not feature.dependencies:
            return True

        feature_list = self.load_feature_list()
        if feature_list is None:
            return False

        for dep_id in feature.dependencies:
            dep_feature = self.get_feature(dep_id)
            if dep_feature is None or dep_feature.status != "completed":
                return False

        return True

    def get_progress_stats(self) -> Dict[str, Any]:
        """
        获取进度统计信息

        返回:
            Dict[str, Any]: 统计信息字典

        说明:
            返回包含总数、完成数、进行中数等待的统计信息。
        """
        feature_list = self.load_feature_list()
        if feature_list is None:
            return {
                "total": 0,
                "completed": 0,
                "in_progress": 0,
                "pending": 0,
                "blocked": 0,
                "completion_rate": 0.0
            }

        total = len(feature_list.features)
        completed = sum(1 for f in feature_list.features if f.status == "completed")
        in_progress = sum(1 for f in feature_list.features if f.status == "in_progress")
        pending = sum(1 for f in feature_list.features if f.status == "pending")
        blocked = sum(1 for f in feature_list.features if f.status == "blocked")

        completion_rate = (completed / total * 100) if total > 0 else 0.0

        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "pending": pending,
            "blocked": blocked,
            "completion_rate": round(completion_rate, 1)
        }

    def get_progress_report(self) -> str:
        """
        生成进度报告

        返回:
            str: 格式化的进度报告
        """
        feature_list = self.load_feature_list()
        stats = self.get_progress_stats()

        report_lines = [
            "# 项目进度报告",
            "",
            f"**项目名称**: {feature_list.project_name if feature_list else '未知'}",
            f"**更新时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 统计信息",
            "",
            f"- 总功能数: {stats['total']}",
            f"- 已完成: {stats['completed']}",
            f"- 进行中: {stats['in_progress']}",
            f"- 待开始: {stats['pending']}",
            f"- 已阻塞: {stats['blocked']}",
            f"- 完成率: {stats['completion_rate']}%",
            "",
            "## 功能状态",
            ""
        ]

        if feature_list and feature_list.features:
            for feature in feature_list.features:
                status_emoji = {
                    "completed": "✅",
                    "in_progress": "🔄",
                    "pending": "⏳",
                    "blocked": "❌"
                }.get(feature.status, "❓")

                report_lines.append(
                    f"- {status_emoji} **{feature.id}**: {feature.name} "
                    f"[{feature.status}]"
                )

        return "\n".join(report_lines)

    def append_to_progress(self, content: str) -> bool:
        """
        追加内容到进度文件

        参数:
            content: 要追加的内容

        返回:
            bool: 是否成功
        """
        try:
            with open(self.progress_file_path, 'a', encoding='utf-8') as f:
                f.write("\n\n" + content)
            return True
        except Exception as e:
            print(f"追加进度失败: {str(e)}")
            return False

    def update_progress_section(
        self,
        section_name: str,
        new_content: str
    ) -> bool:
        """
        更新进度文件的特定章节

        参数:
            section_name: 章节名称（如 "## 已完成"）
            new_content: 新的章节内容

        返回:
            bool: 是否成功
        """
        try:
            current_content = self.load_progress()
            if current_content is None:
                return False

            lines = current_content.split('\n')
            new_lines = []
            in_section = False
            section_found = False

            for line in lines:
                # 检测章节开始
                if line.strip().startswith('## '):
                    if in_section:
                        in_section = False
                    if line.strip() == section_name:
                        in_section = True
                        section_found = True
                        new_lines.append(line)
                        new_lines.append(new_content)
                        continue

                if not in_section:
                    new_lines.append(line)

            # 如果章节不存在，添加到末尾
            if not section_found:
                new_lines.append("")
                new_lines.append(section_name)
                new_lines.append(new_content)

            self._save_progress('\n'.join(new_lines))
            return True

        except Exception as e:
            print(f"更新进度章节失败: {str(e)}")
            return False


# ============================================
# 便捷函数
# ============================================

def create_progress_manager(project_dir: str) -> ProgressManager:
    """
    创建进度管理器实例

    参数:
        project_dir: 项目目录路径

    返回:
        ProgressManager: 进度管理器实例
    """
    return ProgressManager(project_dir)


def quick_status(project_dir: str) -> str:
    """
    快速获取项目状态报告

    参数:
        project_dir: 项目目录路径

    返回:
        str: 状态报告
    """
    manager = ProgressManager(project_dir)
    return manager.get_progress_report()
