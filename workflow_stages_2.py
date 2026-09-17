import os
import json
import asyncio
import re
import time
import logging
import config
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

logger = logging.getLogger(__name__)


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
        elif language in ("ja", "japanese"):
            from markets.japan_isekai_territory.tts import (
                DEFAULT_JA_VOICE_ID,
                DEFAULT_JA_VOICE_RATE,
                DEFAULT_JA_VOICE_PITCH,
            )
            voice_id = raw_voice_id if raw_voice_id and raw_voice_id not in ("ai33pro", "auto", "default") else DEFAULT_JA_VOICE_ID
            rate = DEFAULT_JA_VOICE_RATE
            pitch = DEFAULT_JA_VOICE_PITCH
        elif language in ("vi", "vietnamese"):
            import config
            default_vi_voice = getattr(config, "DEFAULT_VI_VOICE_ID", "clone")
            voice_id = raw_voice_id if raw_voice_id and raw_voice_id not in ("ai33pro", "auto", "default") else default_vi_voice
            rate = getattr(config, "DEFAULT_VI_VOICE_RATE", "+0%")
            pitch = getattr(config, "DEFAULT_VI_VOICE_PITCH", "+0Hz")
        else:
            default_voice = "auto"
            voice_id = normalize_tts_voice_mode(raw_voice_id or default_voice, default=default_voice)

        ref_audio_path = task.payload.get("ref_audio_path")
        if not ref_audio_path and voice_id in ("auto", "clone", "omnivoice", "default"):
            import config
            if language in ("vi", "vietnamese"):
                ref_audio_path = getattr(config, "DEFAULT_VI_REF_AUDIO", getattr(config, "DEFAULT_REF_AUDIO_PATH", None))
            else:
                ref_audio_path = getattr(config, "DEFAULT_REF_AUDIO_PATH", None)

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
                outputs=[audio_path, srt_path, cache_path],
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
            srt_temp_path = srt_path + ".tmp"
            task_lang = task.payload.get("language")
            success = await generate_tts(narration_text, audio_temp_path, srt_temp_path, voice_id, ref_audio_path, rate=rate, pitch=pitch, language=task_lang)
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
            cache.commit(stage="tts", fingerprint=fingerprint, outputs=[audio_path, srt_path, cache_path])

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


def count_meaningful_units(text: str) -> int:
    """
    Counts meaningful alphanumeric / phonetic units in text across ANY language:
    - Latin (English): counts letters & digits
    - Vietnamese: counts letters with diacritics & digits
    - CJK (Japanese, Chinese): counts kanji, kana, hanzi (each is a syllable/mora)
    - Korean: counts hangul syllables
    Strips inline bracket tags like [speed_...] or [1, 9] annotations.
    """
    cleaned = re.sub(r'\[.*?\]', '', text)
    chars = [c for c in cleaned if c.isalnum()]
    return len(chars)


def align_subtitles_to_segments(subtitles: list, segments: list, audio_duration: float = 0.0) -> list:
    """
    Aligns Whisper subtitle cues to recap segments using cumulative phonetic/character ratio.
    Works universally across all languages (Japanese, Korean, Chinese, Vietnamese, English).
    Returns normalized_srt_entries: list of {"start": float, "end": float, "text": str}.
    """
    if not segments:
        return []

    if not subtitles:
        total_chars = sum(max(1, count_meaningful_units(s.get("speech", ""))) for s in segments)
        dur = audio_duration if audio_duration > 0 else len(segments) * 5.0
        curr = 0.0
        result = []
        for s in segments:
            c = max(1, count_meaningful_units(s.get("speech", "")))
            seg_dur = max(2.5, (c / max(1, total_chars)) * dur)
            result.append({
                "start": curr,
                "end": curr + seg_dur,
                "text": s.get("speech", "")
            })
            curr += seg_dur
        return result

    segment_counts = [max(1, count_meaningful_units(seg.get("speech", ""))) for seg in segments]
    total_segment_units = sum(segment_counts)

    segment_ranges = []
    current_idx = 0
    for count in segment_counts:
        segment_ranges.append((current_idx, current_idx + count))
        current_idx += count

    if len(subtitles) == len(segments):
        for idx_sub, sub in enumerate(subtitles):
            sub["matched_segment_idx"] = idx_sub
    else:
        sub_counts = [max(1, count_meaningful_units(sub.get("text", ""))) for sub in subtitles]
        total_sub_units = sum(sub_counts)

        ratio = total_segment_units / total_sub_units if total_sub_units > 0 else 1.0

        prev_units = 0
        for s_idx, sub in enumerate(subtitles):
            count = sub_counts[s_idx]
            mid_unit_idx = prev_units + count / 2.0
            scaled_unit_idx = mid_unit_idx * ratio

            matched_seg = len(segments) - 1
            for seg_idx, (start, end) in enumerate(segment_ranges):
                if start <= scaled_unit_idx < end:
                    matched_seg = seg_idx
                    break
            sub["matched_segment_idx"] = matched_seg
            prev_units += count

    normalized_entries = []
    last_end_time = 0.0

    for seg_idx, seg in enumerate(segments):
        char_count = max(1, count_meaningful_units(seg.get("speech", "")))
        min_seg_dur = max(1.8, min(4.0, char_count * 0.08))

        matched_subs = [sub for sub in subtitles if sub.get("matched_segment_idx") == seg_idx]
        if matched_subs:
            start_time = min(sub["start"] for sub in matched_subs)
            end_time = max(sub["end"] for sub in matched_subs)
        else:
            start_time = last_end_time
            if total_segment_units > 0 and audio_duration > 0:
                estimated_dur = max(min_seg_dur, (char_count / total_segment_units) * audio_duration)
            else:
                estimated_dur = max(min_seg_dur, char_count * 0.15)
            end_time = start_time + estimated_dur

        if start_time < last_end_time:
            start_time = last_end_time
        # Hard floor: Ensure segment duration is at least min_seg_dur (>= 1.8s)
        # Prevents Whisper compression flicker (e.g. 0.11s segments)
        if (end_time - start_time) < min_seg_dur:
            end_time = start_time + min_seg_dur

        last_end_time = end_time
        normalized_entries.append({
            "start": start_time,
            "end": end_time,
            "text": seg.get("speech", "")
        })

    return normalized_entries


class Stage9_SubtitleNormalization(BaseStage):
    @property
    def name(self) -> str: return "Stage 9 - Subtitle Normalization"
    @property
    def weight(self) -> float: return 0.03

    async def execute(self, context: WorkflowContext) -> bool:
        from app import parse_time_to_seconds, find_ffmpeg
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

            audio_dur = 0.0
            if os.path.exists(audio_path):
                try:
                    audio_dur = get_video_duration(audio_path, find_ffmpeg())
                except Exception:
                    pass

            normalized_srt_entries = align_subtitles_to_segments(subtitles, segments, audio_dur)

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


def detect_clean_panel_and_focal_point(img_pil) -> tuple[tuple, tuple, float, tuple, float]:
    """
    Detects the character focal point (with speech bubble suppression and skin tone boost)
    and automatically isolates the active comic panel (excluding neighboring panels and solid gutters).
    Returns (bounds, focal_point, skin_ratio, bubble_centroid, bubble_coverage_ratio) where:
      bounds = (cb_x, cb_y, W_c, H_c)
      focal_point = (focal_x, focal_y) relative to bounds — real subject position, NOT center-locked.
      skin_ratio = float [0..1] fraction of panel pixels with skin tone (drives adaptive zoom strength).
      bubble_centroid = (bx, by) centroid of speech bubble region relative to bounds (for repulsion).
      bubble_coverage_ratio = float [0..1] fraction of panel area covered by speech bubbles.
    """
    import cv2
    import numpy as np

    img_rgb = np.array(img_pil.convert("RGB"))
    h_full, w_full, _ = img_rgb.shape

    if h_full < 20 or w_full < 20:
        return (0, 0, w_full, h_full), (w_full / 2.0, h_full / 2.0), 0.0, (w_full / 2.0, h_full / 2.0)

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

    # 5. Subject / eye-line vertical prior (centered around 40% height for face/torso/action)
    y_idx, x_idx = np.indices((h_full, w_full))
    y_prior = np.exp(-((y_idx - 0.40 * h_full) ** 2) / (2 * (0.35 * h_full) ** 2))
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

    # AI Face Detection Priority (YuNet ONNX)
    detected_faces = []
    try:
        from visual_scorer import VisualSemanticScorer
        bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        detected_faces = VisualSemanticScorer.detect_faces(bgr)
    except Exception:
        detected_faces = []

    if detected_faces:
        # Choose the most prominent face
        best_face = max(detected_faces, key=lambda f: float(f[2] * f[3]) * (1.0 + float(f[-1])))
        fx0, fy0, fw, fh = float(best_face[0]), float(best_face[1]), float(best_face[2]), float(best_face[3])
        # Eye-line focal point with Headroom Protection
        raw_focal_x = float(np.clip(fx0 + fw / 2.0, 0.15 * w_full, 0.85 * w_full))
        raw_focal_y = float(np.clip(fy0 + fh * 0.42, 0.10 * h_full, 0.90 * h_full))
    else:
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
    p_top = panel_top if h_panel >= 250 else top_gutter
    p_bot = panel_bot if h_panel >= 250 else bot_gutter
    h_act = max(20, p_bot - p_top)

    # 7. Asymmetric Void & Vertical Gutter Trimming (Left & Right outer gutters)
    panel_slice = crop_gray[p_top:p_bot, :]
    col_std = np.std(panel_slice, axis=0)
    col_mean = np.mean(panel_slice, axis=0)

    max_left = int(w_full * 0.45)
    left_gutter = 0
    while left_gutter < max_left and col_std[left_gutter] < 4.5 and (col_mean[left_gutter] <= 20 or col_mean[left_gutter] >= 235):
        left_gutter += 1

    min_right = int(w_full * 0.55)
    right_gutter = w_full - 1
    while right_gutter > min_right and col_std[right_gutter] < 4.5 and (col_mean[right_gutter] <= 20 or col_mean[right_gutter] >= 235):
        right_gutter -= 1
    right_gutter += 1

    w_act = right_gutter - left_gutter
    if w_act < 200:
        left_gutter = 0
        w_act = w_full

    clean_bounds = (left_gutter, p_top, w_act, h_act)
    local_focal_x = float(np.clip(raw_focal_x - left_gutter, 0.15 * w_act, 0.85 * w_act))
    local_focal_y = float(np.clip(raw_focal_y - p_top, 0.15 * h_act, 0.85 * h_act))

    panel_region = bubble_mask_dilated[p_top:p_bot, left_gutter:left_gutter + w_act]
    panel_skin = skin_mask[p_top:p_bot, left_gutter:left_gutter + w_act]
    total_panel_pixels = max(1, panel_skin.size)
    skin_ratio = float(np.count_nonzero(panel_skin)) / total_panel_pixels

    # Dominant Bubble Centroid (v1.7.0): Select largest connected bubble to prevent vector cancellation
    if np.any(panel_region):
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(panel_region.astype(np.uint8))
        if num_labels > 1:
            areas = stats[1:, cv2.CC_STAT_AREA]
            max_idx = 1 + int(np.argmax(areas))
            bubble_cx = float(centroids[max_idx][0])
            bubble_cy = float(centroids[max_idx][1])
        else:
            bubble_cx = w_act / 2.0
            bubble_cy = h_act / 2.0
    else:
        # No bubbles detected — centroid at panel center (neutral repulsion)
        bubble_cx = w_act / 2.0
        bubble_cy = h_act / 2.0

    # Compute bubble_coverage_ratio within the active panel (for downstream crop/repulsion)
    panel_bubble = bubble_mask_dilated[p_top:p_bot, left_gutter:left_gutter + w_act]
    bubble_coverage_ratio = float(np.mean(panel_bubble)) if panel_bubble.size > 0 else 0.0

    return clean_bounds, (local_focal_x, local_focal_y), skin_ratio, (bubble_cx, bubble_cy), bubble_coverage_ratio


def detect_content_bounds(img: Image) -> tuple:
    bounds, _, _, _, _ = detect_clean_panel_and_focal_point(img)
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

    # AI Face Detection Priority (YuNet ONNX)
    detected_faces = []
    try:
        from visual_scorer import VisualSemanticScorer
        crop_bgr = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2BGR)
        detected_faces = VisualSemanticScorer.detect_faces(crop_bgr)
    except Exception:
        detected_faces = []

    if detected_faces:
        best_face = max(detected_faces, key=lambda f: float(f[2] * f[3]) * (1.0 + float(f[-1])))
        fx0, fy0, fw, fh = float(best_face[0]), float(best_face[1]), float(best_face[2]), float(best_face[3])
        mean_x = fx0 + fw / 2.0
        mean_y = fy0 + fh * 0.42

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

def soft_linear_glide(t: float) -> float:
    """
    Continuous smooth gliding curve: 5% gentle ease-in, 90% constant velocity, 5% gentle ease-out.
    Prevents abrupt stops while maintaining continuous pacing.
    """
    t = max(0.0, min(1.0, float(t)))
    p = 0.05
    if t < p:
        return 0.5 * (t / p) ** 2 * (p / (1.0 - p))
    elif t > (1.0 - p):
        dt = (1.0 - t) / p
        return 1.0 - 0.5 * (dt ** 2) * (p / (1.0 - p))
    else:
        return (t - p * 0.5) / (1.0 - p)


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
    @classmethod
    def generate_camera_plan(
        cls,
        page_num: int,
        duration: float,
        bounds: tuple,
        focal_point: tuple = None,
        transition: str = "cross_fade",
        skin_ratio: float = 0.0,
        bubble_centroid: tuple = None,
        bubble_coverage_ratio: float = 0.0,
        shot_index: int = 0,
    ) -> dict:
        """
        Generates a continuous, smooth cinematic camera plan for webtoon storytelling.
        - Primary motion: Smooth continuous Vertical Pan (sliding top-to-bottom or bottom-to-top)
          for all portrait and tall panels (aspect_ratio < 1.15).
        - Wide panels (aspect_ratio >= 1.15): Smooth continuous Horizontal Pan.
        - 2D Bubble Repulsion: Repels camera focal point away from speech bubble regions in both X and Y.
        - Zero-Clamping Freeze: Interpolation glides continuously across the full shot duration without stopping.
        """
        cb_x, cb_y, W_c, H_c = bounds
        center_x = W_c / 2.0
        center_y = H_c / 2.0
        aspect_ratio = W_c / max(1.0, float(H_c))

        # Enhanced 2D Bubble-Centroid Repulsion & Exclusion Offset (X & Y)
        y_bias = 0.0
        x_bias = 0.0
        if bubble_centroid:
            bubble_cx, bubble_cy = bubble_centroid
            repulsion_strength = 0.25 + min(0.25, bubble_coverage_ratio * 0.6)
            dx_bubble = center_x - bubble_cx
            if abs(dx_bubble) > W_c * 0.05:
                x_bias = dx_bubble * repulsion_strength
            
            # Y repulsion: push away from bubbles at the top or bottom of panel
            dy_bubble = center_y - bubble_cy
            if abs(dy_bubble) > H_c * 0.05:
                y_bias = dy_bubble * repulsion_strength

            # Strong vertical directional push when bubble is concentrated at top or bottom
            if bubble_coverage_ratio >= 0.18:
                if bubble_cy < 0.38 * H_c:
                    y_bias = max(y_bias, H_c * 0.20)
                elif bubble_cy > 0.62 * H_c:
                    y_bias = min(y_bias, -H_c * 0.22)
                if bubble_cx < 0.38 * W_c:
                    x_bias = max(x_bias, W_c * 0.16)
                elif bubble_cx > 0.62 * W_c:
                    x_bias = min(x_bias, -W_c * 0.16)

        if focal_point is None:
            focal_x = center_x + x_bias
            focal_y = center_y + y_bias
        else:
            fx_raw, fy_raw = focal_point
            focal_x = center_x * 0.25 + float(fx_raw) * 0.75 + x_bias
            focal_y = center_y * 0.25 + float(fy_raw) * 0.75 + y_bias

        focal_x = float(np.clip(focal_x, 0.15 * W_c, 0.85 * W_c))
        focal_y = float(np.clip(focal_y, 0.18 * H_c, 0.82 * H_c))

        easing = "soft_linear_glide"

        # Mode A: Landscape / Extreme Panoramic Panels (aspect_ratio >= 2.20) -> Smooth Cinematic Horizontal Pan
        # (Allows natural scanning across wide manga spreads and landscape battle scenes)
        if aspect_ratio >= 2.20:
            animation_type = "cinematic_pan_horizontal"
            dir_x = 1.0 if (shot_index % 2 == 0) else -1.0
            direction = "left_to_right" if dir_x > 0 else "right_to_left"
            pan_span = max(15.0, min(W_c * 0.12, 80.0))
            x_start = float(np.clip(center_x - dir_x * pan_span * 0.5, 0.15 * W_c, 0.85 * W_c))
            x_end = float(np.clip(center_x + dir_x * pan_span * 0.5, 0.15 * W_c, 0.85 * W_c))
            keyframes = [
                {"time": 0.0, "x": x_start, "y": focal_y, "scale": 1.00, "progress": 0.0},
                {"time": duration, "x": x_end, "y": focal_y, "scale": 1.00, "progress": 1.0}
            ]
            return {
                "page": page_num,
                "duration": duration,
                "animation_type": animation_type,
                "direction": direction,
                "easing": easing,
                "keyframes": keyframes,
                "transition": transition,
                "bubble_centroid": bubble_centroid,
                "bubble_coverage_ratio": bubble_coverage_ratio,
            }

        # Measure usable vertical travel distance for vertical pan
        # Only tall webtoon strips (aspect_ratio < 0.70) have vertical sliding headroom
        if aspect_ratio < 0.70:
            h_view_ref = W_c / 0.68
            usable_v_travel = H_c - h_view_ref
        else:
            usable_v_travel = 0.0

        # Mode B: Tall Webtoon Strip Panel (usable_v_travel >= 160px) -> Continuous Vertical Pan Glide
        # Adaptive Velocity Clamping (v1.7.0): Cap pan speed at 120 px/s to prevent dizzying camera motion
        max_travel_by_speed = max(20.0, float(duration) * 120.0)
        max_travel_by_panel = H_c * 0.35
        travel_span = min(max_travel_by_panel, max_travel_by_speed)

        h_cam_ref = W_c / 0.68
        min_valid_y = float(h_cam_ref * 0.5)
        max_valid_y = float(H_c - h_cam_ref * 0.5)
        if min_valid_y >= max_valid_y:
            min_valid_y, max_valid_y = 0.10 * H_c, 0.90 * H_c

        actual_span = min(travel_span, max(0.0, max_valid_y - min_valid_y))

        if usable_v_travel >= 160.0 and actual_span >= 50.0:
            animation_type = "vertical_pan_glide"
            
            # Smart direction: If bubble is concentrated in upper 38%, pan bottom-to-top to emphasize character first
            if bubble_centroid and bubble_coverage_ratio > 0.18 and bubble_centroid[1] < 0.38 * H_c:
                direction = "bottom_to_top"
            elif bubble_centroid and bubble_coverage_ratio > 0.18 and bubble_centroid[1] > 0.62 * H_c:
                direction = "top_to_bottom"
            else:
                direction = "top_to_bottom" if (shot_index % 2 == 0) else "bottom_to_top"

            y_anchor = float(np.clip(focal_y, min_valid_y + actual_span * 0.5, max_valid_y - actual_span * 0.5))
            y_top = y_anchor - actual_span * 0.5
            y_bot = y_anchor + actual_span * 0.5

            # Bubble-Exclusion Clamping: Prevent camera from panning over speech bubbles at top/bottom
            if bubble_centroid and bubble_coverage_ratio >= 0.15:
                bubble_cx, bubble_cy = bubble_centroid
                if bubble_cy < 0.35 * H_c:
                    bubble_bottom_edge = float(bubble_cy + H_c * 0.14)
                    y_top = max(y_top, min(bubble_bottom_edge, y_anchor))
                elif bubble_cy > 0.65 * H_c:
                    bubble_top_edge = float(bubble_cy - H_c * 0.14)
                    y_bot = min(y_bot, max(bubble_top_edge, y_anchor))

            if y_top >= y_bot:
                y_top = max(min_valid_y, y_anchor - 20.0)
                y_bot = min(max_valid_y, y_anchor + 20.0)

            if direction == "top_to_bottom":
                y_start, y_end = y_top, y_bot
            else:
                y_start, y_end = y_bot, y_top

            keyframes = [
                {"time": 0.0, "x": focal_x, "y": y_start, "scale": 1.00, "progress": 0.0},
                {"time": duration, "x": focal_x, "y": y_end, "scale": 1.00, "progress": 1.0}
            ]
            return {
                "page": page_num,
                "duration": duration,
                "animation_type": animation_type,
                "direction": direction,
                "easing": easing,
                "keyframes": keyframes,
                "transition": transition,
                "bubble_centroid": bubble_centroid,
                "bubble_coverage_ratio": bubble_coverage_ratio,
            }

        # Mode C: Standard / Square / Landscape Panels (usable_v_travel < 160px)
        # Ultra-Long Duration (> 7.0s): Dual-phase continuous Ken Burns motion (Scale 1.00 -> 1.10 -> 1.00)
        # Prevents visual stagnation on long narration without jarring cuts
        if duration > 7.0:
            animation_type = "dual_shot_cinematic"
            direction = "zoom_in_out"
            t_split = round(duration * 0.5, 3)
            keyframes = [
                {"time": 0.0, "x": focal_x, "y": focal_y, "scale": 1.00, "progress": 0.0},
                {"time": t_split, "x": focal_x, "y": focal_y, "scale": 1.10, "progress": 0.5},
                {"time": duration, "x": focal_x, "y": focal_y, "scale": 1.00, "progress": 1.0},
            ]
            return {
                "page": page_num,
                "duration": duration,
                "animation_type": animation_type,
                "direction": direction,
                "easing": easing,
                "keyframes": keyframes,
                "transition": transition,
                "bubble_centroid": bubble_centroid,
                "bubble_coverage_ratio": bubble_coverage_ratio,
            }

        # Smooth Ken Burns Focus Zoom In / Zoom Out luân phiên (Scale 1.00 <-> 1.10)
        # Keeps 100% of panel artwork visible at all times with gentle, cinematic motion
        if shot_index % 2 == 0:
            animation_type = "focal_zoom_in"
            direction = "zoom_in"
            keyframes = [
                {"time": 0.0, "x": focal_x, "y": focal_y, "scale": 1.00, "progress": 0.0},
                {"time": duration, "x": focal_x, "y": focal_y, "scale": 1.10, "progress": 1.0}
            ]
        else:
            animation_type = "focal_zoom_out"
            direction = "zoom_out"
            keyframes = [
                {"time": 0.0, "x": focal_x, "y": focal_y, "scale": 1.10, "progress": 0.0},
                {"time": duration, "x": focal_x, "y": focal_y, "scale": 1.00, "progress": 1.0}
            ]

        return {
            "page": page_num,
            "duration": duration,
            "animation_type": animation_type,
            "direction": direction,
            "easing": easing,
            "keyframes": keyframes,
            "transition": transition,
            "bubble_centroid": bubble_centroid,
            "bubble_coverage_ratio": bubble_coverage_ratio,
        }


def interpolate_camera_progress(plan: dict, t_local: float) -> float:
    keyframes = plan.get("keyframes", [])
    if not keyframes:
        return 0.0
    t0 = keyframes[0]["time"]
    t1 = keyframes[-1]["time"]
    if t_local <= t0:
        return float(keyframes[0].get("progress", 0.0))
    if t_local >= t1:
        return float(keyframes[-1].get("progress", 1.0))
    
    easing_name = plan.get("easing", "soft_linear_glide")
    if easing_name == "soft_linear_glide":
        ease_func = soft_linear_glide
    elif easing_name == "linear":
        ease_func = lambda t: t
    elif easing_name == "easeInOutSine":
        ease_func = ease_in_out_sine
    elif easing_name == "easeOutQuart":
        ease_func = ease_out_quart
    elif easing_name == "easeInOutCubic":
        ease_func = ease_in_out_cubic
    else:
        ease_func = soft_linear_glide

    dur = t1 - t0
    if dur <= 0.001:
        return 0.0
    local_t = (t_local - t0) / dur
    return ease_func(local_t)


def interpolate_camera_plan(plan: dict, t_local: float) -> tuple:
    keyframes = plan["keyframes"]
    if t_local <= keyframes[0]["time"]:
        return keyframes[0]["x"], keyframes[0]["y"], keyframes[0]["scale"]
    if t_local >= keyframes[-1]["time"]:
        return keyframes[-1]["x"], keyframes[-1]["y"], keyframes[-1]["scale"]

    easing_name = plan.get("easing", "soft_linear_glide")
    if easing_name == "soft_linear_glide":
        ease_func = soft_linear_glide
    elif easing_name == "linear":
        ease_func = lambda t: t
    elif easing_name == "easeInOutSine":
        ease_func = ease_in_out_sine
    elif easing_name == "easeOutQuart":
        ease_func = ease_out_quart
    elif easing_name == "easeInOutCubic":
        ease_func = ease_in_out_cubic
    else:
        ease_func = soft_linear_glide

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

        def _render_episode_video_sync_impl(images_blur_dir, image_files, segments, timings, output_video_path, ffmpeg_exe, working_encoder, audio_path, logo_path, overlay_path, subtitles_enabled_flag, srt_filename, fps=30, stderr_file=None, stderr_log_path=None, min_panel_duration=3.5, hard_floor_duration=3.0, **kwargs):
            from PIL import Image, ImageFilter, ImageEnhance, ImageDraw
            import subprocess
            import numpy as np
            import cv2
            import math
            
            # Start single unified FFmpeg process with high quality settings
            if "nvenc" in str(working_encoder).lower():
                extra_args = ["-preset", "p4", "-cq", "19", "-rc", "constqp", "-b:v", "12M"]
            elif "amf" in str(working_encoder).lower():
                extra_args = ["-rc", "cqp", "-qp_i", "19", "-qp_p", "19", "-b:v", "12M"]
            elif "libx264" in str(working_encoder).lower():
                extra_args = ["-crf", "18", "-preset", "veryfast"]
            else:
                extra_args = ["-b:v", "6M"]
            
            ep_dir = os.path.dirname(output_video_path)
            images_pdf_dir = os.path.join(ep_dir, "images_pdf")
            logo_rel = os.path.relpath(logo_path, ep_dir).replace('\\', '/')
            overlay_rel = os.path.relpath(overlay_path, ep_dir).replace('\\', '/')
            
            has_custom_logo = bool(logo_path and os.path.exists(logo_path) and os.path.basename(logo_path) != "logo.png")
            has_custom_overlay = bool(overlay_path and os.path.exists(overlay_path) and os.path.basename(overlay_path) != "overlay.png")

            audio_inputs = ["-i", audio_path]
            if has_custom_logo or has_custom_overlay:
                filter_complex_str = (
                    f"movie={logo_rel} [logo_raw]; [logo_raw]scale=50:50[logo]; "
                    f"movie={overlay_rel} [ol_raw]; [ol_raw]scale=1920:1080,format=rgba,colorchannelmixer=aa=0.005[ol]; "
                    f"[0:v][ol]overlay[temp1]; [temp1][logo]overlay=25:25[v]"
                )
                filter_args = ["-filter_complex", filter_complex_str, "-map", "[v]", "-map", "1:a"]
            else:
                filter_args = ["-map", "0:v", "-map", "1:a"]

            cmd = [
                ffmpeg_exe, "-y",
                "-f", "rawvideo",
                "-pix_fmt", "rgb24",
                "-s", "1920x1080",
                "-r", str(fps),
                "-i", "-",               # Raw video from stdin [0:v]
            ] + audio_inputs + filter_args + [
                "-c:v", working_encoder,
                "-pix_fmt", "yuv420p"
            ] + extra_args + [
                "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "44100", "-shortest", output_video_path
            ]
            
            if stderr_log_path is None:
                stderr_log_path = os.path.join(os.path.dirname(output_video_path), "ffmpeg_render_stderr.log")
            if stderr_file is None:
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
            recent_used_donors = []
            for s_idx, seg in enumerate(segments):
                end_time = timings[s_idx]["end"] if s_idx < len(timings) else current_time + 3.0
                segment_duration = end_time - current_time
                if s_idx == len(segments) - 1:
                    segment_duration = max(3.0, segment_duration + 3.0)
                if segment_duration <= 0:
                    segment_duration = 1.0
                
                seg_images = seg.get("images", [])

                # Universal guardrail against meaningless / text-bubble panels:
                # Works for ALL segments including single-image ones (fixing critical gap).
                if seg_images:
                    from visual_scorer import VisualSemanticScorer
                    scored_candidates = []
                    for img_obj in seg_images:
                        p_idx = int(img_obj["page"]) - 1
                        if 0 <= p_idx < len(image_files):
                            im_path = os.path.join(images_blur_dir, image_files[p_idx])
                            if not os.path.exists(im_path):
                                im_path = os.path.join(images_pdf_dir, image_files[p_idx])
                            try:
                                im_bgr = cv2.imread(im_path)
                                sc, bd = VisualSemanticScorer.calculate_score(im_bgr)
                                bubble_cov = bd.get("bubble_coverage_ratio", 0.0)
                                char_p = bd.get("character_presence", 0.0)
                                is_bad = (
                                    bd.get("is_meaningless", False)
                                    or sc < 50
                                    or (bubble_cov > 0.65 and char_p < 40.0)
                                    or bubble_cov > 0.78
                                    or char_p < 25.0
                                )
                            except Exception:
                                sc, char_p, is_bad = 70, 50.0, False
                                bd = {}
                            scored_candidates.append((img_obj, sc, char_p, is_bad, bd.get("is_meaningless", False)))
                    valid_art = [item[0] for item in scored_candidates if not item[3]]
                    if valid_art:
                        seg_images = valid_art
                        tot_p = sum(float(img.get("priority", 1.0)) for img in seg_images)
                        for img in seg_images:
                            img["priority"] = float(img.get("priority", 1.0)) / max(0.001, tot_p)
                    else:
                        # All images are bad, meaningless, low-character, or bubble-heavy — find best adjacent page as replacement
                        # Ranked by composite score: 60% total + 40% character_presence (character-first priority)
                        best_item = max(scored_candidates, key=lambda x: x[1]) if scored_candidates else None
                        if best_item:
                            bad_page_idx = int(best_item[0]["page"]) - 1
                            best_composite = -1
                            best_idx = bad_page_idx
                            for delta in [1, -1, 2, -2, 3, -3, 4, -4, 5, -5]:
                                candidate = bad_page_idx + delta
                                if 0 <= candidate < len(image_files):
                                    cand_page = candidate + 1
                                    im_path = os.path.join(images_blur_dir, image_files[candidate])
                                    if not os.path.exists(im_path):
                                        im_path = os.path.join(images_pdf_dir, image_files[candidate])
                                    try:
                                        im_bgr = cv2.imread(im_path)
                                        sc, bd = VisualSemanticScorer.calculate_score(im_bgr)
                                        char_p = bd.get("character_presence", 0.0)
                                        bubble_cov = bd.get("bubble_coverage_ratio", 0.0)
                                        # Stateful Deduplication Penalty (v1.7.0): penalize recently used donors to avoid repeated imagery
                                        recent_penalty = 25.0 if cand_page in recent_used_donors[-2:] else 0.0
                                        composite = sc * 0.60 + char_p * 0.40 - recent_penalty
                                        # Adaptive Donor Qualification: char_p >= 30.0 covers shaded/hooded character portraits (sc >= 58)
                                        donor_valid = (
                                            not bd.get("is_meaningless", False)
                                            and bubble_cov < 0.50
                                            and ((char_p >= 40.0 and sc >= 55) or (char_p >= 30.0 and sc >= 58))
                                            and composite > best_composite
                                        )
                                        if donor_valid:
                                            best_composite = composite
                                            best_idx = candidate
                                    except Exception:
                                        pass
                            if best_composite >= 50:
                                chosen_page = best_idx + 1
                                seg_images = [{"page": chosen_page, "priority": 1.0}]
                                recent_used_donors.append(chosen_page)
                                print(f"  [Stage10] Replaced low-quality/junk/bubble page {bad_page_idx + 1} with character page {chosen_page} (composite={best_composite:.1f})")
                            else:
                                # Fallback: drop any explicitly meaningless panels from seg_images if better candidates exist
                                non_meaningless = [c[0] for c in scored_candidates if not c[4] and c[1] >= 40]
                                if non_meaningless:
                                    seg_images = [non_meaningless[0]]
                                elif best_item:
                                    seg_images = [{"page": best_item[0]["page"], "priority": 1.0}]

                # Cinematic Pacing Guardrail & Dynamic Hero Image Selector (Industry Standard >= 3.5s):
                # If a segment is too short for multiple images, keep only the highest-scoring Hero Image(s).
                if seg_images and len(seg_images) > 1 and (segment_duration / len(seg_images)) < min_panel_duration:
                    max_allowed = max(1, int(segment_duration // min_panel_duration))

                    def candidate_hero_score(img_dict):
                        p_num = int(img_dict.get("page", 1)) - 1
                        base_priority = float(img_dict.get("priority", 1.0))
                        if 0 <= p_num < len(image_files):
                            im_p = os.path.join(images_blur_dir, image_files[p_num])
                            if not os.path.exists(im_p):
                                im_p = os.path.join(images_pdf_dir, image_files[p_num])
                            try:
                                im_mat = cv2.imread(im_p)
                                sc, bd = VisualSemanticScorer.calculate_score(im_mat)
                                char_p = bd.get("character_presence", 0.0)
                                bubble_cov = bd.get("bubble_coverage_ratio", 0.0)
                                return (sc * 0.60 + char_p * 0.40 - bubble_cov * 15.0) * base_priority
                            except Exception:
                                pass
                        return 50.0 * base_priority

                    sorted_indices = sorted(
                        range(len(seg_images)),
                        key=lambda i: candidate_hero_score(seg_images[i]),
                        reverse=True
                    )
                    kept_indices = set(sorted_indices[:max_allowed])
                    seg_images = [img for idx, img in enumerate(seg_images) if idx in kept_indices]
                    tot_p = sum(float(img.get("priority", 1.0)) for img in seg_images)
                    for img in seg_images:
                        img["priority"] = float(img.get("priority", 1.0)) / max(0.001, tot_p)

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

            # Merge consecutive displays of the exact same image to avoid redundant cross-fading
            merged_page_displays = []
            for pd in page_displays:
                if merged_page_displays and merged_page_displays[-1]["image_file"] == pd["image_file"]:
                    merged_page_displays[-1]["duration"] += pd["duration"]
                    merged_page_displays[-1]["end_time"] = merged_page_displays[-1]["start_time"] + merged_page_displays[-1]["duration"]
                else:
                    merged_page_displays.append(pd)

            # Hard Floor (>= 3.0s default) Display Guardrail:
            # Eliminate sub-3.0s flicker displays by merging duration into adjacent display
            cleaned_page_displays = []
            for pd in merged_page_displays:
                if cleaned_page_displays and pd["duration"] < hard_floor_duration:
                    cleaned_page_displays[-1]["duration"] += pd["duration"]
                    cleaned_page_displays[-1]["end_time"] = (
                        cleaned_page_displays[-1]["start_time"] + cleaned_page_displays[-1]["duration"]
                    )
                else:
                    cleaned_page_displays.append(pd)

            # If the very first display is < hard_floor_duration and there are subsequent displays, merge into next display
            if len(cleaned_page_displays) > 1 and cleaned_page_displays[0]["duration"] < hard_floor_duration:
                first = cleaned_page_displays.pop(0)
                cleaned_page_displays[0]["duration"] += first["duration"]
                cleaned_page_displays[0]["start_time"] = first["start_time"]

            # Secondary pass: re-merge if duration absorption created consecutive identical images
            final_page_displays = []
            for pd in cleaned_page_displays:
                if final_page_displays and final_page_displays[-1]["image_file"] == pd["image_file"]:
                    final_page_displays[-1]["duration"] += pd["duration"]
                    final_page_displays[-1]["end_time"] = (
                        final_page_displays[-1]["start_time"] + final_page_displays[-1]["duration"]
                    )
                else:
                    final_page_displays.append(pd)
            page_displays = final_page_displays

            # Precompute bounds, focal points, and plans
            bounds_cache_path = os.path.join(ep_dir, "content_bounds_cache.json")
            bounds_cache = {}
            if not kwargs.get("force_render", False) and os.path.exists(bounds_cache_path):
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
                if isinstance(cached_data, dict) and "bounds" in cached_data and "focal_point" in cached_data and "skin_ratio" in cached_data:
                    bounds = tuple(cached_data["bounds"])
                    focal_point = tuple(cached_data["focal_point"])
                    skin_ratio = float(cached_data["skin_ratio"])
                    bubble_centroid = tuple(cached_data["bubble_centroid"]) if "bubble_centroid" in cached_data else None
                    bubble_coverage_ratio = float(cached_data.get("bubble_coverage_ratio", 0.0))
                elif isinstance(cached_data, dict) and "bounds" in cached_data and "focal_point" in cached_data:
                    # Legacy cache entry without skin_ratio — recompute
                    try:
                        with Image.open(img_path) as img:
                            bounds, focal_point, skin_ratio, bubble_centroid, bubble_coverage_ratio = detect_clean_panel_and_focal_point(img)
                            bounds_cache[img_file] = {
                                "bounds": list(bounds), "focal_point": list(focal_point),
                                "skin_ratio": skin_ratio, "bubble_centroid": list(bubble_centroid),
                                "bubble_coverage_ratio": bubble_coverage_ratio
                            }
                            dirty_cache = True
                    except Exception:
                        bounds = tuple(cached_data["bounds"])
                        focal_point = tuple(cached_data["focal_point"])
                        skin_ratio = 0.0
                        bubble_centroid = None
                        bubble_coverage_ratio = 0.0
                elif isinstance(cached_data, list) and len(cached_data) == 4:
                    bounds = tuple(cached_data)
                    try:
                        with Image.open(img_path) as img:
                            _, focal_point_new, skin_ratio, bubble_centroid, bubble_coverage_ratio = detect_clean_panel_and_focal_point(img)
                            focal_point = focal_point_new
                    except Exception:
                        focal_point = (bounds[2] / 2.0, bounds[3] / 2.0)
                        skin_ratio = 0.0
                        bubble_centroid = None
                        bubble_coverage_ratio = 0.0
                    bounds_cache[img_file] = {
                        "bounds": list(bounds), "focal_point": list(focal_point),
                        "skin_ratio": skin_ratio,
                        "bubble_centroid": list(bubble_centroid) if bubble_centroid else [bounds[2] / 2.0, bounds[3] / 2.0],
                        "bubble_coverage_ratio": bubble_coverage_ratio
                    }
                    dirty_cache = True
                else:
                    try:
                        with Image.open(img_path) as img:
                            bounds, focal_point, skin_ratio, bubble_centroid, bubble_coverage_ratio = detect_clean_panel_and_focal_point(img)
                            bounds_cache[img_file] = {
                                "bounds": list(bounds), "focal_point": list(focal_point),
                                "skin_ratio": skin_ratio, "bubble_centroid": list(bubble_centroid),
                                "bubble_coverage_ratio": bubble_coverage_ratio
                            }
                            dirty_cache = True
                    except Exception:
                        bounds = (0, 0, 1920, 1080)
                        focal_point = (960.0, 540.0)
                        skin_ratio = 0.0
                        bubble_centroid = None
                        bubble_coverage_ratio = 0.0
                
                is_last_page = (idx == len(page_displays) - 1)
                trans = "dip_to_black" if is_last_page else "cross_fade"
                
                plan = CameraPlanner.generate_camera_plan(
                    pd["page"], pd["duration"], bounds,
                    focal_point=focal_point, transition=trans,
                    skin_ratio=skin_ratio, bubble_centroid=bubble_centroid,
                    bubble_coverage_ratio=bubble_coverage_ratio,
                    shot_index=idx
                )
                plans.append(plan)
                
            if dirty_cache:
                try:
                    with open(bounds_cache_path, "w", encoding="utf-8") as f:
                        json.dump(bounds_cache, f, indent=4)
                except Exception:
                    pass

            # Page frame rendering helper (Wide Framing, Bubble-Exclusion & Hybrid Motion with OpenCV SIMD)
            def render_page_frame(img_rgb, bg_image, bounds, plan, t_local, card_dims):
                cb_x, cb_y, W_c, H_c = bounds
                card_x, card_y, card_w, card_h, aspect_card = card_dims
                x_focal, y_focal, scale = interpolate_camera_plan(plan, t_local)
                scale = max(1.0, float(scale))

                # True Adaptive Safe-Zone Framing (v1.8.0):
                # Tall webtoon strips with ample sliding travel (usable_v >= 160): w_base = W_c and h_base = W_c / aspect_card
                # Standard / Square / Low-travel panels (usable_v < 160): Fit full panel artwork (w_base = W_c, h_base = H_c)
                aspect_nat = W_c / float(max(1, H_c))
                H_img, W_img = img_rgb.shape[:2]
                usable_v = H_c - (W_c / aspect_card)

                if aspect_nat < 0.70 and usable_v >= 160:
                    w_base = float(W_c)
                    h_base = w_base / aspect_card
                    if h_base > float(H_c):
                        h_base = float(H_c)
                        w_base = h_base * aspect_card
                else:
                    w_base = float(W_c)
                    h_base = float(H_c)
                    # Maintain isotropic scale with zero anamorphic distortion
                    if aspect_card > 0.001:
                        if (w_base / h_base) < aspect_card:
                            w_base = h_base * aspect_card
                        elif (w_base / h_base) > aspect_card:
                            h_base = w_base / aspect_card

                # Clamp to actual image bounds to prevent out-of-bounds crop
                w_base = min(w_base, float(W_img) - cb_x)
                h_base = min(h_base, float(H_img) - cb_y)

                # Dynamic Camera Viewport: scales smoothly with zoom (Ken Burns)
                w_cam = w_base / scale
                h_cam = h_base / scale

                # Travel boundaries inside active panel
                cx_min = cb_x + w_cam / 2.0
                cx_max = cb_x + W_c - w_cam / 2.0

                cy_min = cb_y + h_cam / 2.0
                cy_max = cb_y + H_c - h_cam / 2.0

                # Keyframe-Driven Camera Centering (v1.7.0):
                # Directly honors keyframe coordinates (x_focal, y_focal) from CameraPlanner,
                # guaranteeing velocity clamping, speech bubble exclusion margins, and smooth gliding.
                cy_ideal = cb_y + float(y_focal)
                cy = cy_min if cy_min >= cy_max else float(np.clip(cy_ideal, cy_min, cy_max))

                cx_ideal = cb_x + float(x_focal)
                cx = cx_min if cx_min >= cx_max else float(np.clip(cx_ideal, cx_min, cx_max))

                x1 = cx - w_cam / 2.0
                y1 = cy - h_cam / 2.0
                x2 = cx + w_cam / 2.0
                y2 = cy + h_cam / 2.0

                # High-speed sub-pixel float crop & resize via OpenCV C++ SIMD warpAffine
                sx = float(card_w) / max(0.001, (x2 - x1))
                sy = float(card_h) / max(0.001, (y2 - y1))
                M = np.array([
                    [sx, 0.0, -x1 * sx],
                    [0.0, sy, -y1 * sy]
                ], dtype=np.float32)

                fg_panel = cv2.warpAffine(
                    img_rgb, M, (card_w, card_h),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REPLICATE
                )

                # Composite directly onto background copy in C++ memory
                final_frame = bg_image.copy()
                final_frame[card_y:card_y+card_h, card_x:card_x+card_w] = fg_panel
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

                    # True Adaptive Card Dimensions (v1.8.0):
                    # Preserves 100% of panel artwork without arbitrary cropping or decapitation
                    usable_v = H_c - (W_c / 0.68)
                    if aspect_nat < 0.70 and usable_v >= 160:
                        # Tall webtoon scroll panel with ample vertical headroom -> pillarbox card (0.68) for smooth pan
                        aspect_card = 0.68
                        card_h = 1080
                        card_w = max(10, min(1920, int(round(card_h * aspect_card))))
                        card_x = (1920 - card_w) // 2
                        card_y = 0
                    elif aspect_nat <= 16.0 / 9.0:
                        # Standard / Square / Portrait / Landscape panel -> Fit height 1080, width expands naturally
                        aspect_card = max(0.56, aspect_nat)
                        card_h = 1080
                        card_w = max(10, min(1920, int(round(card_h * aspect_card))))
                        card_x = (1920 - card_w) // 2
                        card_y = 0
                    else:
                        # Ultra-wide panorama (AR > 1.777) -> Fit width 1920, height centered
                        aspect_card = aspect_nat
                        card_w = 1920
                        card_h = max(10, min(1080, int(round(card_w / aspect_card))))
                        card_x = 0
                        card_y = (1080 - card_h) // 2

                    card_dims_map[f_name] = (card_x, card_y, card_w, card_h, aspect_card)
            
            def get_img(img_file, t):
                if img_file not in loaded_images:
                    # Clean up unused cached arrays to keep memory footprint low
                    for k in list(loaded_images.keys()):
                        still_needed = False
                        for pd_check in page_displays:
                            if pd_check["image_file"] == k and pd_check["end_time"] > t - 2.0:
                                still_needed = True
                                break
                        if not still_needed:
                            del loaded_images[k]
                            if k in cached_backgrounds:
                                del cached_backgrounds[k]

                    img_path = os.path.join(images_blur_dir, img_file)
                    with Image.open(img_path) as pil_im:
                        if pil_im.mode != "RGB":
                            pil_im = pil_im.convert("RGB")
                        # Pre-enhance quality ONCE on load (Vibrance 1.06, Contrast 1.04, Sharpness 1.06)
                        enh_color = ImageEnhance.Color(pil_im).enhance(1.06)
                        enh_cont = ImageEnhance.Contrast(enh_color).enhance(1.04)
                        enh_sharp = ImageEnhance.Sharpness(enh_cont).enhance(1.06)
                        img_arr = np.array(enh_sharp, dtype=np.uint8)
                    loaded_images[img_file] = img_arr
                return loaded_images[img_file]

            def get_blurred_background(img_file, img_rgb, bounds):
                if img_file not in cached_backgrounds:
                    cb_x, cb_y, W_c, H_c = bounds
                    H_img, W_img = img_rgb.shape[:2]
                    x1 = max(0, min(W_img - 1, int(cb_x)))
                    y1 = max(0, min(H_img - 1, int(cb_y)))
                    x2 = max(x1 + 1, min(W_img, int(cb_x + W_c)))
                    y2 = max(y1 + 1, min(H_img, int(cb_y + H_c)))
                    cropped = img_rgb[y1:y2, x1:x2]

                    crop_h, crop_w = cropped.shape[:2]
                    bg_scale = max(1920.0 / max(1, crop_w), 1080.0 / max(1, crop_h))
                    bg_w = max(1920, int(round(crop_w * bg_scale)))
                    bg_h = max(1080, int(round(crop_h * bg_scale)))
                    bg_resized = cv2.resize(cropped, (bg_w, bg_h), interpolation=cv2.INTER_AREA)

                    bg_x1 = (bg_w - 1920) // 2
                    bg_y1 = (bg_h - 1080) // 2
                    bg_cropped = bg_resized[bg_y1:bg_y1+1080, bg_x1:bg_x1+1920]

                    # High performance two-pass Gaussian blur (downscale -> blur -> upscale)
                    bg_small = cv2.resize(bg_cropped, (160, 90), interpolation=cv2.INTER_AREA)
                    bg_small_blurred = cv2.GaussianBlur(bg_small, (15, 15), 5)
                    bg_blurred = cv2.resize(bg_small_blurred, (1920, 1080), interpolation=cv2.INTER_LINEAR)

                    # Ambient dark styling (0.42 brightness)
                    cached_backgrounds[img_file] = (bg_blurred.astype(np.float32) * 0.42).astype(np.uint8)
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
                        # Blend current and next page with C++ SIMD addWeighted
                        t_local_curr = t - pd_curr["start_time"]
                        img_curr_obj = get_img(pd_curr["image_file"], t)
                        curr_bounds = get_cached_bounds(pd_curr["image_file"])
                        curr_card_dims = card_dims_map.get(pd_curr["image_file"], (555, 0, 810, 1080, 0.75))
                        bg_curr_obj = get_blurred_background(pd_curr["image_file"], img_curr_obj, curr_bounds)
                        frame_curr = render_page_frame(img_curr_obj, bg_curr_obj, curr_bounds, plans[active_idx], t_local_curr, curr_card_dims)
                        
                        # Incoming next page holds its starting composition (t=0.0) while cross-fading in,
                        # ensuring zero timeline rewind or camera snapping when it becomes active.
                        t_local_next = 0.0
                        img_next_obj = get_img(pd_next["image_file"], t)
                        next_bounds = get_cached_bounds(pd_next["image_file"])
                        next_card_dims = card_dims_map.get(pd_next["image_file"], (555, 0, 810, 1080, 0.75))
                        bg_next_obj = get_blurred_background(pd_next["image_file"], img_next_obj, next_bounds)
                        frame_next = render_page_frame(img_next_obj, bg_next_obj, next_bounds, plans[next_idx], t_local_next, next_card_dims)
                        
                        alpha_linear = (t - t_trans_start) / max(0.001, t_trans_dur)
                        alpha_linear = np.clip(alpha_linear, 0.0, 1.0)
                        # Smooth sinusoidal ease-in-out cross-dissolve
                        alpha = 0.5 * (1.0 - math.cos(math.pi * alpha_linear))
                        final_frame = cv2.addWeighted(frame_curr, 1.0 - alpha, frame_next, alpha, 0)
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
                        final_frame = cv2.convertScaleAbs(final_frame, alpha=1.0 - alpha)
 
                    # Draw subtitles (if enabled)
                    if active_sub:
                        pil_frame = Image.fromarray(final_frame)
                        draw_subtitles_on_frame(pil_frame, active_sub)
                        final_frame = np.array(pil_frame)
 
                    # Output raw bytes directly from C-contiguous array to FFmpeg pipe
                    try:
                        proc.stdin.write(final_frame.tobytes())
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError) as write_err:
                        if is_ffmpeg_pipe_closed_error(write_err):
                            pipe_broken = True
                            break
                        else:
                            raise
                    
            finally:
                loaded_images.clear()
                cached_backgrounds.clear()
                
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.stdin = None
            
            proc.wait()
            if not stderr_file.closed:
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

        def render_episode_video_sync(images_blur_dir, image_files, segments, timings, output_video_path, ffmpeg_exe, working_encoder, audio_path, logo_path, overlay_path, subtitles_enabled_flag, srt_filename, fps=30, min_panel_duration=3.5, hard_floor_duration=3.0, **kwargs):
            stderr_log_path = os.path.join(os.path.dirname(output_video_path), "ffmpeg_render_stderr.log")
            stderr_file = open(stderr_log_path, "w", encoding="utf-8")
            try:
                return _render_episode_video_sync_impl(
                    images_blur_dir, image_files, segments, timings, output_video_path, ffmpeg_exe,
                    working_encoder, audio_path, logo_path, overlay_path, subtitles_enabled_flag,
                    srt_filename, fps=fps,
                    stderr_file=stderr_file, stderr_log_path=stderr_log_path,
                    min_panel_duration=min_panel_duration, hard_floor_duration=hard_floor_duration,
                    **kwargs
                )
            finally:
                if not stderr_file.closed:
                    stderr_file.close()

        total_episodes = to_ep - from_ep + 1
        
        # Pass 1: Xóa chữ cho tất cả các tập chưa hoàn thành trước (nếu bật)
        if task.payload.get("remove_text", False):
            try:
                from tools.text_remover.comic_text_remover import get_easyocr_reader, process_image
            except ImportError:
                pass

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
            video_filename = task.payload.get("video_filename", "video.mp4")
            output_video_path = os.path.join(ep_dir, video_filename)
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

                # On-Demand Inpainting on Selected Recap Pages (Pillar 3)
                if task.payload.get("remove_text", False) or task.payload.get("auto_remove_text", False):
                    try:
                        from tools.text_remover.comic_text_remover import process_image
                        await context.log(f"Tập {ep}: Bắt đầu xóa chữ/bóng thoại tự động trên {len(selected_files)} trang được chọn...", "info")
                        for sel_f in selected_files:
                            target_img_p = os.path.join(images_blur_dir, sel_f)
                            if os.path.exists(target_img_p):
                                try:
                                    process_image(target_img_p, target_img_p, conf_threshold=0.35, inpaint_radius=3)
                                except Exception as text_err:
                                    await context.log(f"  [Warn] Lỗi xóa chữ trên {sel_f}: {text_err}", "warning")
                        await context.log(f"Tập {ep}: Hoàn thành xóa chữ/bóng thoại trên các trang hiển thị.", "success")
                    except Exception as imp_err:
                        await context.log(f"  [Warn] Không thể nạp module xóa chữ: {imp_err}", "warning")

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
            force_render = bool(task.payload.get("force_render", False))
            if not force_render and cache.is_current(
                stage="video",
                fingerprint=fingerprint,
                outputs=[output_video_path],
                validate=lambda: validate_mp4_file(output_video_path),
            ):
                await context.log(f"Tập {ep}: Cache video hợp lệ. Bỏ qua rendering.", "success")
                if "final_videos" not in task.artifacts:
                    task.artifacts["final_videos"] = {}
                task.artifacts["final_videos"][str(ep)] = f"/downloads/{task.artifacts.get('download_folder_name')}/episode_{ep}/{video_filename}"
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
            min_panel_duration = float(task.payload.get("min_panel_duration", 3.5))
            hard_floor_duration = float(task.payload.get("hard_floor_duration", 3.0))

            # Compile episode directly in one single pass
            temp_video_path = output_video_path + ".tmp.mp4"
            if os.path.exists(temp_video_path):
                os.remove(temp_video_path)
            try:
                await asyncio.to_thread(
                    render_episode_video_sync,
                    images_blur_dir, image_files, segments, timings, temp_video_path,
                    ffmpeg_exe, working_encoder, audio_path, logo_path, overlay_path,
                    subtitles_enabled, "transcript.srt", fps,
                    min_panel_duration, hard_floor_duration,
                    force_render=force_render
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
            task.artifacts["final_videos"][str(ep)] = f"/downloads/{task.artifacts.get('download_folder_name')}/episode_{ep}/{video_filename}"

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
    new_total = max(0.0, total_seconds + offset_seconds)
    
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

        # Flash-Forward Teaser Intro (Disabled by default per user request)
        import config
        enable_flash_forward = task.payload.get(
            "enable_flash_forward_intro",
            getattr(config, "ENABLE_FLASH_FORWARD_INTRO", False)
        )
        if enable_flash_forward:
            try:
                await context.log("Đang khởi tạo Flash-Forward Teaser Intro (15s In Medias Res hook)...", "info")
                from arc_intro_engine import ArcClimaxMiner, DynamicHookDirector, MicroIntroRenderer, FastIntroPrepender
                
                climax_info = ArcClimaxMiner.scan_climax_episode(download_dir, from_ep=from_ep, to_ep=to_ep)
                climax_ep = climax_info["climax_episode"]
                await context.log(f"  -> Phát hiện tập cao trào đỉnh cao: Tập {climax_ep} (Score: {climax_info['climax_score']})", "info")

                top_images = ArcClimaxMiner.select_top_climax_images(download_dir, climax_ep, num_images=3)
                top_paths = [img["path"] for img in top_images]

                comic_title = task.comic_title or "Comic"
                protagonist_name = task.payload.get("protagonist_name", "")
                language = task.payload.get("language", "en")
                custom_hook = task.payload.get("flash_forward_custom_hook")

                hook_res = await DynamicHookDirector.generate_dynamic_retention_hook(
                    comic_title=comic_title,
                    protagonist_name=protagonist_name,
                    climax_episode=climax_ep,
                    climax_text=climax_info.get("climax_narration_sample", ""),
                    origin_text=climax_info.get("origin_narration_sample", ""),
                    language=language,
                    custom_hook=custom_hook
                )
                hook_script = hook_res["hook_script"]
                await context.log(f"  -> Kịch bản Hook [{hook_res['archetype']}]: \"{hook_script}\"", "info")

                intro_dir = os.path.join(download_dir, "intro")
                voice_id = task.payload.get("voice_id", "ai33pro")
                ref_audio = task.payload.get("ref_audio_path")

                intro_artifacts = await MicroIntroRenderer.render_intro_clip(
                    intro_dir=intro_dir,
                    hook_script=hook_script,
                    image_paths=top_paths,
                    language=language,
                    voice_id=voice_id,
                    ref_audio_path=ref_audio,
                    enable_bgm=False,
                    enable_sfx=True
                )

                intro_vid = intro_artifacts["video_path"]
                intro_srt = intro_artifacts["srt_path"]
                intro_dur = intro_artifacts["duration"]

                ep1_dir = os.path.join(download_dir, f"episode_{from_ep}")
                ep1_vid = os.path.join(ep1_dir, "video.mp4")
                ep1_srt = os.path.join(ep1_dir, "transcript.srt")
                ep1_backup_vid = os.path.join(ep1_dir, "video_no_intro.mp4")
                ep1_backup_srt = os.path.join(ep1_dir, "transcript_no_intro.srt")

                if os.path.exists(ep1_vid):
                    if not os.path.exists(ep1_backup_vid):
                        shutil.copy2(ep1_vid, ep1_backup_vid)
                    if os.path.exists(ep1_srt) and not os.path.exists(ep1_backup_srt):
                        shutil.copy2(ep1_srt, ep1_backup_srt)

                    target_base_vid = ep1_backup_vid if os.path.exists(ep1_backup_vid) else ep1_vid
                    target_base_srt = ep1_backup_srt if os.path.exists(ep1_backup_srt) else ep1_srt

                    prepended_ok = FastIntroPrepender.prepend_intro(
                        intro_video_path=intro_vid,
                        intro_srt_path=intro_srt,
                        intro_duration=intro_dur,
                        target_video_path=target_base_vid,
                        target_srt_path=target_base_srt,
                        output_video_path=ep1_vid,
                        output_srt_path=ep1_srt
                    )
                    if prepended_ok:
                        task.artifacts["flash_forward_intro"] = {
                            "enabled": True,
                            "duration": intro_dur,
                            "archetype": hook_res["archetype"],
                            "hook_script": hook_script,
                            "climax_episode": climax_ep,
                            "images": [os.path.basename(p) for p in top_paths],
                            "intro_video_url": f"/downloads/{folder_name}/intro/video.mp4" if folder_name else ""
                        }
                        await context.log(f"Đã ghép nối Flash-Forward Intro thành công vào đầu tập {from_ep} (+{intro_dur:.2f}s).", "success")
                    else:
                        await context.log("Không thể ghép Flash-Forward Intro bằng faststream copy, tiếp tục ghép video thông thường.", "warning")
            except Exception as intro_err:
                logger.warning(f"Flash-Forward Intro generation skipped due to: {intro_err}")
                await context.log(f"Bỏ qua tạo Flash-Forward Intro do cảnh báo: {intro_err}", "warning")

        video_durations = []
        srt_paths = []
        for ep in episodes_processed:
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            video_path = os.path.join(ep_dir, "video.mp4")
            srt_path = os.path.join(ep_dir, "transcript.srt")
            video_durations.append(get_video_duration(video_path, ffmpeg_exe))
            srt_paths.append(srt_path)

        chapters = []
        curr_ts = 0.0
        for idx, ep in enumerate(episodes_processed):
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
        task.artifacts["chapters"] = chapters

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
            "elapsed_time_seconds": task.elapsed_time,
            "flash_forward_intro": task.artifacts.get("flash_forward_intro")
        }

        market_id = task.payload.get("market_id")
        if market_id:
            try:
                from markets import get_market
                m = get_market(market_id)
                if m:
                    chapters = task.artifacts.get("chapters")
                    story_memory = None
                    story_mem_path = os.path.join(download_dir, "story_memory.json")
                    if os.path.exists(story_mem_path):
                        try:
                            with open(story_mem_path, "r", encoding="utf-8") as smf:
                                story_memory = json.load(smf)
                        except Exception:
                            pass
                    metadata["youtube_metadata"] = m.generate_youtube_metadata(
                        task.comic_title or "Comic",
                        task.from_episode or 1,
                        task.to_episode or 1,
                        chapters=chapters,
                        story_memory=story_memory,
                        download_dir=download_dir,
                    )
            except Exception as e:
                logger.warning(f"Failed to generate market YouTube metadata: {e}")
        
        yt_meta = metadata.get("youtube_metadata")
        if yt_meta:
            kit_path = os.path.join(output_dir, "youtube_upload_kit.txt")
            folder_name = task.artifacts.get("download_folder_name")
            if yt_meta.get("formatted_kit"):
                kit_content = yt_meta["formatted_kit"]
            else:
                kit_lines = [
                    "=" * 80,
                    f"YOUTUBE UPLOAD KIT: {task.comic_title or 'Comic'}",
                    f"Episodes: {task.from_episode} - {task.to_episode} | Market: {market_id}",
                    "=" * 80,
                    "",
                    "[1. TITLE CANDIDATES (Pick one for YouTube Title)]",
                ]
                for i, opt in enumerate(yt_meta.get("title_options", [yt_meta.get("title", "")]), 1):
                    kit_lines.append(f"{i}. {opt}")
                
                pinned_comm = yt_meta.get("pinned_comment")
                if not pinned_comm:
                    pinned_comm = (
                        "📌 MANHWA INFO & TIMESTAMPS:\n"
                        f"📖 Manhwa: {task.comic_title or 'Comic'}\n"
                        f"📚 Chapters: {task.from_episode} – {task.to_episode}\n\n"
                        "👉 Like & Subscribe for more full-arc manhwa recaps!"
                    )

                kit_lines.extend([
                    "",
                    "[2. DESCRIPTION & TIMESTAMPS (Copy & paste into YouTube Description)]",
                    yt_meta.get("description", ""),
                    "",
                    "[3. PINNED COMMENT (BÌNH LUẬN GHIM NGẮN GỌN - Copy & paste to Pin)]",
                    pinned_comm,
                    "",
                    "[4. TAGS (Copy & paste directly into YouTube Studio Tag Box)]",
                    ", ".join(yt_meta.get("tags", [])) if isinstance(yt_meta.get("tags"), list) else str(yt_meta.get("tags", "")),
                    "",
                    "=" * 80
                ])
                kit_content = "\n".join(kit_lines)

            with open(kit_path, "w", encoding="utf-8") as kf:
                kf.write(kit_content)
            task.artifacts["youtube_upload_kit_path"] = kit_path
            if folder_name:
                task.artifacts["youtube_upload_kit_url"] = f"/downloads/{folder_name}/output/youtube_upload_kit.txt"
            await context.log("Đã tạo bộ công cụ YouTube Upload Kit (youtube_upload_kit.txt).", "success")

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

                # Clean debug_repaging directory (large repagination debug images)
                debug_repaging_dir = os.path.join(ep_dir, "debug_repaging")
                if os.path.isdir(debug_repaging_dir):
                    try:
                        import shutil
                        shutil.rmtree(debug_repaging_dir, ignore_errors=True)
                        await context.log(f"Tập {ep}: Đã dọn debug_repaging/", "info")
                    except Exception:
                        pass

                # Clean gemini_safe directory (moderation fallback PDFs)
                gemini_safe_dir = os.path.join(ep_dir, "gemini_safe")
                if os.path.isdir(gemini_safe_dir):
                    try:
                        import shutil
                        shutil.rmtree(gemini_safe_dir, ignore_errors=True)
                        await context.log(f"Tập {ep}: Đã dọn gemini_safe/", "info")
                    except Exception:
                        pass

                # Clean PDF files (no longer needed after video is generated)
                pdf_dir = os.path.join(ep_dir, "pdf")
                if os.path.isdir(pdf_dir):
                    try:
                        for pdf_file in os.listdir(pdf_dir):
                            if pdf_file.lower().endswith(".pdf"):
                                os.remove(os.path.join(pdf_dir, pdf_file))
                        await context.log(f"Tập {ep}: Đã dọn pdf/", "info")
                    except Exception:
                        pass

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
