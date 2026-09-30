import os
import sys
import asyncio
import json
import time
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
)

class SimpleCancelToken:
    def is_cancelled(self) -> bool:
        return False

class FullBatchConsoleContext:
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
        print(f"[INFO] Bat dau xu ly tap {ep}/41...", flush=True)

    async def complete_episode(self, ep: int):
        print(f"[SUCCESS] Hoan thanh tap {ep}/41.", flush=True)

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
            if os.path.exists(db_path):
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
                db[self.task.id] = self.task.to_storage_dict()
                with open(db_path, "w", encoding="utf-8") as f:
                    json.dump(db, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

async def main():
    target_url = "https://comic.naver.com/webtoon/list?titleId=836848"
    total_eps = 41
    print(f"[START] Bat dau quy trinh full recap cho {total_eps} tap (Tap 1 den Tap {total_eps}) cua '44교시 생존수업'...")

    task = WorkflowTask(
        comic_title="44교시 생존수업",
        comic_url=target_url,
        from_episode=1,
        to_episode=total_eps,
        payload={
            "market_id": "korea_apocalypse",
            "language": "ko",
            "safe_mode": False,
            "retry_count": 3,
            "timeout": 300,
            "concurrency": 4,
            "voice_id": "edge-tts_ko-KR-InJoonNeural",
            "burn_subtitles": False,
            "remove_text": False,
        },
        id="naver-44class-full-41ep"
    )

    ctx = FullBatchConsoleContext(task)

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
    ]

    for stage in pipeline:
        task.current_stage = stage.name
        print(f"\n=======================================================")
        print(f"  >>> BAT DAU: {stage.name}")
        print(f"=======================================================")

        if stage.name == "Stage 2 - Image Crawling":
            prev_ep1 = os.path.join("downloads", "44교시_생존수업_1_1_ko_0aee11a8", "episode_1")
            target_ep1 = os.path.join(task.artifacts["download_dir"], "episode_1")
            if os.path.exists(prev_ep1):
                import shutil
                print("[CACHE] Phat hien tap 1 da xu ly hoan chinh truoc do. Dang sao chep cache sang du an full...")
                for item in os.listdir(prev_ep1):
                    src_item = os.path.join(prev_ep1, item)
                    dst_item = os.path.join(target_ep1, item)
                    if not os.path.exists(dst_item):
                        if os.path.isdir(src_item):
                            shutil.copytree(src_item, dst_item)
                        else:
                            shutil.copy2(src_item, dst_item)

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

    print("\n=======================================================")
    print("  CHUC MUNG: TOAN BO 41 TAP DA DUOC RECAP VA RENDER XONG!")
    print("=======================================================")
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
