"""
rerun_ep79_patch.py — Re-run Stage 8/9/10/11 for Episode 79 only, then re-assemble master video.
Tất cả stages khác sẽ cache-skip. Stage 11 sẽ rebuild toàn bộ master video từ 143 episode.mp4.
"""
import sys, io, asyncio, os, time, json
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_1 import (
    Stage0_ProjectInit, Stage1_ComicParsing,
    Stage2_AsyncImageCrawling, Stage2b_IntelligentRepagination,
    Stage3_NSFWModeration, Stage4_PDFGeneration, Stage5_GeminiAutomation,
    Stage6_JSONExtraction,
)
from workflow_stages_2 import (
    Stage7_NarrationAggregation, Stage8_LocalTTS,
    Stage9_SubtitleNormalization, Stage10_EpisodeVideoRendering,
    Stage11_FinalVideoAssembly, Stage12_MetadataReports, Stage13_Cleanup,
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
    from_ep = 79
    to_ep = 79

    print("=" * 70)
    print(f"  PATCH RE-RUN: Zombie Revelation 82-08 — Episode 79 only")
    print(f"  Purpose: Fix duplicate cliffhanger, re-gen TTS+Subtitle+Video")
    print("=" * 70)

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
            "concurrency": 1,
            "voice_id": "clone_andrew",
            "burn_subtitles": False,
            "remove_text": False,
        },
        id="zombie_revelation_1_143_en"   # same ID as original so it finds same download_dir
    )

    ctx = ConsoleContext(task)

    # Stages 8/9/10 only for ep 79 — stages 0-7 will cache-skip, 11+12 skipped here
    pipeline_ep79 = [
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
    ]

    for stage in pipeline_ep79:
        task.current_stage = stage.name
        t0 = time.time()
        print(f"\n[STAGE] {stage.name}")
        ok = await stage.execute(ctx)
        elapsed = time.time() - t0
        if ok:
            print(f"  ✓ Done in {elapsed:.1f}s")
        else:
            print(f"  ✗ FAILED after {elapsed:.1f}s — stopping.")
            sys.exit(1)

    print("\n" + "=" * 70)
    print("  Ep 79 TTS + Subtitle + Video: DONE")
    print("  Next: Re-assembling master video (all 143 episodes)...")
    print("=" * 70 + "\n")

    # ── Stage 11+12: reuse same task object (artifacts already populated by Stage 0) ──
    task.from_episode = 1
    task.to_episode = 143
    ctx_full = ConsoleContext(task)

    # Ensure download_dir is set
    dl_dir = task.artifacts.get("download_dir")
    print(f"[INFO] download_dir = {dl_dir}")
    if not dl_dir:
        proj = [d for d in os.listdir('downloads') if '8208' in d][0]
        dl_dir = os.path.join(os.getcwd(), 'downloads', proj)
        task.artifacts["download_dir"] = dl_dir
        task.artifacts["download_folder_name"] = proj
        print(f"[INFO] download_dir set manually: {dl_dir}")

    out_dir = os.path.join(dl_dir, 'output')

    # Delete old master video + SRT to force re-assembly
    if os.path.exists(out_dir):
        for fname in os.listdir(out_dir):
            if fname.endswith('.mp4') or (fname.endswith('.srt') and 'episode' not in fname):
                fp = os.path.join(out_dir, fname)
                os.remove(fp)
                print(f"[DEL] output/{fname}")

    for stage in [Stage11_FinalVideoAssembly(), Stage12_MetadataReports()]:
        task.current_stage = stage.name
        t0 = time.time()
        print(f"\n[STAGE] {stage.name}")
        ok = await stage.execute(ctx_full)
        elapsed = time.time() - t0
        if ok:
            print(f"  ✓ Done in {elapsed:.1f}s")
        else:
            print(f"  ✗ FAILED — check logs.")
            sys.exit(1)

    print("\n" + "=" * 70)
    print("  ✅ PATCH COMPLETE — Master Video rebuilt with fixed Ep 79!")
    print("=" * 70)

if __name__ == '__main__':
    asyncio.run(main())
