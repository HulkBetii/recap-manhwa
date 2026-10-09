"""Re-run Stage 10-12 for Tyrant 1-50 (narration, TTS, subtitles and drafts reused)."""
import asyncio
import json
import os
import sys
import time

PROJECT = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
FOLDER = "the_tyrant_of_the_apocalypse_returns_1_50_en_dda17195"
JOB_INPUT = os.path.join(PROJECT, "runtime", "jobs", "4139d806-5b78-4ba6-b37d-88aa06a7686f", "input.json")

sys.stdout.reconfigure(encoding="utf-8")
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)

from workflow_base import WorkflowTask  # noqa: E402
from workflow_stages_2 import (  # noqa: E402
    Stage10_EpisodeVideoRendering, Stage11_FinalVideoAssembly, Stage12_MetadataReports,
)


class Token:
    def is_cancelled(self):
        return False


class Ctx:
    def __init__(self, task):
        self.task = task
        self.cancel_token = Token()
        self.payload = task.payload
        self.config = {}
        self.manager = None

    async def log(self, message, level="info", *args, **kwargs):
        print(f"[{time.strftime('%H:%M:%S')}] [{level.upper()}] {message}", flush=True)

    async def start_episode(self, ep):
        pass

    async def complete_episode(self, ep):
        pass

    async def fail_episode(self, ep, error):
        print(f"[FAIL] episode {ep}: {error}", flush=True)

    async def update_stage_progress(self, stage_name, progress):
        pass

    async def update_progress(self, progress, stage_name=None, episode=None):
        pass


async def main():
    with open(JOB_INPUT, encoding="utf-8") as f:
        payload = json.load(f)
    payload = {**payload, "crop_speech_bubbles": True, "regenerate_drafts": False}
    task = WorkflowTask(
        comic_title="The Tyrant of the Apocalypse Returns", comic_url=payload["comic_url"],
        from_episode=1, to_episode=50, payload=payload, id=f"tyrant-1-50-v7-{int(time.time())}",
    )
    task.artifacts["download_dir"] = os.path.join(PROJECT, "downloads", FOLDER)
    task.artifacts["download_folder_name"] = FOLDER
    task.artifacts["comic_title"] = "The Tyrant of the Apocalypse Returns"
    ctx = Ctx(task)
    for stage in (Stage10_EpisodeVideoRendering(), Stage11_FinalVideoAssembly(), Stage12_MetadataReports()):
        task.current_stage = stage.name
        print(f"[STAGE] {stage.name} start", flush=True)
        t0 = time.time()
        ok = await stage.execute(ctx)
        print(f"[STAGE] {stage.name} -> {'OK' if ok else 'FAILED'} in {time.time() - t0:.1f}s", flush=True)
        if not ok:
            return 1
    print("[RESULT] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
