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

# Ensure working directory is project root
os.chdir(Path(__file__).resolve().parent)

from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_1 import (
    Stage0_ProjectInit,
    Stage1_ComicParsing,
    Stage2_AsyncImageCrawling,
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
    target_url = "https://www.webtoons.com/en/action/veteran-of-the-apocalypse/list?title_no=9675"
    print("=" * 70)
    print("  START WORKFLOW: Veteran of the Apocalypse - Tập 1 & 2 (Tiếng Việt)")
    print("  Model VLM: Google Gemini 3.8 Flash")
    print("  Voice TTS: OmniVoice Voice Cloning (Jessa - Mặc định Tiếng Việt)")
    print("  Narrative Engine: Protagonist Name Anchoring + Gender-Adaptive")
    print("  Story Memory: Binge-watching context continuity across Ep 1 -> Ep 2")
    print("=" * 70)

    task_id = f"veteran-ep1-2-vi-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Veteran of the Apocalypse",
        comic_url=target_url,
        from_episode=1,
        to_episode=2,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "vi",
            "voice_id": "clone",
            "ref_audio_path": r"C:\Users\HulkBeoti\Downloads\jessa - easygoing and effortless.mp3",
            "bgm_genre": "apocalypse",
            "enable_bgm": False,
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

    ctx = ConsoleContext(task)

    # Clean downstream artifacts to force fresh Gemini regeneration with new prompt rules
    clean_target_dir = os.path.join("downloads", "veteran_of_the_apocalypse_1_2_vi_e826e8f9")
    if os.path.exists(clean_target_dir):
        print("[RESET] Dọn dẹp kịch bản, âm thanh và video cũ để sinh mới 100% với chuẩn Contextual Anchoring...")
        story_mem = os.path.join(clean_target_dir, "story_memory.json")
        if os.path.exists(story_mem):
            try:
                os.remove(story_mem)
            except Exception:
                pass
        out_dir = os.path.join(clean_target_dir, "output")
        if os.path.exists(out_dir):
            try:
                shutil.rmtree(out_dir, ignore_errors=True)
            except Exception:
                pass
        for ep in [1, 2]:
            ep_d = os.path.join(clean_target_dir, f"episode_{ep}")
            if os.path.exists(ep_d):
                pdf_dir = os.path.join(ep_d, "pdf")
                if os.path.exists(pdf_dir):
                    try:
                        shutil.rmtree(pdf_dir, ignore_errors=True)
                    except Exception:
                        pass
                for f_del in [
                    "raw_gemini_response.txt", "recap.json", "narration.txt",
                    "audio.mp3", "transcript.srt", "video.mp4", "artifact_manifest.json",
                    "tts_config.json", "content_bounds_cache.json"
                ]:
                    f_path = os.path.join(ep_d, f_del)
                    if os.path.exists(f_path):
                        try:
                            os.remove(f_path)
                        except Exception:
                            pass

    pipeline = [
        Stage0_ProjectInit(),
        Stage1_ComicParsing(),
        Stage2_AsyncImageCrawling(),
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
        print(f"  >>> BẮT ĐẦU: {stage.name}")
        print(f"=======================================================")

        # Fast-track Image Crawling if raw images exist from previous crawl
        if stage.name == "Stage 2 - Image Crawling":
            download_dir = task.artifacts.get("download_dir")
            if download_dir:
                for ep in [1, 2]:
                    target_img_dir = os.path.join(download_dir, f"episode_{ep}", "images")
                    cached_img_dir = os.path.join("downloads", "veteran_of_the_apocalypse_1_30_en_e826e8f9", f"episode_{ep}", "images")
                    if os.path.exists(cached_img_dir) and len(os.listdir(cached_img_dir)) > 30:
                        if not os.path.exists(target_img_dir) or len(os.listdir(target_img_dir)) == 0:
                            os.makedirs(target_img_dir, exist_ok=True)
                            print(f"[CACHE] Tự động tái sử dụng {len(os.listdir(cached_img_dir))} ảnh gốc tập {ep} từ đợt crawl trước...")
                            for fname in os.listdir(cached_img_dir):
                                src_f = os.path.join(cached_img_dir, fname)
                                dst_f = os.path.join(target_img_dir, fname)
                                if not os.path.exists(dst_f):
                                    shutil.copy2(src_f, dst_f)
                            from artifact_cache import EpisodeStageCache, stage_fingerprint
                            ep_dir = os.path.join(download_dir, f"episode_{ep}")
                            cache = EpisodeStageCache(ep_dir)
                            fingerprint = stage_fingerprint(task, "image_crawl", ep, extra=task.artifacts.get("chapter_slugs", []))
                            cache.commit(stage="image_crawl", fingerprint=fingerprint, outputs=[target_img_dir])

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
    print("  CHÚC MỪNG: TẬP 1 VÀ 2 TIẾNG VIỆT ĐÃ HOÀN THÀNH XUẤT SẮC!")
    print(f"  Final Video URL: {final_video_url}")
    print(f"  Artifacts: {task.artifacts.get('download_dir')}")
    print("=======================================================")
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
