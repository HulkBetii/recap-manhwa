import os
import wave
import sys
import subprocess
import asyncio
import numpy as np
import torch
from types import ModuleType

from faster_whisper import WhisperModel
from datetime import timedelta
import logging


# Load configuration
import config
from app import find_ffmpeg, check_ffmpeg_has_mp3lame

logger = logging.getLogger("TTSProvider")

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
    Applies peak normalization to maximize dynamic range and prevent quiet output.
    """
    if len(audio_data) > 0:
        max_val = float(np.max(np.abs(audio_data)))
        if max_val > 1e-4:
            audio_data = (audio_data / max_val) * 0.95
    # Convert float32 [-1.0, 1.0] to 16-bit PCM [-32768, 32767]
    audio_int16 = (audio_data * 32767).astype(np.int16)
    with wave.open(output_path, "wb") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit PCM = 2 bytes
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_int16.tobytes())

def convert_wav_to_mp3(wav_path: str, mp3_path: str):
    """
    Converts a WAV file to MP3 audio format using FFmpeg with EBU R128 loudness normalization (-14 LUFS).
    Supports dynamic fallback to Windows MediaFoundation MP3 encoder (mp3_mf) when libmp3lame is not present.
    """
    ffmpeg_exe = find_ffmpeg()
    has_lame = check_ffmpeg_has_mp3lame(ffmpeg_exe)
    codec_args = ["-codec:a", "libmp3lame", "-qscale:a", "2"] if has_lame else ["-ar", "44100", "-codec:a", "mp3_mf", "-b:a", "192k"]
    
    cmd = [
        ffmpeg_exe, "-y", "-i", wav_path,
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        *codec_args,
        mp3_path
    ]
    startupinfo = None
    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
    if result.returncode != 0:
        err_msg = result.stderr.decode('utf-8', errors='ignore')
        logger.error(f"FFmpeg audio conversion failed: {err_msg}")
        raise Exception(f"FFmpeg audio conversion failed: {err_msg}")

def normalize_audio_file(audio_path: str):
    """
    Normalizes an audio file in-place to EBU R128 standard (-14 LUFS, TP -1.5 dBTP)
    so speech narration has consistent, standard broadcast volume.
    """
    if not os.path.exists(audio_path):
        return
    ffmpeg_exe = find_ffmpeg()
    has_lame = check_ffmpeg_has_mp3lame(ffmpeg_exe)
    codec_args = ["-codec:a", "libmp3lame", "-qscale:a", "2"] if has_lame else ["-ar", "44100", "-codec:a", "mp3_mf", "-b:a", "192k"]
    
    temp_out = audio_path + ".norm.mp3"
    cmd = [
        ffmpeg_exe, "-y", "-i", audio_path,
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        *codec_args,
        temp_out
    ]
    startupinfo = None
    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        if res.returncode == 0 and os.path.exists(temp_out) and os.path.getsize(temp_out) > 1000:
            os.replace(temp_out, audio_path)
            logger.info(f"Successfully normalized audio loudness for {audio_path}")
        else:
            if os.path.exists(temp_out):
                os.remove(temp_out)
    except Exception as e:
        logger.warning(f"Failed to normalize audio {audio_path}: {e}")
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except Exception:
                pass

def format_timestamp(seconds: float) -> str:
    """
    Formats seconds float into SRT timestamp format: HH:MM:SS,mmm
    """
    td = timedelta(seconds=seconds)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = int(td.microseconds / 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def merge_segments_to_sentences(segments: list) -> list:
    """
    Merges Whisper / TTS transcription segments that were split on commas (,)
    or mid-sentence pauses back into complete grammatical sentences.
    Terminal punctuation: [. ! ? … # 。 ！ ？]
    """
    if not segments:
        return []
        
    terminal_punct = ('.', '!', '?', '…', '。', '！', '？', '#')
    merged = []
    curr_seg = None
    
    for seg in segments:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
            
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", 0.0))
        
        if curr_seg is None:
            curr_seg = {
                "start": start,
                "end": end,
                "text": text
            }
        else:
            prev_text = curr_seg["text"].rstrip()
            is_terminal = prev_text.endswith(terminal_punct)
            
            # If previous fragment ended with comma or non-terminal punctuation, merge it
            if not is_terminal:
                curr_seg["end"] = end
                curr_seg["text"] = f"{prev_text} {text}".strip()
            else:
                merged.append(curr_seg)
                curr_seg = {
                    "start": start,
                    "end": end,
                    "text": text
                }
                
    if curr_seg is not None:
        merged.append(curr_seg)
        
    return merged

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

def get_whisper_model() -> WhisperModel:
    """Singleton faster-whisper model (large-v3 FP16 on CUDA / int8 on CPU)."""
    global _whisper_model
    if _whisper_model is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        model_size = os.getenv("WHISPER_MODEL", "large-v3")
        logger.info(f"Initializing faster-whisper ('{model_size}') on device='{device}', compute_type='{compute_type}'...")
        _whisper_model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            num_workers=1,
            cpu_threads=4,
        )
        logger.info("faster-whisper model initialized successfully.")
    return _whisper_model

def generate_transcript(audio_path: str, srt_path: str):
    """
    Transcribes an audio file using faster-whisper and outputs an SRT file,
    automatically merging fragments split by commas/pauses into full sentences.
    """
    model = get_whisper_model()
    logger.info(f"Transcribing audio file '{audio_path}' using faster-whisper...")
    with _whisper_lock:
        segments_gen, info = model.transcribe(
            audio_path,
            language=None,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500}
        )
        raw_segments = [
            {"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()}
            for seg in segments_gen
        ]
    
    logger.info(f"faster-whisper detected lang: {info.language} (prob={info.language_probability:.2f}), {len(raw_segments)} segments")
    raw_srt_path = os.path.splitext(srt_path)[0] + "_raw.srt"
    try:
        write_srt(raw_segments, raw_srt_path)
    except Exception as e:
        logger.warning(f"Could not write raw SRT to '{raw_srt_path}': {e}")
    
    # Merge comma-split / mid-clause fragments into complete sentences
    clean_segments = merge_segments_to_sentences(raw_segments)
    write_srt(clean_segments, srt_path)
    logger.info(f"Successfully generated transcript SRT at '{srt_path}' ({len(clean_segments)} complete sentences, raw={len(raw_segments)})")

_ref_audio_transcriptions = {}

def get_ref_audio_text(ref_audio_path: str) -> str:
    global _ref_audio_transcriptions
    if ref_audio_path not in _ref_audio_transcriptions:
        logger.info(f"Transcribing reference audio '{ref_audio_path}' locally using faster-whisper...")
        model = get_whisper_model()
        with _whisper_lock:
            segments_gen, _ = model.transcribe(ref_audio_path, beam_size=5)
            text = " ".join(seg.text.strip() for seg in segments_gen)
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
    
    def norm_time(t_str):
        t_str = t_str.replace('.', ',')
        parts = t_str.split(':')
        if len(parts) == 3:
            if len(parts[0]) == 1:
                parts[0] = '0' + parts[0]
            return ':'.join(parts)
        return t_str
    
    parsed_cues = []
    for num, start_str, end_str, text_content in matches:
        start_clean = norm_time(start_str.strip())
        end_clean = norm_time(end_str.strip())
        text_lines = [line.strip() for line in text_content.strip().split('\n') if line.strip()]
        text_clean = ' '.join(text_lines)
        if text_clean:
            parsed_cues.append({
                "start_str": start_clean,
                "end_str": end_clean,
                "text": text_clean
            })
            
    # Merge comma-split cues
    terminal_punct = ('.', '!', '?', '…', '。', '！', '？', '#')
    merged_cues = []
    curr_cue = None
    for cue in parsed_cues:
        if curr_cue is None:
            curr_cue = dict(cue)
        else:
            prev_text = curr_cue["text"].rstrip()
            if not prev_text.endswith(terminal_punct):
                curr_cue["end_str"] = cue["end_str"]
                curr_cue["text"] = f"{prev_text} {cue['text']}".strip()
            else:
                merged_cues.append(curr_cue)
                curr_cue = dict(cue)
    if curr_cue is not None:
        merged_cues.append(curr_cue)

    normalized_blocks = []
    for idx, cue in enumerate(merged_cues, 1):
        normalized_blocks.append(f"{idx}\n{cue['start_str']} --> {cue['end_str']}\n{cue['text']}\n")
        
    return '\n'.join(normalized_blocks) + '\n'

async def generate_ai33pro_tts(text: str, output_audio_path: str, output_srt_path: str, voice_id: str = None, api_key: str = None) -> bool:
    import httpx
    if not api_key:
        api_key = os.getenv("XI_API_KEY")
    if not api_key:
        logger.error("AI33Pro API key not found in environment (XI_API_KEY) or parameters.")
        return False
        
    api_key = api_key.strip()
    url = "https://api.ai33.pro/v3/text-to-speech"
    headers = {
        "xi-api-key": api_key
    }
    
    # Use elevenlabs_tnSpp4vdxKPjI9w0GnoV as default if voice_id is not specified, or is "ai33pro",
    # or is not a valid provider prefix ID.
    ai33pro_prefixes = ("elevenlabs_", "minimax_", "clone_", "edge_", "kokoro_", "vbee_", "fishaudio_")
    if not voice_id or voice_id == "ai33pro" or not voice_id.startswith(ai33pro_prefixes):
        voice_id = "elevenlabs_tnSpp4vdxKPjI9w0GnoV"
        
    files = {
        "text": (None, text),
        "voice_id": (None, voice_id),
        "speed": (None, "1.1"),
        "with_transcript": (None, "true")
    }
    
    logger.info(f"AI33Pro: Creating TTS task with voice {voice_id}...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(url, headers=headers, files=files)
            if response.status_code != 200:
                logger.error(f"AI33Pro task creation failed: {response.status_code} - {response.text}")
                return False
                
            res_json = response.json()
            if not res_json.get("success"):
                logger.error(f"AI33Pro task creation response success=False: {res_json}")
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
                            logger.error(f"AI33Pro task completed but missing audio_url: {task_data}")
                            return False
                            
                        logger.info(f"AI33Pro task completed. Downloading audio from {audio_url}...")
                        audio_resp = await client.get(audio_url, timeout=30.0)
                        if audio_resp.status_code != 200:
                            logger.error(f"Failed to download audio from {audio_url}: {audio_resp.status_code}")
                            return False
                            
                        with open(output_audio_path, "wb") as f:
                            f.write(audio_resp.content)
                        logger.info(f"Audio downloaded and saved to {output_audio_path}")
                        await asyncio.to_thread(normalize_audio_file, output_audio_path)
                        
                        if srt_url:
                            logger.info(f"AI33Pro: Downloading SRT from {srt_url}...")
                            srt_resp = await client.get(srt_url, timeout=30.0)
                            if srt_resp.status_code == 200:
                                normalized_srt = normalize_srt_content(srt_resp.text)
                                with open(output_srt_path, "w", encoding="utf-8") as f:
                                    f.write(normalized_srt)
                                logger.info(f"SRT downloaded, normalized, and saved to {output_srt_path}")
                            else:
                                logger.warning(f"Failed to download SRT from {srt_url}: {srt_resp.status_code}")
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

async def generate_tts(text: str, output_audio_path: str, output_srt_path: str, voice_id: str = None, ref_audio_path: str = None, ai33pro_api_key: str = None) -> bool:
    """
    Generates local TTS audio (MP3) and its SRT transcript using OmniVoice.
    Supports Voice Cloning (via ref_audio_path) and Voice Design (via voice_id / instruct).
    """
    ai33pro_prefixes = ("elevenlabs_", "minimax_", "clone_", "edge_", "kokoro_", "vbee_", "fishaudio_")
    if voice_id == "ai33pro" or (voice_id and voice_id.startswith(ai33pro_prefixes)):
        return await generate_ai33pro_tts(text, output_audio_path, output_srt_path, voice_id=voice_id, api_key=ai33pro_api_key)

    try:
        model = get_omnivoice_model()
        kwargs = {
            "num_step": config.OMNIVOICE_NUM_STEPS
        }
        
        if ref_audio_path and not os.path.isabs(ref_audio_path):
            abs_cand = os.path.join(os.path.dirname(os.path.abspath(__file__)), ref_audio_path)
            if os.path.exists(abs_cand):
                ref_audio_path = abs_cand

        # Auto-detect optimal _ref.wav if exists alongside long audio
        if ref_audio_path and os.path.exists(ref_audio_path) and not ref_audio_path.endswith("_ref.wav"):
            base, ext = os.path.splitext(ref_audio_path)
            opt_ref = f"{base}_ref.wav"
            if os.path.exists(opt_ref):
                logger.info(f"Using pre-optimized golden reference sample: {opt_ref}")
                ref_audio_path = opt_ref

        if (not voice_id or voice_id == "auto") and not ref_audio_path:
            # 1. Check configured default English sample first
            env_def = getattr(config, "DEFAULT_EN_VOICE_SAMPLE", "voices/Andrew - Smooth, Smart and Clear.wav")
            cand_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), env_def)
            cand_env_ref = os.path.splitext(cand_env)[0] + "_ref.wav"
            if os.path.exists(cand_env_ref):
                ref_audio_path = cand_env_ref
            elif os.path.exists(cand_env):
                ref_audio_path = cand_env
            else:
                # 2. Check voices directory
                voices_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")
                if os.path.exists(voices_dir):
                    voice_files = sorted([os.path.join(voices_dir, f) for f in os.listdir(voices_dir) if f.lower().endswith(('.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.webm'))])
                    # Prioritize Andrew golden ref or sample
                    andrew_ref = [f for f in voice_files if "andrew" in os.path.basename(f).lower() and "_ref" in f]
                    andrew_cand = [f for f in voice_files if "andrew" in os.path.basename(f).lower()]
                    if andrew_ref:
                        ref_audio_path = andrew_ref[0]
                    elif andrew_cand:
                        ref_audio_path = andrew_cand[0]
                    elif voice_files:
                        ref_audio_path = voice_files[0]
            if not ref_audio_path or not os.path.exists(ref_audio_path):
                amy_ref = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "voice_preview_amy - natural and sweet.mp3")
                if os.path.exists(amy_ref):
                    ref_audio_path = amy_ref
            if ref_audio_path and os.path.exists(ref_audio_path):
                logger.info(f"Auto Voice selected: Using reference audio for cloning: {ref_audio_path}")

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

        def split_text_into_segments(raw_text: str, max_chars: int = 220) -> list:
            import re
            # Split strictly by sentence boundaries (. ! ? ; \n)
            sentences = [s.strip() for s in re.split(r'(?<=[.!?;\n])\s+', raw_text.strip()) if s.strip()]
            
            final_segments = []
            for s in sentences:
                if len(s) <= max_chars:
                    final_segments.append(s)
                else:
                    # Split only when an individual sentence is exceedingly long (> 220 chars)
                    clauses = [c.strip() for c in re.split(r'(?<=[,:\-])\s+', s) if c.strip()]
                    current_chunk = []
                    current_len = 0
                    for clause in clauses:
                        if current_len + len(clause) + 1 <= max_chars:
                            current_chunk.append(clause)
                            current_len += len(clause) + 1
                        else:
                            if current_chunk:
                                final_segments.append(" ".join(current_chunk))
                            current_chunk = [clause]
                            current_len = len(clause)
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
                        # Add a clean natural breath/pause (0.20s) between sentences
                        if idx < len(segments) - 1:
                            inter_silence = int(24000 * 0.20)
                            audio_segments.append(np.zeros(inter_silence, dtype=np.float32))
                    else:
                        logger.warning(f"OmniVoice returned empty audio for segment: '{segment}'")

            if not audio_segments:
                raise Exception("OmniVoice returned empty audio for all segments.")

            # Append trailing silence (0.8s) to prevent clipping at the end of speech
            silence_samples = int(24000 * 0.8)
            audio_segments.append(np.zeros(silence_samples, dtype=np.float32))

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
        


