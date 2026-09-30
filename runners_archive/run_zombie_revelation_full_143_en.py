import os
import sys
import asyncio
import json
import time
import urllib.parse
import shutil

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

    async def log(self, message, level="info", *a, **kw):
        ep_prefix = f"[Ep {self.task.current_episode}] " if self.task.current_episode else ""
        print(f"[{level.upper()}] {ep_prefix}{message}", flush=True)
        self.task.logs.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "stage": self.task.current_stage,
            "episode": self.task.current_episode
        })
        self._sync_task_db()

    async def start_episode(self, ep):
        self.task.current_episode = ep
        await self.log(f"Starting episode {ep}...", "info")

    async def complete_episode(self, ep):
        await self.log(f"Completed episode {ep}.", "success")

    async def fail_episode(self, ep, error):
        await self.log(f"Episode {ep} error: {error}", "error")

    async def update_stage_progress(self, stage_name, progress):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True)
        self._sync_task_db()

    async def update_progress(self, progress, stage_name=None, episode=None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True)
        self._sync_task_db()

    def _sync_task_db(self):
        try:
            db_path = "tasks_db.json"
            tmp = db_path + ".tmp"
            db = {}
            if os.path.exists(db_path):
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
            db[self.task.id] = self.task.to_storage_dict()
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            for _ in range(10):
                try:
                    os.replace(tmp, db_path)
                    break
                except Exception:
                    time.sleep(0.08)
        except Exception:
            pass

async def main():
    target_url = "https://comic.naver.com/webtoon/list?titleId=814742"
    from_ep = 1
    to_ep = 143
    total_eps = to_ep - from_ep + 1

    print("=" * 80)
    print(f"  START FULL RECAP WORKFLOW: Zombie Revelation 82-08 (Episodes {from_ep} -> {to_ep})")
    print(f"  Target URL: {target_url}")
    print(f"  Episodes: {from_ep} to {to_ep} (Total: {total_eps} episodes)")
    print("  Language: English (en)")
    print("  Market: US Apocalypse / Survival Thriller Recaps")
    print("  Voice: OmniVoice Andrew (clone_andrew)")
    print("  Rules: NO BGM / NO SFX | remove_text: False | Safe-Zone Subtitles 1080p")
    print("=" * 80)

    task = WorkflowTask(
        comic_title="좀비묵시록 82-08",
        comic_url=target_url,
        from_episode=from_ep,
        to_episode=to_ep,
        payload={
            "market_id": "us_apocalypse",
            "language": "en",
            "safe_mode": False,
            "retry_count": 3,
            "timeout": 300,
            "concurrency": 4,
            "voice_id": "clone_andrew",
            "burn_subtitles": False,
            "remove_text": False,
        },
        id=f"zombie_revelation_{from_ep}_{to_ep}_en"
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
    ]

    for stage in pipeline:
        task.current_stage = stage.name
        print(f"\n{'='*70}")
        print(f"  >>> BAT DAU GIAI DOAN: {stage.name}")
        print(f"{'='*70}")

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.RUNNING
                s["progress"] = 0.0
        ctx._sync_task_db()

        if stage.name == "Stage 5 - Gemini Automation":
            # Auto-healing loop: keep retrying missing episodes until all 143 episodes have valid recap.json
            max_stage5_rounds = 10
            success = False
            for round_idx in range(1, max_stage5_rounds + 1):
                print(f"\n[AUTO-HEAL] Stage 5 - Gemini Automation: Round {round_idx}/{max_stage5_rounds}...")
                success = await stage.execute(ctx)
                if success:
                    print(f"[AUTO-HEAL] Stage 5 hoan thanh 100% toan bo 143 tap sau Round {round_idx}!")
                    break
                print(f"[AUTO-HEAL] Round {round_idx} chua du 143 tap. Tu dong nghi 5s va quet tiep cac tap con thieu...")
                await asyncio.sleep(5)
        else:
            success = await stage.execute(ctx)

        if not success:
            print(f"\n[FATAL] Giai doan {stage.name} that bai! Dung chuong trinh.")
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
        print(f"[SUCCESS] Giai doan {stage.name} hoan thanh 100%.")

    task.status = WorkflowState.SUCCESS
    task.current_stage = "Completed"
    task.overall_progress = 100.0
    ctx._sync_task_db()

    print("\n" + "=" * 80)
    print("  HOAN TAT TOAN BO QUY TRINH RECAP FULL TRUYEN ZOMBIE REVELATION 82-08 (1-143)!")
    print(f"  Master Video: {task.artifacts.get('final_video_url')}")
    print(f"  Master Subtitle: {task.artifacts.get('final_subtitle_url')}")
    print("=" * 80)
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
