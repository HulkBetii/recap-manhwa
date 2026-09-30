import os
import sys
import asyncio
import json
import time
import shutil

# Ensure UTF-8 everywhere
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_2 import (
    Stage10_EpisodeVideoRendering,
    Stage11_FinalVideoAssembly,
    Stage12_MetadataReports,
    Stage13_Cleanup,
    get_video_duration,
)
from app import find_ffmpeg

class SimpleCancelToken:
    def is_cancelled(self) -> bool:
        return False

class ConsoleContext:
    def __init__(self, task: WorkflowTask):
        self.task = task
        self.cancel_token = SimpleCancelToken()
        self.payload = task.payload

    async def log(self, message: str, level: str = "info", *args, **kwargs):
        prefix = f"[{level.upper()}]"
        print(f"{prefix} {message}", flush=True)
        self.task.logs.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "stage": self.task.current_stage,
            "episode": self.task.current_episode
        })

    async def start_episode(self, ep: int):
        self.task.current_episode = ep
        await self.log(f"Bắt đầu render video tập {ep}...", "info")

    async def complete_episode(self, ep: int):
        await self.log(f"Hoàn thành render video tập {ep}.", "success")

    async def fail_episode(self, ep: int, error: str):
        await self.log(f"Lỗi tập {ep}: {error}", "error")

    async def update_stage_progress(self, stage_name: str, progress: float):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True)

    async def update_progress(self, progress: float, stage_name: str = None, episode: int = None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True)

async def run_rerender():
    folder_name = "the_postman_of_the_apocalypse_1_19_en_1f8f304c"
    download_dir = os.path.join(PROJECT_ROOT, "downloads", folder_name)
    comic_title = "The Postman of the Apocalypse"
    from_ep = 1
    to_ep = 19

    print("=" * 80)
    print(f"  RE-RENDERING FULL SERIES: {comic_title} (Ep {from_ep} - {to_ep})")
    print(f"  Target Dir: {download_dir}")
    print(f"  Enhancements: Ken Burns 2D Drift, 2-Pass Donor Injection, Intro Title Cards, Establishing Shot Preservation")
    print(f"  Concurrency: 3 Parallel NVENC Render Threads")
    print("=" * 80)

    task_id = f"postman-apocalypse-rerender-{int(time.time())}"
    task = WorkflowTask(
        comic_title=comic_title,
        comic_url="https://vortexscans.org/series/the-postman-of-the-apocalypse",
        from_episode=from_ep,
        to_episode=to_ep,
        id=task_id,
        payload={
            "comic_title": comic_title,
            "from_episode": from_ep,
            "to_episode": to_ep,
            "language": "en",
            "market_id": "us_apocalypse",
            "voice_id": "clone_andrew",
            "ref_audio_path": getattr(config, "DEFAULT_EN_REF_AUDIO", None),
            "min_panel_duration": 3.5,
            "hard_floor_duration": 3.0,
            "concurrency": 3,
            "force_render": True,
            "burn_subtitles": False,
            "remove_text": False,
            "split_double_pages": True,
            "reading_direction": "ltr",
            "cleanup": False,
            "safe_mode": False,
            "fps": 30,
        }
    )
    task.artifacts["download_dir"] = download_dir
    task.artifacts["download_folder_name"] = folder_name

    stages = [
        Stage10_EpisodeVideoRendering(),
        Stage11_FinalVideoAssembly(),
        Stage12_MetadataReports(),
        Stage13_Cleanup(),
    ]

    ctx = ConsoleContext(task)
    start_total = time.time()

    for stage in stages:
        task.current_stage = stage.name
        print(f"\n>>> [GIAI ĐOẠN] {stage.name}...")
        stage_start = time.time()

        ok = await stage.execute(ctx)
        stage_elapsed = time.time() - stage_start

        if not ok:
            print(f"\n[ERROR] Giai đoạn {stage.name} thất bại sau {stage_elapsed:.1f}s.")
            task.status = WorkflowState.FAILED
            return False

        print(f"[DONE] {stage.name} hoàn thành xuất sắc trong {stage_elapsed:.1f}s.")

    task.status = WorkflowState.SUCCESS
    total_elapsed = time.time() - start_total

    print("\n" + "=" * 80)
    print(f"  TẤT CẢ 19 TẬP & MASTER VIDEO ĐÃ ĐƯỢC RE-RENDER XONG TRONG {total_elapsed:.1f}s ({total_elapsed/60:.2f} phút)!")
    print("=" * 80)

    # Verification of all 19 episode videos
    ffmpeg_exe = find_ffmpeg()
    total_vid_dur = 0.0
    for ep in range(from_ep, to_ep + 1):
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        video_mp4 = os.path.join(ep_dir, "video.mp4")
        if os.path.exists(video_mp4):
            dur = get_video_duration(video_mp4, ffmpeg_exe)
            size_mb = round(os.path.getsize(video_mp4) / (1024 * 1024), 2)
            total_vid_dur += dur
            print(f"  - Tập {ep:02d}: Video {dur:.1f}s ({size_mb} MB) [NVENC 1080p]")
        else:
            print(f"  - Tập {ep:02d}: THIẾU VIDEO!")

    # Master Video
    final_video_path = task.artifacts.get("final_video_path", "")
    if not final_video_path or not os.path.exists(final_video_path):
        output_dir = os.path.join(download_dir, "output")
        if os.path.exists(output_dir):
            mp4_candidates = [os.path.join(output_dir, f) for f in os.listdir(output_dir) if f.lower().endswith(".mp4")]
            if mp4_candidates:
                final_video_path = mp4_candidates[0]

    if final_video_path and os.path.exists(final_video_path):
        final_dur = get_video_duration(final_video_path, ffmpeg_exe)
        final_size_mb = round(os.path.getsize(final_video_path) / (1024 * 1024), 2)
        print(f"\n🎬 Master Assembled Video: {final_video_path}")
        print(f"   Thời lượng tổng: {final_dur:.1f}s ({round(final_dur / 60, 2)} phút)")
        print(f"   Dung lượng: {final_size_mb} MB")

    return True

if __name__ == "__main__":
    success = asyncio.run(run_rerender())
    sys.exit(0 if success else 1)
