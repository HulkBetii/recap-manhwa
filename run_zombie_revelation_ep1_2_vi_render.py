import os
import sys
import asyncio
import json
import time
import shutil
import traceback

# Ensure UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from workflow_base import WorkflowTask, WorkflowState, StageState
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
    download_dir = os.path.join(PROJECT_ROOT, "downloads", "좀비묵시록_8208_1_2_vi")
    os.makedirs(download_dir, exist_ok=True)
    
    task_id = f"zombie-revelation-ep1-2-vi-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Zombie Revelation 82-08 (Tiếng Việt)",
        comic_url="https://comic.naver.com/webtoon/list?titleId=814742",
        from_episode=1,
        to_episode=2,
        id=task_id,
        payload={
            "language": "vi",
            "market_id": "us_apocalypse",
            "voice_id": config.DEFAULT_VI_VOICE_ID,
            "ref_audio_path": config.DEFAULT_VI_REF_AUDIO,
            "voice_rate": config.DEFAULT_VI_VOICE_RATE,
            "voice_pitch": config.DEFAULT_VI_VOICE_PITCH,
            "min_panel_duration": 3.0,
            "hard_floor_duration": 2.5,
            "enable_nvenc": True,
            "reading_direction": "ltr",
        }
    )
    task.artifacts["download_dir"] = download_dir
    task.artifacts["download_folder_name"] = "좀비묵시록_8208_1_2_vi"
    
    stages = [
        Stage7_NarrationAggregation(),
        Stage8_LocalTTS(),
        Stage9_SubtitleNormalization(),
        Stage10_EpisodeVideoRendering(),
        Stage11_FinalVideoAssembly(),
        Stage12_MetadataReports(),
        Stage13_Cleanup(),
    ]
    
    ctx = ConsoleContext(task)
    print("=" * 80)
    print("  BẮT ĐẦU CHẠY TTS TIẾNG VIỆT & RENDER VIDEO TẬP 1-2 (1080p NVENC)")
    print(f"  Target Dir: {download_dir}")
    print(f"  Voice ID: {task.payload.get('voice_id')} | Ref Audio: {task.payload.get('ref_audio_path')}")
    print("=" * 80)

    start_total = time.time()
    for stage in stages:
        task.current_stage = stage.name
        print(f"\n>>> [GIAI ĐOẠN] {stage.name}...")
        stage_start = time.time()
        
        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.RUNNING
                s["progress"] = 0.0
        ctx._sync_task_db()
        
        ok = await stage.execute(ctx)
        stage_elapsed = time.time() - stage_start
        
        if not ok:
            print(f"\n[ERROR] Giai đoạn {stage.name} thất bại sau {stage_elapsed:.1f}s.")
            for s in task.stages:
                if s["name"] == stage.name:
                    s["status"] = StageState.FAILED
            task.status = WorkflowState.FAILED
            ctx._sync_task_db()
            return
            
        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.SUCCESS
                s["progress"] = 100.0
        ctx._sync_task_db()
        print(f"[DONE] {stage.name} hoàn thành thành công trong {stage_elapsed:.1f}s.")

    task.status = WorkflowState.SUCCESS
    ctx._sync_task_db()
    total_elapsed = time.time() - start_total
    print("\n" + "=" * 80)
    print(f"  TẤT CẢ ĐÃ HOÀN TẤT TRONG {total_elapsed:.1f}s ({total_elapsed/60:.2f} phút)!")
    print(f"  Thành phẩm tại: {download_dir}")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
