# -*- coding: utf-8 -*-
"""
E2E Runner for The Warrior's Ballad (Episodes 1-2) in English
URL: https://www.webtoons.com/en/action/the-warriors-ballad/list?title_no=11210
"""

import os
import sys
import asyncio
import json
import time

# Ensure UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_1 import (
    Stage0_ProjectInit, Stage1_ComicParsing, Stage2_AsyncImageCrawling,
    Stage2b_IntelligentRepagination, Stage3_NSFWModeration, Stage4_PDFGeneration,
    Stage5_GeminiAutomation, Stage6_JSONExtraction,
)
from workflow_stages_2 import (
    Stage7_NarrationAggregation, Stage8_LocalTTS, Stage9_SubtitleNormalization,
    Stage10_EpisodeVideoRendering, Stage11_FinalVideoAssembly,
    Stage12_MetadataReports, Stage13_Cleanup,
)


class SimpleCancelToken:
    def is_cancelled(self):
        return False


class ConsoleContext:
    def __init__(self, task):
        self.task = task
        self.cancel_token = SimpleCancelToken()
        self.payload = task.payload
        self.manager = None

    def get_cancel_token(self, task_id=None):
        return self.cancel_token

    async def log(self, message, level="info", *a, **kw):
        ep_info = f" [Ep {kw.get('episode')}]" if kw.get('episode') else ""
        print(f"[{level.upper()}]{ep_info} {message}", flush=True)
        self.task.logs.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "stage": self.task.current_stage,
            "episode": self.task.current_episode or kw.get('episode')
        })
        self._sync_task_db()

    async def start_episode(self, ep: int):
        self.task.current_episode = ep
        await self.log(f"Bắt đầu xử lý tập {ep}...", "info", episode=ep)

    async def complete_episode(self, ep: int):
        await self.log(f"Hoàn thành tập {ep}.", "success", episode=ep)

    async def fail_episode(self, ep: int, error: str):
        await self.log(f"Lỗi tập {ep}: {error}", "error", episode=ep)

    async def update_stage_progress(self, stage_name: str, progress: float):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True)
        self._sync_task_db()

    async def update_progress(self, progress: float, stage_name: str = None, episode: int = None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True)
        self._sync_task_db()

    def _sync_task_db(self):
        try:
            db_path = "tasks_db.json"
            tmp_path = "tasks_db.json.tmp"
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
                except Exception:
                    time.sleep(0.08)
        except Exception:
            pass


async def main():
    target_url = "https://www.webtoons.com/en/action/the-warriors-ballad/list?title_no=11210"
    from_ep = 1
    to_ep = 2

    print("=" * 80)
    print("  E2E TEST: The Warrior's Ballad (Episodes 1 - 2)")
    print(f"  Target URL: {target_url}")
    print(f"  Voice: {config.DEFAULT_EN_VOICE} ({config.DEFAULT_EN_VOICE_ID})")
    print("=" * 80)

    task_id = f"the-warriors-ballad-ep1-2-en-{int(time.time())}"
    task = WorkflowTask(
        comic_title="The Warrior's Ballad",
        comic_url=target_url,
        from_episode=from_ep,
        to_episode=to_ep,
        payload={
            "vlm_model": "3.8 Flash",
            "ninerouter_model": "ag/gemini-3.8-flash-medium",
            "language": "en",
            "market_id": "us_apocalypse",
            "voice_id": config.DEFAULT_EN_VOICE_ID,
            "ref_audio_path": config.DEFAULT_EN_REF_AUDIO,
            "enable_flash_forward_intro": False,
            "cleanup": False,
            "safe_mode": False,
            "retry_count": 3,
            "timeout": 300,
            "concurrency": 2,
            "burn_subtitles": False,
            "remove_text": False,
        },
        id=task_id,
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

    total_start = time.time()
    for stage in pipeline:
        task.current_stage = stage.name
        print(f"\n{'='*30} >>> {stage.name} {'='*30}", flush=True)
        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.RUNNING
                s["progress"] = 0.0
        ctx._sync_task_db()

        stage_start = time.time()
        ok = await stage.execute(ctx)
        stage_dur = time.time() - stage_start

        if not ok:
            print(f"\n[FATAL] {stage.name} failed after {stage_dur:.1f}s.", flush=True)
            for s in task.stages:
                if s["name"] == stage.name:
                    s["status"] = StageState.FAILED
            task.status = WorkflowState.FAILED
            ctx._sync_task_db()
            return 1

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.SUCCESS
                s["progress"] = 100.0
        ctx._sync_task_db()
        print(f"[DONE] {stage.name} in {stage_dur:.1f}s", flush=True)

    total_dur = time.time() - total_start
    task.status = WorkflowState.SUCCESS
    ctx._sync_task_db()
    print("\n" + "=" * 80)
    print(f"  [SUCCESS] Full E2E Pipeline Completed in {total_dur:.1f}s ({total_dur/60:.2f} mins)!")
    print(f"  Output Directory: {task.artifacts.get('download_dir')}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    ret = asyncio.run(main())
    sys.exit(ret)
