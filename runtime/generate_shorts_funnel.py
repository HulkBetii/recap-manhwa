import os
import re
import sys
import argparse
import subprocess
import shutil

# Fix Unicode output for Windows Console
sys.stdout.reconfigure(encoding='utf-8')

FFMPEG_PATH = r"D:\VibeCoding\recap_comics-windows_version\recap_comics-windows_version\.venv\Scripts\ffmpeg.exe"

def parse_time(time_str):
    # Parses SRT time "HH:MM:SS,mmm" to seconds
    parts = time_str.replace(',', '.').split(':')
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])

def format_time(seconds):
    # Formats seconds to SRT time
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')

def find_smart_hook(srt_path, min_time=40.0, max_time=58.0):
    with open(srt_path, 'r', encoding='utf-8-sig') as f:
        content = f.read().strip()
    
    blocks = re.split(r'\n\n+', content)
    
    best_cutoff = max_time
    
    # We want to find the latest subtitle block that ends before max_time, 
    # preferably ending with a sentence terminator (. ! ?).
    valid_blocks = []
    
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3:
            time_line = lines[1]
            text = " ".join(lines[2:])
            
            match = re.search(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', time_line)
            if match:
                start_s = parse_time(match.group(1))
                end_s = parse_time(match.group(2))
                
                if end_s <= max_time:
                    valid_blocks.append({'end': end_s, 'text': text})
    
    # Search backwards for a natural sentence break
    for b in reversed(valid_blocks):
        if b['end'] < min_time:
            break
        if re.search(r'[.!?¡¿"]$', b['text'].strip()):
            print(f"[Smart Hook] Found natural pause at {b['end']}s: '{b['text']}'")
            return b['end']
    
    # Fallback to the last valid block if no perfect punctuation is found
    if valid_blocks and valid_blocks[-1]['end'] >= min_time:
        print(f"[Smart Hook] No perfect punctuation found. Falling back to {valid_blocks[-1]['end']}s: '{valid_blocks[-1]['text']}'")
        return valid_blocks[-1]['end']
        
    print(f"[Smart Hook] Defaulting to {max_time}s.")
    return max_time

def generate_cta_audio(text, output_path):
    print(f"[CTA] Generating TTS for: '{text}'")
    # Using edge-tts. We use call to edge-tts executable installed in the env
    cmd = [
        "edge-tts",
        "--voice", "es-MX-JorgeNeural",
        "--rate", "+10%",
        "--text", text,
        "--write-media", output_path
    ]
    subprocess.run(cmd, check=True, shell=True) # Shell=True helps resolve commands in Windows venv sometimes

def main():
    parser = argparse.ArgumentParser(description="Generate YouTube Shorts funnel video.")
    parser.add_argument("--video", required=True, help="Input 16:9 mp4 video")
    parser.add_argument("--srt", required=True, help="Input SRT subtitles")
    parser.add_argument("--output", required=True, help="Output Shorts mp4 video")
    parser.add_argument("--min-sec", type=float, default=40.0, help="Minimum seconds for hook")
    parser.add_argument("--max-sec", type=float, default=55.0, help="Maximum seconds for hook (Leaves 5s for CTA)")
    args = parser.parse_args()

    # 1. Find Smart Hook
    print(f"\n--- Bước 1: Tìm điểm ngắt câu thông minh ---")
    cutoff_time = find_smart_hook(args.srt, args.min_sec, args.max_sec)
    
    # Copy SRT to a temporary local file to avoid path escaping issues in FFmpeg filter
    temp_srt = "temp_subs.srt"
    shutil.copy2(args.srt, temp_srt)
    
    # Ensure paths are absolute and formatted for FFmpeg
    video_abs = os.path.abspath(args.video)
    output_abs = os.path.abspath(args.output)
    
    temp_main_video = "temp_main.mp4"
    temp_cta_audio = "temp_cta.mp3"
    temp_cta_video = "temp_cta.mp4"
    temp_list = "temp_list.txt"

    try:
        # 2. Extract & Crop & Burn Subs
        print(f"\n--- Bước 2: Cắt và Render Video Chính (0s -> {cutoff_time}s) ---")
        # Subtitles alignment 2=bottom-center, Outline=2, Shadow=1, PrimaryColour white, Outline black
        vf_string = f"crop=608:1080,scale=1080:1920,subtitles={temp_srt}:force_style='FontSize=22,Alignment=2,MarginV=60,Outline=2,Shadow=0,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000'"
        
        cmd_main = [
            FFMPEG_PATH, "-y",
            "-i", video_abs,
            "-t", str(cutoff_time),
            "-vf", vf_string,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            temp_main_video
        ]
        print(f"Running FFmpeg (Main): {' '.join(cmd_main)}")
        subprocess.run(cmd_main, check=True)

        # 3. Generate CTA Audio
        print(f"\n--- Bước 3: Tạo CTA Audio ---")
        cta_text = "¡Mira el video completo en el enlace relacionado abajo!"
        generate_cta_audio(cta_text, temp_cta_audio)

        # 4. Generate CTA Video segment (Black screen with text, length ~ 4 seconds)
        print(f"\n--- Bước 4: Tạo CTA Video Segment ---")
        cmd_cta = [
            FFMPEG_PATH, "-y",
            "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=4.0",
            "-i", temp_cta_audio,
            "-vf", "drawtext=text='VÍDEO COMPLETO ABAJO \\n    ↓ ↓ ↓':fontcolor=white:fontsize=70:x=(w-text_w)/2:y=(h-text_h)/2",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-shortest",
            temp_cta_video
        ]
        print(f"Running FFmpeg (CTA): {' '.join(cmd_cta)}")
        subprocess.run(cmd_cta, check=True)

        # 5. Concatenate
        print(f"\n--- Bước 5: Nối Video (Merging) ---")
        with open(temp_list, "w", encoding="utf-8") as f:
            f.write(f"file '{temp_main_video}'\n")
            f.write(f"file '{temp_cta_video}'\n")
            
        cmd_concat = [
            FFMPEG_PATH, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", temp_list,
            "-c", "copy",
            output_abs
        ]
        print(f"Running FFmpeg (Concat): {' '.join(cmd_concat)}")
        subprocess.run(cmd_concat, check=True)
        
        print(f"\n✅ Hoàn thành! Video Shorts đã được lưu tại: {output_abs}")

    finally:
        # Cleanup temp files
        for tmp_file in [temp_srt, temp_main_video, temp_cta_audio, temp_cta_video, temp_list]:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception as e:
                    print(f"Warning: Could not remove {tmp_file} - {e}")

if __name__ == "__main__":
    main()
