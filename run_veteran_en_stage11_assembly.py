"""
Run Stage 11 (Final Video Assembly with Flash-Forward Intro) & Stage 12 for Veteran of the Apocalypse Full 33 Episodes (EN).
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

import config
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
        try:
            db_path = "tasks_db.json"
            tmp = db_path + ".script_tmp"
            db = {}
            if os.path.exists(db_path):
                try:
                    with open(db_path, "r", encoding="utf-8") as f:
                        db = json.load(f)
                except Exception:
                    db = {}
            db[self.task.id] = self.task.to_storage_dict()
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            for _ in range(10):
                try:
                    os.replace(tmp, db_path)
                    break
                except Exception:
                    time.sleep(0.08)
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        except Exception:
            pass


async def main():
    download_dir = None
    for item in os.listdir("downloads"):
        if item.startswith("veteran_of_the_apocalypse_1_33_en"):
            download_dir = os.path.join("downloads", item)
            break

    if not download_dir:
        print("[FATAL] Không tìm thấy thư mục download veteran_of_the_apocalypse_1_33_en.")
        return 2

    print("=" * 80)
    print("  ASSEMBLING FULL 33 EPISODES (EN) WITH FLASH-FORWARD INTRO")
    print(f"  Download dir: {download_dir}")
    print("=" * 80)

    # Restore clean base video for ep1 from backup if exists
    ep1_dir = os.path.join(download_dir, "episode_1")
    ep1_bak_vid = os.path.join(ep1_dir, "video_no_intro.mp4")
    ep1_bak_srt = os.path.join(ep1_dir, "transcript_no_intro.srt")
    if os.path.exists(ep1_bak_vid):
        shutil.copy2(ep1_bak_vid, os.path.join(ep1_dir, "video.mp4"))
    if os.path.exists(ep1_bak_srt):
        shutil.copy2(ep1_bak_srt, os.path.join(ep1_dir, "transcript.srt"))

    out_dir = os.path.join(download_dir, "output")
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)

    task_id = f"veteran-33ep-en-assembly-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Veteran of the Apocalypse",
        comic_url="https://www.webtoons.com/en/action/veteran-of-the-apocalypse/list?title_no=9675",
        from_episode=1,
        to_episode=33,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "en",
            "market": "us_apocalypse",
            "voice_id": config.DEFAULT_EN_VOICE_ID,
            "ref_audio_path": config.DEFAULT_EN_REF_AUDIO,
            "min_panel_duration": 3.0,
            "hard_floor_duration": 2.0,
            "enable_flash_forward_intro": True,
            "enable_sfx": False,
            "cleanup": False,
            "safe_mode": False,
            "retry_count": 5,
            "timeout": 360,
            "concurrency": 4,
            "burn_subtitles": False,
            "remove_text": False,
            "split_double_pages": True,
            "reading_direction": "ltr",
        },
        id=task_id
    )

    task.artifacts["download_dir"] = os.path.abspath(download_dir)
    task.artifacts["comic_title"] = "Veteran of the Apocalypse"

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
        ctx._sync_task_db()

        ok = await stage.execute(ctx)
        if not ok:
            print(f"[FATAL] Giai đoạn {stage.name} thất bại. Dừng quy trình.")
            return 2

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.SUCCESS
                s["progress"] = 100.0
        ctx._sync_task_db()
        print(f"[DONE] Giai đoạn {stage.name} hoàn thành 100%.")

    final_video_url = task.artifacts.get("final_video_url")
    print("\n=======================================================")
    print("  CHÚC MỪNG: FULL 33 TẬP TIẾNG ANH (CÓ INTRO) ĐÃ HOÀN TẤT XUẤT SẮC!")
    print(f"  Final Video URL: {final_video_url}")
    print(f"  Intro Artifacts: {task.artifacts.get('flash_forward_intro')}")
    print("=======================================================")
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
