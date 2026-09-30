"""
fix_and_rebuild_full.py — Re-run Stage 8/9/10 for Ep 79 in the official 1_143 folder, then assemble master video.
"""
import sys, io, asyncio, os, time, json, shutil
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_2 import (
    Stage7_NarrationAggregation, Stage8_LocalTTS,
    Stage9_SubtitleNormalization, Stage10_EpisodeVideoRendering,
    Stage11_FinalVideoAssembly, Stage12_MetadataReports,
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
            "level": level, "message": message,
            "stage": self.task.current_stage, "episode": self.task.current_episode
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
            db_path = "tasks_db.json"; tmp = db_path + ".tmp"; db = {}
            if os.path.exists(db_path):
                with open(db_path, "r", encoding="utf-8") as f: db = json.load(f)
            db[self.task.id] = self.task.to_storage_dict()
            with open(tmp, "w", encoding="utf-8") as f: json.dump(db, f, ensure_ascii=False, indent=2)
            for _ in range(10):
                try: os.replace(tmp, db_path); break
                except Exception: time.sleep(0.08)
        except Exception: pass

async def main():
    target_url = "https://comic.naver.com/webtoon/list?titleId=814742"
    proj_name = [d for d in os.listdir('downloads') if '1_143' in d][0]
    dl_dir = os.path.join(PROJECT_ROOT, 'downloads', proj_name)

    print("=" * 75)
    print("  FIX & REBUILD MASTER VIDEO — Zombie Revelation 82-08 (1-143)")
    print(f"  Target directory: {dl_dir}")
    print("=" * 75)

    # 1. Clean up temporary _79_79 folder if it exists
    temp_79_dirs = [d for d in os.listdir('downloads') if '79_79' in d]
    for d in temp_79_dirs:
        try:
            shutil.rmtree(os.path.join(PROJECT_ROOT, 'downloads', d))
            print(f"[CLEANUP] Removed temporary folder: {d}")
        except Exception as e:
            print(f"[WARN] Could not remove {d}: {e}")

    # 2. Setup task for Episode 79
    task = WorkflowTask(
        comic_title="좀비묵시록 82-08",
        comic_url=target_url,
        from_episode=79,
        to_episode=79,
        payload={
            "market_id": "us_apocalypse",
            "language": "en",
            "safe_mode": False,
            "retry_count": 3,
            "timeout": 300,
            "concurrency": 1,
            "voice_id": "clone_andrew",
            "burn_subtitles": False,
            "remove_text": False,
        },
        id="zombie_revelation_1_143_en"
    )
    task.artifacts["download_dir"] = dl_dir
    task.artifacts["download_folder_name"] = proj_name

    ctx = ConsoleContext(task)

    # Step A: Stage 7, 8, 9, 10 on Ep 79
    ep79_stages = [
        Stage7_NarrationAggregation(),
        Stage8_LocalTTS(),
        Stage9_SubtitleNormalization(),
        Stage10_EpisodeVideoRendering(),
    ]

    for stage in ep79_stages:
        task.current_stage = stage.name
        t0 = time.time()
        print(f"\n[STAGE] {stage.name}")
        ok = await stage.execute(ctx)
        elapsed = time.time() - t0
        if ok:
            print(f"  ✓ Done in {elapsed:.1f}s")
        else:
            print(f"  ✗ FAILED {stage.name} after {elapsed:.1f}s — stopping.")
            sys.exit(1)

    print("\n" + "=" * 75)
    print("  ✅ Episode 79: TTS + Subtitle + Video Render SUCCESSFUL!")
    print("  Now assembling Master Video for all 143 episodes...")
    print("=" * 75 + "\n")

    # Step B: Reset episode range for Stage 11 & Stage 12
    task.from_episode = 1
    task.to_episode = 143

    out_dir = os.path.join(dl_dir, 'output')
    os.makedirs(out_dir, exist_ok=True)

    # Delete previous concatenated master video / srt so Stage 11 re-assembles cleanly
    for fname in os.listdir(out_dir):
        if (fname.endswith('.mp4') or fname.endswith('.srt')) and not fname.startswith('episode_'):
            fp = os.path.join(out_dir, fname)
            try:
                os.remove(fp)
                print(f"[DEL OLD MASTER] {fname}")
            except Exception as e:
                print(f"[WARN] Could not remove {fname}: {e}")

    for stage in [Stage11_FinalVideoAssembly(), Stage12_MetadataReports()]:
        task.current_stage = stage.name
        t0 = time.time()
        print(f"\n[STAGE] {stage.name}")
        ok = await stage.execute(ctx)
        elapsed = time.time() - t0
        if ok:
            print(f"  ✓ Done in {elapsed:.1f}s")
        else:
            print(f"  ✗ FAILED {stage.name} after {elapsed:.1f}s — stopping.")
            sys.exit(1)

    print("\n" + "=" * 75)
    print("  🎉 COMPLETE: Master Video rebuilt cleanly with updated Ep 79!")
    print("=" * 75)

if __name__ == '__main__':
    asyncio.run(main())
