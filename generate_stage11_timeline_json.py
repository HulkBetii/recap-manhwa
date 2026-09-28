# -*- coding: utf-8 -*-
"""
Consolidate Stage 11 timeline, scene timestamps, and chapter markers into a unified JSON file.
"""
import os
import sys
import json
import re

PROJECT_ROOT = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version"
os.chdir(PROJECT_ROOT)

def main():
    download_dir = os.path.join(PROJECT_ROOT, "downloads", "좀비묵시록_8208_1_143_en_946016ec")
    output_dir = os.path.join(download_dir, "output")
    
    # 1. Load Chapter Markers from metadata.json
    metadata_path = os.path.join(output_dir, "metadata.json")
    chapters = []
    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        chapters = meta.get("youtube_metadata", {}).get("narrative_chapters", [])

    # 2. Extract scene timestamps & timeline segments from Episodes 1-5
    episodes_timeline = {}
    for ep in range(1, 6):
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        recap_p = os.path.join(ep_dir, "recap.json")
        srt_p = os.path.join(ep_dir, "transcript.srt")
        
        scenes = []
        if os.path.exists(recap_p):
            with open(recap_p, "r", encoding="utf-8") as f:
                recap = json.load(f)
            
            srt_cues = []
            if os.path.exists(srt_p):
                with open(srt_p, "r", encoding="utf-8") as sf:
                    content = sf.read().strip()
                blocks = re.split(r'\n\s*\n', content)
                for b in blocks:
                    lines = b.strip().splitlines()
                    if len(lines) >= 3:
                        timing = lines[1]
                        m = re.match(r'(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)', timing)
                        if m:
                            s_h, s_m, s_s, s_ms = map(int, m.groups()[:4])
                            e_h, e_m, e_s, e_ms = map(int, m.groups()[4:])
                            start_sec = s_h * 3600 + s_m * 60 + s_s + s_ms / 1000.0
                            end_sec = e_h * 3600 + e_m * 60 + e_s + e_ms / 1000.0
                        else:
                            start_sec, end_sec = 0.0, 0.0
                        srt_cues.append({'timing': timing, 'start_seconds': start_sec, 'end_seconds': end_sec})

            for i, seg in enumerate(recap):
                cue = srt_cues[i] if i < len(srt_cues) else {'timing': f'Segment {i+1}', 'start_seconds': 0.0, 'end_seconds': 0.0}
                scenes.append({
                    "scene_index": i + 1,
                    "timing": cue.get("timing"),
                    "start_seconds": round(cue.get("start_seconds", 0.0), 2),
                    "end_seconds": round(cue.get("end_seconds", 0.0), 2),
                    "duration_seconds": round(cue.get("end_seconds", 0.0) - cue.get("start_seconds", 0.0), 2),
                    "pages_used": [img.get("page") for img in seg.get("images", [])],
                    "narration_speech": seg.get("speech", "")
                })

        episodes_timeline[f"episode_{ep}"] = {
            "episode": ep,
            "total_scenes": len(scenes),
            "video_path": os.path.join(ep_dir, "video.mp4"),
            "scenes": scenes
        }

    consolidated_data = {
        "comic_title": "Zombie Revelation: 82-08",
        "description": "Consolidated Stage 11 timeline segments, scene timestamps, and Stage 12 chapter markers.",
        "master_video_outputs": {
            "final_video_mp4": os.path.join(output_dir, "좀비묵시록_8208_1_143_en_946016ec.mp4"),
            "final_timeline_srt": os.path.join(output_dir, "좀비묵시록_8208_1_143_en_946016ec.srt")
        },
        "chapter_markers": chapters,
        "episodes_timeline_segments": episodes_timeline
    }

    out_file = os.path.join(PROJECT_ROOT, "stage11_timeline_and_chapter_markers.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(consolidated_data, f, ensure_ascii=False, indent=2)

    # Also place a copy in v5_3_package/
    pkg_file = os.path.join(PROJECT_ROOT, "v5_3_package", "stage11_timeline_and_chapter_markers.json")
    with open(pkg_file, "w", encoding="utf-8") as f:
        json.dump(consolidated_data, f, ensure_ascii=False, indent=2)

    print(f"Successfully generated {out_file}")

if __name__ == "__main__":
    main()
