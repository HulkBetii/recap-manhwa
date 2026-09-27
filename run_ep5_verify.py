import os, sys, asyncio, time

PROJECT_ROOT = r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import config
from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_2 import Stage10_EpisodeVideoRendering, Stage11_FinalVideoAssembly, get_video_duration
from app import find_ffmpeg

class SimpleCancelToken:
    def is_cancelled(self): return False

class ConsoleContext:
    def __init__(self, task):
        self.task = task
        self.cancel_token = SimpleCancelToken()
        self.payload = task.payload
    async def log(self, msg, level="info", *a, **kw):
        print(f"[{level.upper()}] {msg}", flush=True)
    async def start_episode(self, ep):
        self.task.current_episode = ep
        await self.log(f"Render tập {ep}...")
    async def complete_episode(self, ep):
        await self.log(f"Hoàn thành tập {ep}.", "success")
    async def fail_episode(self, ep, error):
        await self.log(f"Lỗi tập {ep}: {error}", "error")
    async def update_stage_progress(self, name, pct):
        print(f"[PROGRESS] {name}: {pct:.1f}%", flush=True)
    async def update_progress(self, pct, stage_name=None, episode=None):
        print(f"[PROGRESS] {stage_name or '?'}: {pct:.1f}%", flush=True)

async def main():
    folder_name = "the_postman_of_the_apocalypse_1_19_en_1f8f304c"
    download_dir = os.path.join(PROJECT_ROOT, "downloads", folder_name)
    
    task = WorkflowTask(
        comic_title="The Postman of the Apocalypse",
        comic_url="https://vortexscans.org/series/the-postman-of-the-apocalypse",
        from_episode=5,
        to_episode=5,
        id=f"postman-ep5-verify-{int(time.time())}",
        payload={
            "comic_title": "The Postman of the Apocalypse",
            "from_episode": 5,
            "to_episode": 5,
            "language": "en",
            "market_id": "us_apocalypse",
            "voice_id": "clone_andrew",
            "ref_audio_path": getattr(config, "DEFAULT_EN_REF_AUDIO", None),
            "min_panel_duration": 3.5,
            "hard_floor_duration": 3.0,
            "concurrency": 1,
            "force_render": True,
            "fps": 30,
            "safe_mode": False,
            "cleanup": False,
        }
    )
    task.artifacts["download_dir"] = download_dir
    task.artifacts["download_folder_name"] = folder_name

    print("=" * 70)
    print("  VERIFY RENDER: Ep5 single episode (force_render=True)")
    print("  Expected: LongDur donor injection messages in console")
    print("  Expected: multi-image segments > 0")
    print("=" * 70)

    ctx = ConsoleContext(task)
    stage = Stage10_EpisodeVideoRendering()
    t0 = time.time()
    ok = await stage.execute(ctx)
    elapsed = time.time() - t0

    if ok:
        ffmpeg_exe = find_ffmpeg()
        ep_dir = os.path.join(download_dir, "episode_5")
        video = os.path.join(ep_dir, "video.mp4")
        dur = get_video_duration(video, ffmpeg_exe)
        size = round(os.path.getsize(video) / (1024*1024), 2)
        print(f"\n✅ Ep5 render OK in {elapsed:.1f}s")
        print(f"   Video: {dur:.1f}s ({size} MB)")
        print(f"\nNOTE: Search for '[Stage10] LongDur' above to verify donor injection fired")
    else:
        print(f"\n❌ Ep5 render FAILED after {elapsed:.1f}s")

if __name__ == "__main__":
    asyncio.run(main())
