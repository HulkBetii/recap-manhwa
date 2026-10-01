"""
Run pipeline from Stage2b onward using existing crawled images.
Purpose: fast verification of Speech Bubble Overflow Crop (BOC) without re-crawling.
"""
import os
import sys
import asyncio
import json
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
os.chdir(Path(__file__).resolve().parent)

from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_1 import (
    Stage2b_IntelligentRepagination,
    Stage3_NSFWModeration,
    Stage4_PDFGeneration,
    Stage5_GeminiAutomation,
    Stage6_JSONExtraction,
)
from workflow_stages_2 import (
    Stage7_NarrationAggregation,
    Stage8_LocalTTS,
    Stage9_SubtitleNormalization,
    Stage10_EpisodeVideoRendering,
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
        print(f"[{level.upper()}] {message}", flush=True)
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
        print(f"[INFO] Bat dau xu ly tap {ep}...", flush=True)

    async def complete_episode(self, ep: int):
        print(f"[SUCCESS] Hoan thanh tap {ep}.", flush=True)

    async def fail_episode(self, ep: int, error: str):
        print(f"[ERROR] That bai tap {ep}: {error}", flush=True)

    async def update_stage_progress(self, stage_name: str, progress: float):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True)
        self._sync_task_db()

    async def update_progress(self, progress: float, stage_name: str = None, episode: int = None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True)
        self._sync_task_db()

    def _sync_task_db(self):
        try:
            db_path = "tasks_db.json"
            tmp_path = "tasks_db.json.script_tmp"
            if os.path.exists(db_path):
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
                db[self.task.id] = self.task.to_storage_dict()
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(db, f, ensure_ascii=False, indent=2)
                for _ in range(10):
                    try:
                        os.replace(tmp_path, db_path)
                        break
                    except (PermissionError, OSError):
                        time.sleep(0.08)
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
        except Exception:
            pass


async def main():
    # Find existing download dir
    download_dir = None
    for item in os.listdir("downloads"):
        if item.startswith("veteran_of_the_apocalypse_1_2_vi"):
            download_dir = os.path.join("downloads", item)
            break

    if not download_dir:
        print("[FATAL] Khong tim thay thu muc download veteran ep1-2 vi. Chay run_veteran_ep1_2_vi.py truoc.")
        return 2

    print("=" * 70)
    print("  START FROM STAGE2b: Veteran of the Apocalypse - Tap 1 & 2 (VI)")
    print(f"  Download dir: {download_dir}")
    print("  BOC (Bubble Overflow Crop): ENABLED (default)")
    print("=" * 70)

    task_id = f"veteran-ep1-2-vi-boc-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Veteran of the Apocalypse",
        comic_url="https://www.webtoons.com/en/action/veteran-of-the-apocalypse/list?title_no=9675",
        from_episode=1,
        to_episode=2,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "vi",
            "voice_id": "clone",
            "ref_audio_path": r"C:\Users\HulkBeoti\Downloads\jessa - easygoing and effortless.mp3",
            "cleanup": False,
            "safe_mode": False,
            "retry_count": 3,
            "timeout": 300,
            "concurrency": 4,
            "burn_subtitles": False,
            "remove_text": False,
            # BOC config (defaults — same as system defaults, listed for clarity)
            "bubble_overflow_crop": True,
            "boc_margin_px": 20,
            "boc_min_remain_ratio": 0.20,
            "boc_min_remain_px": 150,
        },
        id=task_id
    )

    # Inject existing download_dir — MUST be absolute path for FFmpeg subprocess
    task.artifacts["download_dir"] = os.path.abspath(download_dir)

    ctx = ConsoleContext(task)

    # Clear images_pdf to force Stage2b re-run with new BOC logic
    for ep in [1, 2]:
        pdf_dir = os.path.join(download_dir, f"episode_{ep}", "images_pdf")
        if os.path.isdir(pdf_dir):
            import shutil
            shutil.rmtree(pdf_dir, ignore_errors=True)
            print(f"[RESET] Cleared {pdf_dir}")

    pipeline = [
        Stage2b_IntelligentRepagination(),
        Stage3_NSFWModeration(),
        Stage4_PDFGeneration(),
        Stage5_GeminiAutomation(),
        Stage6_JSONExtraction(),
        Stage7_NarrationAggregation(),
        Stage8_LocalTTS(),
        Stage9_SubtitleNormalization(),
        Stage10_EpisodeVideoRendering(),
        Stage11_FinalVideoAssembly(),
        Stage12_MetadataReports(),
        Stage13_Cleanup(),
    ]

    for stage in pipeline:
        task.current_stage = stage.name
        print(f"\n=======================================================")
        print(f"  >>> BAT DAU: {stage.name}")
        print(f"=======================================================")

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.RUNNING
                s["progress"] = 0.0
        ctx._sync_task_db()

        ok = await stage.execute(ctx)
        if not ok:
            print(f"[FATAL] Giai doan {stage.name} that bai. Dung quy trinh.")
            for s in task.stages:
                if s["name"] == stage.name:
                    s["status"] = StageState.FAILED
            task.status = WorkflowState.FAILED
            ctx._sync_task_db()
            return 2

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.SUCCESS
                s["progress"] = 100.0
        ctx._sync_task_db()
        print(f"[DONE] Giai doan {stage.name} hoan thanh 100%.")

    task.status = WorkflowState.SUCCESS
    task.current_stage = "Completed"
    task.overall_progress = 100.0
    ctx._sync_task_db()

    # Ensure final named video is copied and updated
    out_dir = os.path.join(download_dir, "output")
    none_mp4 = os.path.join(out_dir, "None.mp4")
    named_mp4 = os.path.join(out_dir, f"{os.path.basename(download_dir)}.mp4")
    if os.path.exists(none_mp4):
        shutil.copy2(none_mp4, named_mp4)
        print(f"[SUCCESS] Updated final video at: {named_mp4}")

    print("\n=======================================================")
    print("  HOAN THANH: TAP 1 VA 2 TIENG VIET (FROM STAGE2b)")
    print(f"  Final Video: {named_mp4 if os.path.exists(named_mp4) else final_video_url}")
    print(f"  Artifacts: {task.artifacts.get('download_dir')}")
    print("=======================================================")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
