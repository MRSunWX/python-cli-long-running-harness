# -*- coding: utf-8 -*-
"""
事件日志模块 (event_logger.py)
============================

本模块提供统一的事件日志能力，用于：
- 在终端输出中文前缀的详细事件日志
- 将事件以 JSONL 格式写入项目目录
- 在不影响主流程的前提下提升可观测性
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from config import Config


class EventLogger:
    """
    事件日志器。

    该类负责统一处理日志事件的终端输出与文件落盘。
    """

    def __init__(
        self,
        project_dir: Optional[str] = None,
        verbose_events: bool = True,
        persist_file: bool = True,
        phase: str = "general",
        session_id: Optional[str] = None,
    ):
        """初始化事件日志器。"""
        self.project_dir = os.path.abspath(project_dir) if project_dir else None
        self.verbose_events = bool(verbose_events)
        self.persist_file = bool(persist_file)
        self.phase = phase
        self.session_id = session_id or self._generate_session_id(phase)

    @staticmethod
    def _generate_session_id(phase: str) -> str:
        """生成会话唯一标识。"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"{phase}-{timestamp}"

    @property
    def event_file_path(self) -> Optional[str]:
        """获取事件日志文件路径。"""
        if not self.project_dir:
            return None
        return os.path.join(self.project_dir, Config.EVENT_LOG_FILE)

    def update_context(
        self,
        phase: Optional[str] = None,
        session_id: Optional[str] = None,
        project_dir: Optional[str] = None,
    ) -> None:
        """更新日志上下文。"""
        if phase:
            self.phase = phase
        if session_id:
            self.session_id = session_id
        if project_dir:
            self.project_dir = os.path.abspath(project_dir)

    @staticmethod
    def _truncate_text(text: str, limit: Optional[int] = None) -> str:
        """截断过长文本，避免终端刷屏。"""
        max_len = limit if limit is not None else Config.EVENT_PREVIEW_LENGTH
        if len(text) <= max_len:
            return text
        return text[:max_len] + "...(已截断)"

    def _sanitize_payload(self, payload: Any) -> Any:
        """对事件载荷进行基础脱敏与截断。"""
        if payload is None:
            return {}

        if isinstance(payload, dict):
            sanitized: Dict[str, Any] = {}
            for key, value in payload.items():
                key_lower = str(key).lower()
                if any(word in key_lower for word in ["token", "password", "secret", "api_key"]):
                    sanitized[key] = "***"
                else:
                    sanitized[key] = self._sanitize_payload(value)
            return sanitized

        if isinstance(payload, list):
            return [self._sanitize_payload(item) for item in payload]

        if isinstance(payload, str):
            return self._truncate_text(payload)

        return payload

    @staticmethod
    def _get_prefix(event_type: str) -> str:
        """根据事件类型获取中文前缀。"""
        mapping = {
            "assistant_text": "[助手]",
            "tool_use": "[工具调用]",
            "tool_result": "[工具结果]",
            "session_start": "[会话]",
            "session_end": "[会话]",
            "precheck": "[会话]",
            "verification": "[会话]",
            "git_commit": "[会话]",
            "error": "[会话]",
        }
        return mapping.get(event_type, "[会话]")

    @staticmethod
    def _status_cn(status: str) -> str:
        """将英文状态转换为中文状态词。"""
        mapping = {
            "done": "完成",
            "error": "错误",
            "blocked": "拦截",
        }
        return mapping.get(status, status)

    def _format_console_line(
        self,
        event_type: str,
        name: str,
        payload: Dict[str, Any],
        ok: bool,
    ) -> str:
        """格式化终端输出日志行。"""
        prefix = self._get_prefix(event_type)

        if event_type == "assistant_text":
            content = str(payload.get("text_preview", "")).strip()
            return f"{prefix} {content}" if content else f"{prefix} （空回复）"

        if event_type == "tool_use":
            tool_name = payload.get("tool_name", name)
            input_preview = payload.get("input_preview", "")
            return f"{prefix} <{tool_name} - {input_preview}>"

        if event_type == "tool_result":
            status_cn = self._status_cn(str(payload.get("status", "done")))
            returncode = payload.get("returncode", "")
            duration = payload.get("duration_sec", "")
            extra = f" 返回码={returncode}" if returncode != "" else ""
            duration_text = f" 耗时={duration}s" if duration != "" else ""
            return f"{prefix} [{status_cn}] {name}{extra}{duration_text}"

        message = payload.get("message") or payload.get("summary") or name
        if not ok:
            return f"{prefix} [错误] {message}"
        return f"{prefix} {message}"

    def _write_file_event(self, record: Dict[str, Any]) -> None:
        """将事件记录追加写入 JSONL 文件。"""
        if not self.persist_file:
            return

        event_path = self.event_file_path
        if not event_path:
            return

        try:
            os.makedirs(os.path.dirname(event_path), exist_ok=True)
            with open(event_path, "a", encoding="utf-8") as file_obj:
                file_obj.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # 事件日志写入失败不能影响主流程
            return

    def emit(
        self,
        event_type: str,
        component: str,
        name: str,
        payload: Optional[Dict[str, Any]] = None,
        ok: bool = True,
        iteration: int = 0,
        phase: Optional[str] = None,
    ) -> Dict[str, Any]:
        """发送事件日志到终端并落盘。"""
        current_phase = phase or self.phase
        safe_payload = self._sanitize_payload(payload or {})

        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "session_id": self.session_id,
            "iteration": iteration,
            "phase": current_phase,
            "event_type": event_type,
            "component": component,
            "name": name,
            "payload": safe_payload,
            "ok": bool(ok),
        }

        if self.verbose_events:
            try:
                print(self._format_console_line(event_type, name, safe_payload, ok), flush=True)
            except Exception:
                pass

        self._write_file_event(record)
        return record


# 全局事件日志器实例
_global_event_logger: Optional[EventLogger] = None


def set_event_logger(logger: EventLogger) -> EventLogger:
    """设置全局事件日志器。"""
    global _global_event_logger
    _global_event_logger = logger
    return logger


def get_event_logger() -> Optional[EventLogger]:
    """获取全局事件日志器。"""
    return _global_event_logger


def setup_event_logger(
    project_dir: Optional[str],
    verbose_events: bool = True,
    persist_file: bool = True,
    phase: str = "general",
    session_id: Optional[str] = None,
) -> EventLogger:
    """创建并注册全局事件日志器。"""
    logger = EventLogger(
        project_dir=project_dir,
        verbose_events=verbose_events,
        persist_file=persist_file,
        phase=phase,
        session_id=session_id,
    )
    return set_event_logger(logger)


def update_event_context(
    phase: Optional[str] = None,
    session_id: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> Optional[EventLogger]:
    """更新全局事件日志器上下文。"""
    logger = get_event_logger()
    if logger is None:
        return None
    logger.update_context(phase=phase, session_id=session_id, project_dir=project_dir)
    return logger


def emit_event(
    event_type: str,
    component: str,
    name: str,
    payload: Optional[Dict[str, Any]] = None,
    ok: bool = True,
    iteration: int = 0,
    phase: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """使用全局日志器发送事件。"""
    logger = get_event_logger()
    if logger is None:
        return None
    return logger.emit(
        event_type=event_type,
        component=component,
        name=name,
        payload=payload,
        ok=ok,
        iteration=iteration,
        phase=phase,
    )
