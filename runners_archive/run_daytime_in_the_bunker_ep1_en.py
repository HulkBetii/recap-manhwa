import os
import sys
import asyncio
import json
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

os.chdir(r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version")
sys.path.insert(0, r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version")

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
    def is_cancelled(self): return False

class ConsoleContext:
    def __init__(self, task):
        self.task = task
        self.cancel_token = SimpleCancelToken()
        self.payload = task.payload
    async def log(self, message, level="info", *a, **kw):
        print(f"[{level.upper()}] {message}", flush=True)
        self.task.logs.append({"timestamp": time.strftime("%H:%M:%S"), "level": level, "message": message, "stage": self.task.current_stage, "episode": self.task.current_episode})
        self._sync_task_db()
    async def start_episode(self, ep): self.task.current_episode = ep; await self.log(f"Starting episode {ep}...", "info")
    async def complete_episode(self, ep): await self.log(f"Completed episode {ep}.", "success")
    async def fail_episode(self, ep, error): await self.log(f"Episode {ep} error: {error}", "error")
    async def update_stage_progress(self, stage_name, progress):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True); self._sync_task_db()
    async def update_progress(self, progress, stage_name=None, episode=None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True); self._sync_task_db()
    def _sync_task_db(self):
        try:
            db_path = "tasks_db.json"; tmp = db_path + ".tmp"
            if os.path.exists(db_path):
                with open(db_path, "r", encoding="utf-8") as f: db = json.load(f)
                db[self.task.id] = self.task.to_storage_dict()
                with open(tmp, "w", encoding="utf-8") as f: json.dump(db, f, ensure_ascii=False, indent=2)
                for _ in range(10):
                    try: os.replace(tmp, db_path); break
                    except: time.sleep(0.08)
        except: pass

async def main():
    target_url = "https://www.webtoons.com/en/drama/daytime-in-the-bunker/list?title_no=9842"
    print("=" * 75)
    print("  Daytime in the Bunker - Episode 1 (English)")
    print(f"  URL: {target_url}")
    print(f"  Voice: {config.DEFAULT_EN_VOICE}")
    print("=" * 75)
    task_id = f"daytime-in-the-bunker-ep1-en-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Daytime in the Bunker", comic_url=target_url,
        from_episode=1, to_episode=1,
        payload={
            "vlm_model": "3.8 Flash", "language": "en",
            "voice_id": config.DEFAULT_EN_VOICE_ID,
            "ref_audio_path": config.DEFAULT_EN_REF_AUDIO,
            "enable_flash_forward_intro": False, "cleanup": False,
            "safe_mode": False, "retry_count": 3, "timeout": 300,
            "concurrency": 4, "burn_subtitles": False, "remove_text": False,
        }, id=task_id
    )
    ctx = ConsoleContext(task)
    pipeline = [
        Stage0_ProjectInit(), Stage1_ComicParsing(), Stage2_AsyncImageCrawling(),
        Stage2b_IntelligentRepagination(), Stage3_NSFWModeration(), Stage4_PDFGeneration(),
        Stage5_GeminiAutomation(), Stage6_JSONExtraction(), Stage7_NarrationAggregation(),
        Stage8_LocalTTS(), Stage9_SubtitleNormalization(), Stage10_EpisodeVideoRendering(),
        Stage11_FinalVideoAssembly(), Stage12_MetadataReports(), Stage13_Cleanup(),
    ]
    for stage in pipeline:
        task.current_stage = stage.name
        print(f"\n>>> {stage.name}", flush=True)
        for s in task.stages:
            if s["name"] == stage.name: s["status"] = StageState.RUNNING; s["progress"] = 0.0
        ctx._sync_task_db()
        ok = await stage.execute(ctx)
        if not ok:
            print(f"[FATAL] {stage.name} failed.", flush=True)
            for s in task.stages:
                if s["name"] == stage.name: s["status"] = StageState.FAILED
            task.status = WorkflowState.FAILED; ctx._sync_task_db(); return 2
        for s in task.stages:
            if s["name"] == stage.name: s["status"] = StageState.SUCCESS; s["progress"] = 100.0
        ctx._sync_task_db()
        print(f"[DONE] {stage.name}", flush=True)
    task.status = WorkflowState.SUCCESS; task.current_stage = "Completed"; task.overall_progress = 100.0
    ctx._sync_task_db()
    print(f"\n[COMPLETED] Final: {task.artifacts.get('final_video_url')}")
    return 0

exit_code = asyncio.run(main())
sys.exit(exit_code)
