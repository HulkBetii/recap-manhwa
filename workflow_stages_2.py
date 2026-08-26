import os
import json
import asyncio
import re
import time
import subprocess
import shutil
from PIL import Image
from workflow_base import BaseStage, StageState, WorkflowContext, check_episode_completed
from recap_schema import load_recap_dicts
from artifact_cache import (
    EpisodeStageCache,
    stage_fingerprint,
    validate_mp4_file,
    validate_nonempty_file,
    validate_srt_file,
)
from tts_settings import normalize_tts_voice_mode

class Stage7_NarrationAggregation(BaseStage):
    @property
    def name(self) -> str: return "Stage 7 - Narration Aggregation"
    @property
    def weight(self) -> float: return 0.02

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        download_dir = task.artifacts.get("download_dir")
        
        total_episodes = to_ep - from_ep + 1
        for idx, ep in enumerate(range(from_ep, to_ep + 1)):
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            
            await context.start_episode(ep)
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            recap_json_path = os.path.join(ep_dir, "recap.json")
            narration_txt_path = os.path.join(ep_dir, "narration.txt")
            cache = EpisodeStageCache(ep_dir)
            fingerprint = stage_fingerprint(task, "narration", ep, input_paths=[recap_json_path])
            if cache.is_current(
                stage="narration",
                fingerprint=fingerprint,
                outputs=[narration_txt_path],
                validate=lambda: os.path.isfile(narration_txt_path) and os.path.getsize(narration_txt_path) > 0,
            ):
                await context.log(f"Tập {ep}: Cache narration hợp lệ. Bỏ qua tổng hợp.", "success")
                await context.complete_episode(ep)
                await context.update_stage_progress(self.name, ((idx + 1) / total_episodes) * 100.0)
                continue
            
            if not os.path.exists(recap_json_path):
                await context.fail_episode(ep, "Thiếu recap.json.")
                return False
                
            segments = load_recap_dicts(recap_json_path)
                
            speech_list = []
            for seg in segments:
                speech = seg.get("speech", "").strip()
                if speech: speech_list.append(speech)
                    
            aggregated_narration = " ".join(speech_list)
            narration_temp_path = narration_txt_path + ".tmp"
            with open(narration_temp_path, "w", encoding="utf-8") as nf:
                nf.write(aggregated_narration)
            os.replace(narration_temp_path, narration_txt_path)
            cache.commit(stage="narration", fingerprint=fingerprint, outputs=[narration_txt_path])
                
            await context.log(f"Tập {ep}: Tổng hợp xong narration.txt ({len(aggregated_narration)} ký tự).", "success")
            await context.complete_episode(ep)
            await context.update_stage_progress(self.name, ((idx + 1) / total_episodes) * 100.0)
        return True

class Stage8_LocalTTS(BaseStage):
    @property
    def name(self) -> str: return "Stage 8 - Local TTS"
    @property
    def weight(self) -> float: return 0.15

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        download_dir = task.artifacts.get("download_dir")
        
        language = task.payload.get("language", "vi")
        default_voice = "auto"
        voice_id = normalize_tts_voice_mode(task.payload.get("voice_id", default_voice), default=default_voice)
        ref_audio_path = task.payload.get("ref_audio_path")

        total_episodes = to_ep - from_ep + 1
        completed_eps = 0

        async def process_episode_tts(ep):
            nonlocal completed_eps
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            
            await context.start_episode(ep)
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            
            narration_txt_path = os.path.join(ep_dir, "narration.txt")
            if not os.path.exists(narration_txt_path):
                await context.fail_episode(ep, "Thiếu narration.txt.")
                return False
                
            with open(narration_txt_path, "r", encoding="utf-8") as f:
                narration_text = f.read().strip()
                
            if not narration_text:
                await context.fail_episode(ep, "Nội dung thuyết minh rỗng.")
                return False

            audio_path = os.path.join(ep_dir, "audio.mp3")
            srt_path = os.path.join(ep_dir, "transcript.srt")
            cache_path = os.path.join(ep_dir, "tts_config.json")
            cache = EpisodeStageCache(ep_dir)
            fingerprint = stage_fingerprint(task, "tts", ep, input_paths=[narration_txt_path, ref_audio_path])
            if cache.is_current(
                stage="tts",
                fingerprint=fingerprint,
                outputs=[audio_path, cache_path],
                validate=lambda: (
                    validate_nonempty_file(audio_path)
                    and validate_srt_file(srt_path)
                    and validate_nonempty_file(cache_path)
                ),
            ):
                await context.log(f"Tập {ep}: Cache TTS hợp lệ. Bỏ qua sinh âm thanh.", "success")
                await context.complete_episode(ep)
                completed_eps += 1
                await context.update_stage_progress(self.name, (completed_eps / total_episodes) * 100.0)
                return True
                
            await context.log(f"Tập {ep}: Đang sinh local TTS...", "info")

            from tts_provider import generate_tts
            audio_temp_path = audio_path + ".tmp.mp3"
            srt_temp_path = srt_path + ".tmp.srt"
            success = await generate_tts(narration_text, audio_temp_path, srt_temp_path, voice_id, ref_audio_path)
            if not success:
                for temp_path in (audio_temp_path, srt_temp_path):
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                await context.fail_episode(ep, "Lỗi khi tạo local TTS hoặc Whisper transcript.")
                return False
            os.replace(audio_temp_path, audio_path)
            os.replace(srt_temp_path, srt_path)

            cache_temp_path = cache_path + ".tmp"
            with open(cache_temp_path, "w", encoding="utf-8") as cf:
                json.dump({
                    "voice_id": voice_id,
                    "narration_hash": stage_fingerprint(task, "tts", ep, input_paths=[narration_txt_path]),
                    "ref_audio_path": ref_audio_path,
                }, cf, ensure_ascii=False, indent=4)
            os.replace(cache_temp_path, cache_path)
            cache.commit(stage="tts", fingerprint=fingerprint, outputs=[audio_path, cache_path])

            await context.complete_episode(ep)
            completed_eps += 1
            await context.update_stage_progress(self.name, (completed_eps / total_episodes) * 100.0)
            return True

        concurrency = task.payload.get("concurrency", 5)
        sem = asyncio.Semaphore(concurrency)
        async def process_episode_tts_sem(ep):
            async with sem:
                return await process_episode_tts(ep)

        episodes = list(range(from_ep, to_ep + 1))
        tasks = [process_episode_tts_sem(ep) for ep in episodes]
        results = await asyncio.gather(*tasks)
        return all(results)


class Stage9_SubtitleNormalization(BaseStage):
    @property
    def name(self) -> str: return "Stage 9 - Subtitle Normalization"
    @property
    def weight(self) -> float: return 0.03

    async def execute(self, context: WorkflowContext) -> bool:
        from app import parse_time_to_seconds
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        download_dir = task.artifacts.get("download_dir")
        
        def format_time(seconds: float) -> str:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int(round((seconds - int(seconds)) * 1000))
            if ms == 1000:
                s += 1
                ms = 0
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        total_episodes = to_ep - from_ep + 1
        completed_eps = 0

        async def process_episode_subtitles(ep):
            nonlocal completed_eps
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            
            await context.start_episode(ep)
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            srt_path = os.path.join(ep_dir, "transcript.srt")
            recap_json_path = os.path.join(ep_dir, "recap.json")
            audio_path = os.path.join(ep_dir, "audio.mp3")
            cache = EpisodeStageCache(ep_dir)
            fingerprint = stage_fingerprint(task, "subtitles", ep, input_paths=[recap_json_path, audio_path])
            if cache.is_current(
                stage="subtitles",
                fingerprint=fingerprint,
                outputs=[srt_path],
                validate=lambda: validate_srt_file(srt_path),
            ):
                await context.log(f"Tập {ep}: Cache phụ đề hợp lệ. Bỏ qua chuẩn hóa.", "success")
                await context.complete_episode(ep)
                completed_eps += 1
                await context.update_stage_progress(self.name, (completed_eps / total_episodes) * 100.0)
                return True
            
            if not os.path.exists(srt_path) or not os.path.exists(recap_json_path):
                await context.fail_episode(ep, "Thiếu transcript.srt hoặc recap.json.")
                return False
                
            with open(srt_path, "r", encoding="utf-8") as f:
                srt_content = f.read().replace('\r\n', '\n').strip()
                
            segments = load_recap_dicts(recap_json_path)

            pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\n(.*?)(?=\n\n|\Z)"
            matches = re.findall(pattern, srt_content, re.DOTALL)
            subtitles = []
            for num, start_str, end_str, text in matches:
                text_clean = " ".join([l.strip() for l in text.split('\n') if l.strip()])
                text_clean = re.sub(r'\[speed_[a-z0-9_]+\]', '', text_clean, flags=re.IGNORECASE).strip()
                text_clean = " ".join(text_clean.split())
                subtitles.append({
                    "start": parse_time_to_seconds(start_str),
                    "end": parse_time_to_seconds(end_str),
                    "text": text_clean
                })

            if not subtitles:
                await context.fail_episode(ep, "Không thể phân tích tệp SRT.")
                return False

            def clean_w(word):
                return re.sub(r'[^a-z0-9]', '', word.lower())

            segment_word_counts = []
            for seg in segments:
                speech = seg.get("speech", "")
                words = [clean_w(w) for w in speech.split() if clean_w(w)]
                segment_word_counts.append(len(words))

            segment_ranges = []
            current_idx = 0
            for count in segment_word_counts:
                segment_ranges.append((current_idx, current_idx + count))
                current_idx += count
            total_segment_words = current_idx

            if len(subtitles) == len(segments):
                for idx_sub, sub in enumerate(subtitles):
                    sub["matched_segment_idx"] = idx_sub
            else:
                sub_word_counts = []
                total_subtitle_words = 0
                for sub in subtitles:
                    words = [clean_w(w) for w in sub["text"].split() if clean_w(w)]
                    sub_word_counts.append(len(words))
                    total_subtitle_words += len(words)

                ratio = total_segment_words / total_subtitle_words if total_subtitle_words > 0 else 1

                prev_words = 0
                for s_idx, sub in enumerate(subtitles):
                    count = sub_word_counts[s_idx]
                    mid_word_idx = prev_words + count // 2 if count > 0 else prev_words
                    scaled_word_idx = mid_word_idx * ratio
                    
                    matched_seg = len(segments) - 1
                    for seg_idx, (start, end) in enumerate(segment_ranges):
                        if start <= scaled_word_idx < end:
                            matched_seg = seg_idx
                            break
                    sub["matched_segment_idx"] = matched_seg
                    prev_words += count

            normalized_srt_entries = []
            last_end_time = 0.0
            
            for seg_idx, seg in enumerate(segments):
                matched_subs = [sub for sub in subtitles if sub.get("matched_segment_idx") == seg_idx]
                if matched_subs:
                    start_time = min(sub["start"] for sub in matched_subs)
                    end_time = max(sub["end"] for sub in matched_subs)
                else:
                    start_time = last_end_time
                    word_count = len(seg.get("speech", "").split())
                    estimated_dur = max(2.0, word_count * 0.4)
                    end_time = start_time + estimated_dur
                
                if start_time < last_end_time: start_time = last_end_time
                if end_time <= start_time: end_time = start_time + 1.0
                
                last_end_time = end_time
                normalized_srt_entries.append({
                    "start": start_time,
                    "end": end_time,
                    "text": seg.get("speech", "")
                })

            srt_temp_path = srt_path + ".tmp"
            with open(srt_temp_path, "w", encoding="utf-8") as sf:
                for s_idx, sub in enumerate(normalized_srt_entries, 1):
                    start_str = format_time(sub["start"])
                    end_str = format_time(sub["end"])
                    sf.write(f"{s_idx}\n{start_str} --> {end_str}\n{sub['text']}\n\n")
            os.replace(srt_temp_path, srt_path)
            cache.commit(stage="subtitles", fingerprint=fingerprint, outputs=[srt_path])

            await context.log(f"Tập {ep}: Chuẩn hóa phụ đề thành công ({len(normalized_srt_entries)} mục).", "success")
            await context.complete_episode(ep)
            completed_eps += 1
            await context.update_stage_progress(self.name, (completed_eps / total_episodes) * 100.0)
            return True

        concurrency = task.payload.get("concurrency", 5)
        sem = asyncio.Semaphore(concurrency)
        async def process_episode_subtitles_sem(ep):
            async with sem:
                return await process_episode_subtitles(ep)

        episodes = list(range(from_ep, to_ep + 1))
        tasks = [process_episode_subtitles_sem(ep) for ep in episodes]
        results = await asyncio.gather(*tasks)
        return all(results)

def parse_time_to_seconds_local(t_str):
    t_str = t_str.replace(',', '.')
    parts = t_str.split(':')
    h = float(parts[0])
    m = float(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s

def parse_srt_file(srt_path):
    import re
    if not os.path.exists(srt_path):
        return []
    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read().replace('\r\n', '\n').strip()
        pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\n([\s\S]*?)(?=\n\n|\Z)"
        matches = re.findall(pattern, content)
        subtitles = []
        for num, start_str, end_str, text in matches:
            subtitles.append({
                "start": parse_time_to_seconds_local(start_str),
                "end": parse_time_to_seconds_local(end_str),
                "text": text.strip()
            })
        return subtitles
    except Exception:
        return []

def draw_subtitles_on_frame(image, text, font_size=40):
    from PIL import ImageDraw, ImageFont
    if not text:
        return
    draw = ImageDraw.Draw(image)
    
    # Try to load a clean sans-serif system font
    font = None
    font_paths = [
        "arial.ttf",
        "tahoma.ttf",
        "msjh.ttc",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\tahoma.ttf"
    ]
    for path in font_paths:
        try:
            font = ImageFont.truetype(path, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
        
    # Text wrapping helper
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        current_line.append(word)
        test_line = " ".join(current_line)
        try:
            w = draw.textlength(test_line, font=font)
        except Exception:
            w = len(test_line) * (font_size * 0.6)
            
        if w > 1600:
            current_line.pop()
            lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
        
    line_height = font_size + 10
    total_height = len(lines) * line_height
    y = 1080 - 100 - total_height
    
    for line in lines:
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(line) * (font_size * 0.6)
            
        x = (1920 - w) // 2
        
        # Shadow/Outline for visibility
        shadow_offsets = [(-2, -2), (-2, 2), (2, -2), (2, 2), (0, -2), (0, 2), (-2, 0), (2, 0)]
        for dx, dy in shadow_offsets:
            draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
            
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += line_height


def detect_content_bounds(img: Image) -> tuple:
    import numpy as np
    # Convert to grayscale
    gray = np.array(img.convert("L"))
    h, w = gray.shape
    if h < 20 or w < 20:
        return 0, 0, w, h

    # Sample border pixels to find background color
    border_pixels = np.concatenate([
        gray[0, :],          # top row
        gray[-1, :],         # bottom row
        gray[:, 0],          # left col
        gray[:, -1]          # right col
    ])
    bg_color = np.median(border_pixels)

    # Mask foreground pixels
    if bg_color > 127:
        foreground_mask = gray < (bg_color - 15)
    else:
        foreground_mask = gray > (bg_color + 15)

    coords = np.argwhere(foreground_mask)
    if coords.size > 0:
        y_min, x_min = coords.min(axis=0)
        y_max, x_max = coords.max(axis=0)
        # Add padding
        pad = 10
        x = max(0, int(x_min - pad))
        y = max(0, int(y_min - pad))
        width = min(w - x, int(x_max - x_min + 2 * pad))
        height = min(h - y, int(y_max - y_min + 2 * pad))
        # Don't let it be too small
        if width > 10 and height > 10:
            return x, y, width, height

    return 0, 0, w, h


import math

def ease_in_out_sine(t: float) -> float:
    return 0.5 * (1 - math.cos(t * math.pi))

def ease_out_quart(t: float) -> float:
    return 1 - (1 - t) ** 4

def ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4 * (t ** 3)
    else:
        return 1 - ((-2 * t + 2) ** 3) / 2


def apply_motion_blur(img_np, dx: float, dy: float):
    import cv2
    import numpy as np

    dist = np.sqrt(dx**2 + dy**2)
    if dist < 0.5:
        return img_np

    # Cap motion blur size between 3 and 5 pixels, forcing it to be odd
    raw_size = int(np.clip(dist * 0.4, 2, 5))
    blur_size = raw_size if raw_size % 2 == 1 else raw_size + 1
    if blur_size < 3:
        return img_np

    kernel = np.zeros((blur_size, blur_size))
    center = blur_size // 2

    # Vertical motion
    if abs(dy) > abs(dx) * 1.5:
        kernel[:, center] = 1.0
    # Horizontal motion
    elif abs(dx) > abs(dy) * 1.5:
        kernel[center, :] = 1.0
    # Diagonal motion
    else:
        for i in range(blur_size):
            kernel[i, i] = 1.0

    kernel /= kernel.sum()
    return cv2.filter2D(img_np, -1, kernel)


import random

class CameraPlanner:
    @staticmethod
    def generate_camera_plan(page_num: int, duration: float, bounds: tuple, transition: str = "cross_fade") -> dict:
        cb_x, cb_y, W_c, H_c = bounds
        
        target_aspect = 960 / 1080
        
        # Classification & base scale calculation
        viewport_h_in_page = W_c / target_aspect
        ratio = H_c / viewport_h_in_page
        
        if ratio <= 1.2:
            page_type = "SHORT"
            # Fit height -> scale animation
            h_base = H_c
            w_base = H_c * target_aspect
        else:
            page_type = "LONG"
            # Fit width -> scroll animation
            w_base = W_c
            h_base = W_c / target_aspect
            
        # Choose easing
        easing = random.choice(["easeInOutSine", "easeOutQuart", "easeInOutCubic"])
        
        # Adaptive speed & overrides based on duration
        if duration < 2.0:
            # Overrides to small zoom only
            animation_type = "zoom_in"
            keyframes = [
                {"time": 0.0, "x": W_c / 2, "y": H_c / 2, "scale": 1.0},
                {"time": duration, "x": W_c / 2, "y": H_c / 2, "scale": 1.03}
            ]
            return {
                "page": page_num,
                "duration": duration,
                "animation_type": animation_type,
                "easing": easing,
                "keyframes": keyframes,
                "transition": transition
            }
            
        if page_type == "SHORT":
            # Subtle random movements
            animation_type = random.choices(
                ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"],
                weights=[40, 15, 15, 15, 7, 8],
                k=1
            )[0]
            
            # Zoom range depending on duration
            max_zoom = 1.08 if duration >= 5.0 else 1.05
            
            # Calculate panning ranges
            w_cam = w_base / 1.10
            h_cam = h_base / 1.10
            
            # Pan bounds
            pan_x_range = max(0.0, (W_c - w_cam) * 0.4)
            pan_y_range = max(0.0, (H_c - h_cam) * 0.4)
            
            if animation_type == "zoom_in":
                keyframes = [
                    {"time": 0.0, "x": W_c / 2, "y": H_c / 2, "scale": 1.0},
                    {"time": duration, "x": W_c / 2, "y": H_c / 2, "scale": max_zoom}
                ]
            elif animation_type == "zoom_out":
                keyframes = [
                    {"time": 0.0, "x": W_c / 2, "y": H_c / 2, "scale": max_zoom},
                    {"time": duration, "x": W_c / 2, "y": H_c / 2, "scale": 1.0}
                ]
            elif animation_type == "pan_left" and pan_x_range > 0:
                keyframes = [
                    {"time": 0.0, "x": W_c / 2 + pan_x_range, "y": H_c / 2, "scale": 1.10},
                    {"time": duration, "x": W_c / 2 - pan_x_range, "y": H_c / 2, "scale": 1.10}
                ]
            elif animation_type == "pan_right" and pan_x_range > 0:
                keyframes = [
                    {"time": 0.0, "x": W_c / 2 - pan_x_range, "y": H_c / 2, "scale": 1.10},
                    {"time": duration, "x": W_c / 2 + pan_x_range, "y": H_c / 2, "scale": 1.10}
                ]
            elif animation_type == "pan_up" and pan_y_range > 0:
                keyframes = [
                    {"time": 0.0, "x": W_c / 2, "y": H_c / 2 + pan_y_range, "scale": 1.10},
                    {"time": duration, "x": W_c / 2, "y": H_c / 2 - pan_y_range, "scale": 1.10}
                ]
            elif animation_type == "pan_down" and pan_y_range > 0:
                keyframes = [
                    {"time": 0.0, "x": W_c / 2, "y": H_c / 2 - pan_y_range, "scale": 1.10},
                    {"time": duration, "x": W_c / 2, "y": H_c / 2 + pan_y_range, "scale": 1.10}
                ]
            else:
                # Fallback to zoom in if panning is not possible
                keyframes = [
                    {"time": 0.0, "x": W_c / 2, "y": H_c / 2, "scale": 1.0},
                    {"time": duration, "x": W_c / 2, "y": H_c / 2, "scale": max_zoom}
                ]
                animation_type = "zoom_in"
                
        elif page_type == "MEDIUM":
            # Ken Burns pan and zoom
            animation_type = "ken_burns"
            # Random starting/ending scale
            scale_start = 1.0
            scale_end = random.uniform(1.08, 1.15)
            
            # Compute camera boundaries
            w_cam_end = w_base / scale_end
            h_cam_end = h_base / scale_end
            
            pan_x = max(0.0, (W_c - w_cam_end) * 0.4)
            pan_y = max(0.0, (H_c - h_cam_end) * 0.4)
            
            # Random diagonal directions
            dir_x = random.choice([-1.0, 1.0])
            dir_y = random.choice([-1.0, 1.0])
            
            keyframes = [
                {"time": 0.0, "x": W_c / 2 - dir_x * pan_x * 0.5, "y": H_c / 2 - dir_y * pan_y * 0.5, "scale": scale_start},
                {"time": duration, "x": W_c / 2 + dir_x * pan_x * 0.5, "y": H_c / 2 + dir_y * pan_y * 0.5, "scale": scale_end}
            ]
            
        else: # LONG PAGE
            # Scrolling Top -> Bottom
            animation_type = "scroll_down"
            # Force camera width to fit content box width
            scale = w_base / W_c
            h_cam = W_c / (960 / 1080)
            
            y_start = h_cam / 2
            y_end = H_c - h_cam / 2
            
            if y_end <= y_start:
                # No scrolling needed, center it
                keyframes = [
                    {"time": 0.0, "x": W_c / 2, "y": H_c / 2, "scale": scale},
                    {"time": duration, "x": W_c / 2, "y": H_c / 2, "scale": scale}
                ]
            else:
                if duration > 8.0:
                    # Multi-keyframes
                    keyframes = []
                    num_steps = 4
                    for i in range(num_steps):
                        t_step = (i / (num_steps - 1)) * duration
                        y_step = y_start + (y_end - y_start) * (i / (num_steps - 1))
                        keyframes.append({"time": t_step, "x": W_c / 2, "y": y_step, "scale": scale})
                else:
                    keyframes = [
                        {"time": 0.0, "x": W_c / 2, "y": y_start, "scale": scale},
                        {"time": duration, "x": W_c / 2, "y": y_end, "scale": scale}
                    ]
                    
        return {
            "page": page_num,
            "duration": duration,
            "animation_type": animation_type,
            "easing": easing,
            "keyframes": keyframes,
            "transition": transition
        }


def interpolate_camera_plan(plan: dict, t_local: float) -> tuple:
    keyframes = plan["keyframes"]
    if t_local <= keyframes[0]["time"]:
        return keyframes[0]["x"], keyframes[0]["y"], keyframes[0]["scale"]
    if t_local >= keyframes[-1]["time"]:
        return keyframes[-1]["x"], keyframes[-1]["y"], keyframes[-1]["scale"]

    easing_name = plan.get("easing", "easeInOutSine")
    if easing_name == "easeInOutSine":
        ease_func = ease_in_out_sine
    elif easing_name == "easeOutQuart":
        ease_func = ease_out_quart
    elif easing_name == "easeInOutCubic":
        ease_func = ease_in_out_cubic
    else:
        ease_func = lambda t: t

    for i in range(len(keyframes) - 1):
        kf1 = keyframes[i]
        kf2 = keyframes[i+1]
        if kf1["time"] <= t_local <= kf2["time"]:
            local_t = (t_local - kf1["time"]) / (kf2["time"] - kf1["time"])
            eased_t = ease_func(local_t)
            x = kf1["x"] + (kf2["x"] - kf1["x"]) * eased_t
            y = kf1["y"] + (kf2["y"] - kf1["y"]) * eased_t
            scale = kf1["scale"] + (kf2["scale"] - kf1["scale"]) * eased_t
            return x, y, scale

    return keyframes[-1]["x"], keyframes[-1]["y"], keyframes[-1]["scale"]


class Stage10_EpisodeVideoRendering(BaseStage):
    @property
    def name(self) -> str: return "Stage 10 - Episode Video Rendering"
    @property
    def weight(self) -> float: return 0.15

    async def execute(self, context: WorkflowContext) -> bool:
        from app import find_ffmpeg, get_working_encoder, parse_time_to_seconds
        
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        download_dir = task.artifacts.get("download_dir")
        
        ffmpeg_exe = find_ffmpeg()
        project_dir = os.path.dirname(os.path.abspath(__file__))

        def ensure_transparent_image(path: str, size: tuple):
            if not os.path.exists(path):
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    from PIL import Image
                    img = Image.new("RGBA", size, (0, 0, 0, 0))
                    img.save(path, "PNG")
                    img.close()
                except Exception as e:
                    print(f"Error creating transparent image {path}: {e}")

        # Ensure default logo and overlay exist as transparent PNGs if missing
        ensure_transparent_image(os.path.join(project_dir, "images", "logo.png"), (50, 50))
        ensure_transparent_image(os.path.join(project_dir, "images", "overlay.png"), (1920, 1080))

        logo_path = task.payload.get("logo_path")
        if logo_path:
            logo_path = os.path.abspath(logo_path)
        if not logo_path or not os.path.exists(logo_path):
            logo_path = os.path.join(project_dir, "images", "logo.png")

        overlay_path = task.payload.get("overlay_path")
        if overlay_path:
            overlay_path = os.path.abspath(overlay_path)
        if not overlay_path or not os.path.exists(overlay_path):
            overlay_path = os.path.join(project_dir, "images", "overlay.png")
        subtitles_enabled = False

        def render_episode_video_sync(images_blur_dir, image_files, segments, timings, output_video_path, ffmpeg_exe, working_encoder, audio_path, logo_path, overlay_path, subtitles_enabled_flag, srt_filename, fps=30):
            from PIL import Image, ImageFilter, ImageEnhance
            import subprocess
            import numpy as np
            import cv2
            
            # Start single unified FFmpeg process with high quality settings
            if "nvenc" in str(working_encoder).lower():
                extra_args = ["-preset", "p6", "-cq", "19", "-rc", "constqp", "-b:v", "12M"]
            elif "amf" in str(working_encoder).lower():
                extra_args = ["-rc", "cqp", "-qp_i", "19", "-qp_p", "19", "-b:v", "12M"]
            elif "libx264" in str(working_encoder).lower():
                extra_args = ["-crf", "18", "-preset", "veryfast"]
            else:
                extra_args = ["-b:v", "6M"]
            
            ep_dir = os.path.dirname(output_video_path)
            logo_rel = os.path.relpath(logo_path, ep_dir).replace('\\', '/')
            overlay_rel = os.path.relpath(overlay_path, ep_dir).replace('\\', '/')
            
            filter_complex_str = (
                f"movie={logo_rel} [logo_raw]; [logo_raw]scale=50:50[logo]; "
                f"movie={overlay_rel} [ol_raw]; [ol_raw]scale=1920:1080,format=rgba,colorchannelmixer=aa=0.005[ol]; "
                f"[0:v][ol]overlay[temp1]; [temp1][logo]overlay=25:25[v]"
            )

            cmd = [
                ffmpeg_exe, "-y",
                "-f", "rawvideo",
                "-pix_fmt", "rgb24",
                "-s", "1920x1080",
                "-r", str(fps),
                "-i", "-",               # Raw video from stdin [0:v]
                "-i", audio_path,        # Audio [1:a]
                "-filter_complex", filter_complex_str,
                "-map", "[v]", "-map", "1:a",
                "-c:v", working_encoder,
                "-pix_fmt", "yuv420p"
            ] + extra_args + [
                "-c:a", "aac", "-b:a", "192k", "-shortest", output_video_path
            ]
            
            stderr_log_path = os.path.join(os.path.dirname(output_video_path), "ffmpeg_render_stderr.log")
            stderr_file = open(stderr_log_path, "w", encoding="utf-8")
            
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                cwd=os.path.dirname(output_video_path)
            )
            
            # Parse subtitles from SRT
            subtitles = []
            if subtitles_enabled_flag:
                srt_path = os.path.join(os.path.dirname(output_video_path), srt_filename)
                subtitles = parse_srt_file(srt_path)
                
            # Create flat list of page displays
            page_displays = []
            current_time = 0.0
            for s_idx, seg in enumerate(segments):
                end_time = timings[s_idx]["end"] if s_idx < len(timings) else current_time + 3.0
                segment_duration = end_time - current_time
                if s_idx == len(segments) - 1:
                    segment_duration = max(3.0, segment_duration + 3.0)
                if segment_duration <= 0:
                    segment_duration = 1.0
                
                seg_images = seg.get("images", [])
                for img_obj in seg_images:
                    page = int(img_obj["page"])
                    priority = float(img_obj["priority"])
                    img_dur = segment_duration * priority
                    
                    page_idx = page - 1
                    if 0 <= page_idx < len(image_files):
                        img_file = image_files[page_idx]
                    else:
                        raise ValueError(f"Recap page {page} is outside the available image range 1-{len(image_files)}")
                        
                    page_displays.append({
                        "page": page,
                        "image_file": img_file,
                        "duration": img_dur,
                        "start_time": current_time,
                        "end_time": current_time + img_dur,
                        "segment_index": s_idx
                    })
                    current_time += img_dur

            # Precompute bounds and plans
            bounds_cache_path = os.path.join(ep_dir, "content_bounds_cache.json")
            bounds_cache = {}
            if os.path.exists(bounds_cache_path):
                try:
                    with open(bounds_cache_path, "r", encoding="utf-8") as f:
                        bounds_cache = json.load(f)
                except Exception:
                    pass

            plans = []
            dirty_cache = False
            for idx, pd in enumerate(page_displays):
                img_file = pd["image_file"]
                img_path = os.path.join(images_blur_dir, img_file)
                if img_file in bounds_cache:
                    bounds = tuple(bounds_cache[img_file])
                else:
                    try:
                        with Image.open(img_path) as img:
                            bounds = detect_content_bounds(img)
                            bounds_cache[img_file] = list(bounds)
                            dirty_cache = True
                    except Exception:
                        bounds = (0, 0, 1920, 1080)
                
                is_last_page = (idx == len(page_displays) - 1)
                trans = "dip_to_black" if is_last_page else "cross_fade"
                
                plan = CameraPlanner.generate_camera_plan(pd["page"], pd["duration"], bounds, transition=trans)
                plans.append(plan)
                
            if dirty_cache:
                try:
                    with open(bounds_cache_path, "w", encoding="utf-8") as f:
                        json.dump(bounds_cache, f, indent=4)
                except Exception:
                    pass

            # Page frame rendering helper
            def render_page_frame(img, bg_image, bounds, plan, t_local, dx, dy):
                cb_x, cb_y, W_c, H_c = bounds
                x, y, scale = interpolate_camera_plan(plan, t_local)

                target_aspect = 960 / 1080
                viewport_h_in_page = W_c / target_aspect
                ratio = H_c / viewport_h_in_page
                if ratio <= 1.2:
                    h_base = H_c
                    w_base = H_c * target_aspect
                else:
                    w_base = W_c
                    h_base = W_c / target_aspect
                w_cam = w_base / scale
                h_cam = h_base / scale

                x_img = cb_x + x
                y_img = cb_y + y

                x1 = x_img - w_cam / 2
                y1 = y_img - h_cam / 2
                x2 = x_img + w_cam / 2
                y2 = y_img + h_cam / 2

                x1_clamped = max(cb_x, x1)
                y1_clamped = max(cb_y, y1)
                x2_clamped = min(cb_x + W_c, x2)
                y2_clamped = min(cb_y + H_c, y2)

                w_crop = x2_clamped - x1_clamped
                h_crop = y2_clamped - y1_clamped

                if w_crop < 5 or h_crop < 5:
                    box_to_crop = (cb_x, cb_y, cb_x + W_c, cb_y + H_c)
                    w_crop, h_crop = W_c, H_c
                else:
                    box_to_crop = (x1_clamped, y1_clamped, x2_clamped, y2_clamped)

                aspect_ratio = w_crop / h_crop
                if aspect_ratio > 1.2:
                    scale_factor = 1080 / h_crop
                else:
                    scale_factor = min(960 / w_crop, 1080 / h_crop)
                fg_w = max(1, int(round(w_crop * scale_factor)))
                fg_h = max(1, int(round(h_crop * scale_factor)))

                # Ensure main image width is at least 1/3 of video width
                min_fg_w = 640
                if fg_w < min_fg_w:
                    fg_w = min_fg_w
                    fg_h = int(round(fg_w / aspect_ratio))



                # Crop and resize in one step using float box for sub-pixel accuracy (fixes scroll jitter)
                fg_resized = img.resize((fg_w, fg_h), resample=Image.Resampling.BILINEAR, box=box_to_crop)

                # Apply motion blur on foreground
                fg_np = np.array(fg_resized)
                fg_blurred_np = apply_motion_blur(fg_np, dx, dy)
                fg_resized_blurred = Image.fromarray(fg_blurred_np)

                paste_x = (1920 - fg_w) // 2
                paste_y = (1080 - fg_h) // 2
                
                final_frame = bg_image.copy()
                final_frame.paste(fg_resized_blurred, (paste_x, paste_y))
                
                fg_resized.close()
                fg_resized_blurred.close()
                return final_frame

            # Ensure video duration is aligned with audio duration to prevent cutoffs
            audio_dur = 0.0
            try:
                audio_dur = get_video_duration(audio_path, ffmpeg_exe)
            except Exception:
                pass
            if audio_dur and audio_dur > 0:
                total_duration = max(current_time, audio_dur)
            else:
                total_duration = current_time
            num_frames = int(total_duration * fps)
            loaded_images = {}
            cached_backgrounds = {}
            prev_coords = {}
            pipe_broken = False
            
            def get_img(img_file, t):
                if img_file not in loaded_images:
                    # Close unused images
                    for k in list(loaded_images.keys()):
                        still_needed = False
                        for pd_check in page_displays:
                            if pd_check["image_file"] == k and pd_check["end_time"] > t - 2.0:
                                still_needed = True
                                break
                        if not still_needed:
                            try:
                                loaded_images[k].close()
                            except Exception:
                                pass
                            del loaded_images[k]
                            if k in cached_backgrounds:
                                try:
                                    cached_backgrounds[k].close()
                                except Exception:
                                    pass
                                del cached_backgrounds[k]
                                    
                    img_path = os.path.join(images_blur_dir, img_file)
                    img_open = Image.open(img_path)
                    if img_open.mode != "RGB":
                        img_open = img_open.convert("RGB")
                    loaded_images[img_file] = img_open
                return loaded_images[img_file]

            def get_blurred_background(img_file, img, bounds):
                if img_file not in cached_backgrounds:
                    cb_x, cb_y, W_c, H_c = bounds
                    cropped = img.crop((cb_x, cb_y, cb_x + W_c, cb_y + H_c))
                    
                    bg_scale = max(1920 / W_c, 1080 / H_c)
                    bg_w = max(1920, int(W_c * bg_scale))
                    bg_h = max(1080, int(H_c * bg_scale))
                    bg_resized = cropped.resize((bg_w, bg_h), Image.Resampling.BOX)
                    cropped.close()
                    
                    bg_x1 = (bg_w - 1920) // 2
                    bg_y1 = (bg_h - 1080) // 2
                    bg_cropped = bg_resized.crop((bg_x1, bg_y1, bg_x1 + 1920, bg_y1 + 1080))
                    bg_resized.close()
                    
                    bg_small = bg_cropped.resize((240, 135), Image.Resampling.BOX)
                    bg_small_blurred = bg_small.filter(ImageFilter.GaussianBlur(radius=5))
                    bg_blurred = bg_small_blurred.resize((1920, 1080), Image.Resampling.BILINEAR)
                    bg_small.close()
                    bg_small_blurred.close()
                    bg_cropped.close()
                    
                    enhancer = ImageEnhance.Brightness(bg_blurred)
                    cached_backgrounds[img_file] = enhancer.enhance(0.6)
                    bg_blurred.close()
                return cached_backgrounds[img_file]

            active_idx = 0
            active_sub_idx = 0
            
            try:
                for f_idx in range(num_frames):
                    if pipe_broken:
                        break
                    
                    t = f_idx / fps
                    
                    # Sequential page tracking
                    while active_idx < len(page_displays) - 1 and t >= page_displays[active_idx]["end_time"]:
                        active_idx += 1
                        
                    pd_curr = page_displays[active_idx]
                    
                    # Subtitle checking
                    active_sub = ""
                    if subtitles_enabled_flag and subtitles:
                        # Advance active_sub_idx to match current time t
                        while active_sub_idx < len(subtitles) and t > subtitles[active_sub_idx]["end"]:
                            active_sub_idx += 1
                        # Check if t is within the current subtitle
                        if active_sub_idx < len(subtitles) and subtitles[active_sub_idx]["start"] <= t <= subtitles[active_sub_idx]["end"]:
                            active_sub = subtitles[active_sub_idx]["text"]

                    # Check transitions
                    T_trans = 0.20
                    in_transition = False
                    next_idx = active_idx + 1
                    
                    if next_idx < len(page_displays):
                        pd_next = page_displays[next_idx]
                        t_trans_dur = min(T_trans, pd_curr["duration"] * 0.4, pd_next["duration"] * 0.4)
                        if t >= pd_curr["end_time"] - t_trans_dur:
                            in_transition = True
                            t_trans_start = pd_curr["end_time"] - t_trans_dur
                            
                    if in_transition:
                        # Blend current and next page
                        t_local_curr = t - pd_curr["start_time"]
                        # Interpolate current
                        x_curr, y_curr, scale_curr = interpolate_camera_plan(plans[active_idx], t_local_curr)
                        if active_idx in prev_coords:
                            x_prev, y_prev = prev_coords[active_idx]
                            dx_curr = x_curr - x_prev
                            dy_curr = y_curr - y_prev
                        else:
                            dx_curr, dy_curr = 0.0, 0.0
                        prev_coords[active_idx] = (x_curr, y_curr)
                        
                        img_curr_obj = get_img(pd_curr["image_file"], t)
                        bg_curr_obj = get_blurred_background(pd_curr["image_file"], img_curr_obj, bounds_cache[pd_curr["image_file"]])
                        frame_curr = render_page_frame(img_curr_obj, bg_curr_obj, bounds_cache[pd_curr["image_file"]], plans[active_idx], t_local_curr, dx_curr, dy_curr)
                        
                        # Interpolate next
                        t_local_next = t - t_trans_start
                        x_next, y_next, scale_next = interpolate_camera_plan(plans[next_idx], t_local_next)
                        if next_idx in prev_coords:
                            x_prev, y_prev = prev_coords[next_idx]
                            dx_next = x_next - x_prev
                            dy_next = y_next - y_prev
                        else:
                            dx_next, dy_next = 0.0, 0.0
                        prev_coords[next_idx] = (x_next, y_next)
                        
                        img_next_obj = get_img(pd_next["image_file"], t)
                        bg_next_obj = get_blurred_background(pd_next["image_file"], img_next_obj, bounds_cache[pd_next["image_file"]])
                        frame_next = render_page_frame(img_next_obj, bg_next_obj, bounds_cache[pd_next["image_file"]], plans[next_idx], t_local_next, dx_next, dy_next)
                        
                        # Convert both to numpy arrays to blend
                        np_curr = np.array(frame_curr)
                        np_next = np.array(frame_next)
                        frame_curr.close()
                        frame_next.close()
                        
                        alpha = (t - t_trans_start) / t_trans_dur
                        alpha = np.clip(alpha, 0.0, 1.0)
                        blended_np = cv2.addWeighted(np_curr, 1.0 - alpha, np_next, alpha, 0)
                        final_frame = Image.fromarray(blended_np)
                    else:
                        # Single active page
                        t_local = t - pd_curr["start_time"]
                        x_curr, y_curr, scale_curr = interpolate_camera_plan(plans[active_idx], t_local)
                        if active_idx in prev_coords:
                            x_prev, y_prev = prev_coords[active_idx]
                            dx = x_curr - x_prev
                            dy = y_curr - y_prev
                        else:
                            dx, dy = 0.0, 0.0
                        prev_coords[active_idx] = (x_curr, y_curr)
                        
                        img_curr_obj = get_img(pd_curr["image_file"], t)
                        bg_curr_obj = get_blurred_background(pd_curr["image_file"], img_curr_obj, bounds_cache[pd_curr["image_file"]])
                        final_frame = render_page_frame(img_curr_obj, bg_curr_obj, bounds_cache[pd_curr["image_file"]], plans[active_idx], t_local, dx, dy)
                        
                    # Apply Dip to Black at the end of the video
                    if t >= total_duration - T_trans:
                        alpha = (t - (total_duration - T_trans)) / T_trans
                        alpha = np.clip(alpha, 0.0, 1.0)
                        frame_np = np.array(final_frame)
                        final_frame.close()
                        # Multiply by (1 - alpha)
                        frame_np = (frame_np * (1.0 - alpha)).astype(np.uint8)
                        final_frame = Image.fromarray(frame_np)
 
                    # Draw subtitles
                    if active_sub:
                        draw_subtitles_on_frame(final_frame, active_sub)
 
                    # Output raw bytes to FFmpeg pipe
                    try:
                        proc.stdin.write(final_frame.tobytes())
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError) as write_err:
                        if getattr(write_err, "errno", 0) == 32 or isinstance(write_err, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
                            pipe_broken = True
                            final_frame.close()
                            break
                        else:
                            final_frame.close()
                            raise
                    final_frame.close()
                    
            finally:
                for img in loaded_images.values():
                    try:
                        img.close()
                    except Exception:
                        pass
                loaded_images.clear()
                for img in cached_backgrounds.values():
                    try:
                        img.close()
                    except Exception:
                        pass
                cached_backgrounds.clear()
                
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.stdin = None
            
            proc.wait()
            stderr_file.close()
            
            if proc.returncode != 0:
                try:
                    with open(stderr_log_path, "r", encoding="utf-8") as f:
                        err_msg = f.read().strip()
                except Exception:
                    err_msg = "Unknown error (failed to read ffmpeg log)"
                raise Exception(f"FFmpeg render episode failed (exit code {proc.returncode}): {err_msg}")
            else:
                try:
                    if os.path.exists(stderr_log_path):
                        os.remove(stderr_log_path)
                except Exception:
                    pass

        total_episodes = to_ep - from_ep + 1
        
        # Pass 1: Xóa chữ cho tất cả các tập chưa hoàn thành trước
        if task.payload.get("remove_text", False):
            from tools.text_remover.comic_text_remover import get_easyocr_reader, process_image
         # Pass 2: Tiến hành render video song song cho tất cả các tập
        concurrency = task.payload.get("concurrency", 3)
        await context.log(f"Stage 10: Bắt đầu render video song song với tối đa {concurrency} luồng.", "info")
        semaphore = asyncio.Semaphore(concurrency)
        completed_eps_count = 0
        progress_lock = asyncio.Lock()

        async def process_single_episode_video(ep):
            nonlocal completed_eps_count
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            
            await context.start_episode(ep)
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            images_blur_dir = os.path.join(ep_dir, "images_blur")
            recap_json_path = os.path.join(ep_dir, "recap.json")
            srt_path = os.path.join(ep_dir, "transcript.srt")
            audio_path = os.path.join(ep_dir, "audio.mp3")
            output_video_path = os.path.join(ep_dir, "video.mp4")
            cache = EpisodeStageCache(ep_dir)
            fingerprint = stage_fingerprint(
                task,
                "video",
                ep,
                input_paths=[images_blur_dir, recap_json_path, srt_path, audio_path, logo_path, overlay_path],
            )
            if cache.is_current(
                stage="video",
                fingerprint=fingerprint,
                outputs=[output_video_path],
                validate=lambda: validate_mp4_file(output_video_path),
            ):
                await context.log(f"Tập {ep}: Cache video hợp lệ. Bỏ qua rendering.", "success")
                if "final_videos" not in task.artifacts:
                    task.artifacts["final_videos"] = {}
                task.artifacts["final_videos"][str(ep)] = f"/downloads/{task.artifacts.get('download_folder_name')}/episode_{ep}/video.mp4"
                await context.complete_episode(ep)
                async with progress_lock:
                    completed_eps_count += 1
                    await context.update_stage_progress(self.name, (completed_eps_count / total_episodes) * 100.0)
                return True

            if not os.path.exists(recap_json_path) or not os.path.exists(srt_path) or not os.path.exists(audio_path):
                await context.fail_episode(ep, "Thiếu recap.json, transcript.srt hoặc audio.mp3.")
                return False

            segments = load_recap_dicts(recap_json_path)

            with open(srt_path, "r", encoding="utf-8") as f:
                srt_content = f.read().replace('\r\n', '\n').strip()
            pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})"
            matches = re.findall(pattern, srt_content)
            timings = []
            for num, start_str, end_str in matches:
                timings.append({
                    "start": parse_time_to_seconds(start_str),
                    "end": parse_time_to_seconds(end_str)
                })

            image_files = sorted([f for f in os.listdir(images_blur_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
            if not image_files:
                await context.fail_episode(ep, "Không tìm thấy ảnh moderated.")
                return False
            segments = load_recap_dicts(recap_json_path, max_page=len(image_files))

            working_encoder = get_working_encoder(ffmpeg_exe, os.path.join(images_blur_dir, image_files[0]))
            fps = task.payload.get("fps", 30)

            # Compile episode directly in one single pass
            temp_video_path = output_video_path + ".tmp.mp4"
            if os.path.exists(temp_video_path):
                os.remove(temp_video_path)
            await asyncio.to_thread(
                render_episode_video_sync,
                images_blur_dir, image_files, segments, timings, temp_video_path,
                ffmpeg_exe, working_encoder, audio_path, logo_path, overlay_path,
                subtitles_enabled, "transcript.srt", fps
            )
            if not os.path.isfile(temp_video_path) or os.path.getsize(temp_video_path) == 0:
                raise RuntimeError("FFmpeg did not produce a valid episode video")
            if not validate_mp4_file(temp_video_path):
                raise RuntimeError("FFmpeg produced an invalid episode video")
            os.replace(temp_video_path, output_video_path)
            cache.commit(stage="video", fingerprint=fingerprint, outputs=[output_video_path])

            if "final_videos" not in task.artifacts:
                task.artifacts["final_videos"] = {}
            task.artifacts["final_videos"][str(ep)] = f"/downloads/{task.artifacts.get('download_folder_name')}/episode_{ep}/video.mp4"

            await context.complete_episode(ep)
            async with progress_lock:
                completed_eps_count += 1
                await context.update_stage_progress(self.name, (completed_eps_count / total_episodes) * 100.0)
            return True

        async def sem_render(ep):
            async with semaphore:
                try:
                    return await process_single_episode_video(ep)
                except Exception as e:
                    await context.log(f"Tập {ep}: Lỗi render video: {e}", "error")
                    await context.fail_episode(ep, f"Lỗi render video: {e}")
                    return False

        tasks = [sem_render(ep) for ep in range(from_ep, to_ep + 1)]
        results = await asyncio.gather(*tasks)
        return all(results)

def get_video_duration(video_path: str, ffmpeg_exe: str) -> float:
    ffprobe_exe = "ffprobe"
    if ffmpeg_exe and "ffmpeg" in ffmpeg_exe:
        potential_ffprobe = ffmpeg_exe.replace("ffmpeg", "ffprobe")
        if os.path.exists(potential_ffprobe):
            ffprobe_exe = potential_ffprobe
    try:
        import subprocess
        cmd = [
            ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ]
        out = subprocess.check_output(cmd)
        return float(out.decode().strip())
    except Exception:
        pass

    try:
        import subprocess
        import re
        cmd = [ffmpeg_exe, "-i", video_path]
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        _, stderr = proc.communicate()
        stderr_str = stderr.decode(errors="ignore")
        m = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2})\.(\d{2})", stderr_str)
        if m:
            hrs, mins, secs, ms = map(int, m.groups())
            return hrs * 3600 + mins * 60 + secs + ms / 100.0
    except Exception:
        pass

    try:
        srt_path = os.path.join(os.path.dirname(video_path), "transcript.srt")
        if os.path.exists(srt_path):
            with open(srt_path, "r", encoding="utf-8") as f:
                content = f.read()
            import re
            matches = re.findall(r"(\d{2}):(\d{2}):(\d{2})[,\.](\d{3})", content)
            if matches:
                max_seconds = 0.0
                for hrs_s, mins_s, secs_s, msecs_s in matches:
                    total = int(hrs_s) * 3600 + int(mins_s) * 60 + int(secs_s) + int(msecs_s) / 1000.0
                    if total > max_seconds:
                        max_seconds = total
                return max_seconds
    except Exception:
        pass

    return 0.0

def shift_srt_time(time_str: str, offset_seconds: float) -> str:
    normalized = time_str.replace(".", ",")
    parts = normalized.split(",")
    h_m_s = parts[0].split(":")
    hrs = int(h_m_s[0])
    mins = int(h_m_s[1])
    secs = int(h_m_s[2])
    msecs = int(parts[1]) if len(parts) > 1 else 0
    
    total_seconds = hrs * 3600 + mins * 60 + secs + msecs / 1000.0
    new_total = total_seconds + offset_seconds
    
    new_hrs = int(new_total // 3600)
    new_mins = int((new_total % 3600) // 60)
    new_secs = int(new_total % 60)
    new_msecs = int(round((new_total - int(new_total)) * 1000))
    if new_msecs >= 1000:
        new_msecs -= 1000
        new_secs += 1
    if new_secs >= 60:
        new_secs -= 60
        new_mins += 1
    if new_mins >= 60:
        new_mins -= 60
        new_hrs += 1
        
    return f"{new_hrs:02d}:{new_mins:02d}:{new_secs:02d},{new_msecs:03d}"

def merge_srt_files(srt_paths: list, video_durations: list, output_srt_path: str):
    merged_lines = []
    global_index = 1
    current_offset = 0.0
    
    for idx, srt_path in enumerate(srt_paths):
        if not os.path.exists(srt_path):
            current_offset += video_durations[idx]
            continue
            
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        import re
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
            
        current_offset += video_durations[idx]
        
    temp_output_path = output_srt_path + ".tmp"
    with open(temp_output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(merged_lines))
    os.replace(temp_output_path, output_srt_path)

class Stage11_FinalVideoAssembly(BaseStage):
    @property
    def name(self) -> str: return "Stage 11 - Final Video Assembly"
    @property
    def weight(self) -> float: return 0.05

    async def execute(self, context: WorkflowContext) -> bool:
        from app import find_ffmpeg
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        download_dir = task.artifacts.get("download_dir")
        ffmpeg_exe = find_ffmpeg()

        output_dir = os.path.join(download_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        
        folder_name = task.artifacts.get("download_folder_name")
        final_video_name = f"{folder_name}.mp4"
        final_srt_name = f"{folder_name}.srt"
        
        final_video_path = os.path.join(output_dir, final_video_name)
        final_srt_path = os.path.join(output_dir, final_srt_name)
        temp_final_video_path = final_video_path + ".tmp.mp4"
        temp_final_srt_path = final_srt_path + ".tmp"
        for temp_path in (temp_final_video_path, temp_final_srt_path):
            if os.path.exists(temp_path):
                os.remove(temp_path)

        total_episodes = to_ep - from_ep + 1
        episodes_processed = list(range(from_ep, to_ep + 1))
        
        # Calculate video durations and locate input srt files
        video_durations = []
        srt_paths = []
        for ep in episodes_processed:
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            video_path = os.path.join(ep_dir, "video.mp4")
            srt_path = os.path.join(ep_dir, "transcript.srt")
            
            # Query video duration
            duration = get_video_duration(video_path, ffmpeg_exe)
            video_durations.append(duration)
            srt_paths.append(srt_path)

        if total_episodes == 1:
            shutil.copy2(os.path.join(download_dir, f"episode_{from_ep}", "video.mp4"), temp_final_video_path)
            await context.log(f"Chỉ có 1 tập, sao chép trực tiếp thành {final_video_name}.", "success")
            
            # Copy srt file directly as final_srt_path if it exists
            single_srt = os.path.join(download_dir, f"episode_{from_ep}", "transcript.srt")
            if os.path.exists(single_srt):
                shutil.copy2(single_srt, temp_final_srt_path)
                await context.log(f"Sao chép transcript.srt thành {final_srt_name}.", "success")
        else:
            await context.log("Đang tiến hành ghép nối các đoạn video bằng phương pháp concat demuxer (không encode lại)...", "info")

            # Construct concat list file
            concat_list_path = os.path.join(download_dir, "concat_list.txt")
            try:
                with open(concat_list_path, "w", encoding="utf-8") as f:
                    for ep in episodes_processed:
                        ep_dir = os.path.join(download_dir, f"episode_{ep}")
                        video_path = os.path.join(ep_dir, "video.mp4")
                        rel_path = os.path.relpath(video_path, download_dir).replace('\\', '/')
                        f.write(f"file '{rel_path}'\n")
            except Exception as file_err:
                raise Exception(f"Failed to write concat_list.txt: {file_err}")

            cmd = [
                ffmpeg_exe, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", "concat_list.txt",
                "-c", "copy",
                "-movflags", "faststart",
                temp_final_video_path
            ]

            proc = await asyncio.create_subprocess_exec(*cmd, cwd=download_dir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await proc.communicate()

            # Clean up the manifest file
            if os.path.exists(concat_list_path):
                try:
                    os.remove(concat_list_path)
                except Exception:
                    pass

            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="ignore").strip()
                raise Exception(f"FFmpeg final video assembly failed (exit code {proc.returncode}): {err_msg}")

            # Merge SRT files with offsets
            await context.log("Đang tiến hành gộp các file phụ đề srt...", "info")
            merge_srt_files(srt_paths, video_durations, temp_final_srt_path)
            await context.log(f"Đã hoàn thành gộp phụ đề thành {final_srt_name}.", "success")

        if not os.path.isfile(temp_final_video_path) or os.path.getsize(temp_final_video_path) == 0:
            raise RuntimeError("Final video output is missing or empty")
        if not os.path.isfile(temp_final_srt_path) or os.path.getsize(temp_final_srt_path) == 0:
            raise RuntimeError("Final subtitle output is missing or empty")
        os.replace(temp_final_video_path, final_video_path)
        os.replace(temp_final_srt_path, final_srt_path)
        task.artifacts["final_video_url"] = f"/downloads/{folder_name}/output/{final_video_name}"
        task.artifacts["final_subtitle_url"] = f"/downloads/{folder_name}/output/{final_srt_name}"
        await context.update_stage_progress(self.name, 100.0)
        return True

class Stage12_MetadataReports(BaseStage):
    @property
    def name(self) -> str: return "Stage 12 - Metadata & Reports"
    @property
    def weight(self) -> float: return 0.03

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        download_dir = task.artifacts.get("download_dir")
        output_dir = os.path.join(download_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        metadata = {
            "comic_title": task.comic_title,
            "comic_url": task.comic_url,
            "from_episode": task.from_episode,
            "to_episode": task.to_episode,
            "generation_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "overall_progress": task.overall_progress,
            "elapsed_time_seconds": task.elapsed_time
        }
        
        metadata_path = os.path.join(output_dir, "metadata.json")
        metadata_temp_path = metadata_path + ".tmp"
        with open(metadata_temp_path, "w", encoding="utf-8") as mf:
            json.dump(metadata, mf, ensure_ascii=False, indent=2)
        os.replace(metadata_temp_path, metadata_path)

        report = {
            "task_id": task.id,
            "stages": task.stages,
            "completed_episodes_count": task.completed_count,
            "failed_episodes_count": task.failed_count,
            "error_message": task.error_message
        }
        
        report_path = os.path.join(output_dir, "processing_report.json")
        report_temp_path = report_path + ".tmp"
        with open(report_temp_path, "w", encoding="utf-8") as rf:
            json.dump(report, rf, ensure_ascii=False, indent=2)
        os.replace(report_temp_path, report_path)

        await context.log("Đã tạo tệp metadata.json và processing_report.json.", "success")
        await context.update_stage_progress(self.name, 100.0)
        return True

class Stage13_Cleanup(BaseStage):
    @property
    def name(self) -> str: return "Stage 13 - Cleanup"
    @property
    def weight(self) -> float: return 0.02

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        download_dir = task.artifacts.get("download_dir")
        
        cleanup_enabled = task.payload.get("cleanup", True)
        if cleanup_enabled:
            await context.log("Dọn dẹp các tệp tạm thời...", "info")
            for ep in range(task.from_episode, task.to_episode + 1):
                ep_dir = os.path.join(download_dir, f"episode_{ep}")
                stitched_img = os.path.join(ep_dir, "stitched.jpg")
                if os.path.exists(stitched_img): os.remove(stitched_img)
                stitched_mask = os.path.join(ep_dir, "stitched_mask.jpg")
                if os.path.exists(stitched_mask): os.remove(stitched_mask)
                gemini_prompt = os.path.join(ep_dir, "gemini_prompt.txt")
                if os.path.exists(gemini_prompt): os.remove(gemini_prompt)

        # Clear static/uploads files associated with this task
        for path_key in ["logo_path", "overlay_path"]:
            p = task.payload.get(path_key)
            if p:
                p_abs = os.path.abspath(p)
                if "static/uploads" in p_abs and os.path.exists(p_abs):
                    try:
                        os.remove(p_abs)
                        await context.log(f"Đã dọn dẹp file upload: {os.path.basename(p_abs)}", "info")
                    except Exception as e:
                        await context.log(f"Không thể xóa {os.path.basename(p_abs)}: {e}", "warning")

        await context.update_stage_progress(self.name, 100.0)
        return True
