import os
import sys
import asyncio
import json
import time
import shutil
from pathlib import Path

# Ensure UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Ensure working directory is project root
PROJECT_ROOT = r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
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
        await self.log(f"Bắt đầu xử lý tập {ep}...", "info")

    async def complete_episode(self, ep: int):
        await self.log(f"Hoàn thành tập {ep}.", "success")

    async def fail_episode(self, ep: int, error: str):
        await self.log(f"Lỗi tập {ep}: {error}", "error")

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
            db = {}
            if os.path.exists(db_path):
                try:
                    with open(db_path, "r", encoding="utf-8") as f:
                        db = json.load(f)
                except Exception:
                    db = {}
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
    target_url = "https://www.webtoons.com/en/action/the-world-after-the-fall/list?title_no=4011"
    from_ep = 1
    to_ep = 89

    print("=" * 80)
    print("  START RECAP WORKFLOW: The World After the Fall (Chapters 1–89 — Full Chaos Arc)")
    print("  URL: https://www.webtoons.com/en/action/the-world-after-the-fall/list?title_no=4011")
    print(f"  Episodes: {from_ep} -> {to_ep} (Total: {to_ep - from_ep + 1} chapters)")
    print("  Language: English (US)")
    print("  Market: US Apocalypse (Story Beat First, Point Scoring >= 65, 0-15s Golden Hook)")
    print(f"  Voice TTS: OmniVoice Andrew ({config.DEFAULT_EN_VOICE_ID})")
    print(f"  Ref Audio: {config.DEFAULT_EN_REF_AUDIO}")
    print("  Data Policy: 100% FRESH START (Không sử dụng lại data cũ)")
    print("  BGM: Strictly 0% (Tắt nhạc nền)")
    print("  Intro Policy: Cold Open / Direct Story Start (Bỏ Intro)")
    print("=" * 80)

    # Clean check: Ensure D: drive disk space
    total, used, free = shutil.disk_usage("D:/")
    free_gb = free // (1024 ** 3)
    print(f"[DISK] Drive D: Free Space: {free_gb} GB")
    if free_gb < 5:
        print("[WARNING] Dung lượng đĩa D: thấp (< 5 GB). Vui lòng lưu ý dọn dẹp thêm nếu cần.")

    # Resumption Support: Preserve current run artifacts and resume via EpisodeStageCache
    target_folder_prefix = "the_world_after_the_fall_1_89_en"
    downloads_dir = os.path.join(PROJECT_ROOT, "downloads")
    if os.path.isdir(downloads_dir):
        for item in os.listdir(downloads_dir):
            if item.startswith(target_folder_prefix):
                target_dir = os.path.join(downloads_dir, item)
                print(f"[RESUME] Phát hiện thư mục dữ liệu {target_dir}. Tự động tiếp tục (resume) qua EpisodeStageCache...")

    task_id = f"the-world-after-the-fall-chaos-arc-1-89-en-{int(time.time())}"
    task = WorkflowTask(
        comic_title="The World After The Fall",
        comic_url=target_url,
        from_episode=from_ep,
        to_episode=to_ep,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "en",
            "market_id": "us_apocalypse",
            "voice_id": config.DEFAULT_EN_VOICE_ID,
            "ref_audio_path": config.DEFAULT_EN_REF_AUDIO,
            "bgm_genre": "apocalypse",
            "enable_bgm": False,
            "enable_flash_forward_intro": False,
            "cleanup": False,
            "safe_mode": False,
            "retry_count": 5,
            "timeout": 360,
            "concurrency": 8,
            "burn_subtitles": False,
            "remove_text": False,
        },
        id=task_id
    )

    ctx = ConsoleContext(task)

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
        print(f"\n{'='*75}")
        print(f"  >>> BẮT ĐẦU: {stage.name}")
        print(f"{'='*75}")

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.RUNNING
                s["progress"] = 0.0
        ctx._sync_task_db()

        start_time = time.time()
        ok = await stage.execute(ctx)
        elapsed = time.time() - start_time

        if not ok:
            print(f"\n[FATAL] Giai đoạn {stage.name} thất bại sau {elapsed:.1f}s. Dừng quy trình.")
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
        print(f"[DONE] Giai đoạn {stage.name} hoàn thành 100% trong {elapsed:.1f}s.")

    task.status = WorkflowState.SUCCESS
    task.current_stage = "Completed"
    task.overall_progress = 100.0
    ctx._sync_task_db()

    final_video_url = task.artifacts.get("final_video_url")
    print("\n" + "=" * 80)
    print("  CHÚC MỪNG: TRỌN BỘ 89 TẬP (CHAOS ARC) TIẾNG ANH ĐÃ HOÀN THÀNH XUẤT SẮC!")
    print(f"  Final Video URL: {final_video_url}")
    print(f"  Output Directory: {task.artifacts.get('download_dir')}")
    print("=" * 80)
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
