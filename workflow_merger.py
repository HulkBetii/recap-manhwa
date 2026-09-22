import os
import shutil
import re
import json
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("WorkflowMerger")

def shift_srt_time(time_str: str, offset_seconds: float) -> str:
    """Shift an SRT timestamp string (HH:MM:SS,mmm or HH:MM:SS.mmm) by offset_seconds."""
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})[,\.](\d{3})", time_str.strip())
    if not match:
        return time_str
    hrs, mins, secs, msecs = map(int, match.groups())
    total_ms = (hrs * 3600 + mins * 60 + secs) * 1000 + msecs + int(offset_seconds * 1000)
    total_ms = max(0, total_ms)

    new_hrs = total_ms // 3600000
    rem = total_ms % 3600000
    new_mins = rem // 60000
    rem = rem % 60000
    new_secs = rem // 1000
    new_msecs = rem % 1000

    return f"{new_hrs:02d}:{new_mins:02d}:{new_secs:02d},{new_msecs:03d}"


def merge_srt_files(srt_paths: List[str], video_durations: List[float], output_srt_path: str) -> bool:
    """Merge multiple SRT subtitle files into a single continuous SRT file with offset correction."""
    merged_lines = []
    global_index = 1
    current_offset = 0.0

    for idx, srt_path in enumerate(srt_paths):
        dur = video_durations[idx] if idx < len(video_durations) else 0.0
        if not srt_path or not os.path.exists(srt_path):
            current_offset += dur
            continue

        try:
            with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Failed to read SRT file {srt_path}: {e}")
            current_offset += dur
            continue

        blocks = re.split(r'\n\s*\n', content.replace('\r\n', '\n'))
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.split('\n')
            if len(lines) < 2:
                continue

            time_line_idx = 1
            if "-->" in lines[0]:
                time_line_idx = 0

            time_match = re.search(r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})", lines[time_line_idx])
            if not time_match:
                continue

            start_str, end_str = time_match.groups()
            new_start = shift_srt_time(start_str, current_offset)
            new_end = shift_srt_time(end_str, current_offset)
            sub_text = "\n".join(lines[time_line_idx+1:])

            merged_lines.append(f"{global_index}")
            merged_lines.append(f"{new_start} --> {new_end}")
            merged_lines.append(sub_text)
            merged_lines.append("")
            global_index += 1

        current_offset += dur

    try:
        os.makedirs(os.path.dirname(output_srt_path), exist_ok=True)
        with open(output_srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(merged_lines))
        return True
    except Exception as e:
        logger.error(f"Failed to write merged SRT {output_srt_path}: {e}")
        return False


def get_task_available_episodes(task: Any) -> Dict[str, Any]:
    """
    Inspect a workflow task to find all rendered episode videos and existing merged videos.
    """
    artifacts = getattr(task, "artifacts", {}) or {}
    download_dir = artifacts.get("download_dir")
    folder_name = artifacts.get("download_folder_name") or (os.path.basename(download_dir) if download_dir else "recap")

    if not download_dir or not os.path.isdir(download_dir):
        # Fallback to downloads/{folder_name}
        candidate_dir = os.path.join("downloads", folder_name)
        if os.path.isdir(candidate_dir):
            download_dir = candidate_dir

    episodes = []
    if download_dir and os.path.isdir(download_dir):
        for entry in os.listdir(download_dir):
            if entry.startswith("episode_") and os.path.isdir(os.path.join(download_dir, entry)):
                try:
                    ep_num = int(entry.replace("episode_", ""))
                    video_path = os.path.join(download_dir, entry, "video.mp4")
                    srt_path = os.path.join(download_dir, entry, "transcript.srt")
                    if os.path.isfile(video_path):
                        size_mb = round(os.path.getsize(video_path) / (1024 * 1024), 2)
                        has_srt = os.path.isfile(srt_path)
                        episodes.append({
                            "episode": ep_num,
                            "folder": entry,
                            "video_path": video_path,
                            "video_url": f"/downloads/{folder_name}/{entry}/video.mp4",
                            "has_srt": has_srt,
                            "subtitle_url": f"/downloads/{folder_name}/{entry}/transcript.srt" if has_srt else "",
                            "size_mb": size_mb
                        })
                except ValueError:
                    continue

    episodes.sort(key=lambda x: x["episode"])
    ep_numbers = [e["episode"] for e in episodes]

    # Existing merged videos in artifacts or output folder
    merged_videos = artifacts.get("merged_videos") or []
    if not isinstance(merged_videos, list):
        merged_videos = []

    # Check output folder for any existing merged videos on disk
    output_dir = os.path.join(download_dir, "output") if download_dir else None
    if output_dir and os.path.isdir(output_dir):
        registered_files = {mv.get("file_name") for mv in merged_videos if isinstance(mv, dict)}
        for fname in os.listdir(output_dir):
            if fname.endswith(".mp4") and fname not in registered_files:
                fpath = os.path.join(output_dir, fname)
                size_mb = round(os.path.getsize(fpath) / (1024 * 1024), 2)
                srt_fname = os.path.splitext(fname)[0] + ".srt"
                has_srt = os.path.isfile(os.path.join(output_dir, srt_fname))
                
                # Check if matches pattern folder_epX_Y.mp4
                match = re.search(r"_ep(\d+)_(\d+)\.mp4$", fname)
                from_ep = int(match.group(1)) if match else None
                to_ep = int(match.group(2)) if match else None

                merged_videos.append({
                    "id": f"merged_{fname}",
                    "name": fname.replace(".mp4", ""),
                    "file_name": fname,
                    "from_ep": from_ep,
                    "to_ep": to_ep,
                    "video_url": f"/downloads/{folder_name}/output/{fname}",
                    "has_srt": has_srt,
                    "subtitle_url": f"/downloads/{folder_name}/output/{srt_fname}" if has_srt else "",
                    "size_mb": size_mb,
                    "created_at": datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%d %H:%M:%S")
                })

    t_id = getattr(task, "id", "")
    t_title = getattr(task, "comic_title", folder_name)

    return {
        "task_id": t_id,
        "identifier": t_id or folder_name,
        "comic_title": t_title,
        "title": t_title,
        "download_folder_name": folder_name,
        "folder_name": folder_name,
        "available_episodes": ep_numbers,
        "episodes_detail": episodes,
        "min_episode": min(ep_numbers) if ep_numbers else None,
        "max_episode": max(ep_numbers) if ep_numbers else None,
        "total_rendered": len(episodes),
        "total_episodes": len(episodes),
        "merged_videos": merged_videos
    }



async def merge_episode_ranges_for_task(
    task: Any,
    ranges: List[Dict[str, Any]],
    ffmpeg_exe: Optional[str] = None
) -> Dict[str, Any]:
    """
    Concatenate / split rendered episodes for a task based on requested ranges.
    Reuses already rendered videos without re-encoding (FFmpeg concat demuxer).
    
    ranges: List of {"from_ep": int, "to_ep": int, "custom_name": Optional[str]}
    """
    from app import find_ffmpeg
    from workflow_stages_2 import get_video_duration

    if ffmpeg_exe is None:
        ffmpeg_exe = find_ffmpeg()

    artifacts = getattr(task, "artifacts", {}) or {}
    download_dir = artifacts.get("download_dir")
    folder_name = artifacts.get("download_folder_name") or (os.path.basename(download_dir) if download_dir else "recap")

    if not download_dir or not os.path.isdir(download_dir):
        candidate_dir = os.path.join("downloads", folder_name)
        if os.path.isdir(candidate_dir):
            download_dir = candidate_dir
        else:
            raise ValueError(f"Thư mục tải của nhiệm vụ không tồn tại: {download_dir}")

    output_dir = os.path.join(download_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    if "merged_videos" not in artifacts or not isinstance(artifacts["merged_videos"], list):
        artifacts["merged_videos"] = []

    created_results = []
    errors = []

    for r_idx, r in enumerate(ranges):
        try:
            from_ep = int(r.get("from_ep"))
            to_ep = int(r.get("to_ep"))
            custom_name = str(r.get("custom_name", "")).strip()
        except (ValueError, TypeError):
            errors.append(f"Khoảng tập #{r_idx+1} không hợp lệ.")
            continue

        if from_ep > to_ep:
            errors.append(f"Tập bắt đầu ({from_ep}) không được lớn hơn tập kết thúc ({to_ep}).")
            continue

        episodes_to_merge = list(range(from_ep, to_ep + 1))
        # Validate that all episode videos exist
        missing_eps = []
        video_paths = []
        srt_paths = []
        video_durations = []

        for ep in episodes_to_merge:
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            v_path = os.path.join(ep_dir, "video.mp4")
            s_path = os.path.join(ep_dir, "transcript.srt")
            if not os.path.isfile(v_path):
                missing_eps.append(ep)
            else:
                video_paths.append(v_path)
                srt_paths.append(s_path if os.path.isfile(s_path) else None)
                dur = get_video_duration(v_path, ffmpeg_exe)
                video_durations.append(dur)

        if missing_eps:
            errors.append(f"Không tìm thấy video đã render của tập: {missing_eps} trong khoảng ({from_ep} → {to_ep}).")
            continue

        # Sanitize filename
        if custom_name:
            clean_label = re.sub(r'[^\w\s-]', '', custom_name).strip().replace(' ', '_')
            if not clean_label:
                clean_label = f"ep{from_ep}_{to_ep}"
            final_video_name = f"{folder_name}_{clean_label}.mp4"
            final_srt_name = f"{folder_name}_{clean_label}.srt"
            display_title = custom_name
        else:
            final_video_name = f"{folder_name}_ep{from_ep}_{to_ep}.mp4"
            final_srt_name = f"{folder_name}_ep{from_ep}_{to_ep}.srt"
            display_title = f"Tập {from_ep} - {to_ep}"

        final_video_path = os.path.join(output_dir, final_video_name)
        final_srt_path = os.path.join(output_dir, final_srt_name)

        # Merge process
        if len(episodes_to_merge) == 1:
            # Single episode copy
            shutil.copy2(video_paths[0], final_video_path)
            if srt_paths[0] and os.path.isfile(srt_paths[0]):
                shutil.copy2(srt_paths[0], final_srt_path)
        else:
            # Multi-episode fast concat demuxer
            concat_list_path = os.path.join(download_dir, f"concat_list_{from_ep}_{to_ep}_{r_idx}.txt")
            try:
                with open(concat_list_path, "w", encoding="utf-8") as f:
                    for v_path in video_paths:
                        rel_path = os.path.relpath(v_path, download_dir).replace('\\', '/')
                        f.write(f"file '{rel_path}'\n")

                cmd = [
                    ffmpeg_exe, "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_list_path,
                    "-c", "copy",
                    "-movflags", "faststart",
                    final_video_path
                ]

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=download_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()

                # Fallback to re-encode if stream copy fails for any reason
                if proc.returncode != 0:
                    logger.warning(f"FFmpeg copy concat failed for {from_ep}-{to_ep}, falling back to fast remux: {stderr.decode('utf-8', errors='ignore')}")
                    cmd_remux = [
                        ffmpeg_exe, "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", concat_list_path,
                        "-c:v", "libx264",
                        "-preset", "ultrafast",
                        "-c:a", "aac",
                        "-movflags", "faststart",
                        final_video_path
                    ]
                    proc_remux = await asyncio.create_subprocess_exec(
                        *cmd_remux,
                        cwd=download_dir,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await proc_remux.communicate()

                # Merge SRT subtitles
                merge_srt_files(srt_paths, video_durations, final_srt_path)

            finally:
                if os.path.exists(concat_list_path):
                    try:
                        os.remove(concat_list_path)
                    except Exception:
                        pass

        # Calculate final metadata
        size_mb = round(os.path.getsize(final_video_path) / (1024 * 1024), 2) if os.path.isfile(final_video_path) else 0.0
        total_duration = sum(video_durations)
        has_srt = os.path.isfile(final_srt_path)

        merged_record = {
            "id": f"merged_{from_ep}_{to_ep}_{int(datetime.now().timestamp())}",
            "name": display_title,
            "file_name": final_video_name,
            "from_ep": from_ep,
            "to_ep": to_ep,
            "total_episodes": len(episodes_to_merge),
            "video_url": f"/downloads/{folder_name}/output/{final_video_name}",
            "has_srt": has_srt,
            "subtitle_url": f"/downloads/{folder_name}/output/{final_srt_name}" if has_srt else "",
            "duration": total_duration,
            "size_mb": size_mb,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # Replace or append in artifacts["merged_videos"]
        existing_idx = next((i for i, mv in enumerate(artifacts["merged_videos"]) if mv.get("file_name") == final_video_name), None)
        if existing_idx is not None:
            artifacts["merged_videos"][existing_idx] = merged_record
        else:
            artifacts["merged_videos"].append(merged_record)

        created_results.append(merged_record)

    task.artifacts = artifacts

    return {
        "status": "success" if created_results else ("error" if errors else "empty"),
        "created_count": len(created_results),
        "merged_videos": created_results,
        "all_merged_videos": artifacts.get("merged_videos", []),
        "errors": errors
    }


def delete_merged_video_file(task: Any, file_name: str) -> bool:
    """Delete a merged video output file and remove it from task artifacts."""
    artifacts = getattr(task, "artifacts", {}) or {}
    download_dir = artifacts.get("download_dir")
    folder_name = artifacts.get("download_folder_name") or (os.path.basename(download_dir) if download_dir else "recap")

    if not download_dir or not os.path.isdir(download_dir):
        candidate_dir = os.path.join("downloads", folder_name)
        if os.path.isdir(candidate_dir):
            download_dir = candidate_dir

    if download_dir:
        output_dir = os.path.join(download_dir, "output")
        v_path = os.path.join(output_dir, file_name)
        s_path = os.path.join(output_dir, os.path.splitext(file_name)[0] + ".srt")
        if os.path.isfile(v_path):
            try:
                os.remove(v_path)
            except Exception as e:
                logger.warning(f"Could not remove {v_path}: {e}")
        if os.path.isfile(s_path):
            try:
                os.remove(s_path)
            except Exception as e:
                logger.warning(f"Could not remove {s_path}: {e}")

    # Remove from artifacts
    merged_videos = artifacts.get("merged_videos") or []
    if isinstance(merged_videos, list):
        artifacts["merged_videos"] = [mv for mv in merged_videos if mv.get("file_name") != file_name]
        task.artifacts = artifacts
        return True

    return False
