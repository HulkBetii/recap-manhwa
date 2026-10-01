"""
Run pipeline from Stage 5 (Gemini Automation) onward for Veteran of the Apocalypse Ep 1 & 2.
Applies the newly updated prompt (Protagonist Early Lock, Cliffhanger Tension, Increased Bro Commentary).
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
from workflow_stages_1 import (
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
    download_dir = None
    for item in os.listdir("downloads"):
        if item.startswith("veteran_of_the_apocalypse_1_2_vi"):
            download_dir = os.path.join("downloads", item)
            break

    if not download_dir:
        print("[FATAL] Không tìm thấy thư mục download veteran_of_the_apocalypse_1_2_vi.")
        return 2

    print("=" * 70)
    print("  RE-RENDER 2 TẬP: Veteran of the Apocalypse - Tập 1 & 2 (Tiếng Việt)")
    print("  Prompt Mới: Protagonist Early Lock + Cliffhanger Tension + High Commentary")
    print(f"  Download dir: {download_dir}")
    print("=" * 70)

    # Clean previous generated scripts and media to force clean Stage 5 -> 12
    for ep in [1, 2]:
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        for fname in [
            "raw_gemini_response.txt", "recap.json", "narration.txt",
            "audio.mp3", "transcript.srt", "tts_config.json", "video.mp4",
            "content_bounds_cache.json", "artifact_manifest.json"
        ]:
            fpath = os.path.join(ep_dir, fname)
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                    print(f"[CLEAN] Đã xóa {fname} tại {ep_dir}")
                except Exception as e:
                    print(f"[WARN] Không thể xóa {fpath}: {e}")

    # Clean story memory and output dir
    sm_path = os.path.join(download_dir, "story_memory.json")
    if os.path.exists(sm_path):
        try:
            os.remove(sm_path)
            print(f"[CLEAN] Đã xóa story_memory.json cũ.")
        except Exception:
            pass

    out_dir = os.path.join(download_dir, "output")
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
        print(f"[CLEAN] Đã dọn dẹp thư mục output cũ.")

    task_id = f"veteran-ep1-2-vi-rerender-{int(time.time())}"
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
        },
        id=task_id
    )

    task.artifacts["download_dir"] = os.path.abspath(download_dir)
    task.artifacts["comic_title"] = "Veteran of the Apocalypse"

    ctx = ConsoleContext(task)

    pipeline = [
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
        print(f"[DONE] Giai đoạn {stage.name} hoàn thành 100%.")

    task.status = WorkflowState.SUCCESS
    task.current_stage = "Completed"
    task.overall_progress = 100.0
    ctx._sync_task_db()

    final_video_url = task.artifacts.get("final_video_url")
    print("\n=======================================================")
    print("  CHÚC MỪNG: TẬP 1 VÀ 2 TIẾNG VIỆT ĐÃ RENDER LẠI XUẤT SẮC!")
    print(f"  Final Video URL: {final_video_url}")
    print(f"  Artifacts: {task.artifacts.get('download_dir')}")
    print("=======================================================")
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
