import os
import sys
import asyncio
import json
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_1 import Stage5_GeminiAutomation

class SimpleCancelToken:
    def is_cancelled(self): return False

class ConsoleContext:
    def __init__(self, task):
        self.task = task
        self.cancel_token = SimpleCancelToken()
        self.payload = task.payload

    async def log(self, message, level="info", *a, **kw):
        ep_prefix = f"[Ep {self.task.current_episode}] " if self.task.current_episode else ""
        print(f"[{level.upper()}] {ep_prefix}{message}", flush=True)

    async def start_episode(self, ep):
        self.task.current_episode = ep
        await self.log(f"Starting episode {ep}...", "info")

    async def complete_episode(self, ep):
        await self.log(f"Completed episode {ep}.", "success")

    async def fail_episode(self, ep, error):
        await self.log(f"Episode {ep} error: {error}", "error")

    async def update_stage_progress(self, stage_name, progress):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True)

    async def update_progress(self, progress, stage_name=None, episode=None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True)

async def main():
    target_url = "https://www.webtoons.com/en/thriller/surviving-the-apocalypse/list?title_no=6678"
    download_dir = os.path.join(PROJECT_ROOT, "downloads", "surviving_the_apocalypse_1_57_en_947dedf7")
    
    task = WorkflowTask(
        comic_title="Surviving the Apocalypse",
        comic_url=target_url,
        from_episode=17,
        to_episode=17,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "en",
            "market_id": "us_apocalypse",
            "market": "us_apocalypse",
            "voice_id": config.DEFAULT_EN_VOICE_ID,
            "ref_audio_path": config.DEFAULT_EN_REF_AUDIO,
            "min_panel_duration": 3.5,
            "hard_floor_duration": 3.0,
            "retry_count": 5,
            "timeout": 360,
            "concurrency": 1,
        },
        id=f"heal-ep17-{int(time.time())}"
    )
    task.artifacts["download_dir"] = download_dir
    task.artifacts["download_folder_name"] = "surviving_the_apocalypse_1_57_en_947dedf7"
    task.artifacts["comic_title"] = "Surviving the Apocalypse"

    ctx = ConsoleContext(task)
    stage5 = Stage5_GeminiAutomation()
    print("Executing Stage 5 for Episode 17...")
    ok = await stage5.execute(ctx)
    print(f"Stage 5 Result for Ep 17: {ok}")
    
    recap_path = os.path.join(download_dir, "episode_17", "recap.json")
    if os.path.isfile(recap_path) and os.path.getsize(recap_path) > 10:
        print("[SUCCESS] Episode 17 recap.json generated successfully!")
        with open(recap_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"Episode 17 title: {data.get('title')}, segments count: {len(data.get('segments', []))}")
        return 0
    else:
        print("[FAIL] Episode 17 recap.json not found or empty.")
        return 1

if __name__ == "__main__":
    ret = asyncio.run(main())
    sys.exit(ret)
