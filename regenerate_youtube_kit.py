"""
Re-generate youtube_upload_kit.txt, metadata.json, and processing_report.json
for Veteran of the Apocalypse (Episodes 1 to 33 EN) with latest code.
"""
import os
import sys
import json
import time
from pathlib import Path

PROJECT_ROOT = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from app import find_ffmpeg
from workflow_stages_2 import get_video_duration
from youtube_metadata import generate_youtube_metadata

ffmpeg_exe = find_ffmpeg()
download_dir = os.path.abspath(r"downloads\veteran_of_the_apocalypse_1_33_en_e826e8f9")
output_dir = os.path.join(download_dir, "output")
os.makedirs(output_dir, exist_ok=True)

comic_title = "Veteran of the Apocalypse"
from_ep = 1
to_ep = 33

print("==================================================================")
print("  RE-GENERATING YOUTUBE UPLOAD KIT WITH LATEST CODE")
print(f"  Comic: {comic_title} (Ep {from_ep} -> {to_ep})")
print(f"  Directory: {download_dir}")
print("==================================================================")

# 1. Calculate exact chapter durations
video_durations = []
for ep in range(from_ep, to_ep + 1):
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    video_path = os.path.join(ep_dir, "video.mp4")
    dur = get_video_duration(video_path, ffmpeg_exe)
    video_durations.append(dur)
    print(f"  Ep {ep:02d}: {dur:.2f}s")

chapters = []
curr_ts = 0.0
for idx, ep in enumerate(range(from_ep, to_ep + 1)):
    dur = video_durations[idx]
    hrs = int(curr_ts // 3600)
    mins = int((curr_ts % 3600) // 60)
    secs = int(curr_ts % 60)
    ts_str = f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"
    chapters.append({
        "episode": ep,
        "timestamp": ts_str,
        "title": f"Episode {ep}",
        "duration_seconds": dur
    })
    curr_ts += dur

print(f"\nTotal video duration: {curr_ts:.2f}s ({int(curr_ts//3600)}h {int((curr_ts%3600)//60)}m {int(curr_ts%60)}s)")

# 2. Load story memory if available
story_memory = None
story_mem_path = os.path.join(download_dir, "story_memory.json")
if os.path.exists(story_mem_path):
    try:
        with open(story_mem_path, "r", encoding="utf-8") as smf:
            story_memory = json.load(smf)
            print(f"Loaded story_memory.json with {len(story_memory.get('episodes', {}))} episode entries.")
    except Exception as e:
        print(f"Failed to load story_memory.json: {e}")

# 3. Generate YouTube Metadata
yt_meta = generate_youtube_metadata(
    comic_title=comic_title,
    from_ep=from_ep,
    to_ep=to_ep,
    chapters=chapters,
    story_memory=story_memory,
    download_dir=download_dir,
)

# 4. Save formatted youtube_upload_kit.txt
kit_path = os.path.join(output_dir, "youtube_upload_kit.txt")
kit_content = yt_meta.get("formatted_kit", "")

if not kit_content:
    print("[ERROR] formatted_kit was empty!")
else:
    with open(kit_path, "w", encoding="utf-8") as kf:
        kf.write(kit_content)
    print(f"\n[SUCCESS] Wrote new youtube_upload_kit.txt to: {kit_path} ({len(kit_content)} chars)")

# 5. Save metadata.json
metadata = {
    "comic_title": comic_title,
    "comic_url": "https://www.webtoons.com/en/action/veteran-of-the-apocalypse/list?title_no=9675",
    "from_episode": from_ep,
    "to_episode": to_ep,
    "generation_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "flash_forward_intro": {
        "enabled": True,
        "duration": 17.3,
        "archetype": "outrageous_flex",
        "climax_episode": 6
    },
    "youtube_metadata": yt_meta,
    "compliance_audit": yt_meta.get("compliance_flags")
}

metadata_path = os.path.join(output_dir, "metadata.json")
with open(metadata_path, "w", encoding="utf-8") as mf:
    json.dump(metadata, mf, ensure_ascii=False, indent=2)
print(f"[SUCCESS] Wrote metadata.json to: {metadata_path}")

# 6. Save processing_report.json
report = {
    "task_id": f"veteran-of-the-apocalypse-full-1-33-en",
    "completed_episodes_count": 33,
    "failed_episodes_count": 0,
    "compliance_audit": yt_meta.get("compliance_flags")
}
report_path = os.path.join(output_dir, "processing_report.json")
with open(report_path, "w", encoding="utf-8") as rf:
    json.dump(report, rf, ensure_ascii=False, indent=2)
print(f"[SUCCESS] Wrote processing_report.json to: {report_path}")

print("\n==================================================================")
print("  RE-GENERATION COMPLETED SUCCESSFULLY")
print("==================================================================")
