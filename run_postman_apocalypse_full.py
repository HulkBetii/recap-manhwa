import os
import sys
import asyncio
import json
import time
from pathlib import Path

# Ensure UTF-8 everywhere
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

os.chdir(r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version")
sys.path.insert(0, r"d:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version")

import config
from workflow_base import WorkflowTask, WorkflowState, StageState, JSONWorkflowRepository, EventBus
from workflow import WorkflowManager

async def run_full_series():
    target_url = "https://vortexscans.org/series/the-postman-of-the-apocalypse"
    comic_title = "The Postman of the Apocalypse"
    from_ep = 1
    to_ep = 19

    print("=" * 80)
    print(f"  FULL COMIC RUN: {comic_title} (Episodes {from_ep} - {to_ep})")
    print(f"  URL: {target_url}")
    print(f"  Language: English (en)")
    print(f"  Market: US Apocalypse & Survival (us_apocalypse)")
    print(f"  Concurrency: 3 Chrome Profiles (Parallel Arc Partitioning)")
    print(f"  Streaming Pipeline: Enabled (Interleaved TTS + NVENC Render)")
    print(f"  Voice: OmniVoice English (clone_andrew)")
    print("=" * 80)

    task_id = f"postman-apocalypse-full-1-19-{int(time.time())}"
    payload = {
        "comic_title": comic_title,
        "comic_url": target_url,
        "from_episode": from_ep,
        "to_episode": to_ep,
        "language": "en",
        "market_id": "us_apocalypse",
        "voice_id": "clone_andrew",
        "ref_audio_path": getattr(config, "DEFAULT_EN_REF_AUDIO", None),
        "min_panel_duration": 3.5,
        "hard_floor_duration": 3.0,
        "concurrency": 2,
        "streaming_pipeline": True,
        "burn_subtitles": False,
        "remove_text": False,
        "split_double_pages": True,
        "reading_direction": "ltr",
        "retry_count": 3,
        "timeout": 240,
        "cleanup": False,
        "safe_mode": False,
    }

    task = WorkflowTask(
        comic_title=comic_title,
        comic_url=target_url,
        from_episode=from_ep,
        to_episode=to_ep,
        payload=payload,
        id=task_id,
    )

    repo = JSONWorkflowRepository()
    event_bus = EventBus()

    last_logged_stage = None
    last_log_time = time.monotonic()

    def on_event(event_name, task_id, data):
        nonlocal last_logged_stage, last_log_time
        now = time.monotonic()
        if event_name == "StageStarted":
            current_stage = data.get("current_stage")
            print(f"\n[STAGE STARTED] {current_stage}")
            last_logged_stage = current_stage
            last_log_time = now
        elif event_name == "StageCompleted":
            elapsed = data.get("elapsed_time", 0)
            print(f"[STAGE COMPLETED] {last_logged_stage} (Elapsed: {elapsed}s)")
        elif event_name == "WorkflowProgressUpdated":
            if now - last_log_time >= 30:
                last_log_time = now
                stage_name = data.get("current_stage") or "Init"
                eta = f"{data.get('estimated_remaining_time')}s" if data.get('estimated_remaining_time') else "calc..."
                print(f"  [Progress] Stage: {stage_name} | Elapsed: {data.get('elapsed_time')}s | ETA: {eta}")

    event_bus.subscribe(on_event)

    manager = WorkflowManager(repo, event_bus, max_workers=1, run_in_subprocess=False)
    manager.cancel_tokens[task.id] = manager.get_cancel_token(task.id)

    start_time = time.time()
    print(f"\n[WorkflowManager] Bắt đầu thực thi workflow: {task.id}...")
    
    try:
        await manager._execute_workflow(task)
    except Exception as exc:
        print(f"\n[FATAL] Workflow gặp lỗi: {exc}", flush=True)

    success = (task.status == WorkflowState.SUCCESS)
    total_time = round(time.time() - start_time, 2)

    print("\n" + "=" * 80)
    print(f"  PIPELINE RESULT: {'SUCCESS' if success else 'FAILED'}")
    print(f"  Tổng thời gian: {total_time}s ({round(total_time / 60, 2)} phút)")
    print("=" * 80)

    print("\nChi tiết tiến độ từng Stage:")
    for s in task.stages:
        status_icon = "✅" if s["status"] == StageState.SUCCESS else ("❌" if s["status"] == StageState.FAILED else "⏳")
        print(f"  {status_icon} {s['name']:<38}: {s['status']} ({s.get('progress', 0):.1f}%)")

    download_dir = task.artifacts.get("download_dir", "")
    print(f"\nThư mục xuất bản: {download_dir}")

    if download_dir and os.path.exists(download_dir):
        print("\nKiểm tra Artifacts từng tập (1 - 19):")
        from app import find_ffmpeg
        ffmpeg_exe = find_ffmpeg()
        from workflow_stages_2 import get_video_duration

        total_vid_dur = 0.0
        all_episodes_ok = True

        for ep in range(from_ep, to_ep + 1):
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            recap_json = os.path.join(ep_dir, "recap.json")
            audio_mp3 = os.path.join(ep_dir, "audio.mp3")
            transcript_srt = os.path.join(ep_dir, "transcript.srt")
            video_mp4 = os.path.join(ep_dir, "video.mp4")

            has_recap = os.path.exists(recap_json) and os.path.getsize(recap_json) > 0
            has_audio = os.path.exists(audio_mp3) and os.path.getsize(audio_mp3) > 0
            has_srt = os.path.exists(transcript_srt) and os.path.getsize(transcript_srt) > 0
            has_video = os.path.exists(video_mp4) and os.path.getsize(video_mp4) > 0

            dur = get_video_duration(video_mp4, ffmpeg_exe) if has_video else 0.0
            size_mb = round(os.path.getsize(video_mp4) / (1024 * 1024), 2) if has_video else 0.0
            total_vid_dur += dur

            status = "OK" if (has_recap and has_audio and has_srt and has_video) else "INCOMPLETE"
            if status != "OK":
                all_episodes_ok = False
            print(f"  - Tập {ep:02d}: {status} | Video: {dur:.1f}s ({size_mb} MB) | recap: {'✓' if has_recap else '✗'} | audio: {'✓' if has_audio else '✗'} | srt: {'✓' if has_srt else '✗'}")

        # Final assembled video
        final_video_path = task.artifacts.get("final_video_path", "")
        if not final_video_path or not os.path.exists(final_video_path):
            output_dir = os.path.join(download_dir, "output")
            if os.path.exists(output_dir):
                mp4_candidates = [os.path.join(output_dir, f) for f in os.listdir(output_dir) if f.lower().endswith(".mp4")]
                if mp4_candidates:
                    final_video_path = mp4_candidates[0]

        if final_video_path and os.path.exists(final_video_path):
            final_dur = get_video_duration(final_video_path, ffmpeg_exe)
            final_size_mb = round(os.path.getsize(final_video_path) / (1024 * 1024), 2)
            print(f"\n🎬 Master Assembled Video: {final_video_path}")
            print(f"   Thời lượng tổng: {final_dur:.1f}s ({round(final_dur / 60, 2)} phút)")
            print(f"   Dung lượng: {final_size_mb} MB")

        # YouTube Upload Kit
        yt_kit_path = os.path.join(download_dir, "output", "youtube_upload_kit.txt")
        if os.path.exists(yt_kit_path):
            print(f"\n📝 YouTube Upload Kit: {yt_kit_path}")
            with open(yt_kit_path, "r", encoding="utf-8") as f:
                content = f.read()
                print("=" * 80)
                print(content[:1500])
                if len(content) > 1500:
                    print("\n... [xem toàn bộ trong file youtube_upload_kit.txt] ...")
                print("=" * 80)

    return success

if __name__ == "__main__":
    success = asyncio.run(run_full_series())
    sys.exit(0 if success else 1)
