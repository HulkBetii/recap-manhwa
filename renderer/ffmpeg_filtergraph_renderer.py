# -*- coding: utf-8 -*-
"""
Direct FFmpeg Filtergraph Video Renderer:
Constructs high-performance native FFmpeg filtergraphs for manga/comic recap videos.
Performs background blur, Ken Burns zoom/pan, aspect ratio centering, cross-fade transitions,
and audio normalization entirely within FFmpeg C/AVX2 / NVENC hardware pipelines.
"""

import os
import sys
import subprocess
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("FFmpegFiltergraphRenderer")


def render_video_with_ffmpeg_filtergraph(
    page_displays: List[Dict[str, Any]],
    audio_path: str,
    output_video_path: str,
    ffmpeg_exe: str,
    working_encoder: str = "h264_nvenc",
    fps: int = 30,
    subtitles_path: Optional[str] = None,
    logo_path: Optional[str] = None,
    overlay_path: Optional[str] = None,
    video_mark_path: Optional[str] = None,
    video_mark_alpha: float = 0.01,
    target_lufs: float = -14.0,
    target_tp: float = -1.5,
    trans_duration: float = 0.25
) -> bool:
    """
    Renders video using pure native FFmpeg filter complex.
    Zero Python frame looping and zero raw pipe IPC overhead.
    """
    if not page_displays:
        raise ValueError("No page displays provided for FFmpeg filtergraph render.")

    ep_dir = os.path.dirname(output_video_path)
    os.makedirs(ep_dir, exist_ok=True)

    # Configure encoder options
    enc_str = str(working_encoder).lower()
    gop_size = str(fps)
    if "nvenc" in enc_str:
        extra_args = [
            "-preset", "p1", "-tune", "ll", "-rc", "vbr", "-cq", "28",
            "-b:v", "1800k", "-maxrate", "2800k", "-bufsize", "4000k",
            "-g", gop_size, "-keyint_min", gop_size, "-threads", "0"
        ]
    elif "amf" in enc_str:
        extra_args = ["-rc", "cqp", "-qp_i", "27", "-qp_p", "27", "-b:v", "1800k", "-maxrate", "2800k", "-g", gop_size, "-keyint_min", gop_size, "-quality", "speed", "-threads", "0"]
    elif "qsv" in enc_str:
        extra_args = ["-preset", "veryfast", "-global_quality", "27", "-b:v", "1800k", "-maxrate", "2800k", "-g", gop_size, "-keyint_min", gop_size, "-threads", "0"]
    elif "libx264" in enc_str:
        extra_args = ["-crf", "24", "-preset", "veryfast", "-b:v", "1800k", "-maxrate", "2800k", "-bufsize", "4000k", "-g", gop_size, "-keyint_min", gop_size, "-threads", "0"]
    else:
        extra_args = ["-b:v", "1500k", "-g", gop_size, "-keyint_min", gop_size, "-threads", "0"]

    # Build inputs
    cmd = [ffmpeg_exe, "-y"]
    
    # 1. Add image inputs
    for idx, pd in enumerate(page_displays):
        img_path = pd.get("image_path") or pd.get("image_file")
        if not os.path.isabs(img_path):
            candidate = os.path.join(ep_dir, "images", img_path)
            if os.path.exists(candidate):
                img_path = candidate
            else:
                candidate2 = os.path.join(ep_dir, "images_source_raw", img_path)
                if os.path.exists(candidate2):
                    img_path = candidate2

        dur = float(pd["duration"])
        # Add transition padding for crossfade
        clip_t = dur + (trans_duration if idx < len(page_displays) - 1 else 0.5)
        cmd.extend(["-loop", "1", "-t", f"{clip_t:.3f}", "-i", img_path])

    # 2. Add Audio input
    audio_input_idx = len(page_displays)
    cmd.extend(["-i", audio_path])

    # 3. Build Filter Complex
    filter_chains = []
    num_clips = len(page_displays)

    # Process each clip: (Background blur + Foreground aspect-centered + subtle Ken Burns zoom)
    for i in range(num_clips):
        dur = float(page_displays[i]["duration"])
        clip_frames = max(1, int(round((dur + trans_duration) * fps)))
        
        # Subtle zoom equation
        zoom_speed = 0.0006
        zoom_expr = f"min(zoom+{zoom_speed:.6f},1.15)"
        
        filter_chains.append(
            f"[{i}:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
            f"boxblur=20:5,setsar=1[bg_{i}];"
            f"[{i}:v]scale=-1:1080,setsar=1[fg_{i}];"
            f"[bg_{i}][fg_{i}]overlay=(W-w)/2:(H-h)/2:shortest=1[comp_{i}];"
            f"[comp_{i}]zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={clip_frames}:s=1920x1080:fps={fps}[clip_{i}]"
        )

    # Chain clips with xfade transitions
    if num_clips == 1:
        last_v = "clip_0"
    else:
        current_offset = float(page_displays[0]["duration"])
        filter_chains.append(
            f"[clip_0][clip_1]xfade=transition=fade:duration={trans_duration:.2f}:offset={current_offset:.3f}[v_xfade_1]"
        )
        last_v = "v_xfade_1"

        for k in range(2, num_clips):
            current_offset += float(page_displays[k - 1]["duration"]) - trans_duration
            next_v = f"v_xfade_{k}"
            filter_chains.append(
                f"[{last_v}][clip_{k}]xfade=transition=fade:duration={trans_duration:.2f}:offset={current_offset:.3f}[{next_v}]"
            )
            last_v = next_v

    # Audio loudness normalization
    filter_chains.append(
        f"[{audio_input_idx}:a]loudnorm=I={target_lufs}:TP={target_tp}:LRA=11[a_norm]"
    )

    full_filter_str = ";\n".join(filter_chains)

    # Write filter complex to a temporary script file to prevent Windows command line length limits
    filter_script_path = os.path.join(ep_dir, "ffmpeg_filter_script.txt")
    with open(filter_script_path, "w", encoding="utf-8") as f:
        f.write(full_filter_str)

    cmd.extend([
        "-filter_complex_script", filter_script_path,
        "-map", f"[{last_v}]",
        "-map", "[a_norm]",
        "-c:v", working_encoder,
        "-pix_fmt", "yuv420p"
    ])
    cmd.extend(extra_args)
    cmd.extend([
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        output_video_path
    ])

    stderr_log_path = os.path.join(ep_dir, "ffmpeg_filtergraph_stderr.log")
    with open(stderr_log_path, "w", encoding="utf-8") as stderr_f:
        logger.info("Executing native FFmpeg filter complex rendering...")
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=stderr_f, cwd=ep_dir)

    if proc.returncode != 0:
        with open(stderr_log_path, "r", encoding="utf-8") as err_f:
            err_msg = err_f.read().strip()
        logger.error(f"FFmpeg filtergraph rendering failed: {err_msg[:500]}")
        raise RuntimeError(f"FFmpeg filtergraph failed (code {proc.returncode}): {err_msg[-400:]}")

    # Clean up script file
    try:
        if os.path.exists(filter_script_path):
            os.remove(filter_script_path)
    except Exception:
        pass

    return True
