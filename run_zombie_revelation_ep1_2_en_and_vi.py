import os
import sys
import asyncio
import json
import time
import shutil
import traceback
from deep_translator import MyMemoryTranslator

# Ensure UTF-8 on Windows
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

def translate_gt(text: str) -> str:
    if not text or not text.strip():
        return ""
    import urllib.request, urllib.parse, json
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=vi&dt=t&q=" + urllib.parse.quote(text)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return "".join([part[0] for part in res[0] if part[0]])

def translate_and_sync_1to1(en_dir, vi_dir, from_ep=1, to_ep=2):
    """
    Ensure the Vietnamese recap.json and visual folders match the English recap 1:1.
    Translates all English narration sentences to natural Vietnamese.
    """
    for ep in range(from_ep, to_ep + 1):
        en_ep_dir = os.path.join(en_dir, f"episode_{ep}")
        vi_ep_dir = os.path.join(vi_dir, f"episode_{ep}")
        os.makedirs(vi_ep_dir, exist_ok=True)
        
        # Copy visual folders to guarantee exact 100% visual frame match if not already copied
        for sub in ["images", "images_pdf", "images_blur"]:
            src = os.path.join(en_ep_dir, sub)
            dst = os.path.join(vi_ep_dir, sub)
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copytree(src, dst)
        
        en_recap_path = os.path.join(en_ep_dir, "recap.json")
        vi_recap_path = os.path.join(vi_ep_dir, "recap.json")
        
        if not os.path.exists(en_recap_path):
            raise FileNotFoundError(f"English recap not found: {en_recap_path}")

        if os.path.exists(vi_recap_path) and os.path.getsize(vi_recap_path) > 100:
            print(f"[1:1 SYNC] Episode {ep}: Using existing Vietnamese recap at {vi_recap_path}", flush=True)
            continue

        with open(en_recap_path, "r", encoding="utf-8") as f:
            en_scenes = json.load(f)
            
        print(f"[1:1 SYNC] Translating Episode {ep} ({len(en_scenes)} scenes) to Vietnamese...", flush=True)
        merged_scenes = []
        for i, en_s in enumerate(en_scenes):
            en_speech = en_s.get("speech", "").strip()
            if not en_speech:
                vi_speech = ""
            else:
                vi_speech = None
                for _ in range(4):
                    try:
                        vi_speech = translate_gt(en_speech)
                        if vi_speech and vi_speech.strip():
                            break
                    except Exception as err:
                        time.sleep(0.5)
                if not vi_speech:
                    vi_speech = en_speech
            merged_scenes.append({
                "speech": vi_speech,
                "images": en_s.get("images", []),
                "action_type": en_s.get("action_type", "pan_zoom"),
            })
            time.sleep(0.08)
            
        with open(vi_recap_path, "w", encoding="utf-8") as f:
            json.dump(merged_scenes, f, ensure_ascii=False, indent=2)
        print(f"[1:1 SYNC] Episode {ep}: Successfully wrote {len(merged_scenes)} 1:1 translated scenes to {vi_recap_path}", flush=True)

async def run_pipeline(task, pipeline_stages, label=""):
    ctx = ConsoleContext(task)
    print(f"\n================================================================================")
    print(f"  >>> BẮT ĐẦU PIPELINE: {label}")
    print(f"================================================================================")
    
    for stage in pipeline_stages:
        task.current_stage = stage.name
        print(f"\n{'='*75}")
        print(f"  >>> GIAI ĐOẠN: {stage.name}")
        print(f"{'='*75}")

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.RUNNING
                s["progress"] = 0.0
        ctx._sync_task_db()

        start_t = time.time()
        ok = await stage.execute(ctx)
        elapsed = time.time() - start_t

        if not ok:
            print(f"\n[FATAL] Giai đoạn {stage.name} thất bại sau {elapsed:.1f}s. Dừng pipeline.")
            for s in task.stages:
                if s["name"] == stage.name:
                    s["status"] = StageState.FAILED
            task.status = WorkflowState.FAILED
            ctx._sync_task_db()
            return False

        for s in task.stages:
            if s["name"] == stage.name:
                s["status"] = StageState.SUCCESS
                s["progress"] = 100.0
        ctx._sync_task_db()
        print(f"[DONE] Giai đoạn {stage.name} hoàn thành 100% trong {elapsed:.1f}s.")

    task.status = WorkflowState.SUCCESS
    ctx._sync_task_db()
    return True

async def main():
    target_url = "https://comic.naver.com/webtoon/list?titleId=814742"
    comic_title = "Zombie Revelation 82-08"
    from_ep = 1
    to_ep = 2

    print("=" * 80)
    print("  WORKFLOW: ZOMBIE REVELATION 82-08 (EPISODES 1-2) — EN & 1:1 VIETNAMESE")
    print(f"  URL: {target_url}")
    print("  Market: US Apocalypse (Prompt v2.0 with Calibrated Pacing)")
    print(f"  Voice EN: OmniVoice Andrew ({config.DEFAULT_EN_VOICE_ID})")
    print(f"  Voice VI: OmniVoice Jessa ({config.DEFAULT_VI_VOICE_ID})")
    print("=" * 80)

    # Check if English production is already complete
    import glob
    existing_en_dirs = glob.glob(os.path.join(PROJECT_ROOT, "downloads", "*8208*_en_*"))
    en_dir = None
    if existing_en_dirs:
        for candidate in existing_en_dirs:
            out_files = glob.glob(os.path.join(candidate, "output", "*.mp4"))
            if out_files and os.path.getsize(out_files[0]) > 10_000_000:
                en_dir = candidate
                print(f"\n[SKIP] English production already 100% completed at: {en_dir}")
                break

    if not en_dir:
        # -------------------------------------------------------------
        # STEP 1: Run Full English Workflow
        # -------------------------------------------------------------
        en_task_id = f"zombie-revelation-ep1-2-en-{int(time.time())}"
        en_task = WorkflowTask(
            comic_title=comic_title,
            comic_url=target_url,
            from_episode=from_ep,
            to_episode=to_ep,
            payload={
                "vlm_model": "3.8 Flash",
                "language": "en",
                "market_id": "us_apocalypse",
                "market": "us_apocalypse",
                "ip_context": {
                    "protagonist_name": "Kang-Min",
                    "unique_hook": "the terrifying viral apocalypse triggered by doomed container vessel Zombie Revelation 82-08",
                    "setting": "Seoul, South Korea under military lockdown against feral mutant infected",
                },
                "voice_id": config.DEFAULT_EN_VOICE_ID,
                "ref_audio_path": config.DEFAULT_EN_REF_AUDIO,
                "min_panel_duration": 3.5,
                "hard_floor_duration": 3.0,
                "enable_flash_forward_intro": False,
                "cleanup": False,
                "safe_mode": False,
                "force_render": True,
                "retry_count": 5,
                "timeout": 360,
                "concurrency": 2,
                "burn_subtitles": False,
                "remove_text": False,
                "split_double_pages": True,
                "reading_direction": "ltr",
            },
            id=en_task_id
        )

        en_stages = [
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

        ok_en = await run_pipeline(en_task, en_stages, label="ENGLISH PRODUCTION (EPISODES 1-2)")
        if not ok_en:
            print("[FATAL] Quy trình Tiếng Anh thất bại.")
            return 1

        en_dir = en_task.artifacts.get("download_dir")
        print(f"\n[SUCCESS] Hoàn thành quy trình Tiếng Anh tại: {en_dir}")

    # -------------------------------------------------------------
    # STEP 2: 1:1 Translation & Vietnamese Video Generation
    # -------------------------------------------------------------
    # Compute Vietnamese download directory
    project_dir = os.path.dirname(os.path.abspath(__file__))
    en_folder_name = os.path.basename(en_dir)
    vi_folder_name = en_folder_name.replace("_en_", "_vi_")
    vi_dir = os.path.join(project_dir, "downloads", vi_folder_name)
    os.makedirs(vi_dir, exist_ok=True)

    # Perform 1:1 translation of scenes and image sync if not already done
    translate_and_sync_1to1(en_dir, vi_dir, from_ep, to_ep)

    # Ensure VI output directory
    vi_output_dir = os.path.join(vi_dir, "output")
    os.makedirs(vi_output_dir, exist_ok=True)

    vi_task_id = f"zombie-revelation-ep1-2-vi-{int(time.time())}"
    vi_task = WorkflowTask(
        comic_title=comic_title,
        comic_url=target_url,
        from_episode=from_ep,
        to_episode=to_ep,
        payload={
            "vlm_model": "3.8 Flash",
            "language": "vi",
            "market_id": "us_apocalypse",
            "market": "us_apocalypse",
            "voice_id": config.DEFAULT_VI_VOICE_ID,
            "ref_audio_path": config.DEFAULT_VI_REF_AUDIO,
            "min_panel_duration": 3.5,
            "hard_floor_duration": 3.0,
            "enable_flash_forward_intro": False,
            "cleanup": False,
            "safe_mode": False,
            "force_render": True,
            "retry_count": 5,
            "timeout": 360,
            "concurrency": 2,
            "burn_subtitles": False,
            "remove_text": False,
            "split_double_pages": True,
            "reading_direction": "ltr",
        },
        id=vi_task_id
    )

    vi_task.artifacts["download_dir"] = vi_dir
    vi_task.artifacts["download_folder_name"] = os.path.basename(vi_dir)
    vi_task.artifacts["comic_title"] = comic_title
    vi_task.artifacts["chapter_slugs"] = ["episode-1", "episode-2"]

    vi_stages = [
        Stage7_NarrationAggregation(),
        Stage8_LocalTTS(),
        Stage9_SubtitleNormalization(),
        Stage10_EpisodeVideoRendering(),
        Stage11_FinalVideoAssembly(),
        Stage12_MetadataReports(),
        Stage13_Cleanup(),
    ]

    ok_vi = await run_pipeline(vi_task, vi_stages, label="VIETNAMESE 1:1 PRODUCTION (EPISODES 1-2)")
    if not ok_vi:
        print("[FATAL] Quy trình Tiếng Việt thất bại.")
        return 2

    print("\n================================================================================")
    print("  [SUCCESS] 100% RECAP COMPLETE FOR BOTH EN & 1:1 VI (ZOMBIE REVELATION 82-08)!")
    print(f"  EN Output: {en_dir}/output")
    print(f"  VI Output: {vi_dir}/output")
    print("================================================================================")
    return 0

if __name__ == "__main__":
    try:
        ret = asyncio.run(main())
        sys.exit(ret)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
