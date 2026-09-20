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
    def is_cancelled(self): return False

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
    target_url = "https://www.webtoons.com/en/thriller/surviving-the-apocalypse/list?title_no=6678"
    from_ep = 1
    to_ep = 58
    total_eps = to_ep - from_ep + 1

    print("=" * 80)
    print("  START RECAP WORKFLOW: Surviving the Apocalypse (Full Series: Episodes 1 -> 58)")
    print(f"  Target URL: {target_url}")
    print(f"  Episodes: {from_ep} to {to_ep} (Total: {total_eps} episodes)")
    print("  Language: English (en)")
    print("  Market: US Apocalypse / Survival Thriller Recaps")
    print(f"  Voice TTS: OmniVoice English ({config.DEFAULT_EN_VOICE_ID})")
    print(f"  Ref Audio: {config.DEFAULT_EN_REF_AUDIO}")
    print("  VLM Automation: Google Gemini 3.8 Flash (Narration v2.0 - 5 Golden Rules)")
    print("  Video Rendering: OpenCV C++ NVENC / Fast-Scan (1080p 9:16)")
    print("=" * 80)

    # Check disk space
    total, used, free = shutil.disk_usage("D:/")
    free_gb = free // (1024 ** 3)
    print(f"[DISK] Drive D: Free Space: {free_gb} GB")
    if free_gb < 10:
        print("[WARNING] Low disk space on drive D: (< 10 GB).")

    task_id = f"surviving-the-apocalypse-full-1-58-en-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Surviving the Apocalypse",
        comic_url=target_url,
        from_episode=from_ep,
        to_episode=to_ep,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "en",
            "market_id": "us_apocalypse",
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

    for stage in pipeline:
        task.current_stage = stage.name
        print(f"\n=======================================================")
        print(f"  >>> STARTING STAGE: {stage.name}")
        print(f"=======================================================")

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.RUNNING
                s["progress"] = 0.0
        ctx._sync_task_db()

        start_time = time.time()
        ok = await stage.execute(ctx)
        elapsed = time.time() - start_time

        # Autonomous Self-Healing for Stage 5 missing episodes
        if stage.name == "Stage 5 - Gemini Automation" and not ok:
            download_dir = task.artifacts.get("download_dir", "")
            for heal_round in range(1, 4):
                missing_eps = [
                    e for e in range(from_ep, to_ep + 1)
                    if not (os.path.isfile(os.path.join(download_dir, f"episode_{e}", "recap.json")) and os.path.getsize(os.path.join(download_dir, f"episode_{e}", "recap.json")) > 10)
                ]
                if not missing_eps:
                    print(f"\n[SELF-HEAL] All {total_eps} episodes now have valid recap.json!", flush=True)
                    ok = True
                    break
                print(f"\n[SELF-HEAL] Round {heal_round}/3: Auto re-running missing {len(missing_eps)} episodes: {missing_eps}...", flush=True)
                for m_ep in missing_eps:
                    mini_task = WorkflowTask(
                        comic_title=task.comic_title,
                        comic_url=task.comic_url,
                        from_episode=m_ep,
                        to_episode=m_ep,
                        payload=dict(task.payload, retry_count=3, timeout=180),
                        id=f"heal-ep{m_ep}-{int(time.time())}"
                    )
                    mini_task.artifacts = dict(task.artifacts)
                    mini_ctx = ConsoleContext(mini_task)
                    mini_stage = Stage5_GeminiAutomation()
                    await mini_stage.execute(mini_ctx)

            missing_eps = [
                e for e in range(from_ep, to_ep + 1)
                if not (os.path.isfile(os.path.join(download_dir, f"episode_{e}", "recap.json")) and os.path.getsize(os.path.join(download_dir, f"episode_{e}", "recap.json")) > 10)
            ]
            if not missing_eps:
                ok = True

        if not ok:
            print(f"\n[FATAL] Stage {stage.name} failed after {elapsed:.1f}s. Aborting workflow.")
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
        print(f"[DONE] Stage {stage.name} completed 100% in {elapsed:.1f}s.")

    task.status = WorkflowState.SUCCESS
    ctx._sync_task_db()
    print("\n================================================================================")
    print(f"  [SUCCESS] 100% COMPLETED RECAP FOR SURVIVING THE APOCALYPSE (EP 1 -> 57, ENGLISH)!")
    download_dir = task.artifacts.get("download_dir", "")
    print(f"  Output Directory: {download_dir}")
    final_vids = task.artifacts.get("final_videos", {})
    for ep_k, v_path in final_vids.items():
        print(f"  Episode {ep_k} Video: {v_path}")
    print("================================================================================")
    return 0

if __name__ == "__main__":
    ret = asyncio.run(main())
    sys.exit(ret)
