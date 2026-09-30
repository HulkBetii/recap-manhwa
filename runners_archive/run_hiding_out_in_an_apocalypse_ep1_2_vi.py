import os
import sys
import asyncio
import json
import time
import shutil
from pathlib import Path

# Ensure UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Ensure working directory is project root
os.chdir(r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version")
sys.path.insert(0, r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version")

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
            if os.path.exists(db_path):
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
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
    target_url = "https://www.webtoons.com/en/action/hiding-out-in-an-apocalypse/list?title_no=6469"
    print("=" * 75)
    print("  START WORKFLOW: Hiding Out in an Apocalypse - Tập 1 & 2 (Tiếng Việt)")
    print("  URL: https://www.webtoons.com/en/action/hiding-out-in-an-apocalypse/list?title_no=6469")
    print("  Model VLM: Google Gemini 3.8 Flash (Vietnamese Prompt + Point Scoring)")
    print(f"  Voice TTS: OmniVoice ({config.DEFAULT_VI_VOICE})")
    print("  Engine: Recap Comics Automation Engine v1.8.0")
    print("=" * 75)

    task_id = f"hiding-out-in-an-apocalypse-ep1-2-vi-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Hiding Out in an Apocalypse",
        comic_url=target_url,
        from_episode=1,
        to_episode=2,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "vi",
            "voice_id": config.DEFAULT_VI_VOICE_ID,
            "ref_audio_path": config.DEFAULT_VI_REF_AUDIO,
            "enable_flash_forward_intro": False,
            "cleanup": False,
            "safe_mode": False,
            "retry_count": 5,
            "timeout": 360,
            "concurrency": 1,
            "burn_subtitles": False,
            "remove_text": False,
        },
        id=task_id
    )

    ctx = ConsoleContext(task)

    pipeline = [
        Stage0_ProjectInit(),
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
        print(f"  >>> BẮT ĐẦU: {stage.name}")
        print(f"=======================================================")

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.RUNNING
                s["progress"] = 0.0
        ctx._sync_task_db()

        ok = await stage.execute(ctx)
        if not ok:
            print(f"[FATAL] Giai đoạn {stage.name} thất bại. Dừng quy trình.")
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
        print(f"[DONE] Giai đoạn {stage.name} hoàn thành 100%.")

    task.status = WorkflowState.SUCCESS
    task.current_stage = "Completed"
    task.overall_progress = 100.0
    ctx._sync_task_db()

    final_video_url = task.artifacts.get("final_video_url")
    print("\n=======================================================")
    print("  CHÚC MỪNG: TẬP 1 VÀ 2 TIẾNG VIỆT ĐÃ HOÀN THÀNH XUẤT SẮC!")
    print(f"  Final Video URL: {final_video_url}")
    print(f"  Artifacts: {task.artifacts.get('download_dir')}")
    print("=======================================================")
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
