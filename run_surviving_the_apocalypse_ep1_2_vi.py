import os
import sys
import asyncio
import json
import time
import urllib.parse
import shutil

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
    target_url = "https://www.webtoons.com/en/thriller/surviving-the-apocalypse/list?title_no=6678"
    print("=" * 75)
    print("  START WORKFLOW: Surviving the Apocalypse - Tập 1-2 (Tiếng Việt)")
    print(f"  URL: {target_url}")
    print("  Model VLM: Google Gemini (Narration v2.0 - 5 Golden Rules + Few-shot)")
    print(f"  Voice TTS: OmniVoice ({config.DEFAULT_VI_VOICE})")
    print("  Pacing Guardrail: >= 3.5s per Hero Image")
    print("  Auto Clean-Crop: 4-Directional Adaptive Void Trimmer + Gutter Filtering")
    print("=" * 75)

    task_id = f"surviving-the-apocalypse-ep1-2-vi-{int(time.time())}"
    task = WorkflowTask(
        comic_title="Surviving the Apocalypse",
        comic_url=target_url,
        from_episode=1,
        to_episode=2,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "vi",
            "voice_id": config.DEFAULT_VI_VOICE_ID,
            "ref_audio_path": config.DEFAULT_VI_REF_AUDIO,
            "min_panel_duration": 3.5,
            "hard_floor_duration": 3.0,
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
    ctx._sync_task_db()
    print("\n================================================================================")
    print("  [SUCCESS] HOÀN TẤT 100% QUY TRÌNH RECAP SURVIVING THE APOCALYPSE TẬP 1-2 (TIẾNG VIỆT)!")
    download_dir = task.artifacts.get("download_dir", "")
    print(f"  Thư mục kết quả: {download_dir}")
    final_vids = task.artifacts.get("final_videos", {})
    for ep_k, v_path in final_vids.items():
        print(f"  Tập {ep_k} Video: {v_path}")
    print("================================================================================")
    return 0

if __name__ == "__main__":
    ret = asyncio.run(main())
    sys.exit(ret)
