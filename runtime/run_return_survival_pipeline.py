"""Master pipeline runner for Return Survival Part 1 (Episodes 1 - 30, Spanish/LATAM).
Fully clean slate rebuild with latest prompt, TTS JorgeNeural, Shorts Funnel & Content QA Auditor.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time

PROJECT_DIR = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
FOLDER_NAME = "return_survival_new_1_33_es_9b1e12cd"

sys.stdout.reconfigure(encoding="utf-8")
os.chdir(PROJECT_DIR)
sys.path.insert(0, PROJECT_DIR)

from workflow_base import WorkflowTask, StageState
from workflow import EventBus, WorkflowManager, WorkflowState
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


class ConsoleLogger:
    def __init__(self, task):
        self.task = task
        self.cancel_token = None

    async def log(self, message, level="info", *args, **kwargs):
        ep_prefix = f"[Ep {kwargs.get('episode')}] " if kwargs.get("episode") else ""
        print(f"[{time.strftime('%H:%M:%S')}] [{level.upper()}] {ep_prefix}{message}", flush=True)

    async def start_episode(self, ep):
        print(f"[{time.strftime('%H:%M:%S')}] [START_EP] Episode {ep} started", flush=True)

    async def complete_episode(self, ep):
        print(f"[{time.strftime('%H:%M:%S')}] [COMPLETE_EP] Episode {ep} finished", flush=True)

    async def fail_episode(self, ep, error):
        print(f"[{time.strftime('%H:%M:%S')}] [FAIL_EP] Episode {ep} error: {error}", flush=True)

    async def update_stage_progress(self, stage_name, progress):
        pass

    async def update_progress(self, progress, stage_name=None, episode=None):
        pass


class ContextWrapper:
    def __init__(self, task):
        self.task = task
        self.cancel_token = type("CancelToken", (), {"is_cancelled": lambda self: False})()
        self.payload = task.payload
        self.config = {}
        self.manager = None
        self._logger = ConsoleLogger(task)

    async def log(self, message, level="info", *args, **kwargs):
        await self._logger.log(message, level, *args, **kwargs)

    async def start_episode(self, ep):
        await self._logger.start_episode(ep)

    async def complete_episode(self, ep):
        await self._logger.complete_episode(ep)

    async def fail_episode(self, ep, error):
        await self._logger.fail_episode(ep, error)

    async def update_stage_progress(self, stage_name, progress):
        await self._logger.update_stage_progress(stage_name, progress)

    async def update_progress(self, progress, stage_name=None, episode=None):
        await self._logger.update_progress(progress, stage_name, episode)


def clean_all_generated_data(download_dir: str):
    """Xóa toàn bộ các artifact và cache đã tạo của 33 tập (kịch bản, audio, srt, video, pdf, v.v.).
    Giữ nguyên images/ (ảnh gốc) và images_pdf/ (bản cắt khung truyện 16:9) để tránh rủi ro mạng.
    """
    print("=" * 60, flush=True)
    print("🧹 [CLEANUP] BẮT ĐẦU XÓA SẠCH TOÀN BỘ DỮ LIỆU ĐÃ TẠO (33 TẬP)...", flush=True)

    artifacts_to_remove = [
        "recap.json",
        "raw_gemini_response.txt",
        "narration.txt",
        "audio.mp3",
        "tts_config.json",
        "transcript.srt",
        "transcript_no_intro.srt",
        "video.mp4",
        "video_no_intro.mp4",
        "intro_state.json",
        "artifact_manifest.json",
    ]

    cleaned_eps = 0
    for ep in range(1, 34):
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        if not os.path.exists(ep_dir):
            continue
        for fname in artifacts_to_remove:
            p = os.path.join(ep_dir, fname)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception as e:
                    print(f"  [Warn] Không thể xóa {p}: {e}", flush=True)
        # Xóa thư mục pdf trong episode để Stage 4 biên dịch lại sạch sẽ
        pdf_dir = os.path.join(ep_dir, "pdf")
        if os.path.exists(pdf_dir):
            shutil.rmtree(pdf_dir, ignore_errors=True)
        cleaned_eps += 1

    print(f"✔ Đã xóa dữ liệu generated của {cleaned_eps} tập (kịch bản, audio, srt, video, pdf, cache).", flush=True)

    # Xóa các thư mục tổng hợp ở root của project
    for folder_to_wipe in ["output", "intro_pitch", "outro"]:
        p = os.path.join(download_dir, folder_to_wipe)
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)
            print(f"✔ Đã xóa thư mục: {folder_to_wipe}", flush=True)

    print("✔ ĐÃ HOÀN TẤT DỌN DẸP SẠCH SẼ! BẮT ĐẦU TÁI SINH DỰ ÁN VỚI CODE MỚI NHẤT.", flush=True)
    print("=" * 60, flush=True)


async def run_pipeline(force_clean: bool = False):
    download_dir = os.path.join(PROJECT_DIR, "downloads", FOLDER_NAME)
    
    # Bước 1: Dọn sạch data cũ nếu có flag force_clean
    if force_clean:
        clean_all_generated_data(download_dir)
    else:
        print("⚡ [RESUME] Giữ nguyên các tập đã render thành công, tiếp tục quy trình...", flush=True)

    payload = {
        "comic_title": "Return Survival - New",
        "comic_url": "https://manhwatop.com/manga/return-survival-series/",
        "from_episode": 1,
        "to_episode": 33,
        "language": "es",
        "voice_id": "es-MX-JorgeNeural",
        "vlm_provider": "gemini",
        "burn_subtitles": False,
        "enable_flash_forward_intro": True,
        "enable_premise_pitch": True,
        "enable_outro": True,
        "crop_speech_bubbles": True,
        "safe_mode": False,
        "protagonist_name": "Seongho Kang",
        "streaming_pipeline": True,
        "image_quality": 20,
        "pdf_quality": 20,
        "retry_count": 3,
        "concurrency": 4,
    }

    task = WorkflowTask(
        comic_title=payload["comic_title"],
        comic_url=payload["comic_url"],
        from_episode=1,
        to_episode=33,
        payload=payload,
        id=f"return-survival-1-33-es-{int(time.time())}",
    )
    task.artifacts["download_dir"] = download_dir
    task.artifacts["download_folder_name"] = FOLDER_NAME
    task.artifacts["comic_title"] = payload["comic_title"]

    ctx = ContextWrapper(task)

    stages_pipeline = [
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
    ]

    total_start = time.time()
    print("=" * 60, flush=True)
    print("🚀 BẮT ĐẦU PIPELINE TỰ ĐỘNG HÓA: RETURN SURVIVAL (EP 1 - 33)", flush=True)
    print(f"Ngôn ngữ: Tiếng Tây Ban Nha (LATAM) | Giọng đọc: es-MX-JorgeNeural (+10% Speed)", flush=True)
    print(f"Thư mục làm việc: {download_dir}", flush=True)
    print("=" * 60, flush=True)

    for stage in stages_pipeline:
        task.current_stage = stage.name
        print(f"\n▶ [{stage.name}] Bắt đầu thực thi...", flush=True)
        t_stage_start = time.time()
        try:
            success = await stage.execute(ctx)
            duration = time.time() - t_stage_start
            if success:
                print(f"✔ [{stage.name}] Hoàn thành thành công ({duration:.1f}s)", flush=True)
            else:
                print(f"❌ [{stage.name}] Thất bại sau ({duration:.1f}s)", flush=True)
                return False
        except Exception as e:
            print(f"💥 Lỗi ngoại lệ trong [{stage.name}]: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return False

    total_duration = time.time() - total_start
    print("\n" + "=" * 60, flush=True)
    print(f"🎉 TOÀN BỘ PIPELINE ĐÃ HOÀN TẤT THÀNH CÔNG TRONG {total_duration/60:.1f} PHÚT!", flush=True)
    output_kit = os.path.join(download_dir, "output", "youtube_upload_kit.txt")
    if os.path.exists(output_kit):
        print(f"📦 YouTube Upload Kit sẵn sàng tại: {output_kit}", flush=True)
    print("=" * 60, flush=True)

    # 13. Tự động cắt và tạo Shorts phễu (3 Shorts/tuần)
    upload_dir = os.path.join(download_dir, "output", "upload")
    if os.path.exists(upload_dir):
        mp4_files = [f for f in os.listdir(upload_dir) if f.endswith(".mp4") and "_SHORTS" not in f]
        srt_files = [f for f in os.listdir(upload_dir) if f.endswith(".srt")]
        if mp4_files and srt_files:
            master_mp4 = os.path.join(upload_dir, mp4_files[0])
            master_srt = os.path.join(upload_dir, srt_files[0])
            print(f"\n🎬 [SHORTS] Đang tự động cắt & tạo Bộ 3 YouTube Shorts phễu từ {master_mp4}...", flush=True)
            try:
                cmd = [
                    sys.executable,
                    os.path.join(PROJECT_DIR, "runtime", "generate_shorts_funnel.py"),
                    "--video", master_mp4,
                    "--srt", master_srt,
                    "--output-dir", upload_dir,
                    "--comic-title", payload["comic_title"],
                ]
                subprocess.run(cmd, check=True)
                print(f"✔ [SHORTS] Đã tạo thành công Bộ 3 YouTube Shorts và youtube_shorts_kit.txt trong: {upload_dir}", flush=True)
            except Exception as ex:
                print(f"⚠ [SHORTS] Lỗi sinh Shorts: {ex}", flush=True)

    # 14. Tự động chạy Content QA Auditor
    if os.path.exists(upload_dir):
        srt_files = [f for f in os.listdir(upload_dir) if f.endswith(".srt")]
        if srt_files:
            master_srt = os.path.join(upload_dir, srt_files[0])
            qa_report_path = os.path.join(upload_dir, "QA_Report_VI_Final_Run.md")
            print(f"\n🕵️‍♂️ [QA AUDITOR] Đang kích hoạt Content QA Auditor cho {master_srt}...", flush=True)
            try:
                from runtime.content_qa_auditor import generate_qa_report
                await generate_qa_report(master_srt, qa_report_path)
                print(f"✔ [QA AUDITOR] Báo cáo QA nghiệm thu hoàn thành tại: {qa_report_path}", flush=True)
            except Exception as ex:
                print(f"⚠ [QA AUDITOR] Lỗi chạy QA Auditor: {ex}", flush=True)

    return True


if __name__ == "__main__":
    force_clean = "--clean" in sys.argv
    success = asyncio.run(run_pipeline(force_clean=force_clean))
    sys.exit(0 if success else 1)
