import os
import re
from typing import List, Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont
from renderer.types import ImageClip, SubtitleItem, RenderConfig


def parse_time_to_seconds(time_str: str) -> float:
    """
    Parses timestamp string HH:MM:SS,mmm or HH:MM:SS.mmm to seconds.
    """
    try:
        parts = time_str.replace(',', '.').split(':')
        if len(parts) == 3:
            h = float(parts[0])
            m = float(parts[1])
            s = float(parts[2])
            return h * 3600.0 + m * 60.0 + s
        elif len(parts) == 2:
            m = float(parts[0])
            s = float(parts[1])
            return m * 60.0 + s
        else:
            return float(parts[0])
    except Exception:
        return 0.0


class TimelineManager:
    """
    Manages cumulative timeline calculation, adaptive transitions, and subtitle overlay.
    """

    @staticmethod
    def build_timeline_from_segments(
        segments: List[Dict[str, Any]],
        timings: List[Dict[str, float]],
        image_files: List[str],
        audio_duration: float = 0.0,
        default_seg_duration: float = 3.0
    ) -> List[ImageClip]:
        """
        Builds a linear list of ImageClips from recap segments & timestamps.
        """
        clips: List[ImageClip] = []
        current_time = 0.0

        for s_idx, seg in enumerate(segments):
            if s_idx < len(timings):
                seg_end = timings[s_idx]["end"]
                seg_dur = max(0.3, seg_end - current_time)
            else:
                seg_dur = default_seg_duration

            if s_idx == len(segments) - 1:
                # Add trailing safety buffer for the final outro segment
                seg_dur = max(3.0, seg_dur + 3.0)

            seg_images = seg.get("images", [])
            if not seg_images:
                # If no explicit image list, pick one sequentially
                page_idx = min(s_idx, len(image_files) - 1) if image_files else 0
                img_file = image_files[page_idx] if image_files else ""
                clips.append(ImageClip(
                    image_file=img_file,
                    duration=seg_dur,
                    start_time=current_time,
                    end_time=current_time + seg_dur,
                    page_num=page_idx + 1,
                    segment_index=s_idx,
                    priority=1.0
                ))
                current_time += seg_dur
            else:
                total_prio = sum(float(img_obj.get("priority", 1.0)) for img_obj in seg_images)
                if total_prio <= 0:
                    total_prio = float(len(seg_images))

                for img_obj in seg_images:
                    page = int(img_obj.get("page", 1))
                    priority = float(img_obj.get("priority", 1.0))
                    normalized_weight = priority / total_prio
                    img_dur = max(0.2, seg_dur * normalized_weight)

                    page_idx = page - 1
                    if 0 <= page_idx < len(image_files):
                        img_file = image_files[page_idx]
                    elif image_files:
                        img_file = image_files[min(len(image_files) - 1, max(0, page_idx))]
                    else:
                        img_file = ""

                    clips.append(ImageClip(
                        image_file=img_file,
                        duration=img_dur,
                        start_time=current_time,
                        end_time=current_time + img_dur,
                        page_num=page,
                        segment_index=s_idx,
                        priority=priority,
                        custom_motion=img_obj.get("motion")
                    ))
                    current_time += img_dur

        # Ensure timeline extends to full audio duration if audio is longer
        if audio_duration > current_time and clips:
            diff = audio_duration - current_time
            clips[-1].duration += diff
            clips[-1].end_time += diff

        return clips

    @staticmethod
    def calculate_cumulative_timeline(clips: List[ImageClip]) -> float:
        """
        Calculates and fills cumulative start and end times for all clips in sequence.
        """
        curr = 0.0
        for clip in clips:
            clip.start_time = curr
            clip.end_time = curr + clip.duration
            curr = clip.end_time
        return curr

    @staticmethod
    def get_adaptive_transition_duration(
        curr_clip: ImageClip,
        next_clip: ImageClip,
        base_transition: float = 0.22
    ) -> float:
        """
        Adapts transition length to prevent transitions from consuming short clips (<0.7s).
        """
        return min(base_transition, curr_clip.duration * 0.35, next_clip.duration * 0.35)

    @staticmethod
    def parse_srt_file(srt_path_or_text: str) -> List[SubtitleItem]:
        """
        Parses an SRT file or raw SRT string into a list of SubtitleItems.
        """
        subtitles: List[SubtitleItem] = []
        content = ""
        if os.path.exists(srt_path_or_text):
            try:
                with open(srt_path_or_text, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                return []
        else:
            content = srt_path_or_text

        content = content.replace('\r\n', '\n').strip()
        pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\n([\s\S]*?)(?=\n\s*\n\d+|\Z)"
        matches = re.findall(pattern, content)

        for match in matches:
            idx = int(match[0])
            start_sec = parse_time_to_seconds(match[1])
            end_sec = parse_time_to_seconds(match[2])
            text = match[3].replace('\n', ' ').strip()
            subtitles.append(SubtitleItem(index=idx, start=start_sec, end=end_sec, text=text))

        return subtitles

    @staticmethod
    def draw_subtitles_on_frame(
        image: Image.Image,
        text: str,
        font_size: int = 40,
        target_w: int = 1920,
        target_h: int = 1080
    ) -> None:
        """
        Draws high-contrast bordered subtitle text on the bottom safe region of the frame.
        """
        if not text:
            return

        draw = ImageDraw.Draw(image)
        font = None
        font_candidates = [
            "arial.ttf",
            "tahoma.ttf",
            "msjh.ttc",
            "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\tahoma.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf"
        ]
        for p in font_candidates:
            try:
                font = ImageFont.truetype(p, font_size)
                break
            except Exception:
                continue

        if font is None:
            font = ImageFont.load_default()

        # Word wrap within max text width
        max_width = int(target_w * 0.82)
        words = text.split()
        lines = []
        cur_line = []
        for word in words:
            cur_line.append(word)
            test_line = " ".join(cur_line)
            try:
                w = draw.textlength(test_line, font=font)
            except Exception:
                w = len(test_line) * (font_size * 0.6)

            if w > max_width:
                cur_line.pop()
                if cur_line:
                    lines.append(" ".join(cur_line))
                cur_line = [word]

        if cur_line:
            lines.append(" ".join(cur_line))

        line_h = font_size + 12
        total_h = len(lines) * line_h
        y_start = target_h - 110 - total_h

        for line in lines:
            try:
                bbox = draw.textbbox((0, 0), line, font=font)
                w = bbox[2] - bbox[0]
            except Exception:
                w = len(line) * (font_size * 0.6)

            x = (target_w - w) // 2

            # Heavy outline for high legibility
            outline_range = 2
            for dx in range(-outline_range, outline_range + 1):
                for dy in range(-outline_range, outline_range + 1):
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y_start + dy), line, font=font, fill=(0, 0, 0))

            draw.text((x, y_start), line, font=font, fill=(255, 255, 255))
            y_start += line_h
