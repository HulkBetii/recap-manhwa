from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from workflow import EventBus, WorkflowManager, WorkflowState, WorkflowTask
from worker_protocol import FileCancellationToken, WorkerStatusRepository
from security_utils import RedactingTextStream, redact_sensitive_text


def load_task(input_path: Path) -> WorkflowTask:
    value = json.loads(input_path.read_text(encoding="utf-8"))
    return WorkflowTask(
        comic_title=value.get("comic_title", "Unknown Comic"),
        comic_url=value.get("comic_url", ""),
        from_episode=int(value.get("from_episode", 1)),
        to_episode=int(value.get("to_episode", 1)),
        payload=value,
        id=value["id"],
    )


async def run_worker(job_dir: Path) -> int:
    task = load_task(job_dir / "input.json")
    repository = WorkerStatusRepository(job_dir / "status.json")
    manager = WorkflowManager(repository, EventBus(), max_workers=0, run_in_subprocess=False)
    manager.cancel_tokens[task.id] = FileCancellationToken(job_dir / "cancel.flag")
    repository.save(task)
    await manager._execute_workflow(task)
    return 0 if task.status == WorkflowState.SUCCESS else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", type=Path, required=True)
    args = parser.parse_args()
    job_dir = args.job_dir.resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    os.environ["RECAP_WORKER_PROCESS"] = "1"
    os.environ["RECAP_TASK_DB"] = str(job_dir / "worker_app_state.json")
    with (job_dir / "worker.log").open("a", encoding="utf-8") as log:
        safe_log = RedactingTextStream(log)
        with redirect_stdout(safe_log), redirect_stderr(safe_log):
            try:
                return asyncio.run(run_worker(job_dir))
            except Exception as exc:
                print(f"Worker fatal error: {redact_sensitive_text(str(exc))}", flush=True)
                return 3


if __name__ == "__main__":
    sys.exit(main())
