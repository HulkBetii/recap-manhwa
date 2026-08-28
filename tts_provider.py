import os
import wave
import sys
import subprocess
import asyncio
import numpy as np
import torch
from types import ModuleType

class TritonMock:
    def __getitem__(self, item):
        return self
    def __call__(self, *args, **kwargs):
        raise RuntimeError("Triton not available")

# Mock whisper.triton_ops to prevent ImportError in whisper.timing on Windows/systems without Triton
try:
    import whisper.triton_ops
except Exception:
    mock_triton = ModuleType("whisper.triton_ops")
    mock_triton.median_filter_cuda = TritonMock()
    mock_triton.dtw_kernel = TritonMock()
    sys.modules["whisper.triton_ops"] = mock_triton

try:
    import whisper
except ImportError:
    whisper = None
from datetime import timedelta
import logging
from security_utils import redact_sensitive_text
from tts_settings import get_ai33pro_voice_id, uses_ai33pro


# Load configuration
import config
from app import find_ffmpeg

logger = logging.getLogger("TTSProvider")


class SensitiveLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive_text(record.getMessage()) or ""
        record.args = ()
        return True


logger.addFilter(SensitiveLogFilter())

# Singleton OmniVoice model to avoid re-initializing on every call
_omnivoice_model = None

def get_omnivoice_model():
    global _omnivoice_model
    if _omnivoice_model is None:
        from omnivoice import OmniVoice
        device = config.DEVICE
        device_map = "cuda:0" if device == "cuda" else device
        dtype = torch.float16 if "cuda" in device or "mps" in device else torch.float32
        logger.info(f"Initializing OmniVoice model 'k2-fsa/OmniVoice' on device='{device_map}' with dtype={dtype}...")
        _omnivoice_model = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice",
            device_map=device_map,
            dtype=dtype
        )
    return _omnivoice_model

def save_wav_built_in(audio_data: np.ndarray, sample_rate: int, output_path: str):
    """
    Saves a float32 numpy array as a mono 16-bit PCM WAV file using Python's built-in wave module.
    """
    # Convert float32 [-1.0, 1.0] to 16-bit PCM [-32768, 32767]
    audio_int16 = (audio_data * 32767).astype(np.int16)
    with wave.open(output_path, "wb") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit PCM = 2 bytes
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_int16.tobytes())

def convert_wav_to_mp3(wav_path: str, mp3_path: str):
    """
    Converts a WAV file to MP3 format using FFmpeg.
    """
    ffmpeg_exe = find_ffmpeg()
    cmd = [
        ffmpeg_exe, "-y", "-i", wav_path,
        "-codec:a", "libmp3lame", "-qscale:a", "2",
        mp3_path
    ]
    startupinfo = None
    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
    if result.returncode != 0:
        err_msg = result.stderr.decode('utf-8', errors='ignore')
        logger.error(f"FFmpeg conversion failed: {err_msg}")
        raise Exception(f"FFmpeg conversion failed: {err_msg}")

def format_timestamp(seconds: float) -> str:
    """
    Formats seconds float into SRT timestamp format: HH:MM:SS,mmm
    """
    td = timedelta(seconds=seconds)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = int(td.microseconds / 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def write_srt(segments, srt_path):
    """
    Writes Whisper transcription segments to an SRT file.
    """
    with open(srt_path, "w", encoding="utf-8") as f:
        for idx, segment in enumerate(segments, 1):
            start = format_timestamp(segment["start"])
            end = format_timestamp(segment["end"])
            text = segment["text"].strip()
            f.write(f"{idx}\n{start} --> {end}\n{text}\n\n")

import threading

_whisper_lock = threading.Lock()
_omnivoice_lock = threading.Lock()

_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        if whisper is None:
            raise RuntimeError("Thư viện whisper chưa được cài đặt.")
        logger.info(f"Initializing Whisper model ('base') on device='{config.DEVICE}'...")
        _whisper_model = whisper.load_model("base", device=config.DEVICE)
    return _whisper_model

def generate_transcript(audio_path: str, srt_path: str):
    """
    Transcribes an audio file using local OpenAI Whisper and outputs an SRT file.
    """
    model = get_whisper_model()
    logger.info(f"Transcribing audio file '{audio_path}' using Whisper...")
    with _whisper_lock:
        result = model.transcribe(audio_path, word_timestamps=True)
    write_srt(result["segments"], srt_path)
    logger.info(f"Successfully generated transcript SRT at '{srt_path}'")

_ref_audio_transcriptions = {}

def get_ref_audio_text(ref_audio_path: str) -> str:
    global _ref_audio_transcriptions
    if ref_audio_path not in _ref_audio_transcriptions:
        logger.info(f"Transcribing reference audio '{ref_audio_path}' locally using Whisper...")
        model = get_whisper_model()
        with _whisper_lock:
            result = model.transcribe(ref_audio_path)
        text = result.get("text", "").strip()
        logger.info(f"Transcribed reference audio text: '{text}'")
        _ref_audio_transcriptions[ref_audio_path] = text
    return _ref_audio_transcriptions[ref_audio_path]

def normalize_srt_content(raw_srt: str) -> str:
    import re
    # 1. Normalize line endings to LF
    content = raw_srt.replace('\r\n', '\n').replace('\r', '\n')
    
    # 2. Extract entries using a loose regex that supports different formats
    entry_pattern = r"(?:^|\n+)(\d+)\s*\n(\d{1,2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{3})\s*\n(.*?)(?=\n+\d+\s*\n\d{1,2}:|\Z)"
    matches = re.findall(entry_pattern, content, re.DOTALL)
    
    normalized_blocks = []
    for idx, (num, start_str, end_str, text_content) in enumerate(matches, 1):
        # Normalize time strings: replace dots with commas, pad hours if single digit
        def norm_time(t_str):
            t_str = t_str.replace('.', ',')
            parts = t_str.split(':')
            if len(parts) == 3:
                if len(parts[0]) == 1:
                    parts[0] = '0' + parts[0]
                return ':'.join(parts)
            return t_str
            
        start_clean = norm_time(start_str.strip())
        end_clean = norm_time(end_str.strip())
        
        # Clean text lines
        text_lines = [line.strip() for line in text_content.strip().split('\n') if line.strip()]
        text_clean = '\n'.join(text_lines)
        
        normalized_blocks.append(f"{idx}\n{start_clean} --> {end_clean}\n{text_clean}\n")
        
    return '\n'.join(normalized_blocks) + '\n'

async def generate_ai33pro_tts(text: str, output_audio_path: str, output_srt_path: str) -> bool:
    import httpx
    api_key = os.getenv("XI_API_KEY")
    if not api_key:
        logger.error("AI33Pro API key not found in environment (XI_API_KEY).")
        return False
        
    api_key = api_key.strip()
    url = "https://api.ai33.pro/v3/text-to-speech"
    headers = {
        "xi-api-key": api_key
    }
    
    voice_id = get_ai33pro_voice_id()
        
    files = {
        "text": (None, text),
        "voice_id": (None, voice_id),
        "speed": (None, "1"),
        "with_transcript": (None, "true")
    }
    
    logger.info("AI33Pro: Creating TTS task with the configured environment voice...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(url, headers=headers, files=files)
            if response.status_code != 200:
                logger.error(f"AI33Pro task creation failed with HTTP {response.status_code}.")
                return False
                
            res_json = response.json()
            if not res_json.get("success"):
                logger.error("AI33Pro task creation response reported success=False.")
                return False
                
            task_id = res_json.get("task_id")
            if not task_id:
                logger.error("AI33Pro task creation did not return task_id.")
                return False
                
            logger.info(f"AI33Pro task created successfully. Task ID: {task_id}. Polling status...")
            
            poll_url = f"https://api.ai33.pro/v1/task/{task_id}"
            max_attempts = 120  # poll for up to 10 minutes (120 * 5s)
            
            for attempt in range(max_attempts):
                await asyncio.sleep(5)
                try:
                    poll_response = await client.get(poll_url, headers=headers, timeout=10.0)
                    if poll_response.status_code != 200:
                        logger.warning(f"AI33Pro poll failed ({poll_response.status_code}), retrying...")
                        continue
                        
                    task_data = poll_response.json()
                    status = task_data.get("status")
                    logger.info(f"AI33Pro task {task_id} status: {status} (Progress: {task_data.get('progress', 0)}%)")
                    
                    if status == "done":
                        metadata = task_data.get("metadata", {})
                        audio_url = metadata.get("audio_url")
                        srt_url = metadata.get("srt_url")
                        
                        if not audio_url:
                            logger.error("AI33Pro task completed but did not return an audio URL.")
                            return False
                            
                        logger.info("AI33Pro task completed. Downloading generated audio...")
                        audio_resp = await client.get(audio_url, timeout=30.0)
                        if audio_resp.status_code != 200:
                            logger.error(f"Failed to download generated audio: HTTP {audio_resp.status_code}.")
                            return False
                            
                        with open(output_audio_path, "wb") as f:
                            f.write(audio_resp.content)
                        logger.info(f"Audio downloaded and saved to {output_audio_path}")
                        
                        if srt_url:
                            logger.info("AI33Pro: Downloading generated SRT...")
                            srt_resp = await client.get(srt_url, timeout=30.0)
                            if srt_resp.status_code == 200:
                                normalized_srt = normalize_srt_content(srt_resp.text)
                                with open(output_srt_path, "w", encoding="utf-8") as f:
                                    f.write(normalized_srt)
                                logger.info(f"SRT downloaded, normalized, and saved to {output_srt_path}")
                            else:
                                logger.warning(f"Failed to download generated SRT: HTTP {srt_resp.status_code}.")
                                logger.info("Generating SRT locally using Whisper fallback...")
                                await asyncio.to_thread(generate_transcript, output_audio_path, output_srt_path)
                        else:
                            logger.info("No SRT url returned, transcribing locally using Whisper...")
                            await asyncio.to_thread(generate_transcript, output_audio_path, output_srt_path)
                            
                        return True
                        
                    elif status == "error":
                        err_msg = task_data.get("error_message") or "Unknown error"
                        logger.error(f"AI33Pro task failed with error: {err_msg}")
                        return False
                        
                except Exception as e:
                    logger.warning(f"Exception during AI33Pro polling: {e}")
                    
            logger.error("AI33Pro task timed out.")
            return False
            
        except Exception as e:
            logger.error(f"Exception during AI33Pro request: {e}", exc_info=True)
            return False

async def generate_tts(text: str, output_audio_path: str, output_srt_path: str, voice_id: str = None, ref_audio_path: str = None) -> bool:
    """
    Generates local TTS audio (MP3) and its SRT transcript using OmniVoice.
    Supports Voice Cloning (via ref_audio_path) and Voice Design (via voice_id / instruct).
    """
    if uses_ai33pro(voice_id):
        return await generate_ai33pro_tts(text, output_audio_path, output_srt_path)

    try:
        model = get_omnivoice_model()
        kwargs = {
            "num_step": config.OMNIVOICE_NUM_STEPS
        }
        
        if (not voice_id or voice_id == "auto") and not ref_audio_path:
            jessa_ref = os.path.join(os.getcwd(), "static", "jessa - easygoing and effortless.mp3")
            if os.path.exists(jessa_ref):
                ref_audio_path = jessa_ref
                logger.info(f"Auto Voice selected: Using default reference audio for cloning: {ref_audio_path}")

        if ref_audio_path and os.path.exists(ref_audio_path):
            logger.info(f"OmniVoice: Generating TTS with Voice Cloning from reference audio: {ref_audio_path}")
            ref_text = await asyncio.to_thread(get_ref_audio_text, ref_audio_path)
            kwargs["ref_audio"] = ref_audio_path
            kwargs["ref_text"] = ref_text
        elif voice_id and voice_id != "auto" and voice_id.strip() != "":
            logger.info(f"OmniVoice: Generating TTS with Voice Design instruct: {voice_id}")
            kwargs["instruct"] = voice_id
        else:
            logger.info("OmniVoice: Generating TTS with Auto Voice")

        def split_text_into_segments(raw_text: str, max_chars: int = 300) -> list:
            import re
            # Split by period, exclamation, question mark, semicolon or newline followed by space
            sentences = re.split(r'(?<=[.!?;\n])\s+', raw_text.strip())
            
            # First level processing (clauses/words)
            temp_segments = []
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                if len(s) <= max_chars:
                    temp_segments.append(s)
                else:
                    # Split by clause boundaries (comma, colon, dash)
                    clauses = re.split(r'(?<=[,:\-])\s+', s)
                    current_chunk = []
                    current_len = 0
                    for clause in clauses:
                        clause = clause.strip()
                        if not clause:
                            continue
                        if current_len + len(clause) + 1 <= max_chars:
                            current_chunk.append(clause)
                            current_len += len(clause) + 1
                        else:
                            if current_chunk:
                                temp_segments.append(" ".join(current_chunk))
                            current_chunk = [clause]
                            current_len = len(clause)
                    if current_chunk:
                        temp_segments.append(" ".join(current_chunk))
                        
            # Second level processing (split by words if any chunk is still too long)
            final_segments = []
            for s in temp_segments:
                if len(s) <= max_chars:
                    final_segments.append(s)
                else:
                    words = s.split(" ")
                    current_chunk = []
                    current_len = 0
                    for word in words:
                        if current_len + len(word) + 1 <= max_chars:
                            current_chunk.append(word)
                            current_len += len(word) + 1
                        else:
                            if current_chunk:
                                final_segments.append(" ".join(current_chunk))
                            current_chunk = [word]
                            current_len = len(word)
                    if current_chunk:
                        final_segments.append(" ".join(current_chunk))
            return final_segments

        def synthesize():
            segments = split_text_into_segments(text)
            if not segments:
                raise Exception("No text segments to synthesize.")

            audio_segments = []
            with _omnivoice_lock:
                for idx, segment in enumerate(segments):
                    logger.info(f"OmniVoice: Generating segment {idx+1}/{len(segments)} ({len(segment)} chars)...")
                    audio = model.generate(text=segment, **kwargs)
                    if audio and len(audio) > 0:
                        audio_segments.append(audio[0])
                    else:
                        logger.warning(f"OmniVoice returned empty audio for segment: '{segment}'")

            if not audio_segments:
                raise Exception("OmniVoice returned empty audio for all segments.")

            return np.concatenate(audio_segments)

        audio_data = await asyncio.to_thread(synthesize)
        
        # Save to temp WAV file
        temp_wav_path = output_audio_path + ".temp.wav"
        await asyncio.to_thread(save_wav_built_in, audio_data, 24000, temp_wav_path)
        
        # Convert WAV to MP3 using FFmpeg
        await asyncio.to_thread(convert_wav_to_mp3, temp_wav_path, output_audio_path)
        
        # Clean up temp WAV file
        try:
            os.remove(temp_wav_path)
        except Exception:
            pass
        
        # Generate SRT transcript using Whisper in thread pool
        await asyncio.to_thread(generate_transcript, output_audio_path, output_srt_path)
        
        return True
    except Exception as e:
        logger.error(f"TTS generation failed: {e}", exc_info=True)
        return False
        
