import os
import sys
import json
import time
import asyncio
import shutil

PROJECT_DIR = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
FOLDER_NAME = "return_survival_new_1_30_es_9b1e12cd"

sys.stdout.reconfigure(encoding="utf-8")
os.chdir(PROJECT_DIR)
sys.path.insert(0, PROJECT_DIR)

from workflow_base import WorkflowTask
from workflow_stages_1 import (
    Stage5_GeminiAutomation,
    Stage6_JSONExtraction,
)
from workflow_stages_2 import (
    Stage7_NarrationAggregation,
    Stage8_LocalTTS,
    Stage9_SubtitleNormalization,
    merge_srt_files,
)
from runtime.run_return_survival_pipeline import ContextWrapper

async def main():
    download_dir = os.path.join(PROJECT_DIR, "downloads", FOLDER_NAME)
    
    print("=" * 60)
    print("🧹 BẮT ĐẦU RESET CACHE CHO STAGE 5 -> 9 (KỊCH BẢN & SUBTITLE)")
    print("=" * 60)
    
    # 1. Clear old script artifacts so Stage 5 is forced to call Gemini with the new prompt
    for ep in range(1, 31):
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        if not os.path.exists(ep_dir):
            continue
            
        # Files to remove
        for fname in ["recap.json", "raw_gemini_response.txt", "narration.txt", "audio.mp3", "transcript.srt", "transcript_no_intro.srt"]:
            p = os.path.join(ep_dir, fname)
            if os.path.exists(p):
                os.remove(p)
                
        # Clear stages in manifest
        manifest_p = os.path.join(ep_dir, "artifact_manifest.json")
        if os.path.exists(manifest_p):
            try:
                with open(manifest_p, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                stages = manifest.get("stages", {})
                for st in ["gemini", "narration", "tts", "subtitles"]:
                    stages.pop(st, None)
                with open(manifest_p, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2)
            except Exception as e:
                pass

    print("✅ Đã xóa sạch cache kịch bản cũ! Sẵn sàng chạy lại Stage 5 với NÃO MỚI.")

    # 2. Setup task
    payload = {
        "comic_title": "Return Survival",
        "comic_url": "https://manhwatop.com/manga/return-survival-series/",
        "from_episode": 1,
        "to_episode": 30,
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
        comic_title="Return Survival",
        comic_url=payload["comic_url"],
        from_episode=1,
        to_episode=30,
        payload=payload,
        id=f"return-survival-regen-{int(time.time())}",
    )
    task.artifacts["download_dir"] = download_dir
    task.artifacts["download_folder_name"] = FOLDER_NAME
    task.artifacts["comic_title"] = "Return Survival"

    ctx = ContextWrapper(task)

    # 3. Execute Stages 5 -> 9
    pipeline = [
        Stage5_GeminiAutomation(),
        Stage6_JSONExtraction(),
        Stage7_NarrationAggregation(),
        Stage8_LocalTTS(),
        Stage9_SubtitleNormalization(),
    ]

    for stage in pipeline:
        task.current_stage = stage.name
        print(f"\n▶ [{stage.name}] Đang chạy...")
        start_t = time.time()
        success = await stage.execute(ctx)
        if not success:
            print(f"❌ [{stage.name}] Thất bại!")
            return
        print(f"✔ [{stage.name}] Xong trong {time.time() - start_t:.1f}s")

    # 4. Merge all episode transcripts into a unified SRT file
    print("\n📦 Đang gộp toàn bộ phụ đề (SRT) của 30 tập thành 1 file thống nhất...")
    srt_paths = []
    video_durations = []
    
    # We can get durations from audio.mp3 files
    import mutagen.mp3
    for ep in range(1, 31):
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        srt_p = os.path.join(ep_dir, "transcript.srt")
        audio_p = os.path.join(ep_dir, "audio.mp3")
        
        dur = 100.0 # fallback
        if os.path.exists(audio_p):
            try:
                mp3_info = mutagen.mp3.MP3(audio_p)
                dur = mp3_info.info.length
            except Exception:
                pass
                
        srt_paths.append(srt_p)
        video_durations.append(dur)

    out_srt = os.path.join(download_dir, "output", "upload", "he_returned_in_time_to_prepare_for_the_zombie_outbreak_es_V3.srt")
    merge_srt_files(srt_paths, video_durations, out_srt)
    print(f"✅ Đã tạo file phụ đề V3 mới nhất tại: {out_srt}")

    # 5. Run Content QA Auditor on the new V3 SRT file
    print("\n🕵️‍♂️ ĐANG KÍCH HOẠT CONTENT QA AUDITOR ĐỂ CHẤM ĐIỂM KỊCH BẢN MỚI...")
    from runtime.content_qa_auditor import generate_qa_report
    qa_report_path = os.path.join(download_dir, "output", "upload", "QA_Report_VI_V3.md")
    await generate_qa_report(out_srt, qa_report_path)
    print(f"\n🎉 HOÀN TẤT TẤT CẢ! Báo cáo nghiệm thu mới đã sẵn sàng tại: {qa_report_path}")

if __name__ == "__main__":
    asyncio.run(main())
