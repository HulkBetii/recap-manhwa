# -*- coding: utf-8 -*-
"""
Regenerate Episode 1 using Stage 5 V5.3 (Retention & Protagonist Bootstrap)
"""
import os
import sys
import asyncio
import json
import time
import shutil

# Ensure UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from workflow_base import WorkflowTask, WorkflowState, StageState
from workflow_stages_1 import Stage5_GeminiAutomation, Stage6_JSONExtraction

class SimpleCancelToken:
    def is_cancelled(self): return False

class ConsoleContext:
    def __init__(self, task):
        self.task = task
        self.cancel_token = SimpleCancelToken()
        self.payload = task.payload

    async def log(self, message, level="info", *a, **kw):
        print(f"[{level.upper()}] {message}", flush=True)
        self.task.logs.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "stage": self.task.current_stage,
            "episode": self.task.current_episode
        })

    async def start_episode(self, ep: int):
        self.task.current_episode = ep
        await self.log(f"Bắt đầu xử lý tập {ep}...", "info")

    async def complete_episode(self, ep: int):
        await self.log(f"Hoàn thành tập {ep}.", "success")

    async def fail_episode(self, ep: int, error: str):
        await self.log(f"Lỗi tập {ep}: {error}", "error")

    async def update_stage_progress(self, stage_name: str, progress: float):
        print(f"[PROGRESS] {stage_name}: {progress:.1f}%", flush=True)

    async def update_progress(self, progress: float, stage_name: str = None, episode: int = None):
        print(f"[PROGRESS] {stage_name or self.task.current_stage}: {progress:.1f}%", flush=True)


async def main():
    target_dir = os.path.join(PROJECT_ROOT, "downloads", "좀비묵시록_8208_1_143_en_946016ec")
    ep1_dir = os.path.join(target_dir, "episode_1")
    
    # 1. Backup old files
    backup_dir = os.path.join(ep1_dir, "v5_2_backup")
    os.makedirs(backup_dir, exist_ok=True)
    for fname in ["raw_gemini_response.txt", "recap.json", "narration.txt", "artifact_manifest.json"]:
        src = os.path.join(ep1_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(backup_dir, fname))
            print(f"[BACKUP] Backed up {fname} to v5_2_backup/")
            # Remove from ep1_dir to force fresh Stage 5 generation
            os.remove(src)

    # 2. Setup Task
    task_id = f"zombie-revelation-ep1-v5-3-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Zombie Revelation: 82-08",
        comic_url="https://www.webtoons.com/en/action/zombie-revelation-82-08/list?title_no=6065",
        from_episode=1,
        to_episode=1,
        payload={
            "vlm_model": "ag/gemini-3.8-flash-medium",
            "language": "en",
            "market_id": "us_apocalypse",
            "voice_id": config.DEFAULT_EN_VOICE_ID,
            "ref_audio_path": config.DEFAULT_EN_REF_AUDIO,
            "enable_flash_forward_intro": False,
            "cleanup": False,
            "safe_mode": False,
            "retry_count": 3,
            "timeout": 300,
        },
        id=task_id
    )
    task.artifacts["download_dir"] = target_dir
    task.artifacts["comic_title"] = "Zombie Revelation: 82-08"

    ctx = ConsoleContext(task)

    # 3. Execute Stage 5
    print("\n" + "=" * 80)
    print("  EXECUTING STAGE 5: Gemini Automation with V5.3 Retention Patch")
    print("=" * 80)
    stage5 = Stage5_GeminiAutomation()
    task.current_stage = stage5.name
    ok5 = await stage5.execute(ctx)
    if not ok5:
        print("[ERROR] Stage 5 failed!")
        return 1

    # 4. Execute Stage 6
    print("\n" + "=" * 80)
    print("  EXECUTING STAGE 6: JSON Extraction & Normalization")
    print("=" * 80)
    stage6 = Stage6_JSONExtraction()
    task.current_stage = stage6.name
    ok6 = await stage6.execute(ctx)
    if not ok6:
        print("[ERROR] Stage 6 failed!")
        return 1

    # 5. Display New Narration & Segment Analysis
    recap_path = os.path.join(ep1_dir, "recap.json")
    if os.path.exists(recap_path):
        with open(recap_path, "r", encoding="utf-8") as f:
            recap = json.load(f)

        print("\n" + "=" * 80)
        print("  STAGE 5 V5.3 GENERATION COMPLETE — EPISODE 1 RECAP RESULTS")
        print("=" * 80)
        print(f"Total Segments Generated: {len(recap)}")
        print("\nFIRST 10 SEGMENTS:")
        for idx, seg in enumerate(recap[:10], start=1):
            pages = seg.get("pages", seg.get("page", "?"))
            speech = seg.get("speech", "")
            print(f"  [{idx:02d}] Pages {pages}: \"{speech}\"")

        # Check for protagonist name mentions
        has_tae = any("Tae" in seg.get("speech", "") for seg in recap)
        has_paran = any("Paran" in seg.get("speech", "") for seg in recap)
        first_tae_seg = next((i + 1 for i, s in enumerate(recap) if "Tae" in s.get("speech", "")), None)

        print("\n--- RETENTION AUDIT ---")
        print(f"Protagonist 'Tae' Present: {has_tae} (First appeared at Segment {first_tae_seg})")
        print(f"Placeholder 'Paran' Present: {has_paran}")
        if first_tae_seg and first_tae_seg <= 2:
            print(">>> SUCCESS: Protagonist established in Golden 0-15s Hook (Segment 1/2)! <<<")
        else:
            print(f">>> Protagonist first appearance at Segment {first_tae_seg} <<<")

    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
