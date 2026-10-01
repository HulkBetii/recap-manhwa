"""
Run Stage 11 (Final Video Assembly with Flash-Forward Intro) & Stage 12 for Vampire Family Ep 1 & 2.
"""
import os
import sys
import asyncio
import json
import time
import shutil
from pathlib import Path

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
os.chdir(Path(__file__).resolve().parent)

from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_2 import (
    Stage11_FinalVideoAssembly,
    Stage12_MetadataReports,
    Stage13_Cleanup,
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
        prefix = f"[{level.upper()}]"
        print(f"{prefix} {message}", flush=True)
        self.task.logs.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "stage": self.task.current_stage,
            "episode": self.task.current_episode
        })
        self._sync_task_db()

    async def start_episode(self, ep: int):
        self.task.current_episode = ep
        print(f"[INFO] Bắt đầu xử lý tập {ep}...", flush=True)

    async def complete_episode(self, ep: int):
        print(f"[SUCCESS] Hoàn thành tập {ep}.", flush=True)

    async def fail_episode(self, ep: int, error: str):
        print(f"[ERROR] Thất bại tập {ep}: {error}", flush=True)

    async def update_stage_progress(self, stage_name: str, progress: float):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True)
        self._sync_task_db()

    async def update_progress(self, progress: float, stage_name: str = None, episode: int = None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True)
        self._sync_task_db()

    def _sync_task_db(self):
        pass


async def main():
    download_dir = None
    for item in os.listdir("downloads"):
        if item.startswith("vampire_family_1_2_vi"):
            download_dir = os.path.join("downloads", item)
            break

    if not download_dir:
        print("[FATAL] Không tìm thấy thư mục download vampire_family_1_2_vi.")
        return 2

    print("=" * 70)
    print("  ASSEMBLING VAMPIRE FAMILY EP 1 & 2 WITH FLASH-FORWARD INTRO")
    print(f"  Download dir: {download_dir}")
    print("=" * 70)

    # Restore backup video/srt if exists or clean output dir
    ep1_dir = os.path.join(download_dir, "episode_1")
    ep1_backup_vid = os.path.join(ep1_dir, "video_no_intro.mp4")
    ep1_backup_srt = os.path.join(ep1_dir, "transcript_no_intro.srt")
    if os.path.exists(ep1_backup_vid):
        shutil.copy2(ep1_backup_vid, os.path.join(ep1_dir, "video.mp4"))
    if os.path.exists(ep1_backup_srt):
        shutil.copy2(ep1_backup_srt, os.path.join(ep1_dir, "transcript.srt"))

    out_dir = os.path.join(download_dir, "output")
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)

    task_id = f"vampire-family-ep1-2-vi-intro-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Vampire Family",
        comic_url="https://www.webtoons.com/en/comedy/vampire-family/list?title_no=6402",
        from_episode=1,
        to_episode=2,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "vi",
            "voice_id": "clone",
            "ref_audio_path": r"C:\Users\HulkBeoti\Downloads\jessa - easygoing and effortless.mp3",
            "enable_flash_forward_intro": True,
            "cleanup": False,
            "safe_mode": False,
            "retry_count": 3,
            "timeout": 300,
            "concurrency": 4,
            "burn_subtitles": False,
            "remove_text": False,
        },
        id=task_id
    )

    task.artifacts["download_dir"] = os.path.abspath(download_dir)
    task.artifacts["comic_title"] = "Vampire Family"

    ctx = ConsoleContext(task)

    pipeline = [
        Stage11_FinalVideoAssembly(),
        Stage12_MetadataReports(),
        Stage13_Cleanup(),
    ]

    for stage in pipeline:
        task.current_stage = stage.name
        print(f"\n=======================================================")
        print(f"  >>> BẮT ĐẦU: {stage.name}")
        print(f"=======================================================")

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.RUNNING
                s["progress"] = 0.0

        ok = await stage.execute(ctx)
        if not ok:
            print(f"[FATAL] Giai đoạn {stage.name} thất bại. Dừng quy trình.")
            return 2

        print(f"[DONE] Giai đoạn {stage.name} hoàn thành 100%.")

    final_video_url = task.artifacts.get("final_video_url")
    print("\n=======================================================")
    print("  CHÚC MỪNG: VAMPIRE FAMILY (CÓ INTRO) ĐÃ HOÀN TẤT XUẤT SẮC!")
    print(f"  Final Video URL: {final_video_url}")
    print(f"  Intro Artifacts: {task.artifacts.get('flash_forward_intro')}")
    print("=======================================================")
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
