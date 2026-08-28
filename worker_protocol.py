from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import List, Optional

from workflow_base import BaseWorkflowRepository, CancellationToken, WorkflowTask


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        for attempt in range(50):
            try:
                os.replace(temp_path, path)
                return
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(min(0.25, 0.02 * (attempt + 1)))
    finally:
        if temp_path.exists():
            temp_path.unlink()


class FileCancellationToken(CancellationToken):
    def __init__(self, cancel_path: Path):
        super().__init__()
        self.cancel_path = cancel_path

    def is_cancelled(self) -> bool:
        return super().is_cancelled() or self.cancel_path.exists()


class WorkerStatusRepository(BaseWorkflowRepository):
    def __init__(self, status_path: Path):
        self.status_path = status_path
        self._task: WorkflowTask | None = None
        self._revision = 0
        self._lock = threading.Lock()

    def _write(self, task: WorkflowTask) -> None:
        with self._lock:
            self._task = task
            self._revision += 1
            atomic_write_json(self.status_path, {
                "revision": self._revision,
                "task": task.to_storage_dict(),
            })

    def save(self, task: WorkflowTask) -> None:
        self._write(task)

    def load(self, task_id: str) -> Optional[WorkflowTask]:
        if self._task is not None and self._task.id == task_id:
            return self._task
        return None

    def load_all(self) -> List[WorkflowTask]:
        return [self._task] if self._task is not None else []

    def update(self, task: WorkflowTask) -> None:
        self._write(task)

    def delete(self, task_id: str) -> None:
        if self._task is not None and self._task.id == task_id:
            self._task = None
