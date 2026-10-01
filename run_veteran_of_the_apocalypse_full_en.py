import os
import sys
import asyncio
import json
import time
import urllib.parse
import shutil
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
        ep = kwargs.get("episode", self.task.current_episode)
        ep_prefix = f"[Ep {ep}] " if ep is not None else ""
        print(f"[{level.upper()}] {ep_prefix}{message}", flush=True)
        self.task.logs.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "stage": self.task.current_stage,
            "episode": ep
        })
        self._sync_task_db()

    async def start_episode(self, ep: int):
        self.task.current_episode = ep
        await self.log(f"Starting episode {ep}...", "info", episode=ep)

    async def complete_episode(self, ep: int):
        await self.log(f"Completed episode {ep}.", "success", episode=ep)

    async def fail_episode(self, ep: int, error: str):
        await self.log(f"Episode {ep} failed: {error}", "error", episode=ep)

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
    target_url = "https://www.webtoons.com/en/action/veteran-of-the-apocalypse/list?title_no=9675"
    from_ep = 1
    to_ep = 33
    total_eps = to_ep - from_ep + 1

    print("=" * 80)
    print("  START FULL RECAP WORKFLOW: Veteran of the Apocalypse (Episodes 1 -> 33)")
    print(f"  Target URL: {target_url}")
    print(f"  Episodes: {from_ep} to {to_ep} (Total: {total_eps} episodes)")
    print("  Language: English (en)")
    print("  Market: US Apocalypse / Survival Action Recaps")
    print(f"  Voice TTS: OmniVoice English ({config.DEFAULT_EN_VOICE_ID})")
    print(f"  Ref Audio: {config.DEFAULT_EN_REF_AUDIO}")
    print("  VLM Automation: Google Gemini 3.8 Flash (via 9router)")
    print("  Video Rendering: OpenCV C++ NVENC Direct Pipe (1080p)")
    print("=" * 80)

    # Check disk space
    try:
        total, used, free = shutil.disk_usage("D:/")
        free_gb = free // (1024 ** 3)
        print(f"[DISK] Drive D: Free Space: {free_gb} GB")
        if free_gb < 10:
            print("[WARNING] Low disk space on drive D: (< 10 GB).")
    except Exception:
        pass

    task_id = f"veteran-of-the-apocalypse-full-1-33-en-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Veteran of the Apocalypse",
        comic_url=target_url,
        from_episode=from_ep,
        to_episode=to_ep,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "en",
            "market": "us_apocalypse",
            "voice_id": config.DEFAULT_EN_VOICE_ID,
            "ref_audio_path": config.DEFAULT_EN_REF_AUDIO,
            "min_panel_duration": 3.5,
            "hard_floor_duration": 3.0,
            "enable_flash_forward_intro": False,
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

    start_all = time.time()
    task.status = WorkflowState.RUNNING
    task.started_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ctx._sync_task_db()

    for stage in pipeline:
        task.current_stage = stage.name
        print(f"\n=======================================================")
        print(f"  >>> BẮT ĐẦU: {stage.name}")
        print(f"=======================================================")

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.RUNNING

        t0 = time.time()
        try:
            success = await stage.execute(ctx)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await ctx.log(f"Stage {stage.name} crashed with unhandled exception: {e}", "error")
            success = False

        duration = time.time() - t0

        if success:
            for s in task.stages:
                if s["name"] == stage.name:
                    s["status"] = StageState.SUCCESS
                    s["progress"] = 100.0
            print(f"\n[PASS] Hoàn thành {stage.name} trong {duration:.1f}s")
            ctx._sync_task_db()
        else:
            for s in task.stages:
                if s["name"] == stage.name:
                    s["status"] = StageState.FAILED
            print(f"\n[FAIL] Thất bại tại {stage.name} sau {duration:.1f}s")
            task.status = WorkflowState.FAILED
            task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            ctx._sync_task_db()
            return

    total_duration = time.time() - start_all
    task.status = WorkflowState.SUCCESS
    task.overall_progress = 100.0
    task.finished_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ctx._sync_task_db()

    print("\n" + "=" * 80)
    print(f"  WORKFLOW HOÀN THÀNH TOÀN DIỆN!")
    print(f"  Tổng thời gian xử lý: {total_duration / 60:.1f} phút")
    print(f"  Master video & Metadata đã sẵn sàng tại thư mục download của dự án.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
