import os
import sys
import asyncio
import json
import time
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

from workflow_base import WorkflowTask, WorkflowState, StageState
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

    async def is_cancelled(self) -> bool:
        return False

    def complete_episode_stage(self, ep: int, stage_key: str):
        pass

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
    target_url = "https://www.webtoons.com/en/action/veteran-of-the-apocalypse/list?title_no=9675"
    download_dir = os.path.abspath(r"downloads\veteran_of_the_apocalypse_1_5_vi_e826e8f9")

    print("=" * 70)
    print("  RENDER LẠI (TẮT INTRO): Veteran of the Apocalypse - Tập 1 đến 5 (Tiếng Việt)")
    print(f"  Target Dir: {download_dir}")
    print("=" * 70)

    # 1. Clean old Episode 1 audio, srt, narration, video to re-render without intro hook
    ep1_dir = os.path.join(download_dir, "episode_1")
    for f_del in ["audio.mp3", "audio.mp3.tmp.mp3", "tts_config.json", "tts_cache.json", "transcript.srt", "narration.txt", "stage_cache.json", "content_bounds_cache.json", "episode_1.mp4", "episode_1.mp4.tmp.mp4", "video.mp4", "video.mp4.tmp.mp4"]:
        fp = os.path.join(ep1_dir, f_del)
        if os.path.exists(fp):
            try:
                os.remove(fp)
                print(f"[CLEANUP] Đã xóa {f_del} cũ của Tập 1 để làm mới.")
            except Exception as e:
                print(f"[WARN] Không thể xóa {fp}: {e}")

    # Clean full video and metadata
    for f_del in ["full_video.mp4", "full_video.mp4.tmp.mp4", "youtube_metadata.json", "youtube_metadata.txt"]:
        fp = os.path.join(download_dir, f_del)
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception:
                pass
    output_dir = os.path.join(download_dir, "output")
    for f_del in ["veteran_of_the_apocalypse_1_5_vi_e826e8f9.mp4", "veteran_of_the_apocalypse_1_5_vi_e826e8f9.srt", "youtube_upload_kit.txt", "metadata.json", "processing_report.json"]:
        fp = os.path.join(output_dir, f_del)
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception:
                pass

    # Re-run Stage 7, 8, 9 for Episode 1
    task_ep1 = WorkflowTask(
        comic_title="Veteran of the Apocalypse",
        comic_url=target_url,
        from_episode=1,
        to_episode=1,
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
            "protagonist_name": "Kang Seongho",
        },
        id=f"veteran-ep1-tts-{int(time.time())}"
    )
    task_ep1.artifacts["download_dir"] = download_dir
    task_ep1.artifacts["download_folder_name"] = os.path.basename(download_dir)
    ctx_ep1 = ConsoleContext(task_ep1)

    print("\n--- [BƯỚC 1]: CHẠY LẠI TTS & PHỤ ĐỀ CHO TẬP 1 (BỎ INTRO HOOK) ---")
    s7 = Stage7_NarrationAggregation()
    s8 = Stage8_LocalTTS()
    s9 = Stage9_SubtitleNormalization()

    await s7.execute(ctx_ep1)
    await s8.execute(ctx_ep1)
    await s9.execute(ctx_ep1)

    # Full task for Stage 10-13
    task_full = WorkflowTask(
        comic_title="Veteran of the Apocalypse",
        comic_url=target_url,
        from_episode=1,
        to_episode=5,
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
            "force_render": False, # Will render Episode 1 fresh since its video was deleted, and keep Ep 2-5
            "hard_floor_duration": 2.0,
            "min_panel_duration": 3.0,
            "protagonist_name": "Kang Seongho",
        },
        id=f"veteran-ep1-5-assembly-{int(time.time())}"
    )
    task_full.artifacts["download_dir"] = download_dir
    task_artifacts_folder = os.path.basename(download_dir)
    task_full.artifacts["download_folder_name"] = task_artifacts_folder
    ctx_full = ConsoleContext(task_full)

    print("\n--- [BƯỚC 2]: RENDER TẬP 1 VÀ GHÉP FULL 5 TẬP (STAGE 10-13) ---")
    pipeline = [
        Stage10_EpisodeVideoRendering(),
        Stage11_FinalVideoAssembly(),
        Stage12_MetadataReports(),
        Stage13_Cleanup(),
    ]

    for stage in pipeline:
        task_full.current_stage = stage.name
        print(f"\n=======================================================")
        print(f"  >>> BẮT ĐẦU: {stage.name}")
        print(f"=======================================================")

        for s in task_full.stages:
            if s["name"] == stage.name:
                s["state"] = StageState.RUNNING
                break
        ctx_full._sync_task_db()

        success = await stage.execute(ctx_full)
        if not success:
            print(f"\n[CRITICAL ERROR] Giai đoạn {stage.name} thất bại!")
            return False

        for s in task_full.stages:
            if s["name"] == stage.name:
                s["state"] = StageState.SUCCESS
                break
        ctx_full._sync_task_db()
        print(f"  >>> HOÀN THÀNH: {stage.name}")

    print("\n" + "=" * 70)
    print("  HOÀN THÀNH RENDER VÀ GHÉP VIDEO 5 TẬP KHÔNG CÓ INTRO!")
    print("=" * 70)
    return True

if __name__ == "__main__":
    asyncio.run(main())
