import os
import sys
import asyncio
from pathlib import Path

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

os.chdir(Path(__file__).resolve().parent)

from app import find_ffmpeg
ffmpeg_exe = find_ffmpeg()
if ffmpeg_exe and os.path.exists(ffmpeg_exe):
    ffmpeg_dir = os.path.dirname(os.path.abspath(ffmpeg_exe))
    if ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    print(f"[INIT] Configured FFmpeg on PATH: {ffmpeg_dir}")

from workflow_base import WorkflowTask, StageState
from workflow_stages_2 import (
    Stage7_NarrationAggregation,
    Stage8_LocalTTS,
    Stage9_SubtitleNormalization,
)

class SimpleCancelToken:
    def is_cancelled(self) -> bool:
        return False

class ConsoleContext:
    def __init__(self, task: WorkflowTask):
        self.task = task
        self.cancel_token = SimpleCancelToken()
        self.payload = task.payload

    async def log(self, message: str, level: str = "info", *args, **kwargs):
        print(f"[{level.upper()}] {message}", flush=True)

    async def is_cancelled(self) -> bool:
        return False

    def complete_episode_stage(self, ep: int, stage_key: str):
        pass

    async def start_episode(self, ep: int):
        print(f"[INFO] Bắt đầu xử lý tập {ep}...", flush=True)

    async def complete_episode(self, ep: int):
        print(f"[SUCCESS] Hoàn thành tập {ep}.", flush=True)

    async def fail_episode(self, ep: int, error: str):
        print(f"[ERROR] Thất bại tập {ep}: {error}", flush=True)

    async def update_stage_progress(self, stage_name: str, progress: float):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True)

    async def update_progress(self, progress: float, stage_name: str = None, episode: int = None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True)

async def main():
    download_dir = os.path.abspath(r"downloads\veteran_of_the_apocalypse_1_5_vi_e826e8f9")
    ep5_dir = os.path.join(download_dir, "episode_5")
    for f in ["audio.mp3", "audio.mp3.tmp.mp3", "tts_config.json", "tts_cache.json", "transcript.srt", "timings.json", "narration.txt", "stage_cache.json"]:
        p = os.path.join(ep5_dir, f)
        if os.path.exists(p):
            try:
                os.remove(p)
                print(f"Deleted {f}")
            except Exception as e:
                print(f"Error deleting {f}: {e}")

    task = WorkflowTask(
        comic_title="Veteran of the Apocalypse",
        comic_url="https://www.webtoons.com/en/action/veteran-of-the-apocalypse/list?title_no=9675",
        from_episode=5,
        to_episode=5,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "vi",
            "voice_id": "clone",
            "ref_audio_path": r"C:\Users\HulkBeoti\Downloads\jessa - easygoing and effortless.mp3",
            "cleanup": False,
            "safe_mode": False,
            "protagonist_name": "Kang Seongho",
        },
        id="test-tts-ep5"
    )
    task.artifacts["download_dir"] = download_dir
    ctx = ConsoleContext(task)

    print("Running Stage 7...")
    s7 = Stage7_NarrationAggregation()
    await s7.execute(ctx)

    print("Running Stage 8...")
    s8 = Stage8_LocalTTS()
    res8 = await s8.execute(ctx)
    print(f"Stage 8 result: {res8}")

    print("Running Stage 9...")
    s9 = Stage9_SubtitleNormalization()
    res9 = await s9.execute(ctx)
    print(f"Stage 9 result: {res9}")

if __name__ == "__main__":
    asyncio.run(main())
