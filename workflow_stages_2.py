import os
import json
import asyncio
import re
import time
import subprocess
import shutil
import logging
from typing import Optional, Dict, Any, List
from PIL import Image
from workflow_base import BaseStage, StageState, WorkflowContext, check_episode_completed

logger = logging.getLogger("WorkflowStages2")

def strip_gemini_citations(text: str) -> str:
    """
    Loại bỏ triệt để tất cả các thẻ trích dẫn / grounding / citation do AI Gemini hoặc web UI sinh ra
    (e.g. [cite: 1], [cite: 1, 2], [source: 1], [PDF], (PDF), [1], [2]).
    """
    if not text:
        return ""
    text = re.sub(r"\[\s*cite:\s*[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*(?:source|trích dẫn|nguồn):\s*[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*(?:PDF|\.pdf)\s*\]|\(\s*(?:PDF|\.pdf)\s*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", "", text)
    text = re.sub(r"\s+([,.:;!?])", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()

def natural_sort_key(s: str) -> list:
    """Natural sort key helper so '001.webp' or '1.jpg' sort in exact numerical order."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]


async def execute_single_episode_stage6(ep: int, context: WorkflowContext) -> bool:
    """Stage 6 - JSON Extraction & Validation for a single episode."""
    stage_name = "Stage 6 - JSON Extraction"
    task = context.task
    download_dir = task.artifacts.get("download_dir")
    from workflow_stages_1 import validate_recap_json
    recap_json_path = os.path.join(download_dir, f"episode_{ep}", "recap.json")
    
    ep_key = str(ep)
    if ep_key not in task.episode_progress:
        task.episode_progress[ep_key] = {}
        
    task.episode_progress[ep_key][stage_name] = StageState.RUNNING
    await context.manager.save_and_broadcast("EpisodeProgressUpdated", task)

    if not os.path.exists(recap_json_path) or not validate_recap_json(recap_json_path):
        await context.log(f"Tập {ep}: recap.json không hợp lệ hoặc không tồn tại.", "error", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.FAILED
        return False

    # Clean any remaining citations in recap.json in place
    try:
        with open(recap_json_path, "r", encoding="utf-8") as f:
            segments = json.load(f)
        modified = False
        for seg in segments:
            if isinstance(seg, dict) and "speech" in seg:
                cleaned_sp = strip_gemini_citations(seg["speech"])
                if cleaned_sp != seg["speech"]:
                    seg["speech"] = cleaned_sp
                    modified = True
        if modified:
            with open(recap_json_path, "w", encoding="utf-8") as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to clean citations in recap.json: {e}")

    task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
    total_eps = task.to_episode - task.from_episode + 1
    completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
    await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
    return True

async def execute_single_episode_stage7(ep: int, context: WorkflowContext) -> bool:
    """Stage 7 - Narration Aggregation for a single episode."""
    stage_name = "Stage 7 - Narration Aggregation"
    task = context.task
    download_dir = task.artifacts.get("download_dir")
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    recap_json_path = os.path.join(ep_dir, "recap.json")
    narration_txt_path = os.path.join(ep_dir, "narration.txt")
    
    ep_key = str(ep)
    if ep_key not in task.episode_progress:
        task.episode_progress[ep_key] = {}
    
    if check_episode_completed(download_dir, ep) or (task.episode_progress.get(ep_key, {}).get(stage_name) == StageState.SUCCESS and os.path.exists(narration_txt_path)):
        return True
        
    task.episode_progress[ep_key][stage_name] = StageState.RUNNING
    await context.manager.save_and_broadcast("EpisodeProgressUpdated", task)

    if not os.path.exists(recap_json_path):
        await context.log(f"Tập {ep}: Thiếu recap.json.", "error", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.FAILED
        return False
        
    try:
        with open(recap_json_path, "r", encoding="utf-8") as f:
            segments = json.load(f)
            
        speech_list = []
        for seg in segments:
            speech = strip_gemini_citations(seg.get("speech", "")).strip()
            if speech:
                speech_list.append(speech)
                
        aggregated_narration = " ".join(speech_list)
        with open(narration_txt_path, "w", encoding="utf-8") as nf:
            nf.write(aggregated_narration)
            
        await context.log(f"Tập {ep}: Tổng hợp xong narration.txt ({len(aggregated_narration)} ký tự).", "success", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
        
        total_eps = task.to_episode - task.from_episode + 1
        completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
        await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
        return True
    except Exception as err:
        await context.log(f"Tập {ep}: Lỗi tổng hợp narration: {err}", "error", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.FAILED
        return False

class Stage7_NarrationAggregation(BaseStage):
    @property
    def name(self) -> str: return "Stage 7 - Narration Aggregation"
    @property
    def weight(self) -> float: return 0.02

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        
        for ep in range(from_ep, to_ep + 1):
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            await context.start_episode(ep)
            ok = await execute_single_episode_stage7(ep, context)
            if not ok:
                await context.fail_episode(ep, "Lỗi tổng hợp narration.txt.")
                return False
            await context.complete_episode(ep)
        return True

async def execute_single_episode_stage8(ep: int, context: WorkflowContext, tts_sem: Optional[asyncio.Semaphore] = None) -> bool:
    """Stage 8 - Local TTS for a single episode."""
    stage_name = "Stage 8 - Local TTS"
    task = context.task
    download_dir = task.artifacts.get("download_dir")
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    narration_txt_path = os.path.join(ep_dir, "narration.txt")
    audio_path = os.path.join(ep_dir, "audio.mp3")
    srt_path = os.path.join(ep_dir, "transcript.srt")
    cache_path = os.path.join(ep_dir, "tts_config.json")
    
    default_voice = "auto"
    voice_id = task.payload.get("voice_id", default_voice)
    ref_audio_path = task.payload.get("ref_audio_path")
    ai33pro_api_key = task.payload.get("ai33pro_api_key")
    
    ep_key = str(ep)
    if ep_key not in task.episode_progress:
        task.episode_progress[ep_key] = {}
    
    if check_episode_completed(download_dir, ep) or (task.episode_progress.get(ep_key, {}).get(stage_name) == StageState.SUCCESS and os.path.exists(audio_path) and os.path.exists(srt_path)):
        return True
        
    task.episode_progress[ep_key][stage_name] = StageState.RUNNING
    for s in task.stages:
        if s["name"] == stage_name and s.get("status") != StageState.SUCCESS:
            s["status"] = StageState.RUNNING
            break
    await context.manager.save_and_broadcast("EpisodeProgressUpdated", task)

    if not os.path.exists(narration_txt_path):
        await context.log(f"Tập {ep}: Thiếu narration.txt.", "error", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.FAILED
        return False
        
    with open(narration_txt_path, "r", encoding="utf-8") as f:
        narration_text = f.read().strip()
        
    if not narration_text:
        await context.log(f"Tập {ep}: Nội dung thuyết minh rỗng.", "error", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.FAILED
        return False
        
    cache_valid = False
    if os.path.exists(cache_path) and os.path.exists(audio_path) and os.path.exists(srt_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as cf:
                saved_config = json.load(cf)
            if (saved_config.get("voice_id") == voice_id and 
                saved_config.get("text") == narration_text and 
                saved_config.get("ref_audio_path") == ref_audio_path):
                cache_valid = True
        except Exception:
            pass
            
    if cache_valid:
        await context.log(f"Tập {ep}: Phát hiện audio.mp3 và transcript.srt có sẵn với cấu hình trùng khớp. Bỏ qua sinh local TTS.", "success", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
        total_eps = task.to_episode - task.from_episode + 1
        completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
        await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
        return True
        
    await context.log(f"Tập {ep}: Đang sinh local TTS...", "info", stage_name=stage_name, episode=ep)
    
    class AsyncNullContext:
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc_val, exc_tb): pass

    sem_ctx = tts_sem if tts_sem is not None else AsyncNullContext()
    async with sem_ctx:
        from tts_provider import generate_tts
        success = await generate_tts(narration_text, audio_path, srt_path, voice_id, ref_audio_path, ai33pro_api_key=ai33pro_api_key)
        if not success:
            await context.log(f"Tập {ep}: Lỗi khi tạo local TTS hoặc Whisper transcript.", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False

    try:
        with open(cache_path, "w", encoding="utf-8") as cf:
            json.dump({
                "voice_id": voice_id, 
                "text": narration_text,
                "ref_audio_path": ref_audio_path
            }, cf, ensure_ascii=False, indent=4)
    except Exception:
        pass

    task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
    total_eps = task.to_episode - task.from_episode + 1
    completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
    await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
    return True

def align_transcript_to_segments(subtitles: List[Dict[str, Any]], segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Chuẩn hóa và khớp nối chính xác 1-to-1 giữa danh sách câu kịch bản (segments từ recap.json)
    và danh sách phụ đề / timestamps (subtitles từ Whisper / transcript.srt).
    Trả về đúng len(segments) mục với start, end, text đảm bảo tính đơn điệu không đè thời gian.
    """
    if not segments:
        return []
    if not subtitles:
        res = []
        cur = 0.0
        for seg in segments:
            speech_clean = strip_gemini_citations(seg.get("speech", ""))
            w_count = len(speech_clean.split())
            dur = max(2.5, w_count * 0.35)
            res.append({"start": cur, "end": cur + dur, "text": speech_clean})
            cur += dur
        return res

    def clean_w(w):
        return re.sub(r"[^a-zA-Z0-9\u00C0-\u1EF9]", "", w.lower())

    # Tính cumulative words cho segments
    seg_words = []
    for seg in segments:
        speech_clean = strip_gemini_citations(seg.get("speech", ""))
        words = [clean_w(w) for w in speech_clean.split() if clean_w(w)]
        seg_words.append(len(words))

    seg_ranges = []
    cur_w = 0
    for count in seg_words:
        seg_ranges.append((cur_w, cur_w + count))
        cur_w += count
    total_seg_words = cur_w

    # Tính cumulative words cho subtitles
    sub_words = []
    total_sub_words = 0
    for sub in subtitles:
        sub_text_clean = strip_gemini_citations(sub.get("text", ""))
        words = [clean_w(w) for w in sub_text_clean.split() if clean_w(w)]
        sub_words.append(len(words))
        total_sub_words += len(words)

    if total_sub_words == 0:
        # Fallback an toàn: nếu subtitles không có text, map theo tỷ lệ thời lượng (duration)
        sub_durs = [max(0.1, float(sub.get("end", 0.0)) - float(sub.get("start", 0.0))) for sub in subtitles]
        total_dur = sum(sub_durs) if sub_durs else 1.0
        prev_d = 0.0
        for idx, sub in enumerate(subtitles):
            d = sub_durs[idx]
            mid_d = prev_d + d / 2.0
            scaled_w = (mid_d / total_dur) * total_seg_words if total_dur > 0 else 0
            matched = len(segments) - 1
            for s_idx, (s_start, s_end) in enumerate(seg_ranges):
                if s_start <= scaled_w < s_end:
                    matched = s_idx
                    break
            sub["matched_seg"] = matched
            prev_d += d
    elif len(subtitles) == len(segments):
        for idx, sub in enumerate(subtitles):
            sub["matched_seg"] = idx
    else:
        ratio = total_seg_words / total_sub_words if total_sub_words > 0 else 1.0
        prev_w = 0
        for idx, sub in enumerate(subtitles):
            c = sub_words[idx]
            mid = prev_w + c // 2 if c > 0 else prev_w
            scaled = mid * ratio
            matched = len(segments) - 1
            for s_idx, (s_start, s_end) in enumerate(seg_ranges):
                if s_start <= scaled < s_end:
                    matched = s_idx
                    break
            sub["matched_seg"] = matched
            prev_w += c

    normalized = []
    last_end = 0.0
    for s_idx, seg in enumerate(segments):
        matched = [sub for sub in subtitles if sub.get("matched_seg") == s_idx]
        speech_text = strip_gemini_citations(seg.get("speech", ""))
        if matched:
            start_t = min(float(sub["start"]) for sub in matched)
            end_t = max(float(sub["end"]) for sub in matched)
        else:
            start_t = last_end
            w_count = len(speech_text.split())
            end_t = start_t + max(2.0, w_count * 0.35)

        if start_t < last_end:
            start_t = last_end
        if end_t <= start_t:
            end_t = start_t + 1.0

        last_end = end_t
        normalized.append({
            "start": round(start_t, 3),
            "end": round(end_t, 3),
            "text": speech_text
        })

    return normalized

async def execute_single_episode_stage9(ep: int, context: WorkflowContext) -> bool:
    """Stage 9 - Subtitle Normalization for a single episode."""
    stage_name = "Stage 9 - Subtitle Normalization"
    from app import parse_time_to_seconds
    task = context.task
    download_dir = task.artifacts.get("download_dir")
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    srt_path = os.path.join(ep_dir, "transcript.srt")
    raw_srt_path = os.path.join(ep_dir, "transcript_raw.srt")
    recap_json_path = os.path.join(ep_dir, "recap.json")
    
    def format_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int(round((seconds - int(seconds)) * 1000))
        if ms >= 1000:
            s += ms // 1000
            ms = ms % 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    ep_key = str(ep)
    if ep_key not in task.episode_progress:
        task.episode_progress[ep_key] = {}
    
    # Check if transcript.srt already exists and has matching cue count
    if os.path.exists(srt_path) and os.path.exists(recap_json_path):
        try:
            with open(recap_json_path, "r", encoding="utf-8") as rf:
                segs = json.load(rf)
            with open(srt_path, "r", encoding="utf-8") as sf:
                cues = re.findall(r"\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}", sf.read())
            if len(cues) == len(segs) and check_episode_completed(download_dir, ep):
                return True
        except Exception:
            pass
        
    task.episode_progress[ep_key][stage_name] = StageState.RUNNING
    for s in task.stages:
        if s["name"] == stage_name and s.get("status") != StageState.SUCCESS:
            s["status"] = StageState.RUNNING
            break
    await context.manager.save_and_broadcast("EpisodeProgressUpdated", task)

    source_srt_path = raw_srt_path if os.path.exists(raw_srt_path) else srt_path
    if not os.path.exists(source_srt_path) or not os.path.exists(recap_json_path):
        await context.log(f"Tập {ep}: Thiếu transcript.srt hoặc recap.json.", "error", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.FAILED
        return False
        
    with open(source_srt_path, "r", encoding="utf-8") as f:
        srt_content = f.read().replace('\r\n', '\n').strip()
        
    with open(recap_json_path, "r", encoding="utf-8") as f:
        segments = json.load(f)

    pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\n(.*?)(?=\n\n|\Z)"
    matches = re.findall(pattern, srt_content, re.DOTALL)
    subtitles = []
    for num, start_str, end_str, text in matches:
        text_clean = " ".join([l.strip() for l in text.split('\n') if l.strip()])
        text_clean = re.sub(r'\[speed_[a-z0-9_]+\]', '', text_clean, flags=re.IGNORECASE).strip()
        text_clean = strip_gemini_citations(text_clean)
        text_clean = " ".join(text_clean.split())
        subtitles.append({
            "start": parse_time_to_seconds(start_str),
            "end": parse_time_to_seconds(end_str),
            "text": text_clean
        })

    if not subtitles:
        await context.log(f"Tập {ep}: Không thể phân tích tệp SRT.", "error", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.FAILED
        return False

    normalized_srt_entries = align_transcript_to_segments(subtitles, segments)

    with open(srt_path, "w", encoding="utf-8") as sf:
        for s_idx, sub in enumerate(normalized_srt_entries, 1):
            start_str = format_time(sub["start"])
            end_str = format_time(sub["end"])
            sf.write(f"{s_idx}\n{start_str} --> {end_str}\n{sub['text']}\n\n")

    await context.log(f"Tập {ep}: Chuẩn hóa phụ đề thành công ({len(normalized_srt_entries)} mục).", "success", stage_name=stage_name, episode=ep)
    task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
    total_eps = task.to_episode - task.from_episode + 1
    completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
    await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
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
        concurrency = task.payload.get("concurrency", 5)
        sem = asyncio.Semaphore(concurrency)
        
        async def run_ep(ep):
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            await context.start_episode(ep)
            ok = await execute_single_episode_stage8(ep, context, sem)
            if ok:
                await context.complete_episode(ep)
            else:
                await context.fail_episode(ep, "Lỗi tạo local TTS.")
            return ok

        episodes = list(range(from_ep, to_ep + 1))
        tasks = [run_ep(ep) for ep in episodes]
        results = await asyncio.gather(*tasks)
        return all(results)


class Stage9_SubtitleNormalization(BaseStage):
    @property
    def name(self) -> str: return "Stage 9 - Subtitle Normalization"
    @property
    def weight(self) -> float: return 0.03

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        concurrency = task.payload.get("concurrency", 5)
        sem = asyncio.Semaphore(concurrency)
        
        async def run_ep(ep):
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            await context.start_episode(ep)
            async with sem:
                ok = await execute_single_episode_stage9(ep, context)
            if ok:
                await context.complete_episode(ep)
            else:
                await context.fail_episode(ep, "Lỗi chuẩn hóa phụ đề.")
            return ok

        episodes = list(range(from_ep, to_ep + 1))
        tasks = [run_ep(ep) for ep in episodes]
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

_SUBTITLE_FONT_CACHE = {}

def get_subtitle_font(font_size=40):
    if font_size not in _SUBTITLE_FONT_CACHE:
        from PIL import ImageFont
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
        _SUBTITLE_FONT_CACHE[font_size] = font
    return _SUBTITLE_FONT_CACHE[font_size]

def draw_subtitles_on_frame(image, text, font_size=40):
    from PIL import ImageDraw
    if not text:
        return
    draw = ImageDraw.Draw(image)
    font = get_subtitle_font(font_size)
        
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
    try:
        from pure_visual.frame_refiner import PureVisualFrameRefiner
        refiner = PureVisualFrameRefiner()
        img_np = np.array(img.convert("RGB"))
        x, y, w, h = refiner.refine_frame(img_np)
        if w > 10 and h > 10:
            return int(x), int(y), int(w), int(h)
    except Exception:
        pass

    # Fallback to standard
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

    dist_sq = dx * dx + dy * dy
    if dist_sq < 0.25:
        return img_np
    dist = np.sqrt(dist_sq)

    raw_size = int(np.clip(dist * 0.4, 2, 5))
    blur_size = raw_size if raw_size % 2 == 1 else raw_size + 1
    if blur_size < 3:
        return img_np

    # Direction key
    if abs(dy) > abs(dx) * 1.5:
        dir_key = 0 # Vertical
    elif abs(dx) > abs(dy) * 1.5:
        dir_key = 1 # Horizontal
    else:
        dir_key = 2 # Diagonal

    k_key = (blur_size, dir_key)
    global _MOTION_BLUR_KERNELS
    if '_MOTION_BLUR_KERNELS' not in globals():
        _MOTION_BLUR_KERNELS = {}

    if k_key not in _MOTION_BLUR_KERNELS:
        k = np.zeros((blur_size, blur_size), dtype=np.float32)
        c = blur_size // 2
        if dir_key == 0:
            k[:, c] = 1.0
        elif dir_key == 1:
            k[c, :] = 1.0
        else:
            for i in range(blur_size):
                k[i, i] = 1.0
        k /= k.sum()
        _MOTION_BLUR_KERNELS[k_key] = k

    return cv2.filter2D(img_np, -1, _MOTION_BLUR_KERNELS[k_key])


import random

class CameraPlanner:
    @staticmethod
    def generate_camera_plan(page_num: int, duration: float, bounds: tuple, is_tall: bool = False, base_fg_w: float = 640.0, transition: str = "cross_fade") -> dict:
        _, _, W_c, H_c = bounds
        cx = float(W_c) / 2.0
        cy = float(H_c) / 2.0

        if is_tall:
            # Tall vertical manhwa frame -> Slide down from top to bottom
            h_cam = float(W_c) * (1080.0 / base_fg_w) if W_c > 0 else 1080.0
            y_start = h_cam / 2.0
            y_end = max(y_start, float(H_c) - h_cam / 2.0)
            return {
                "page": page_num,
                "duration": duration,
                "animation_type": "slide_down",
                "easing": "easeInOutSine",
                "keyframes": [
                    {"time": 0.0,      "x": cx, "y": y_start, "scale": 1.0},
                    {"time": duration, "x": cx, "y": y_end,   "scale": 1.0},
                ],
                "transition": transition,
            }
        else:
            # Standard / wide frame -> Ken Burns zoom in 10% (1.0 -> 1.10)
            return {
                "page": page_num,
                "duration": duration,
                "animation_type": "zoom_in",
                "easing": "easeInOutSine",
                "keyframes": [
                    {"time": 0.0,      "x": cx, "y": cy, "scale": 1.0},
                    {"time": duration, "x": cx, "y": cy, "scale": 1.10},
                ],
                "transition": transition,
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

def is_valid_custom_image(image_path: str) -> bool:
    if not image_path or not os.path.exists(image_path):
        return False
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            if img.size[0] <= 1 or img.size[1] <= 1:
                return False
            if img.mode == "RGBA":
                extrema = img.getextrema()
                if len(extrema) >= 4 and extrema[3][1] == 0:
                    return False  # Fully transparent image
    except Exception:
        return False
    return True

def is_valid_video(video_path: str) -> bool:
    if not video_path or not os.path.exists(video_path):
        return False
    try:
        return os.path.getsize(video_path) > 1000
    except Exception:
        return False

def render_episode_video_sync(
    images_blur_dir, image_files, segments, timings, output_video_path,
    ffmpeg_exe, working_encoder, audio_path, logo_path, overlay_path,
    subtitles_enabled_flag, srt_filename, fps=30, render_config_kwargs=None,
    video_mark_path=None, video_mark_alpha=0.01
):
    from PIL import Image
    import subprocess
    import numpy as np
    import cv2
    import queue
    import threading
    
    # Check if native FFmpeg filtergraph mode is requested
    render_mode = (render_config_kwargs.get("render_mode") or "").lower() if render_config_kwargs else ""
    if render_mode in ("ffmpeg_filtergraph", "native"):
        from renderer.ffmpeg_filtergraph_renderer import render_video_with_ffmpeg_filtergraph
        return render_video_with_ffmpeg_filtergraph(
            page_displays=[],
            audio_path=audio_path,
            output_video_path=output_video_path,
            ffmpeg_exe=ffmpeg_exe,
            working_encoder=working_encoder,
            fps=fps,
            subtitles_path=os.path.join(os.path.dirname(output_video_path), srt_filename) if subtitles_enabled_flag else None,
            logo_path=logo_path,
            overlay_path=overlay_path,
            video_mark_path=video_mark_path,
            video_mark_alpha=video_mark_alpha
        )

    # Configure encoder settings for fast, high-quality, lightweight output (~40-60 MB) and instant seeking
    enc_str = str(working_encoder).lower()
    # Keyframe interval: 1 second (e.g. 30 frames at 30fps) ensures instant seeking & sub-second buffering
    gop_size = str(fps)
    if "nvenc" in enc_str:
        extra_args = [
            "-preset", "p1",
            "-tune", "ll",
            "-rc", "vbr",
            "-cq", "28",
            "-b:v", "1800k",
            "-maxrate", "2800k",
            "-bufsize", "4000k",
            "-g", gop_size,
            "-keyint_min", gop_size,
            "-spatial_aq", "0",
            "-temporal_aq", "0",
            "-threads", "0"
        ]
    elif "amf" in enc_str:
        extra_args = ["-rc", "cqp", "-qp_i", "27", "-qp_p", "27", "-b:v", "1800k", "-maxrate", "2800k", "-g", gop_size, "-keyint_min", gop_size, "-quality", "speed", "-threads", "0"]
    elif "qsv" in enc_str:
        extra_args = ["-preset", "veryfast", "-global_quality", "27", "-b:v", "1800k", "-maxrate", "2800k", "-g", gop_size, "-keyint_min", gop_size, "-threads", "0"]
    elif "libx264" in enc_str:
        extra_args = ["-crf", "24", "-preset", "veryfast", "-b:v", "1800k", "-maxrate", "2800k", "-bufsize", "4000k", "-g", gop_size, "-keyint_min", gop_size, "-threads", "0"]
    else:
        extra_args = ["-b:v", "1500k", "-g", gop_size, "-keyint_min", gop_size, "-threads", "0"]
    
    # Resolve video_mark_path fallback to static/video_mark.mp4
    project_dir = os.path.dirname(os.path.abspath(__file__))
    if not video_mark_path:
        default_video_mark = os.path.join(project_dir, "static", "video_mark.mp4")
        if os.path.exists(default_video_mark):
            video_mark_path = default_video_mark

    enable_video_mark = True
    if render_config_kwargs:
        if "enable_video_mark" in render_config_kwargs:
            enable_video_mark = bool(render_config_kwargs["enable_video_mark"])
        if "video_mark_alpha" in render_config_kwargs:
            try:
                video_mark_alpha = float(render_config_kwargs["video_mark_alpha"])
            except Exception:
                pass

    has_video_mark = enable_video_mark and is_valid_video(video_mark_path)
    audio_path = os.path.abspath(audio_path)
    output_video_path = os.path.abspath(output_video_path)
    if logo_path: logo_path = os.path.abspath(logo_path)
    if overlay_path: overlay_path = os.path.abspath(overlay_path)
    if video_mark_path: video_mark_path = os.path.abspath(video_mark_path)

    has_logo = is_valid_custom_image(logo_path)
    has_overlay = is_valid_custom_image(overlay_path)

    ep_dir = os.path.dirname(output_video_path)
    cmd = [
        ffmpeg_exe, "-y",
        "-threads", "0",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", "1920x1080",
        "-r", str(fps),
        "-i", "-",               # Raw video from stdin [0:v]
        "-i", audio_path,        # Audio [1:a]
    ]

    filter_parts = []
    current_v = "0:v"

    # Normalize audio loudness to standard online video level (-14 LUFS, True Peak -1.5 dBTP)
    target_lufs = -14.0
    target_tp = -1.5
    if render_config_kwargs:
        if "target_lufs" in render_config_kwargs:
            try: target_lufs = float(render_config_kwargs["target_lufs"])
            except Exception: pass
        if "target_tp" in render_config_kwargs:
            try: target_tp = float(render_config_kwargs["target_tp"])
            except Exception: pass

    if has_overlay:
        ol_rel = os.path.relpath(overlay_path, ep_dir).replace('\\', '/')
        filter_parts.append(
            f"movie='{ol_rel}' [ol_raw]; [ol_raw]scale=1920:1080,format=rgba,colorchannelmixer=aa=0.005[ol]"
        )
        next_v = "v_ol" if has_logo else "v"
        filter_parts.append(f"[{current_v}][ol]overlay[{next_v}]")
        current_v = next_v

    if has_logo:
        logo_rel = os.path.relpath(logo_path, ep_dir).replace('\\', '/')
        filter_parts.append(
            f"movie='{logo_rel}' [logo_raw]; [logo_raw]scale=50:50[logo]"
        )
        filter_parts.append(f"[{current_v}][logo]overlay=25:25[v]")
        current_v = "v"

    if current_v == "0:v":
        # Zero video filter overhead: map raw video stream directly to encoder
        cmd += [
            "-filter_complex", f"[1:a]loudnorm=I={target_lufs}:TP={target_tp}:LRA=11[a]",
            "-map", "0:v",
            "-map", "[a]"
        ]
    else:
        filter_parts.append(f"[1:a]loudnorm=I={target_lufs}:TP={target_tp}:LRA=11[a]")
        filter_complex_str = "; ".join(filter_parts)
        cmd += ["-filter_complex", filter_complex_str, "-map", f"[{current_v}]", "-map", "[a]"]

    cmd += ["-c:v", working_encoder, "-pix_fmt", "yuv420p"] + extra_args + [
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", output_video_path
    ]
    
    stderr_log_path = os.path.join(ep_dir, "ffmpeg_render_stderr.log")
    stderr_file = open(stderr_log_path, "w", encoding="utf-8")
    
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
        cwd=ep_dir,
        bufsize=10485760
    )
    
    cv2.setNumThreads(2)

    # Parse subtitles from SRT
    subtitles = []
    if subtitles_enabled_flag:
        srt_path = os.path.join(ep_dir, srt_filename)
        subtitles = parse_srt_file(srt_path)
        
    # Visual lead offset: image cuts slightly ahead of speech onset (default 0.6s) for snappy professional pacing
    visual_lead_offset = 0.6
    if render_config_kwargs and "visual_lead_offset" in render_config_kwargs:
        try:
            visual_lead_offset = float(render_config_kwargs["visual_lead_offset"])
        except Exception:
            pass

    # Ensure timings matches segments count exactly 1-to-1 without desynchronization
    if len(timings) != len(segments):
        timings = align_transcript_to_segments(timings, segments)

    # Sort image_files naturally
    image_files = sorted(image_files, key=natural_sort_key)

    # Calculate segment visual boundaries with visual lead offset
    seg_visual_bounds = []
    for s_idx in range(len(segments)):
        if s_idx == 0:
            v_start = 0.0
        else:
            srt_s = timings[s_idx]["start"] if s_idx < len(timings) else (seg_visual_bounds[-1]["end"] if seg_visual_bounds else 0.0)
            prev_s = seg_visual_bounds[-1]["start"] if seg_visual_bounds else 0.0
            v_start = max(prev_s + 0.3, srt_s - visual_lead_offset)
        
        if s_idx < len(segments) - 1:
            next_srt_s = timings[s_idx + 1]["start"] if (s_idx + 1 < len(timings)) else (v_start + 5.0)
            v_end = max(v_start + 0.3, next_srt_s - visual_lead_offset)
        else:
            final_audio_end = timings[-1]["end"] if timings else v_start + 3.0
            v_end = max(v_start + 1.0, final_audio_end + 1.0)
            
        seg_visual_bounds.append({"start": v_start, "end": v_end})

    # Create flat list of page displays
    page_displays = []
    for s_idx, seg in enumerate(segments):
        v_bound = seg_visual_bounds[s_idx]
        v_start = v_bound["start"]
        v_end = v_bound["end"]
        seg_duration = max(1.0, v_end - v_start)
        
        seg_images = seg.get("images", [])
        if not seg_images:
            seg_images = [{"page": 1, "priority": 1.0}]
            
        img_curr_time = v_start
        for img_obj in seg_images:
            page = int(img_obj.get("page", 1))
            priority = float(img_obj.get("priority", 1.0 / len(seg_images)))
            img_dur = seg_duration * priority
            
            page_idx = page - 1
            if 0 <= page_idx < len(image_files):
                img_file = image_files[page_idx]
            else:
                img_file = image_files[min(len(image_files)-1, max(0, page_idx))]
                
            page_displays.append({
                "page": page,
                "image_file": img_file,
                "duration": img_dur,
                "start_time": img_curr_time,
                "end_time": img_curr_time + img_dur,
                "segment_index": s_idx
            })
            img_curr_time += img_dur

    flip_horizontal = bool(render_config_kwargs.get("flip_horizontal", render_config_kwargs.get("mirror", False))) if render_config_kwargs else False

    from pure_visual.frame_refiner import PureVisualFrameRefiner
    from pure_visual.image_enhancer import PureVisualImageEnhancer, EnhancerConfig

    use_ai_sr = True
    if render_config_kwargs:
        if "use_ai_sr" in render_config_kwargs:
            use_ai_sr = bool(render_config_kwargs["use_ai_sr"])

    frame_refiner = PureVisualFrameRefiner()
    image_enhancer = PureVisualImageEnhancer(EnhancerConfig(use_ai_sr=use_ai_sr, max_target_width=2560))

    # Pre-load, clean borders, precompute background blur and tall panels (Zero-Allocation Render Engine)
    preloaded_assets = {}
    gpu_sr_lock = threading.Lock()

    def prepare_single_frame_asset(img_file):
        cache_key = f"{img_file}_flipped" if flip_horizontal else img_file
        if cache_key in preloaded_assets:
            return preloaded_assets[cache_key]

        img_path = os.path.join(images_blur_dir, img_file)
        if not os.path.exists(img_path):
            img_path = os.path.join(ep_dir, "images", img_file)

        img_bgr = cv2.imread(img_path)
        if img_bgr is None:
            with Image.open(img_path) as img_open:
                img_rgb = np.array(img_open.convert("RGB"), dtype=np.uint8)
                img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)

        if flip_horizontal:
            img_bgr = cv2.flip(img_bgr, 1)

        # Clean visual frame boundaries (trims gutters, whitespace, panel borders)
        raw_bounds = frame_refiner.refine_frame(img_bgr)
        h_orig, w_orig = img_bgr.shape[:2]
        
        # Smart Skip: Only run Real-ESRGAN if image dimensions are below 1080p/1280p
        if use_ai_sr and (w_orig < 1280 and h_orig < 1080):
            with gpu_sr_lock:
                enhanced_bgr, scaled_bounds = image_enhancer.enhance_image(img_bgr, raw_bounds)
        else:
            enhanced_bgr = img_bgr
            scaled_bounds = raw_bounds

        cb_x, cb_y, W_c, H_c = scaled_bounds
        h_img, w_img = enhanced_bgr.shape[:2]
        cb_x = max(0, min(w_img - 1, int(cb_x)))
        cb_y = max(0, min(h_img - 1, int(cb_y)))
        W_c = max(1, min(w_img - cb_x, int(W_c)))
        H_c = max(1, min(h_img - cb_y, int(H_c)))
        
        # 2. Extract clean cropped panel
        crop_bgr = enhanced_bgr[cb_y:cb_y+H_c, cb_x:cb_x+W_c].copy()
        clean_panel = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)


        # Pre-apply subtle cinematic color grading & contrast in memory
        color_tint_enabled = render_config_kwargs.get("color_tint_enabled", True) if render_config_kwargs else True
        if color_tint_enabled:
            tint_type = (render_config_kwargs.get("color_tint_type") or "warm_cinema").lower() if render_config_kwargs else "warm_cinema"
            tint_arr = np.array([1.03, 1.01, 0.98], dtype=np.float32) # RGB warm
            if "cool" in tint_type:
                tint_arr = np.array([0.98, 1.01, 1.03], dtype=np.float32)
            elif "vintage" in tint_type or "sepia" in tint_type:
                tint_arr = np.array([1.05, 1.02, 0.96], dtype=np.float32)
            clean_panel = np.clip(clean_panel.astype(np.float32) * tint_arr * 1.01 + 1.0, 0, 255).astype(np.uint8)

        ratio = float(H_c) / float(W_c) if W_c > 0 else 1.0
        base_fg_w = 640.0
        h_cam_640 = float(W_c) * (1080.0 / base_fg_w) if W_c > 0 else 1080.0
        is_tall = (H_c > h_cam_640 * 1.05) and (ratio >= 1.5)

        # 2. Dynamic crisp black border calculation scaled to 1080p video canvas
        target_screen_border = 6.0  # Target 6px crisp border on 1080p video display
        if render_config_kwargs and "border_thickness" in render_config_kwargs:
            try:
                target_screen_border = float(render_config_kwargs["border_thickness"])
            except Exception:
                pass

        if is_tall:
            scale_to_screen = base_fg_w / float(W_c) if W_c > 0 else 1.0
        else:
            scale_to_screen = min(1920.0 / float(W_c), 1080.0 / float(H_c)) if (W_c > 0 and H_c > 0) else 1.0

        b_px = max(4, int(round(target_screen_border / max(0.001, scale_to_screen))))
        b_px = min(b_px, max(1, min(W_c, H_c) // 12))  # Safety clamp: max ~8% of panel dimension

        if H_c >= 2 * b_px and W_c >= 2 * b_px and b_px > 0:
            clean_panel[:b_px, :] = 0
            clean_panel[-b_px:, :] = 0
            clean_panel[:, :b_px] = 0
            clean_panel[:, -b_px:] = 0

        margin = 1.25
        if is_tall:
            needed_w = 3.0 * float(W_c)
            needed_h = float(h_cam_640)
            pad_x = max(10, int(round((needed_w * margin - W_c) / 2.0)))
            pad_y = max(10, int(round(needed_h * (margin - 1.0) / 2.0)))
        else:
            needed_h = float(H_c)
            needed_w = max(float(W_c), H_c * (16.0 / 9.0))
            if needed_w / needed_h > 16.0 / 9.0:
                needed_h = needed_w * (9.0 / 16.0)
            else:
                needed_w = needed_h * (16.0 / 9.0)
            pad_x = max(10, int(round((needed_w * margin - W_c) / 2.0)))
            pad_y = max(10, int(round((needed_h * margin - H_c) / 2.0)))

        # 3. Pre-generate Background Canvas (blurred)
        padded = cv2.copyMakeBorder(clean_panel, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_REFLECT_101)
        ph, pw = padded.shape[:2]
        small_w = 320
        small_h = max(180, int(round(ph * (small_w / pw))))
        small = cv2.resize(padded, (small_w, small_h), interpolation=cv2.INTER_AREA)
        blurred_small = cv2.GaussianBlur(small, (21, 21), 7)
        canvas_np = cv2.resize(blurred_small, (pw, ph), interpolation=cv2.INTER_LINEAR)
        bg_canvas = np.ascontiguousarray(cv2.convertScaleAbs(canvas_np, alpha=0.6, beta=0), dtype=np.uint8)

        # 4. Pre-generate Tall Panel if applicable
        tall_panel = None
        if is_tall:
            pw_tall = int(base_fg_w) # 640px
            ph_tall = max(2, int(round(float(H_c) * (base_fg_w / float(W_c)) / 2.0)) * 2)
            tall_panel = cv2.resize(clean_panel, (pw_tall, ph_tall), interpolation=cv2.INTER_LINEAR)

        asset_data = {
            "panel": clean_panel,
            "bg_canvas": bg_canvas,
            "tall_panel": tall_panel,
            "is_tall": is_tall,
            "bounds": (cb_x, cb_y, W_c, H_c),
            "needed_w": needed_w,
            "pad_x": pad_x,
            "pad_y": pad_y,
            "base_fg_w": base_fg_w
        }
        preloaded_assets[cache_key] = asset_data
        return asset_data

    # Pre-load only the unique frames selected by the recap script using multi-threaded CPU pool
    import concurrent.futures
    unique_img_files = list(dict.fromkeys(pd["image_file"] for pd in page_displays))
    logger.info(f"Đang chuẩn bị {len(unique_img_files)} visual frames cho kịch bản recap (đa luồng CPU + GPU AI SR)...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, os.cpu_count() or 8)) as executor:
        list(executor.map(prepare_single_frame_asset, unique_img_files))

    # Bind assets and precompute Camera Plans for each display segment
    for idx, pd in enumerate(page_displays):
        img_file = pd["image_file"]
        cache_key = f"{img_file}_flipped" if flip_horizontal else img_file
        asset = preloaded_assets[cache_key]
        pd["asset"] = asset

        is_last_page = (idx == len(page_displays) - 1)
        trans = "dip_to_black" if is_last_page else "cross_fade"
        pd["plan"] = CameraPlanner.generate_camera_plan(
            pd["page"], pd["duration"], asset["bounds"],
            is_tall=asset.get("is_tall", False),
            base_fg_w=asset.get("base_fg_w", 640.0),
            transition=trans
        )

    logger.info(f"Đã chuẩn bị xong {len(page_displays)} camera plans. Bắt đầu render song song sang FFmpeg ({fps} FPS)...")

    # Ensure video duration is aligned with audio duration + trailing buffer to prevent cutoffs
    audio_dur = 0.0
    try:
        audio_dur = get_video_duration(audio_path, ffmpeg_exe)
    except Exception:
        pass
    
    # Add 1.0s tail buffer so speech/subtitles never cut off abruptly
    tail_padding = 1.0
    last_page_end = page_displays[-1]["end_time"] if page_displays else 0.0
    if audio_dur and audio_dur > 0:
        total_duration = max(last_page_end, audio_dur + tail_padding)
    else:
        total_duration = last_page_end + tail_padding
    num_frames = max(1, int(round(total_duration * fps)))

    def draw_single_asset_frame(asset, plan, t_local, out_buffer, M_bg_buf, M_fg_buf):
        bounds = asset["bounds"]
        W_c = bounds[2]
        H_c = bounds[3]
        x, y, scale = interpolate_camera_plan(plan, t_local)
        scale = max(0.5, min(1.25, scale))

        # 1. Render animated blurred background
        bg_np = asset["bg_canvas"]
        canvas_h, canvas_w = bg_np.shape[:2]
        if canvas_w == 1920 and canvas_h == 1080:
            np.copyto(out_buffer, bg_np)
        else:
            pad_x = asset["pad_x"]
            pad_y = asset["pad_y"]
            needed_w = asset["needed_w"]
            src_cx = float(pad_x) + float(x)
            src_cy = float(pad_y) + float(y)
            clamped_scale = max(0.5, min(1.35, scale))
            s_out = (1920.0 / needed_w) * clamped_scale

            M_bg_buf[0, 0] = s_out; M_bg_buf[0, 1] = 0.0;   M_bg_buf[0, 2] = 960.0 - src_cx * s_out
            M_bg_buf[1, 0] = 0.0;   M_bg_buf[1, 1] = s_out; M_bg_buf[1, 2] = 540.0 - src_cy * s_out
            cv2.warpAffine(bg_np, M_bg_buf, (1920, 1080), dst=out_buffer, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)

        # 2. Render foreground panel
        if not asset["is_tall"]:
            # Case A: Standard / Short panel -> Sub-pixel Continuous Affine Zoom
            base_scale = 1080.0 / float(H_c)
            if float(W_c) * base_scale > 1920.0:
                base_scale = 1920.0 / float(W_c)

            s_curr = float(base_scale) * float(scale)
            w_dst = float(W_c) * s_curr
            h_dst = float(H_c) * s_curr

            x1 = max(0, int(np.floor(960.0 - w_dst / 2.0)))
            y1 = max(0, int(np.floor(540.0 - h_dst / 2.0)))
            x2 = min(1920, int(np.ceil(960.0 + w_dst / 2.0)))
            y2 = min(1080, int(np.ceil(540.0 + h_dst / 2.0)))
            bw = x2 - x1
            bh = y2 - y1

            if bw > 0 and bh > 0:
                cx_src = float(W_c) / 2.0
                cy_src = float(H_c) / 2.0
                M_fg_buf[0, 0] = s_curr; M_fg_buf[0, 1] = 0.0;    M_fg_buf[0, 2] = (960.0 - float(x1)) - cx_src * s_curr
                M_fg_buf[1, 0] = 0.0;    M_fg_buf[1, 1] = s_curr; M_fg_buf[1, 2] = (540.0 - float(y1)) - cy_src * s_curr

                cv2.warpAffine(
                    asset["panel"], M_fg_buf, (bw, bh),
                    dst=out_buffer[y1:y2, x1:x2],
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=(0, 0, 0)
                )
        else:
            # Case B: Tall panel -> Scaled centered / slide with zoom
            panel_np = asset["tall_panel"]
            pw, ph = panel_np.shape[1], panel_np.shape[0]
            base_fg_w = asset["base_fg_w"]
            s_tall = float(scale)

            curr_pw = float(pw) * s_tall
            curr_ph = float(ph) * s_tall

            pos_x = 960.0 - curr_pw / 2.0
            cy_scaled = (base_fg_w / float(W_c)) * y * s_tall
            pos_y = 540.0 - cy_scaled

            bx1 = max(0, int(np.floor(pos_x)))
            by1 = max(0, int(np.floor(pos_y)))
            bx2 = min(1920, int(np.ceil(pos_x + curr_pw)))
            by2 = min(1080, int(np.ceil(pos_y + curr_ph)))

            bw = bx2 - bx1
            bh = by2 - by1

            if bw > 0 and bh > 0:
                M_fg_buf[0, 0] = s_tall; M_fg_buf[0, 1] = 0.0;    M_fg_buf[0, 2] = pos_x - float(bx1)
                M_fg_buf[1, 0] = 0.0;    M_fg_buf[1, 1] = s_tall; M_fg_buf[1, 2] = pos_y - float(by1)

                cv2.warpAffine(
                    panel_np, M_fg_buf, (bw, bh),
                    dst=out_buffer[by1:by2, bx1:bx2],
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=(0, 0, 0)
                )

    def render_chunk_worker(chunk_indices):
        cv2.setNumThreads(1)
        frame_buf = np.empty((1080, 1920, 3), dtype=np.uint8)
        blend_buf = np.empty((1080, 1920, 3), dtype=np.uint8)
        M_bg_buf = np.zeros((2, 3), dtype=np.float32)
        M_fg_buf = np.zeros((2, 3), dtype=np.float32)
        byte_list = []
        T_trans = 0.20

        for f_idx in chunk_indices:
            t = f_idx / float(fps)
            curr_idx = 0
            for i, pd in enumerate(page_displays):
                if pd["start_time"] <= t < pd["end_time"]:
                    curr_idx = i
                    break
                elif t >= pd["end_time"]:
                    curr_idx = i
            pd_curr = page_displays[curr_idx]

            in_trans = False
            t_trans_start = 0.0
            t_trans_dur = 0.20
            pd_next = None
            if curr_idx + 1 < len(page_displays):
                pd_next = page_displays[curr_idx + 1]
                t_trans_dur = min(T_trans, pd_curr["duration"] * 0.4, pd_next["duration"] * 0.4)
                if t >= pd_curr["end_time"] - t_trans_dur:
                    in_trans = True
                    t_trans_start = pd_curr["end_time"] - t_trans_dur

            if in_trans:
                draw_single_asset_frame(pd_curr["asset"], pd_curr["plan"], t - pd_curr["start_time"], frame_buf, M_bg_buf, M_fg_buf)
                draw_single_asset_frame(pd_next["asset"], pd_next["plan"], max(0.0, t - pd_next["start_time"]), blend_buf, M_bg_buf, M_fg_buf)
                alpha = np.clip((t - t_trans_start) / t_trans_dur, 0.0, 1.0)
                cv2.addWeighted(frame_buf, 1.0 - alpha, blend_buf, alpha, 0, dst=frame_buf)
            else:
                draw_single_asset_frame(pd_curr["asset"], pd_curr["plan"], t - pd_curr["start_time"], frame_buf, M_bg_buf, M_fg_buf)

            # Dip to black
            if t >= total_duration - T_trans:
                alpha = np.clip((t - (total_duration - T_trans)) / T_trans, 0.0, 1.0)
                cv2.convertScaleAbs(frame_buf, alpha=1.0 - alpha, beta=0, dst=frame_buf)

            byte_list.append(frame_buf.tobytes())

        return b"".join(byte_list)

    # Decoupled Producer-Consumer stdin writer worker thread (Zero Pipe Stalling)
    chunk_queue = queue.Queue(maxsize=20)
    writer_error = []

    def stdin_writer_worker():
        try:
            while True:
                chunk_data = chunk_queue.get()
                if chunk_data is None:
                    break
                if proc.stdin:
                    try:
                        proc.stdin.write(chunk_data)
                    except (BrokenPipeError, OSError):
                        break
                chunk_queue.task_done()
        except Exception as e:
            writer_error.append(e)

    writer_thread = threading.Thread(target=stdin_writer_worker, daemon=True)
    writer_thread.start()

    chunk_size = 15
    chunks = [list(range(i, min(i + chunk_size, num_frames))) for i in range(0, num_frames, chunk_size)]
    num_render_workers = min(8, os.cpu_count() or 4)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_render_workers) as executor:
            for chunk_bytes in executor.map(render_chunk_worker, chunks):
                chunk_queue.put(chunk_bytes)
    finally:
        preloaded_assets.clear()
        chunk_queue.put(None)
        writer_thread.join(timeout=15.0)

    try:
        if proc.stdin:
            proc.stdin.flush()
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

async def execute_single_episode_stage10(ep: int, context: WorkflowContext, render_sem: Optional[asyncio.Semaphore] = None) -> bool:
    """Stage 10 - Episode Video Rendering for a single episode."""
    stage_name = "Stage 10 - Episode Video Rendering"
    from app import find_ffmpeg, get_working_encoder, parse_time_to_seconds
    task = context.task
    download_dir = task.artifacts.get("download_dir")
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    images_blur_dir = os.path.join(ep_dir, "images_blur")
    recap_json_path = os.path.join(ep_dir, "recap.json")
    srt_path = os.path.join(ep_dir, "transcript.srt")
    audio_path = os.path.join(ep_dir, "audio.mp3")
    output_video_path = os.path.join(ep_dir, "video.mp4")
    
    ep_key = str(ep)
    if ep_key not in task.episode_progress:
        task.episode_progress[ep_key] = {}
        
    folder_name = task.artifacts.get("download_folder_name") or (os.path.basename(download_dir) if download_dir else "recap")
    if folder_name and not task.artifacts.get("download_folder_name"):
        task.artifacts["download_folder_name"] = folder_name

    if check_episode_completed(download_dir, ep) or (task.episode_progress.get(ep_key, {}).get(stage_name) == StageState.SUCCESS and os.path.exists(output_video_path)):
        if "final_videos" not in task.artifacts:
            task.artifacts["final_videos"] = {}
        task.artifacts["final_videos"][str(ep)] = f"/downloads/{folder_name}/episode_{ep}/video.mp4"
        if "final_subtitles" not in task.artifacts:
            task.artifacts["final_subtitles"] = {}
        task.artifacts["final_subtitles"][str(ep)] = f"/downloads/{folder_name}/episode_{ep}/transcript.srt"
        return True

    task.episode_progress[ep_key][stage_name] = StageState.RUNNING
    for s in task.stages:
        if s["name"] == stage_name and s.get("status") != StageState.SUCCESS:
            s["status"] = StageState.RUNNING
            break
    task.current_stage = stage_name
    await context.manager.save_and_broadcast("EpisodeProgressUpdated", task)

    if not os.path.exists(recap_json_path) or not os.path.exists(srt_path) or not os.path.exists(audio_path):
        await context.log(f"Tập {ep}: Thiếu recap.json, transcript.srt hoặc audio.mp3.", "error", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.FAILED
        return False

    with open(recap_json_path, "r", encoding="utf-8") as f:
        segments = json.load(f)

    raw_srt_path = os.path.join(ep_dir, "transcript_raw.srt")
    source_srt_path = raw_srt_path if (os.path.exists(raw_srt_path) and os.path.getsize(raw_srt_path) > 0) else srt_path

    with open(source_srt_path, "r", encoding="utf-8") as f:
        srt_content = f.read().replace('\r\n', '\n').strip()
    pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\n(.*?)(?=\n\n|\Z)"
    matches = re.findall(pattern, srt_content, re.DOTALL)
    parsed_subs = []
    for num, start_str, end_str, text in matches:
        text_clean = " ".join([l.strip() for l in text.split('\n') if l.strip()])
        text_clean = strip_gemini_citations(text_clean)
        parsed_subs.append({
            "start": parse_time_to_seconds(start_str),
            "end": parse_time_to_seconds(end_str),
            "text": text_clean
        })

    if len(parsed_subs) == len(segments) and source_srt_path == srt_path:
        timings = parsed_subs
    else:
        timings = align_transcript_to_segments(parsed_subs, segments)
        try:
            with open(srt_path, "w", encoding="utf-8") as sf:
                for s_idx, sub in enumerate(timings, 1):
                    s_ms = int(sub["start"] * 1000)
                    e_ms = int(sub["end"] * 1000)
                    s_str = f"{s_ms//3600000:02d}:{(s_ms%3600000)//60000:02d}:{(s_ms%60000)//1000:02d},{s_ms%1000:03d}"
                    e_str = f"{e_ms//3600000:02d}:{(e_ms%3600000)//60000:02d}:{(e_ms%60000)//1000:02d},{e_ms%1000:03d}"
                    sf.write(f"{s_idx}\n{s_str} --> {e_str}\n{sub.get('text', '')}\n\n")
        except Exception:
            pass

    images_dir = os.path.join(ep_dir, "images")
    images_pdf_dir = os.path.join(ep_dir, "images_pdf")
    if os.path.exists(images_blur_dir) and any(f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) for f in os.listdir(images_blur_dir)):
        render_images_dir = images_blur_dir
    elif os.path.exists(images_pdf_dir) and any(f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) for f in os.listdir(images_pdf_dir)):
        render_images_dir = images_pdf_dir
    else:
        render_images_dir = images_dir
    image_files = sorted([f for f in os.listdir(render_images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))], key=natural_sort_key)
    if not image_files:
        await context.log(f"Tập {ep}: Không tìm thấy ảnh trong images.", "error", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.FAILED
        return False

    ffmpeg_exe = find_ffmpeg()
    project_dir = os.path.dirname(os.path.abspath(__file__))

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

    video_mark_path = task.payload.get("video_mark_path")
    if video_mark_path:
        video_mark_path = os.path.abspath(video_mark_path)
    if not video_mark_path or not os.path.exists(video_mark_path):
        video_mark_path = os.path.join(project_dir, "static", "video_mark.mp4")

    enable_video_mark = task.payload.get("enable_video_mark", True)
    video_mark_alpha = float(task.payload.get("video_mark_alpha", 0.01))

    subtitles_enabled = False

    working_encoder = get_working_encoder(ffmpeg_exe, os.path.join(render_images_dir, image_files[0]))
    fps = task.payload.get("fps", 30)

    render_config_kwargs = {
        "film_grain": task.payload.get("film_grain", task.payload.get("grain", True)),
        "grain_strength": task.payload.get("grain_strength", 8),
        "flip_horizontal": task.payload.get("flip_horizontal", task.payload.get("mirror", False)),
        "vignette_enabled": task.payload.get("vignette", task.payload.get("vignette_enabled", True)),
        "vignette_strength": float(task.payload.get("vignette_strength", 0.38)),
        "color_tint_enabled": task.payload.get("color_tint", task.payload.get("color_tint_enabled", True)),
        "color_tint_type": task.payload.get("color_tint_type", "warm_cinema"),
        "color_tint_opacity": float(task.payload.get("color_tint_opacity", 0.035)),
        "visual_lead_offset": float(task.payload.get("visual_lead_offset", task.payload.get("image_lead_offset", 0.6))),
        "use_ai_sr": bool(task.payload.get("use_ai_sr", True)),
        "enable_video_mark": enable_video_mark,
        "video_mark_alpha": video_mark_alpha
    }

    class AsyncNullContext:
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc_val, exc_tb): pass

    sem_ctx = render_sem if render_sem is not None else AsyncNullContext()
    await context.log(f"Tập {ep}: Đang render video...", "info", stage_name=stage_name, episode=ep)
    
    async with sem_ctx:
        await asyncio.to_thread(
            render_episode_video_sync,
            images_blur_dir, image_files, segments, timings, output_video_path,
            ffmpeg_exe, working_encoder, audio_path, logo_path, overlay_path,
            subtitles_enabled, "transcript.srt", fps, render_config_kwargs,
            video_mark_path, video_mark_alpha
        )

    if not os.path.exists(output_video_path) or os.path.getsize(output_video_path) < 100 * 1024:
        await context.log(f"Tập {ep}: Render video thất bại hoặc file video không hợp lệ (<100KB).", "error", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.FAILED
        return False

    folder_name = task.artifacts.get("download_folder_name") or (os.path.basename(download_dir) if download_dir else "recap")
    if folder_name and not task.artifacts.get("download_folder_name"):
        task.artifacts["download_folder_name"] = folder_name

    if "final_videos" not in task.artifacts:
        task.artifacts["final_videos"] = {}
    task.artifacts["final_videos"][str(ep)] = f"/downloads/{folder_name}/episode_{ep}/video.mp4"
    if "final_subtitles" not in task.artifacts:
        task.artifacts["final_subtitles"] = {}
    task.artifacts["final_subtitles"][str(ep)] = f"/downloads/{folder_name}/episode_{ep}/transcript.srt"

    await context.log(f"Tập {ep}: Render video hoàn tất!", "success", stage_name=stage_name, episode=ep)
    task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
    total_eps = task.to_episode - task.from_episode + 1
    completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
    await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
    return True

async def execute_episode_recap_to_video_pipeline(
    ep: int,
    context: WorkflowContext,
    tts_sem: Optional[asyncio.Semaphore] = None,
    render_sem: Optional[asyncio.Semaphore] = None
) -> bool:
    """
    Executes the full post-recap pipeline for a single episode:
    JSON Extraction -> Narration Aggregation -> Local TTS -> Subtitle Normalization -> Video Rendering.
    Runs immediately in background as soon as an episode's script is generated.
    """
    try:
        if context.cancel_token.is_cancelled():
            return False

        await context.log(f"[Pipeline Tập {ep}] Bắt đầu xử lý chuỗi: Kịch bản -> TTS -> Render Video...", "info", episode=ep)
        
        # Step 1: Stage 6 (JSON Extraction / Validation)
        ok = await execute_single_episode_stage6(ep, context)
        if not ok: return False
        
        # Step 2: Stage 7 (Narration Aggregation)
        ok = await execute_single_episode_stage7(ep, context)
        if not ok: return False
        
        # Step 3: Stage 8 (Local TTS)
        if context.task.current_stage.startswith("Stage 5") or context.task.current_stage.startswith("Stage 6") or context.task.current_stage.startswith("Stage 7"):
            context.task.current_stage = "Stage 8 - Local TTS"
            for s in context.task.stages:
                if s["name"] == "Stage 8 - Local TTS" and s.get("status") != StageState.SUCCESS:
                    s["status"] = StageState.RUNNING
                    break
            await context.manager.calculate_overall_progress(context.task)
            await context.manager.save_and_broadcast("WorkflowProgressUpdated", context.task)
        ok = await execute_single_episode_stage8(ep, context, tts_sem)
        if not ok: return False
        
        # Step 4: Stage 9 (Subtitle Normalization)
        ok = await execute_single_episode_stage9(ep, context)
        if not ok: return False
        
        # Step 5: Stage 10 (Episode Video Rendering)
        context.task.current_stage = "Stage 10 - Episode Video Rendering"
        for s in context.task.stages:
            if s["name"] == "Stage 10 - Episode Video Rendering" and s.get("status") != StageState.SUCCESS:
                s["status"] = StageState.RUNNING
                break
        await context.manager.calculate_overall_progress(context.task)
        await context.manager.save_and_broadcast("WorkflowProgressUpdated", context.task)
        ok = await execute_single_episode_stage10(ep, context, render_sem)
        if not ok: return False
        
        await context.log(f"[Pipeline Tập {ep}] Hoàn thành trọn vẹn kịch bản & render video!", "success", episode=ep)
        return True
    except Exception as e:
        await context.log(f"[Pipeline Tập {ep}] Gặp lỗi trong tiến trình render video: {e}", "error", episode=ep)
        return False

class Stage10_EpisodeVideoRendering(BaseStage):
    @property
    def name(self) -> str: return "Stage 10 - Episode Video Rendering"
    @property
    def weight(self) -> float: return 0.17

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        concurrency = task.payload.get("concurrency", 3)
        await context.log(f"Stage 10: Bắt đầu render video song song với tối đa {concurrency} luồng.", "info")
        sem = asyncio.Semaphore(concurrency)

        async def run_ep(ep):
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            await context.start_episode(ep)
            ok = await execute_single_episode_stage10(ep, context, sem)
            if ok:
                await context.complete_episode(ep)
            else:
                await context.fail_episode(ep, "Lỗi render video.")
            return ok

        episodes = list(range(from_ep, to_ep + 1))
        tasks = [run_ep(ep) for ep in episodes]
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
        
    with open(output_srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(merged_lines))

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
        
        folder_name = task.artifacts.get("download_folder_name") or (os.path.basename(download_dir) if download_dir else "recap")
        if folder_name and not task.artifacts.get("download_folder_name"):
            task.artifacts["download_folder_name"] = folder_name
        final_video_name = f"{folder_name}.mp4"
        final_srt_name = f"{folder_name}.srt"
        
        final_video_path = os.path.join(output_dir, final_video_name)
        final_srt_path = os.path.join(output_dir, final_srt_name)

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
            shutil.copy2(os.path.join(download_dir, f"episode_{from_ep}", "video.mp4"), final_video_path)
            await context.log(f"Chỉ có 1 tập, sao chép trực tiếp thành {final_video_name}.", "success")
            
            # Copy srt file directly as final_srt_path if it exists
            single_srt = os.path.join(download_dir, f"episode_{from_ep}", "transcript.srt")
            if os.path.exists(single_srt):
                shutil.copy2(single_srt, final_srt_path)
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
                final_video_path
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
            try:
                merge_srt_files(srt_paths, video_durations, final_srt_path)
                await context.log(f"Đã hoàn thành gộp phụ đề thành {final_srt_name}.", "success")
            except Exception as e:
                await context.log(f"Lỗi khi gộp file phụ đề srt: {e}", "warning")

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
        
        with open(os.path.join(output_dir, "metadata.json"), "w", encoding="utf-8") as mf:
            json.dump(metadata, mf, ensure_ascii=False, indent=2)

        report = {
            "task_id": task.id,
            "stages": task.stages,
            "completed_episodes_count": task.completed_count,
            "failed_episodes_count": task.failed_count,
            "error_message": task.error_message
        }
        
        with open(os.path.join(output_dir, "processing_report.json"), "w", encoding="utf-8") as rf:
            json.dump(report, rf, ensure_ascii=False, indent=2)

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

        # Thu gom rác & Xóa cache browser cuối cùng
        try:
            from app import clear_browser_cache
            res = await asyncio.to_thread(clear_browser_cache)
            await context.log(f"Thu gom rác trình duyệt: {res.get('message', 'Đã xóa cache browser.')}", "info")
        except Exception as cache_err:
            await context.log(f"Cảnh báo dọn dẹp browser cache: {cache_err}", "warning")

        await context.update_stage_progress(self.name, 100.0)
        return True
