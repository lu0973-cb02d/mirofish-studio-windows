"""
任务状态管理
用于跟踪长时间运行的任务（如图谱构建）
"""

import copy
import json
import logging
import math
import os
import re
import tempfile
import uuid
import threading
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

from ..utils.locale import t


class TaskPersistenceError(RuntimeError):
    """Safe storage error; underlying paths/provider bodies are never exposed."""


_INTERRUPTED_MESSAGE = "本机引擎曾中断，该任务未自动续跑。请查看已保存的结果后重试。"
_REDACTED = "[已隐藏]"
_MAX_TASK_BYTES = 4 * 1024 * 1024
_SENSITIVE_NAMES = {
    "key", "token", "secret", "password", "passwd", "credential", "credentials",
    "authorization", "proxyauthorization", "cookie", "setcookie", "privatekey",
    "accesskey", "accesskeyid", "secretaccesskey", "clientsecret", "sessionid",
}
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[-_ ]?key|authorization|password|secret|access[-_ ]?token|refresh[-_ ]?token)"
    r"\b\s*[:=]\s*)(?:(?:Bearer|Api-Key)\s+)?[\"']?[^\s,;\"'}]+"
)


def _sensitive_name(name):
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return (normalized in _SENSITIVE_NAMES or "apikey" in normalized
            or normalized.endswith(("password", "secret", "token", "privatekey")))


def _safe_payload(payload):
    """Drop credential fields recursively and redact known keys in free text."""
    secrets = set()
    for name in ("LLM_API_KEY", "LLM_BOOST_API_KEY", "ZEP_API_KEY", "OPENAI_API_KEY",
                 "ANTHROPIC_API_KEY", "MIROFISH_ENGINE_TOKEN"):
        value = os.environ.get(name, "")
        if len(value) >= 4:
            secrets.add(value)

    def collect(value, protected=False, depth=0):
        if depth > 32:
            raise ValueError("task nesting limit")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("task field type")
                collect(item, protected or _sensitive_name(key), depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item, protected, depth + 1)
        elif protected and isinstance(value, str) and len(value) >= 4:
            secrets.add(value)

    collect(payload)
    ordered_secrets = sorted(secrets, key=len, reverse=True)

    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if not _sensitive_name(key)}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        if isinstance(value, str):
            for secret in ordered_secrets:
                value = value.replace(secret, _REDACTED)
            return _CREDENTIAL_ASSIGNMENT.sub(lambda match: match.group(1) + _REDACTED, value)
        if value is None or type(value) in (bool, int):
            return value
        if type(value) is float and math.isfinite(value):
            return value
        raise ValueError("task data must be JSON-compatible")

    return clean(payload)


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待中
    PROCESSING = "processing"    # 处理中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败


@dataclass
class Task:
    """任务数据类"""
    task_id: str
    task_type: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    progress: int = 0              # 总进度百分比 0-100
    message: str = ""              # 状态消息
    result: Optional[Dict] = None  # 任务结果
    error: Optional[str] = None    # 错误信息
    metadata: Dict = field(default_factory=dict)  # 额外元数据
    progress_detail: Dict = field(default_factory=dict)  # 详细进度信息
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "progress": self.progress,
            "message": self.message,
            "progress_detail": self.progress_detail,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


class TaskManager:
    """
    任务管理器
    线程安全的任务状态管理
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._tasks: Dict[str, Task] = {}
                    instance._task_lock = threading.Lock()
                    studio_root = os.environ.get("MIROFISH_DATA_ROOT", os.environ.get("MIROFISH_STUDIO_ROOT"))
                    instance._persistence_dir = (
                        Path(studio_root).resolve() / "backend" / "uploads" / "tasks"
                        if studio_root else None
                    )
                    # Publish the singleton only after loading/recovery succeeds.
                    # A disk failure must not leave a half-loaded global instance.
                    if instance._persistence_dir is not None:
                        instance._load_persisted_tasks()
                    cls._instance = instance
        return cls._instance

    @staticmethod
    def _decode_task(data, expected_id):
        if not isinstance(data, dict) or data.get("task_id") != expected_id:
            raise ValueError("invalid task identity")
        if str(uuid.UUID(expected_id)) != expected_id:
            raise ValueError("invalid task identity")
        for name in ("task_type", "created_at", "updated_at", "message"):
            if not isinstance(data.get(name), str):
                raise ValueError("invalid task field")
        if not isinstance(data.get("metadata"), dict) or not isinstance(data.get("progress_detail"), dict):
            raise ValueError("invalid task details")
        if data.get("result") is not None and not isinstance(data["result"], dict):
            raise ValueError("invalid task result")
        if data.get("error") is not None and not isinstance(data["error"], str):
            raise ValueError("invalid task error")
        progress = data.get("progress")
        if type(progress) not in (int, float) or not math.isfinite(progress) or not 0 <= progress <= 100:
            raise ValueError("invalid task progress")

        def date(value):
            parsed = datetime.fromisoformat(value)
            return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed

        return Task(task_id=expected_id, task_type=data["task_type"], status=TaskStatus(data["status"]),
                    created_at=date(data["created_at"]), updated_at=date(data["updated_at"]),
                    progress=progress, message=data["message"], result=data.get("result"),
                    error=data.get("error"), metadata=data["metadata"], progress_detail=data["progress_detail"])

    def _clean_task(self, task):
        try:
            return self._decode_task(_safe_payload(task.to_dict()), task.task_id)
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
            raise TaskPersistenceError("任务状态格式无法安全保存，未更新任务。") from None

    def _write_task(self, task):
        if self._persistence_dir is None:
            return
        temporary = None
        try:
            encoded = json.dumps({"version": 1, **task.to_dict()}, ensure_ascii=False, allow_nan=False) + "\n"
            if len(encoded.encode("utf-8")) > _MAX_TASK_BYTES:
                raise TaskPersistenceError("任务记录过大，未确认本次状态更新。请减少任务结果中的冗余内容。")
            self._persistence_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                             prefix=".task-", suffix=".tmp", delete=False,
                                             dir=self._persistence_dir) as handle:
                temporary = Path(handle.name)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._persistence_dir / (task.task_id + ".json"))
        except (OSError, ValueError, TypeError):
            raise TaskPersistenceError("任务记录保存失败，未确认本次状态更新。请检查本地磁盘空间与目录权限后重试。") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _load_persisted_tasks(self):
        skipped = 0
        try:
            paths = list(self._persistence_dir.glob("*.json"))
        except OSError:
            raise TaskPersistenceError("任务记录目录无法读取，请检查本地目录权限后重试。") from None
        for path in paths:
            try:
                if path.is_symlink() or path.stat().st_size > _MAX_TASK_BYTES:
                    raise ValueError("unsupported task file")
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(raw, dict) or type(raw.get("version")) is not int or raw["version"] != 1:
                    raise ValueError("unsupported task version")
                task = self._decode_task(_safe_payload(raw), path.stem)
            except (OSError, UnicodeError, ValueError, KeyError, TypeError, RecursionError, OverflowError):
                # A single damaged task does not hide other completed records.
                # Keep the original file for manual repair; do not log its body.
                skipped += 1
                continue
            if task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING}:
                task.status = TaskStatus.FAILED
                task.message = task.error = _INTERRUPTED_MESSAGE
                task.updated_at = datetime.now()
            canonical = {"version": 1, **task.to_dict()}
            if canonical != raw:
                # Also remove any sensitive fields from otherwise valid old data.
                # A failed write propagates instead of claiming recovery succeeded.
                self._write_task(task)
            self._tasks[task.task_id] = task
        if skipped:
            logging.getLogger(__name__).warning("已跳过 %s 个无法读取的任务记录，原文件已保留。", skipped)
    
    def create_task(self, task_type: str, metadata: Optional[Dict] = None) -> str:
        """
        创建新任务
        
        Args:
            task_type: 任务类型
            metadata: 额外元数据
            
        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())
        now = datetime.now()
        
        task = Task(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=metadata or {}
        )
        
        with self._task_lock:
            if self._persistence_dir is not None:
                task = self._clean_task(task)
                self._write_task(task)
            self._tasks[task_id] = task
        
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        with self._task_lock:
            task = self._tasks.get(task_id)
            return copy.deepcopy(task) if self._persistence_dir is not None else task
    
    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        progress_detail: Optional[Dict] = None
    ):
        """
        更新任务状态
        
        Args:
            task_id: 任务ID
            status: 新状态
            progress: 进度
            message: 消息
            result: 结果
            error: 错误信息
            progress_detail: 详细进度信息
        """
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task:
                if self._persistence_dir is not None:
                    task = copy.deepcopy(task)
                task.updated_at = datetime.now()
                if status is not None:
                    task.status = status
                if progress is not None:
                    task.progress = progress
                if message is not None:
                    task.message = message
                if result is not None:
                    task.result = result
                if error is not None:
                    task.error = error
                if progress_detail is not None:
                    task.progress_detail = progress_detail
                if self._persistence_dir is not None:
                    task = self._clean_task(task)
                    self._write_task(task)
                    self._tasks[task_id] = task
    
    def complete_task(self, task_id: str, result: Dict):
        """标记任务完成"""
        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message=t('progress.taskComplete'),
            result=result
        )
    
    def fail_task(self, task_id: str, error: str):
        """标记任务失败"""
        self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            message=t('progress.taskFailed'),
            error=error
        )
    
    def list_tasks(self, task_type: Optional[str] = None) -> list:
        """列出任务"""
        with self._task_lock:
            tasks = list(self._tasks.values())
            if task_type:
                tasks = [t for t in tasks if t.task_type == task_type]
            result = [t.to_dict() for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)]
            return copy.deepcopy(result) if self._persistence_dir is not None else result
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        
        with self._task_lock:
            old_ids = [
                tid for tid, task in self._tasks.items()
                if task.created_at < cutoff and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            ]
            for tid in old_ids:
                if self._persistence_dir is not None:
                    try:
                        (self._persistence_dir / (tid + ".json")).unlink(missing_ok=True)
                    except OSError:
                        raise TaskPersistenceError("旧任务记录清理失败，记录已保留，请检查本地目录权限。") from None
                del self._tasks[tid]
