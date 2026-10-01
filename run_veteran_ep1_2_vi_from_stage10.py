"""
Run pipeline from Stage10 onward — TTS & stages 2b-9 already done.
Dùng khi FFmpeg fail do path issue, không cần re-run TTS.
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
from workflow_stages_2 import (
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
            download_dir = os.path.abspath(os.path.join("downloads", item))
            break

    if not download_dir:
        print("[FATAL] Khong tim thay thu muc download veteran ep1-2 vi.")
        return 2

    # Verify audio files exist
    for ep in [1, 2]:
        audio = os.path.join(download_dir, f"episode_{ep}", "audio.mp3")
        if not os.path.exists(audio):
            print(f"[FATAL] Khong tim thay {audio} — chay lai Stage 8 TTS truoc.")
            return 2
        print(f"[OK] audio Tap {ep}: {audio} ({os.path.getsize(audio)//1024}KB)")

    print("=" * 70)
    print("  START FROM STAGE10: Veteran of the Apocalypse - Tap 1 & 2 (VI)")
    print(f"  Download dir (absolute): {download_dir}")
    print("=" * 70)

    task_id = f"veteran-ep1-2-vi-stage10-{int(time.time())}"
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
            "bubble_overflow_crop": True,
            "force_render": True,
        },
        id=task_id
    )

    # CRITICAL: absolute path so FFmpeg subprocess resolves audio.mp3 correctly
    task.artifacts["download_dir"] = download_dir
    task.artifacts["download_folder_name"] = os.path.basename(download_dir)

    ctx = ConsoleContext(task)

    # Clear bounds cache and old videos to force fresh CameraPlanner generation & video re-encoding
    for ep in [1, 2]:
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        for target_del in ["content_bounds_cache.json", "stage_cache.json", "video.mp4", "video.mp4.tmp.mp4"]:
            target_p = os.path.join(ep_dir, target_del)
            if os.path.exists(target_p):
                try:
                    os.remove(target_p)
                    print(f"[RESET] Cleared {target_p}")
                except Exception as del_err:
                    print(f"[WARN] Could not remove {target_p}: {del_err}")

    pipeline = [
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

    final_video_url = task.artifacts.get("final_video_url")
    print("\n=======================================================")
    print("  HOAN THANH: TAP 1 VA 2 TIENG VIET - VIDEO XUAT SUAT!")
    print(f"  Final Video: {final_video_url}")
    print(f"  Artifacts: {download_dir}")
    print("=======================================================")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
