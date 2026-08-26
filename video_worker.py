from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from urllib.parse import quote

from security_utils import RedactingTextStream, redact_sensitive_text
from worker_protocol import atomic_write_json


def public_final_video_url(comic_folder: str) -> str:
    folder = quote(comic_folder, safe="")
    return f"/downloads/{folder}/output/{folder}.mp4"


async def run(job_dir: Path) -> int:
    payload = json.loads((job_dir / "input.json").read_text(encoding="utf-8"))
    atomic_write_json(job_dir / "status.json", {"status": "running", "message": "Video worker started."})

    from app import run_video_pipeline

    success = await run_video_pipeline(
        payload["comic_folder"],
        int(payload["from_episode"]),
        int(payload["to_episode"]),
        payload.get("voice_id", "ai33pro"),
        payload.get("logo_path"),
        payload.get("overlay_path"),
        bool(payload.get("remove_text", True)),
        float(payload.get("remove_text_conf", 0.3)),
        int(payload.get("remove_text_radius", 3)),
        payload.get("ref_audio_path"),
    )
    if success:
        atomic_write_json(job_dir / "status.json", {
            "status": "success",
            "message": "Video generation completed.",
            "final_video_url": public_final_video_url(payload["comic_folder"]),
        })
        return 0
    atomic_write_json(job_dir / "status.json", {
        "status": "failed",
        "message": "Video generation failed. See the worker log for details.",
    })
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", type=Path, required=True)
    args = parser.parse_args()
    job_dir = args.job_dir.resolve()
    os.environ["RECAP_WORKER_PROCESS"] = "1"
    os.environ["RECAP_TASK_DB"] = str(job_dir / "worker_app_state.json")
    with (job_dir / "worker.log").open("a", encoding="utf-8") as log:
        safe_log = RedactingTextStream(log)
        with redirect_stdout(safe_log), redirect_stderr(safe_log):
            try:
                return asyncio.run(run(job_dir))
            except Exception as exc:
                message = redact_sensitive_text(str(exc)) or "Video worker failed."
                atomic_write_json(job_dir / "status.json", {"status": "failed", "message": message})
                print(f"Video worker fatal error: {message}", flush=True)
                return 3


if __name__ == "__main__":
    sys.exit(main())
