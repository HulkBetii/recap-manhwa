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

async def run_e2e():
    target_url = "https://www.webtoons.com/en/thriller/surviving-the-apocalypse/list?title_no=6678"
    comic_title = "Surviving The Apocalypse"
    from_ep = 1
    to_ep = 4

    print("=" * 80)
    print(f"  E2E TEST: {comic_title} (Episodes {from_ep} - {to_ep})")
    print(f"  URL: {target_url}")
    print(f"  Concurrency: 4 Chrome Profiles (Arc-based parallel)")
    print(f"  Streaming Pipeline: Enabled (Interleaved TTS + NVENC Render)")
    print(f"  Voice TTS: OmniVoice English (clone_andrew)")
    print("=" * 80)

    task_id = f"test-e2e-surviving-4ep-{int(time.time())}"
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
        "concurrency": 4,
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
        id=task_id
    )

    repo = JSONWorkflowRepository("tasks_db.json")
    repo.save(task)

    event_bus = EventBus()
    async def on_event(event_name, task_id, data):
        pass
    event_bus.subscribe(on_event)

    manager = WorkflowManager(repo, event_bus, max_workers=1, run_in_subprocess=False)
    manager.cancel_tokens[task.id] = manager.get_cancel_token(task.id)

    start_wall_time = time.time()
    print(f"\n[START] Bắt đầu thực thi pipeline E2E lúc: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_wall_time))}\n")

    try:
        await manager._execute_workflow(task)
    except Exception as exc:
        print(f"\n[FATAL] Workflow gặp ngoại lệ nghiêm trọng: {exc}", flush=True)

    end_wall_time = time.time()
    total_elapsed = round(end_wall_time - start_wall_time, 2)

    print("\n" + "=" * 80)
    print(f"  E2E TEST RESULT: {task.status}")
    print(f"  Tổng thời gian thực thi: {total_elapsed}s ({round(total_elapsed / 60, 2)} phút)")
    print("=" * 80)

    # In ra thời gian và trạng thái từng stage
    print("\nChi tiết tiến độ từng Stage:")
    for s in task.stages:
        status_symbol = "✅" if s["status"] == StageState.SUCCESS else ("❌" if s["status"] == StageState.FAILED else "⏳")
        print(f"  {status_symbol} {s['name']:<35} : {s['status']} ({s.get('progress', 0.0):.1f}%)")

    # Kiểm tra các artifact sinh ra
    download_dir = task.artifacts.get("download_dir", "")
    print(f"\nThư mục tải & xuất bản: {download_dir}")

    if download_dir and os.path.exists(download_dir):
        print("\nKiểm tra Artifacts từng tập:")
        from app import find_ffmpeg
        ffmpeg_exe = find_ffmpeg()
        from workflow_stages_2 import get_video_duration

        for ep in range(from_ep, to_ep + 1):
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            recap_json = os.path.join(ep_dir, "recap.json")
            audio_mp3 = os.path.join(ep_dir, "audio.mp3")
            transcript_srt = os.path.join(ep_dir, "transcript.srt")
            video_mp4 = os.path.join(ep_dir, f"video_{ep}.mp4")

            has_recap = os.path.exists(recap_json) and os.path.getsize(recap_json) > 0
            has_audio = os.path.exists(audio_mp3) and os.path.getsize(audio_mp3) > 0
            has_srt = os.path.exists(transcript_srt) and os.path.getsize(transcript_srt) > 0
            has_video = os.path.exists(video_mp4) and os.path.getsize(video_mp4) > 0

            dur = get_video_duration(video_mp4, ffmpeg_exe) if has_video else 0.0
            size_mb = round(os.path.getsize(video_mp4) / (1024 * 1024), 2) if has_video else 0.0

            print(f"  - Tập {ep}:")
            print(f"      recap.json   : {'OK' if has_recap else 'MISSING'}")
            print(f"      audio.mp3    : {'OK' if has_audio else 'MISSING'}")
            print(f"      transcript.srt: {'OK' if has_srt else 'MISSING'}")
            print(f"      video_{ep}.mp4 : {'OK' if has_video else 'MISSING'} ({dur:.1f}s, {size_mb} MB)")

        # Final assembled video
        final_video_path = task.artifacts.get("final_video_path", "")
        if not final_video_path:
            final_video_path = os.path.join(download_dir, "output", f"full_ep_{from_ep}_to_{to_ep}.mp4")

        if os.path.exists(final_video_path):
            final_dur = get_video_duration(final_video_path, ffmpeg_exe)
            final_size_mb = round(os.path.getsize(final_video_path) / (1024 * 1024), 2)
            print(f"\n🎬 Final Assembled Video: {final_video_path}")
            print(f"   Thời lượng: {final_dur:.1f}s ({round(final_dur / 60, 2)} phút)")
            print(f"   Dung lượng: {final_size_mb} MB")

        # YouTube Upload Kit
        yt_kit_path = os.path.join(download_dir, "output", "youtube_upload_kit.txt")
        if os.path.exists(yt_kit_path):
            print(f"\n📝 YouTube Upload Kit: {yt_kit_path}")
            with open(yt_kit_path, "r", encoding="utf-8") as yf:
                lines = yf.readlines()[:15]
                print("".join(lines))

    print("\n" + "=" * 80)
    return 0 if task.status == WorkflowState.SUCCESS else 1

if __name__ == "__main__":
    exit_code = asyncio.run(run_e2e())
    sys.exit(exit_code)
