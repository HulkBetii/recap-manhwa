import os
import json
import asyncio
import re
import time
import subprocess
import shutil
import math
import random
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
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
from moderation_utils import (
    MODERATION_MODEL_VERSION,
    MODERATION_PROMPT_VERSION,
    list_image_files,
    prepare_moderated_directory,
    selected_file_names,
    selected_page_numbers,
)


def is_ffmpeg_pipe_closed_error(error: BaseException) -> bool:
    return (
        isinstance(error, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError))
        or getattr(error, "errno", None) in {22, 32}
        or getattr(error, "winerror", None) in {87, 109, 232}
    )


def can_recover_ffmpeg_pipe_output(error: BaseException, output_path: str) -> bool:
    return is_ffmpeg_pipe_closed_error(error) and validate_mp4_file(output_path)

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
        
        language = task.payload.get("language", "en")
        market_id = task.payload.get("market_id")
        raw_voice_id = task.payload.get("voice_id")
        rate = "+0%"
        pitch = "+0Hz"

        from markets import get_market
        market = get_market(market_id)
        if market:
            if not raw_voice_id or raw_voice_id in ("ai33pro", "auto", "default"):
                voice_id = market.default_voice_id
            else:
                voice_id = raw_voice_id
            if market.voice_rate:
                rate = market.voice_rate
            if market.voice_pitch:
                pitch = market.voice_pitch
        elif language == "ko":
            from markets.korea_apocalypse.tts import (
                DEFAULT_KR_VOICE_ID,
                DEFAULT_KR_VOICE_RATE,
                DEFAULT_KR_VOICE_PITCH,
            )
            voice_id = raw_voice_id if raw_voice_id and raw_voice_id not in ("ai33pro", "auto", "default") else DEFAULT_KR_VOICE_ID
            rate = DEFAULT_KR_VOICE_RATE
            pitch = DEFAULT_KR_VOICE_PITCH
        else:
            default_voice = "auto"
            voice_id = normalize_tts_voice_mode(raw_voice_id or default_voice, default=default_voice)

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
                
            await context.log(f"Tập {ep}: Đang sinh local TTS ({voice_id}, rate={rate}, pitch={pitch})...", "info")

            from tts_provider import generate_tts
            audio_temp_path = audio_path + ".tmp.mp3"
            srt_temp_path = srt_path + ".tmp.srt"
            success = await generate_tts(narration_text, audio_temp_path, srt_temp_path, voice_id, ref_audio_path, rate=rate, pitch=pitch)
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

def draw_subtitles_on_frame(image, text, font_size=42):
    from PIL import ImageDraw, ImageFont, Image
    if not text:
        return
        
    # Try to load a clean bold sans-serif system font (with Korean and Japanese fallback)
    font = None
    has_korean = any(0xAC00 <= ord(c) <= 0xD7AF or 0x1100 <= ord(c) <= 0x11FF or 0x3130 <= ord(c) <= 0x318F for c in text)
    has_japanese = any(0x3040 <= ord(c) <= 0x30FF for c in text)

    font_paths = []
    if has_korean:
        font_paths.extend([
            "C:\\Windows\\Fonts\\malgunbd.ttf",
            "C:\\Windows\\Fonts\\malgun.ttf",
            "malgunbd.ttf",
            "malgun.ttf",
        ])
    elif has_japanese:
        font_paths.extend([
            "C:\\Windows\\Fonts\\meiryo.ttc",
            "C:\\Windows\\Fonts\\msgothic.ttc",
            "meiryo.ttc",
        ])
    font_paths.extend([
        "arialbd.ttf",
        "seguisb.ttf",
        "arial.ttf",
        "tahoma.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\seguisb.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\tahoma.ttf"
    ])
    for path in font_paths:
        try:
            font = ImageFont.truetype(path, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
        
    # Text wrapping helper with safe width margins (max 1450px)
    draw_temp = ImageDraw.Draw(image)
    max_line_width = 1450
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        current_line.append(word)
        test_line = " ".join(current_line)
        try:
            w = draw_temp.textlength(test_line, font=font)
        except Exception:
            w = len(test_line) * (font_size * 0.6)
            
        if w > max_line_width:
            current_line.pop()
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
        
    if not lines:
        return
        
    line_height = int(font_size * 1.3)
    total_text_h = len(lines) * line_height
    padding_x = 24
    padding_y = 12

    # Safe bottom position (y_bottom = 1080 - 120px safe zone)
    box_bottom = 1080 - 120
    box_top = box_bottom - total_text_h - (padding_y * 2)

    # Compute maximum width among lines to create a unified rounded backdrop box
    line_widths = []
    for line in lines:
        try:
            bbox = draw_temp.textbbox((0, 0), line, font=font)
            line_widths.append(bbox[2] - bbox[0])
        except Exception:
            line_widths.append(len(line) * (font_size * 0.6))

    max_w = max(line_widths) if line_widths else 300
    box_w = max_w + (padding_x * 2)
    box_left = (1920 - box_w) // 2
    box_right = box_left + box_w

    # Draw semi-transparent rounded rectangle backdrop
    backdrop_overlay = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    backdrop_draw = ImageDraw.Draw(backdrop_overlay)
    backdrop_draw.rounded_rectangle(
        [box_left, box_top, box_right, box_bottom],
        radius=14,
        fill=(0, 0, 0, 160),
        outline=(255, 255, 255, 30),
        width=1
    )
    
    if image.mode == "RGBA":
        image.alpha_composite(backdrop_overlay)
    else:
        composited_bg = Image.alpha_composite(image.convert("RGBA"), backdrop_overlay).convert("RGB")
        image.paste(composited_bg, (0, 0))
        composited_bg.close()
    backdrop_overlay.close()

    # Draw text with crisp outline
    draw = ImageDraw.Draw(image)
    y_cursor = box_top + padding_y
    for idx, line in enumerate(lines):
        w_line = line_widths[idx]
        x = (1920 - w_line) // 2
        
        # Stroke/Outline for maximum readability on bright backgrounds
        outline_color = (0, 0, 0)
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y_cursor + dy), line, font=font, fill=outline_color)
            
        draw.text((x, y_cursor), line, font=font, fill=(255, 255, 255))
        y_cursor += line_height


def detect_clean_panel_and_focal_point(img_pil) -> tuple[tuple, tuple]:
    """
    Detects the character focal point (with speech bubble suppression and skin tone boost)
    and automatically isolates the active comic panel (excluding neighboring panels and solid gutters).
    Returns (bounds, focal_point) where:
      bounds = (cb_x, cb_y, W_c, H_c)
      focal_point = (focal_x, focal_y) relative to bounds.
    """
    import cv2
    import numpy as np

    img_rgb = np.array(img_pil.convert("RGB"))
    h_full, w_full, _ = img_rgb.shape

    if h_full < 20 or w_full < 20:
        return (0, 0, w_full, h_full), (w_full / 2.0, h_full / 2.0)

    crop_hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
    crop_gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    h_chan, s_chan, v_chan = cv2.split(crop_hsv)

    # 1. Speech bubble suppression mask (High Value, Low Saturation)
    bubble_mask = (v_chan > 210) & (s_chan < 50)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    bubble_mask_dilated = cv2.dilate(bubble_mask.astype(np.uint8), kernel).astype(bool)

    # 2. Skin tone & human face color mask
    skin_mask = ((h_chan <= 28) | (h_chan >= 165)) & (s_chan >= 20) & (s_chan <= 180) & (v_chan >= 70)

    # 3. Sobel edge magnitude
    sobelx = cv2.Sobel(crop_gray, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(crop_gray, cv2.CV_64F, 0, 1, ksize=3)
    mag = np.sqrt(sobelx**2 + sobely**2)

    # 4. Saliency weighting
    saliency = mag.copy()
    saliency[bubble_mask_dilated] *= 0.05
    saliency[skin_mask] *= 3.5

    # 5. Eye-line vertical prior
    y_idx, x_idx = np.indices((h_full, w_full))
    y_prior = np.exp(-((y_idx - 0.35 * h_full) ** 2) / (2 * (0.32 * h_full) ** 2))
    weighted_map = saliency * y_prior

    if np.max(weighted_map) > 1.0:
        pos_vals = weighted_map[weighted_map > 1.0]
        thresh = float(np.percentile(pos_vals, 70))
        salient_coords = np.argwhere(weighted_map >= thresh)
        if len(salient_coords) > 0:
            weights = weighted_map[salient_coords[:, 0], salient_coords[:, 1]]
            mean_y = float(np.average(salient_coords[:, 0], weights=weights))
            mean_x = float(np.average(salient_coords[:, 1], weights=weights))
        else:
            mean_x, mean_y = w_full / 2.0, h_full / 2.0
    else:
        mean_x, mean_y = w_full / 2.0, h_full / 2.0

    raw_focal_x = float(np.clip(mean_x, 0.15 * w_full, 0.85 * w_full))
    raw_focal_y = float(np.clip(mean_y, 0.10 * h_full, 0.90 * h_full))

    # 6. Active panel isolation: detect horizontal gutters and dividers
    mid_strip = crop_gray[:, int(w_full * 0.08):int(w_full * 0.92)]
    row_std = np.std(mid_strip, axis=1)
    row_mean = np.mean(mid_strip, axis=1)

    # Detect top/bottom outer gutters
    top_gutter = 0
    while top_gutter < h_full // 2 and row_std[top_gutter] < 4.0 and (row_mean[top_gutter] <= 18 or row_mean[top_gutter] >= 238):
        top_gutter += 1

    bot_gutter = h_full - 1
    while bot_gutter > h_full // 2 and row_std[bot_gutter] < 4.0 and (row_mean[bot_gutter] <= 18 or row_mean[bot_gutter] >= 238):
        bot_gutter -= 1
    bot_gutter += 1

    # Detect internal panel divider bands
    gutters = []
    for y in range(top_gutter, bot_gutter):
        if row_std[y] < 3.5 and (row_mean[y] <= 18 or row_mean[y] >= 238):
            gutters.append(y)

    bands = []
    if gutters:
        s = gutters[0]
        for i in range(1, len(gutters)):
            if gutters[i] != gutters[i-1] + 1:
                if (gutters[i-1] - s + 1) >= 8:
                    bands.append((s, gutters[i-1]))
                s = gutters[i]
        if (gutters[-1] - s + 1) >= 8:
            bands.append((s, gutters[-1]))

    panel_top = top_gutter
    panel_bot = bot_gutter

    for s, e in bands:
        if e < raw_focal_y:
            panel_top = max(panel_top, e + 1)
        elif s > raw_focal_y:
            panel_bot = min(panel_bot, s - 1)
            break

    panel_top = max(top_gutter, panel_top - 5)
    panel_bot = min(bot_gutter, panel_bot + 5)

    h_panel = panel_bot - panel_top
    if h_panel >= 250:
        clean_bounds = (0, panel_top, w_full, h_panel)
        local_focal_x = w_full / 2.0
        local_focal_y = float(np.clip(raw_focal_y - panel_top, 0.20 * h_panel, 0.80 * h_panel))
    else:
        clean_bounds = (0, top_gutter, w_full, max(20, bot_gutter - top_gutter))
        local_focal_x = w_full / 2.0
        local_focal_y = float(np.clip(raw_focal_y - top_gutter, 0.20 * clean_bounds[3], 0.80 * clean_bounds[3]))

    return clean_bounds, (local_focal_x, local_focal_y)


def detect_content_bounds(img: Image) -> tuple:
    bounds, _ = detect_clean_panel_and_focal_point(img)
    return bounds


def detect_focal_point(img_pil, bounds: tuple = None) -> tuple[float, float]:
    import cv2
    import numpy as np

    img_rgb = np.array(img_pil.convert("RGB"))
    h_full, w_full, _ = img_rgb.shape

    if bounds:
        cb_x, cb_y, W_c, H_c = bounds
        cb_x = max(0, min(w_full - 1, int(cb_x)))
        cb_y = max(0, min(h_full - 1, int(cb_y)))
        W_c = max(10, min(w_full - cb_x, int(W_c)))
        H_c = max(10, min(h_full - cb_y, int(H_c)))
        crop_rgb = img_rgb[cb_y:cb_y+H_c, cb_x:cb_x+W_c]
    else:
        cb_x, cb_y, W_c, H_c = 0, 0, w_full, h_full
        crop_rgb = img_rgb

    if W_c < 20 or H_c < 20:
        return W_c / 2.0, H_c / 2.0

    crop_hsv = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2HSV)
    crop_gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
    h_chan, s_chan, v_chan = cv2.split(crop_hsv)

    bubble_mask = (v_chan > 210) & (s_chan < 50)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    bubble_mask_dilated = cv2.dilate(bubble_mask.astype(np.uint8), kernel).astype(bool)

    skin_mask = ((h_chan <= 28) | (h_chan >= 165)) & (s_chan >= 20) & (s_chan <= 180) & (v_chan >= 70)

    sobelx = cv2.Sobel(crop_gray, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(crop_gray, cv2.CV_64F, 0, 1, ksize=3)
    mag = np.sqrt(sobelx**2 + sobely**2)

    saliency = mag.copy()
    saliency[bubble_mask_dilated] *= 0.05
    saliency[skin_mask] *= 3.5

    if np.max(saliency) > 1.0:
        pos_vals = saliency[saliency > 1.0]
        thresh = float(np.percentile(pos_vals, 70))
        salient_coords = np.argwhere(saliency >= thresh)
        if len(salient_coords) > 0:
            weights = saliency[salient_coords[:, 0], salient_coords[:, 1]]
            mean_y = float(np.average(salient_coords[:, 0], weights=weights))
            mean_x = float(np.average(salient_coords[:, 1], weights=weights))
        else:
            mean_x, mean_y = W_c / 2.0, H_c / 2.0
    else:
        mean_x, mean_y = W_c / 2.0, H_c / 2.0

    focal_x = float(np.clip(mean_x, 0.15 * W_c, 0.85 * W_c))
    focal_y = float(np.clip(mean_y, 0.15 * H_c, 0.85 * H_c))
    return focal_x, focal_y


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
    def generate_camera_plan(
        page_num: int,
        duration: float,
        bounds: tuple,
        focal_point: tuple = None,
        transition: str = "cross_fade"
    ) -> dict:
        """
        Generates a cinematic camera plan that preserves full panel width and text readability,
        centering the X-axis and applying subtle micro-motion zoom (1.00x -> 1.035x).
        """
        cb_x, cb_y, W_c, H_c = bounds

        center_x = W_c / 2.0
        center_y = H_c / 2.0

        # Center-lock X axis to guarantee zero clipping of text bubbles on left/right borders
        focal_x = center_x

        if focal_point is None:
            focal_y = center_y
        else:
            _, fy_raw = focal_point
            # Gentle vertical bias towards character eye-line / action while staying well inside safe margins
            focal_y = center_y * 0.60 + float(fy_raw) * 0.40

        focal_y = float(np.clip(focal_y, 0.25 * H_c, 0.75 * H_c))

        aspect_ratio = W_c / max(1.0, float(H_c))
        easing = "easeInOutSine"

        # Mode 1: Short Duration (< 1.8s) -> Subtle Micro-Motion Breathing (1.00x -> 1.020x)
        if duration < 1.8:
            animation_type = "subtle_breath"
            keyframes = [
                {"time": 0.0, "x": center_x, "y": center_y, "scale": 1.00},
                {"time": duration, "x": center_x, "y": focal_y, "scale": 1.020}
            ]
            return {
                "page": page_num,
                "duration": duration,
                "animation_type": animation_type,
                "easing": easing,
                "keyframes": keyframes,
                "transition": transition
            }

        # Mode 2: Long Duration (> 4.5s) -> Deep Gentle Cinematic Motion (1.00x -> 1.045x)
        if duration > 4.5:
            animation_type = "virtual_multicam"
            keyframes = [
                {"time": 0.0, "x": center_x, "y": center_y, "scale": 1.00},
                {"time": duration, "x": center_x, "y": focal_y, "scale": 1.045}
            ]
            return {
                "page": page_num,
                "duration": duration,
                "animation_type": animation_type,
                "easing": easing,
                "keyframes": keyframes,
                "transition": transition
            }

        # Mode 3: Wide Horizontal Panel (W/H >= 1.25) -> Cinematic Horizontal Micro-Pan (scale 1.00x -> 1.030x)
        if aspect_ratio >= 1.25:
            animation_type = "cinematic_pan_horizontal"
            pan_span = max(10.0, min(W_c * 0.04, 30.0))
            dir_x = random.choice([-1.0, 1.0])
            keyframes = [
                {"time": 0.0, "x": center_x - dir_x * pan_span, "y": center_y, "scale": 1.00},
                {"time": duration, "x": center_x + dir_x * pan_span, "y": focal_y, "scale": 1.030}
            ]
            return {
                "page": page_num,
                "duration": duration,
                "animation_type": animation_type,
                "easing": easing,
                "keyframes": keyframes,
                "transition": transition
            }

        # Mode 4: Standard Panels -> Dynamic Focal Micro-Zoom In (1.00x -> 1.035x)
        animation_type = "focal_zoom_in"
        target_scale = 1.035 if duration >= 3.0 else 1.025
        keyframes = [
            {"time": 0.0, "x": center_x, "y": center_y, "scale": 1.00},
            {"time": duration, "x": center_x, "y": focal_y, "scale": target_scale}
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
        dt = kf2["time"] - kf1["time"]
        if kf1["time"] <= t_local <= kf2["time"]:
            if dt < 0.005:  # Instant Jump Cut
                return kf2["x"], kf2["y"], kf2["scale"]
            local_t = (t_local - kf1["time"]) / dt
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
        subtitles_enabled = bool(task.payload.get("burn_subtitles", False))

        def render_episode_video_sync(images_blur_dir, image_files, segments, timings, output_video_path, ffmpeg_exe, working_encoder, audio_path, logo_path, overlay_path, subtitles_enabled_flag, srt_filename, fps=30):
            from PIL import Image, ImageFilter, ImageEnhance, ImageDraw
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

            # Precompute bounds, focal points, and plans
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
                
                cached_data = bounds_cache.get(img_file)
                if isinstance(cached_data, dict) and "bounds" in cached_data and "focal_point" in cached_data:
                    bounds = tuple(cached_data["bounds"])
                    focal_point = tuple(cached_data["focal_point"])
                elif isinstance(cached_data, list) and len(cached_data) == 4:
                    bounds = tuple(cached_data)
                    try:
                        with Image.open(img_path) as img:
                            focal_point = detect_focal_point(img, bounds)
                    except Exception:
                        focal_point = (bounds[2] / 2.0, bounds[3] / 2.0)
                    bounds_cache[img_file] = {"bounds": list(bounds), "focal_point": list(focal_point)}
                    dirty_cache = True
                else:
                    try:
                        with Image.open(img_path) as img:
                            bounds, focal_point = detect_clean_panel_and_focal_point(img)
                            bounds_cache[img_file] = {"bounds": list(bounds), "focal_point": list(focal_point)}
                            dirty_cache = True
                    except Exception:
                        bounds = (0, 0, 1920, 1080)
                        focal_point = (960.0, 540.0)
                
                is_last_page = (idx == len(page_displays) - 1)
                trans = "dip_to_black" if is_last_page else "cross_fade"
                
                plan = CameraPlanner.generate_camera_plan(pd["page"], pd["duration"], bounds, focal_point=focal_point, transition=trans)
                plans.append(plan)
                
            if dirty_cache:
                try:
                    with open(bounds_cache_path, "w", encoding="utf-8") as f:
                        json.dump(bounds_cache, f, indent=4)
                except Exception:
                    pass

            # Page frame rendering helper (Fixed-Dimension Viewport & Flat Edge-to-Edge Card)
            def render_page_frame(img, bg_image, bounds, plan, t_local, card_dims):
                cb_x, cb_y, W_c, H_c = bounds
                card_x, card_y, card_w, card_h, aspect_card = card_dims
                x_focal, y_focal, scale = interpolate_camera_plan(plan, t_local)
                scale = max(1.0, float(scale))

                # Viewport base dimensions matching the card's exact aspect ratio
                if aspect_card <= (W_c / max(1.0, float(H_c))):
                    h_base = float(H_c)
                    w_base = min(float(W_c), h_base * aspect_card)
                else:
                    w_base = float(W_c)
                    h_base = min(float(H_c), w_base / aspect_card)

                w_cam = w_base / scale
                h_cam = h_base / scale

                cx_ideal = cb_x + float(x_focal)
                cy_ideal = cb_y + float(y_focal)

                cx_min = cb_x + w_cam / 2.0
                cx_max = cb_x + W_c - w_cam / 2.0
                cx = cx_min if cx_min >= cx_max else float(np.clip(cx_ideal, cx_min, cx_max))

                cy_min = cb_y + h_cam / 2.0
                cy_max = cb_y + H_c - h_cam / 2.0
                cy = cy_min if cy_min >= cy_max else float(np.clip(cy_ideal, cy_min, cy_max))

                box_to_crop = (cx - w_cam / 2.0, cy - h_cam / 2.0, cx + w_cam / 2.0, cy + h_cam / 2.0)

                # Sub-pixel float crop & resize directly to fixed card dimensions (100% rock-solid, zero jitter)
                fg_resized = img.resize((card_w, card_h), resample=Image.Resampling.BILINEAR, box=box_to_crop)

                # Apply color enhancement (Vibrance & Contrast & Sharpness)
                enh_color = ImageEnhance.Color(fg_resized).enhance(1.06)
                enh_cont = ImageEnhance.Contrast(enh_color).enhance(1.04)
                enh_sharp = ImageEnhance.Sharpness(enh_cont).enhance(1.06)
                fg_enhanced = enh_sharp

                # Flat clean frame paste without 3D shadow or rounded corners
                final_frame = bg_image.copy()
                final_frame.paste(fg_enhanced, (card_x, card_y))

                fg_resized.close()
                enh_color.close()
                enh_cont.close()
                fg_enhanced.close()
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
            pipe_broken = False

            def get_cached_bounds(file_name):
                val = bounds_cache.get(file_name)
                if isinstance(val, dict) and "bounds" in val:
                    return tuple(val["bounds"])
                elif isinstance(val, (list, tuple)) and len(val) == 4:
                    return tuple(val)
                return (0, 0, 1920, 1080)

            # Precompute fixed card dimensions per image to guarantee zero-pixel jitter
            card_dims_map = {}
            for pd in page_displays:
                f_name = pd["image_file"]
                if f_name not in card_dims_map:
                    cb_x, cb_y, W_c, H_c = get_cached_bounds(f_name)
                    W_c = max(10, W_c)
                    H_c = max(10, H_c)
                    aspect_nat = W_c / float(H_c)
                    aspect_card = max(0.50, min(16.0 / 9.0, aspect_nat))

                    card_h = 1080
                    card_w = max(10, min(1920, int(round(card_h * aspect_card))))
                    card_x = (1920 - card_w) // 2
                    card_y = 0
                    card_dims_map[f_name] = (card_x, card_y, card_w, card_h, aspect_card)
            
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
                    
                    bg_small = bg_cropped.resize((160, 90), Image.Resampling.BOX)
                    bg_small_blurred = bg_small.filter(ImageFilter.GaussianBlur(radius=8))
                    bg_blurred = bg_small_blurred.resize((1920, 1080), Image.Resampling.BILINEAR)
                    bg_small.close()
                    bg_small_blurred.close()
                    bg_cropped.close()
                    
                    enhancer = ImageEnhance.Brightness(bg_blurred)
                    cached_backgrounds[img_file] = enhancer.enhance(0.42)
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
                        img_curr_obj = get_img(pd_curr["image_file"], t)
                        curr_bounds = get_cached_bounds(pd_curr["image_file"])
                        curr_card_dims = card_dims_map.get(pd_curr["image_file"], (555, 0, 810, 1080, 0.75))
                        bg_curr_obj = get_blurred_background(pd_curr["image_file"], img_curr_obj, curr_bounds)
                        frame_curr = render_page_frame(img_curr_obj, bg_curr_obj, curr_bounds, plans[active_idx], t_local_curr, curr_card_dims)
                        
                        # Interpolate next
                        t_local_next = t - t_trans_start
                        img_next_obj = get_img(pd_next["image_file"], t)
                        next_bounds = get_cached_bounds(pd_next["image_file"])
                        next_card_dims = card_dims_map.get(pd_next["image_file"], (555, 0, 810, 1080, 0.75))
                        bg_next_obj = get_blurred_background(pd_next["image_file"], img_next_obj, next_bounds)
                        frame_next = render_page_frame(img_next_obj, bg_next_obj, next_bounds, plans[next_idx], t_local_next, next_card_dims)
                        
                        # Convert both to numpy arrays to blend
                        np_curr = np.array(frame_curr)
                        np_next = np.array(frame_next)
                        frame_curr.close()
                        frame_next.close()
                        
                        alpha_linear = (t - t_trans_start) / max(0.001, t_trans_dur)
                        alpha_linear = np.clip(alpha_linear, 0.0, 1.0)
                        # Smooth sinusoidal ease-in-out cross-dissolve
                        alpha = 0.5 * (1.0 - math.cos(math.pi * alpha_linear))
                        blended_np = cv2.addWeighted(np_curr, 1.0 - alpha, np_next, alpha, 0)
                        final_frame = Image.fromarray(blended_np)
                    else:
                        # Single active page
                        t_local = t - pd_curr["start_time"]
                        img_curr_obj = get_img(pd_curr["image_file"], t)
                        curr_bounds = get_cached_bounds(pd_curr["image_file"])
                        curr_card_dims = card_dims_map.get(pd_curr["image_file"], (555, 0, 810, 1080, 0.75))
                        bg_curr_obj = get_blurred_background(pd_curr["image_file"], img_curr_obj, curr_bounds)
                        final_frame = render_page_frame(img_curr_obj, bg_curr_obj, curr_bounds, plans[active_idx], t_local, curr_card_dims)
                        
                    # Apply Dip to Black at the end of the video
                    if t >= total_duration - T_trans:
                        alpha_linear = (t - (total_duration - T_trans)) / max(0.001, T_trans)
                        alpha_linear = np.clip(alpha_linear, 0.0, 1.0)
                        alpha = 0.5 * (1.0 - math.cos(math.pi * alpha_linear))
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
                        if is_ffmpeg_pipe_closed_error(write_err):
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
            images_pdf_dir = os.path.join(ep_dir, "images_pdf")
            images_blur_dir = os.path.join(ep_dir, "images_blur")
            recap_json_path = os.path.join(ep_dir, "recap.json")
            srt_path = os.path.join(ep_dir, "transcript.srt")
            audio_path = os.path.join(ep_dir, "audio.mp3")
            output_video_path = os.path.join(ep_dir, "video.mp4")
            cache = EpisodeStageCache(ep_dir)

            if not os.path.exists(recap_json_path) or not os.path.exists(srt_path) or not os.path.exists(audio_path):
                await context.fail_episode(ep, "Thiếu recap.json, transcript.srt hoặc audio.mp3.")
                return False

            canonical_image_files = list_image_files(images_pdf_dir)
            if not canonical_image_files:
                await context.fail_episode(ep, "Không tìm thấy ảnh chuẩn trong images_pdf.")
                return False

            segments = load_recap_dicts(recap_json_path, max_page=len(canonical_image_files))
            selected_pages = selected_page_numbers(segments, max_page=len(canonical_image_files))
            selected_files = selected_file_names(canonical_image_files, selected_pages)
            safe_mode = task.payload.get("safe_mode", False)
            moderation_fingerprint = stage_fingerprint(
                task,
                "selected_moderation",
                ep,
                input_paths=[images_pdf_dir],
                extra={
                    "selected_pages": selected_pages,
                    "model": MODERATION_MODEL_VERSION,
                    "prompt": MODERATION_PROMPT_VERSION,
                },
            )
            moderation_current = cache.is_current(
                stage="selected_moderation",
                fingerprint=moderation_fingerprint,
                outputs=[images_blur_dir],
                validate=lambda: list_image_files(images_blur_dir) == canonical_image_files,
            )
            if moderation_current:
                await context.log(
                    f"Tập {ep}: Cache kiểm duyệt ảnh đã chọn hợp lệ ({len(selected_pages)} page).",
                    "success",
                )
            else:
                sanitizer = None
                if safe_mode:
                    from app import sanitize_episode_images
                    sanitizer = sanitize_episode_images
                    await context.log(
                        f"Tập {ep}: Kiểm duyệt {len(selected_pages)}/{len(canonical_image_files)} page được chọn cho video: {selected_pages}",
                        "info",
                    )
                else:
                    await context.log(
                        f"Tập {ep}: Safe Mode tắt; sao chép ảnh render mà không chạy DINO/SAM.",
                        "info",
                    )

                await prepare_moderated_directory(
                    images_pdf_dir,
                    images_blur_dir,
                    sanitizer=sanitizer,
                    selected_files=selected_files,
                    sanitizer_kwargs={
                        "nsfw_threshold": task.payload.get("nsfw_threshold", 0.3),
                        "nsfw_mode": task.payload.get("nsfw_mode", "mask"),
                        "sse_logger": context,
                        "concurrency": task.payload.get("concurrency", 5),
                    },
                )
                cache.commit(
                    stage="selected_moderation",
                    fingerprint=moderation_fingerprint,
                    outputs=[images_blur_dir],
                )

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

            image_files = list_image_files(images_blur_dir)
            if image_files != canonical_image_files:
                await context.fail_episode(ep, "Ảnh render không giữ nguyên page mapping từ images_pdf.")
                return False

            working_encoder = get_working_encoder(ffmpeg_exe, os.path.join(images_blur_dir, image_files[0]))
            fps = task.payload.get("fps", 30)

            # Compile episode directly in one single pass
            temp_video_path = output_video_path + ".tmp.mp4"
            if os.path.exists(temp_video_path):
                os.remove(temp_video_path)
            try:
                await asyncio.to_thread(
                    render_episode_video_sync,
                    images_blur_dir, image_files, segments, timings, temp_video_path,
                    ffmpeg_exe, working_encoder, audio_path, logo_path, overlay_path,
                    subtitles_enabled, "transcript.srt", fps
                )
            except Exception as render_error:
                if not can_recover_ffmpeg_pipe_output(render_error, temp_video_path):
                    raise
                await context.log(
                    f"Tập {ep}: FFmpeg đóng pipe sau khi đã tạo MP4 hợp lệ; tiếp tục commit output.",
                    "warning",
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
        import shutil
        import time
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
        
        video_durations = []
        srt_paths = []
        for ep in episodes_processed:
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            video_path = os.path.join(ep_dir, "video.mp4")
            srt_path = os.path.join(ep_dir, "transcript.srt")
            video_durations.append(get_video_duration(video_path, ffmpeg_exe))
            srt_paths.append(srt_path)

        if total_episodes == 1:
            single_video = os.path.join(download_dir, f"episode_{from_ep}", "video.mp4")
            cmd = [
                ffmpeg_exe, "-y",
                "-i", single_video,
                "-c", "copy",
                "-movflags", "faststart",
                temp_final_video_path
            ]
            proc = await asyncio.create_subprocess_exec(*cmd, cwd=download_dir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                shutil.copy2(single_video, temp_final_video_path)
            await context.log(f"Chỉ có 1 tập, đóng gói hoàn thiện {final_video_name} (faststart).", "success")
            
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

            await context.log("Đang tiến hành gộp các file phụ đề srt...", "info")
            merge_srt_files(srt_paths, video_durations, temp_final_srt_path)
            await context.log(f"Đã hoàn thành gộp phụ đề thành {final_srt_name}.", "success")

        if not os.path.isfile(temp_final_video_path) or os.path.getsize(temp_final_video_path) == 0:
            raise RuntimeError("Final video output is missing or empty")
        if not os.path.isfile(temp_final_srt_path) or os.path.getsize(temp_final_srt_path) == 0:
            raise RuntimeError("Final subtitle output is missing or empty")
        for p_src, p_dst in [(temp_final_video_path, final_video_path), (temp_final_srt_path, final_srt_path)]:
            if os.path.exists(p_dst):
                try:
                    os.remove(p_dst)
                except Exception:
                    pass
            for _ in range(5):
                try:
                    shutil.move(p_src, p_dst)
                    break
                except Exception:
                    time.sleep(0.5)
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
