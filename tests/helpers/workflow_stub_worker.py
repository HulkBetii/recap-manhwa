from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def write_status(path: Path, revision: int, task: dict, status: str, progress: float, error: str | None = None) -> None:
    snapshot = dict(task)
    snapshot.update({
        "status": status,
        "overall_progress": progress,
        "error_message": error,
    })
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps({"revision": revision, "task": snapshot}), encoding="utf-8")
    os.replace(temp_path, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", type=Path, required=True)
    args = parser.parse_args()
    job_dir = args.job_dir.resolve()
    task = json.loads((job_dir / "input.json").read_text(encoding="utf-8"))
    mode = task.get("worker_test_mode", "success")
    status_path = job_dir / "status.json"
    write_status(status_path, 1, task, "running", 42.0)

    if mode == "crash":
        return 7
    if mode == "stubborn":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        (job_dir / "child.pid").write_text(str(child.pid), encoding="utf-8")
        time.sleep(60)
        return 9

    deadline = time.monotonic() + (1.2 if mode == "slow_success" else 0.15)
    while time.monotonic() < deadline:
        if (job_dir / "cancel.flag").exists():
            write_status(status_path, 2, task, "cancelled", 42.0)
            return 2
        time.sleep(0.03)

    write_status(status_path, 2, task, "success", 100.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
