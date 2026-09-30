import os
import sys
import asyncio
import json
import time
import shutil

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

os.chdir(r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version")
sys.path.insert(0, r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version")

import config
from workflow_base import WorkflowTask, WorkflowState, StageState
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

def sync_1to1_recap(en_dir, vi_dir):
    """
    Ensure the Vietnamese recap.json and images match the English recap 1:1.
    """
    for ep in [1, 2]:
        en_ep_dir = os.path.join(en_dir, f"episode_{ep}")
        vi_ep_dir = os.path.join(vi_dir, f"episode_{ep}")
        os.makedirs(vi_ep_dir, exist_ok=True)
        
        # Copy images and images_pdf to ensure exact visual sync
        for sub in ["images", "images_pdf"]:
            src = os.path.join(en_ep_dir, sub)
            dst = os.path.join(vi_ep_dir, sub)
            if os.path.exists(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
        
        en_recap_path = os.path.join(en_ep_dir, "recap.json")
        vi_recap_path = os.path.join(vi_ep_dir, "recap.json")
        
        if not os.path.exists(en_recap_path):
            raise FileNotFoundError(f"English recap not found: {en_recap_path}")
            
        with open(en_recap_path, "r", encoding="utf-8") as f:
            en_scenes = json.load(f)
            
        # Check existing VI recap
        existing_vi_scenes = []
        if os.path.exists(vi_recap_path):
            with open(vi_recap_path, "r", encoding="utf-8") as f:
                try:
                    existing_vi_scenes = json.load(f)
                except Exception:
                    existing_vi_scenes = []
                    
        # Check if existing VI recap is already a 1:1 match in length
        if len(existing_vi_scenes) == len(en_scenes):
            # Update image references to be strictly identical to EN scenes
            merged_scenes = []
            for i, en_s in enumerate(en_scenes):
                vi_s = existing_vi_scenes[i]
                merged_scenes.append({
                    "speech": vi_s.get("speech", en_s.get("speech", "")),
                    "images": en_s.get("images", []),
                    "action_type": en_s.get("action_type", vi_s.get("action_type", "pan_zoom")),
                })
            with open(vi_recap_path, "w", encoding="utf-8") as f:
                json.dump(merged_scenes, f, ensure_ascii=False, indent=2)
            print(f"[1:1 SYNC] Episode {ep}: Synchronized {len(merged_scenes)} scenes from existing 1:1 Vietnamese translation.")
        else:
            print(f"[1:1 SYNC] Episode {ep}: Length mismatch (EN: {len(en_scenes)}, VI: {len(existing_vi_scenes)}).")
            # If length mismatch, write en_scenes structure
            with open(vi_recap_path, "w", encoding="utf-8") as f:
                json.dump(en_scenes, f, ensure_ascii=False, indent=2)

async def main():
    target_url = "https://www.webtoons.com/en/thriller/surviving-the-apocalypse/list?title_no=6678"
    print("=" * 80)
    print("  START WORKFLOW: Surviving the Apocalypse - Episodes 1-2 (1:1 Vietnamese)")
    print(f"  URL: {target_url}")
    print("  Mode: 1:1 Visual & Script Sync with Restored v1.8.0 Pipeline")
    print(f"  Voice TTS: OmniVoice ({config.DEFAULT_VI_VOICE})")
    print("  Pacing Guardrail: >= 3.5s per Hero Image")
    print("=" * 80)

    en_dir = os.path.join("downloads", "surviving_the_apocalypse_1_2_en_947dedf7")
    vi_dir = os.path.join("downloads", "surviving_the_apocalypse_1_2_vi_947dedf7")
    
    sync_1to1_recap(en_dir, vi_dir)

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
            "split_double_pages": True,
            "reading_direction": "ltr",
        },
        id=task_id
    )

    task.artifacts["download_dir"] = vi_dir
    task.artifacts["comic_title"] = "Surviving the Apocalypse"
    task.artifacts["chapter_slugs"] = ["episode-1", "episode-2"]

    ctx = ConsoleContext(task)

    pipeline = [
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
    print("  [SUCCESS] 100% RECAP COMPLETE: SURVIVING THE APOCALYPSE EPISODES 1-2 (1:1 VIETNAMESE)!")
    download_dir = task.artifacts.get("download_dir", "")
    print(f"  Output Directory: {download_dir}")
    final_vids = task.artifacts.get("final_videos", {})
    for ep_k, v_path in final_vids.items():
        print(f"  Episode {ep_k} Video: {v_path}")
    final_combined = task.artifacts.get("final_video_path", "")
    if final_combined:
        print(f"  Combined Full Video: {final_combined}")
    print("================================================================================")
    return 0

if __name__ == "__main__":
    ret = asyncio.run(main())
    sys.exit(ret)
