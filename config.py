import os
import torch

APP_NAME = "Recap Comics Automation"
APP_VERSION = "1.8.0"

# TTS Configuration
# Supported providers: "kokoro"
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "kokoro")

# Hugging Face model repository or local path
TTS_MODEL = os.getenv("TTS_MODEL", "hexgrad/Kokoro-82M")

# Default voice: af_sarah or af_bella (natural American female voices)
TTS_VOICE = os.getenv("TTS_VOICE", "af_sarah")

# Device to run inference on: "cuda" (Windows NVIDIA), "mps" (macOS Apple Silicon), or "cpu"
DEVICE = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu"))

# OmniVoice Settings: number of steps for diffusion/flow matching.
# 32 steps is default. 16 steps is 2x faster with almost identical quality (officially recommended).
OMNIVOICE_NUM_STEPS = int(os.getenv("OMNIVOICE_NUM_STEPS", "16"))

# Static directory path
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Default reference audio for OmniVoice voice cloning (Vietnamese & General default)
USER_DEFAULT_REF_AUDIO = r"C:\Users\HulkBeoti\Downloads\jessa - easygoing and effortless.mp3"
STATIC_DEFAULT_REF_AUDIO = os.path.join(STATIC_DIR, "jessa - easygoing and effortless.mp3")
DEFAULT_REF_AUDIO_PATH = os.getenv(
    "DEFAULT_REF_AUDIO_PATH",
    USER_DEFAULT_REF_AUDIO if os.path.exists(USER_DEFAULT_REF_AUDIO) else STATIC_DEFAULT_REF_AUDIO
)

# Default English (US) TTS Voice Configuration (OmniVoice Voice Cloning: Andrew - Smooth, Smart and Clear)
ANDREW_DEFAULT_REF_AUDIO = os.path.join(STATIC_DIR, "voices", "andrew_smooth_ref.wav")
DEFAULT_EN_VOICE = os.getenv("DEFAULT_EN_VOICE", "Andrew - Smooth, Smart and Clear (US)")
DEFAULT_EN_VOICE_ID = os.getenv("DEFAULT_EN_VOICE_ID", "clone_andrew")
DEFAULT_EN_REF_AUDIO = os.getenv("DEFAULT_EN_REF_AUDIO", ANDREW_DEFAULT_REF_AUDIO)
DEFAULT_EN_VOICE_RATE = os.getenv("DEFAULT_EN_VOICE_RATE", "+0%")
DEFAULT_EN_VOICE_PITCH = os.getenv("DEFAULT_EN_VOICE_PITCH", "+0Hz")

# Default Vietnamese TTS Voice Configuration (OmniVoice Voice Cloning: Jessa - Easygoing and Effortless)
DEFAULT_VI_VOICE = os.getenv("DEFAULT_VI_VOICE", "jessa - easygoing and effortless")
DEFAULT_VI_VOICE_ID = os.getenv("DEFAULT_VI_VOICE_ID", "clone")
DEFAULT_VI_REF_AUDIO = os.getenv("DEFAULT_VI_REF_AUDIO", DEFAULT_REF_AUDIO_PATH)
DEFAULT_VI_VOICE_RATE = os.getenv("DEFAULT_VI_VOICE_RATE", "+0%")
DEFAULT_VI_VOICE_PITCH = os.getenv("DEFAULT_VI_VOICE_PITCH", "+0Hz")

# Centralized OmniVoice Voice Presets Registry
OMNIVOICE_PRESETS = {
    "andrew": {
        "id": "clone_andrew",
        "name": "Andrew - Smooth, Smart and Clear (US)",
        "language": "English",
        "gender": "male",
        "accent": "American",
        "ref_audio": ANDREW_DEFAULT_REF_AUDIO,
        "ref_text": "Hello there. If you stop and think about it, the world has a quiet way of surprising us when we least expect it.",
        "preview_audio": "/voices/andrew_preview_en.mp3",
    },
    "jessa": {
        "id": "clone_jessa",
        "name": "Jessa - Easygoing and Effortless",
        "language": "English",
        "gender": "female",
        "accent": "American",
        "ref_audio": DEFAULT_REF_AUDIO_PATH,
        "ref_text": "Okay, so it's been a really fascinating journey. It all started with this tiny idea my sister shared while we were biking.",
        "preview_audio": "/jessa - easygoing and effortless.mp3",
    }
}

# Flash-Forward Intro Policy: Disabled by default per user request (Cold Open / Direct Start)
ENABLE_FLASH_FORWARD_INTRO = os.getenv("ENABLE_FLASH_FORWARD_INTRO", "false").lower() in ("true", "1", "yes")

# Premise Pitch: 30-45s title-aligned cold open prepended to the first episode (replaces the
# template flash-forward). Enabled by default after the channel's 0:30-7:50 retention collapse.
ENABLE_PREMISE_PITCH = os.getenv("ENABLE_PREMISE_PITCH", "true").lower() in ("true", "1", "yes")
PREMISE_PITCH_IMAGE_COUNT = 8

# Outro: 20-25s closing appended after the last episode; its wording follows the comic's release
# status (continues / hiatus / finale / neutral), read in Stage 1 (outro_engine.py).
ENABLE_OUTRO = os.getenv("ENABLE_OUTRO", "true").lower() in ("true", "1", "yes")

# Frame episode panels without their speech bubbles when a crop keeps the faces and most of the art
# (bubble_crop.py); panels whose bubbles cannot be cut away stay whole. Text removal stays separate.
CROP_SPEECH_BUBBLES = os.getenv("CROP_SPEECH_BUBBLES", "true").lower() in ("true", "1", "yes")

# Seam bridge: rewrites the first lines of an episode narrated without the previous episode's ending
# (first episode of each parallel chunk) so back-to-back episodes flow (seam_bridge.py).
ENABLE_SEAM_BRIDGE = os.getenv("ENABLE_SEAM_BRIDGE", "true").lower() in ("true", "1", "yes")

# Universal Automation Defaults (Pacing, Auto Clean-Crop, On-Demand Text Removal)
DEFAULT_MIN_PANEL_DURATION = float(os.getenv("MIN_PANEL_DURATION", "3.5"))
DEFAULT_HARD_FLOOR_DURATION = float(os.getenv("HARD_FLOOR_DURATION", "3.0"))
DEFAULT_AUTO_TRIM_VOIDS = os.getenv("AUTO_TRIM_VOIDS", "true").lower() in ("true", "1", "yes")
DEFAULT_AUTO_REMOVE_TEXT = os.getenv("AUTO_REMOVE_TEXT", "false").lower() in ("true", "1", "yes")

# ─── Language-specific TTS defaults ────────────────────────────────────────
# US English (formerly markets/us_apocalypse/tts.py)
DEFAULT_EN_VOICE_ID    = os.getenv("DEFAULT_EN_VOICE_ID",    "clone_andrew")
DEFAULT_EN_VOICE_RATE  = os.getenv("DEFAULT_EN_VOICE_RATE",  "+0%")
DEFAULT_EN_VOICE_PITCH = os.getenv("DEFAULT_EN_VOICE_PITCH", "+0Hz")
PREFERRED_EN_FONTS = [
    "arialbd.ttf", "seguisb.ttf", "tahoma.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "C:\\Windows\\Fonts\\seguisb.ttf",
]

# Korean (formerly markets/korea_apocalypse/tts.py)
DEFAULT_KR_VOICE_ID    = os.getenv("DEFAULT_KR_VOICE_ID",    "ko-KR-InJoonNeural")
DEFAULT_KR_VOICE_RATE  = os.getenv("DEFAULT_KR_VOICE_RATE",  "+0%")
DEFAULT_KR_VOICE_PITCH = os.getenv("DEFAULT_KR_VOICE_PITCH", "+0Hz")

# Japanese (formerly markets/japan_isekai_territory/tts.py)
DEFAULT_JA_VOICE_ID    = os.getenv("DEFAULT_JA_VOICE_ID",    "ja-JP-KeitaNeural")
DEFAULT_JA_VOICE_RATE  = os.getenv("DEFAULT_JA_VOICE_RATE",  "+0%")
DEFAULT_JA_VOICE_PITCH = os.getenv("DEFAULT_JA_VOICE_PITCH", "+0Hz")

# Spanish / LATAM (market: LATAM Traición & Apocalipsis)
DEFAULT_ES_VOICE_ID    = os.getenv("DEFAULT_ES_VOICE_ID",    "es-MX-JorgeNeural")
DEFAULT_ES_VOICE_RATE  = os.getenv("DEFAULT_ES_VOICE_RATE",  "+10%")
DEFAULT_ES_VOICE_PITCH = os.getenv("DEFAULT_ES_VOICE_PITCH", "+0Hz")

# ─── Speech Bubble Overflow Crop (Stage 2b) ─────────────────────────────────
# Detect & crop speech bubbles that bleed past the panel edge.
# All values can be overridden per-run via task.payload with the same key names.
BUBBLE_OVERFLOW_CROP_ENABLED = os.getenv("BUBBLE_OVERFLOW_CROP", "true").lower() in ("true", "1", "yes")
BOC_MARGIN_PX         = int(os.getenv("BOC_MARGIN_PX",        "20"))   # px strip to scan near each edge
BOC_WHITE_THRESH      = int(os.getenv("BOC_WHITE_THRESH",     "230"))  # brightness >= this => white (bubble bg)
BOC_DARK_THRESH       = int(os.getenv("BOC_DARK_THRESH",      "30"))   # brightness <= this => dark bubble bg
BOC_DENSITY_THRESH    = float(os.getenv("BOC_DENSITY_THRESH", "0.40")) # fraction of white/dark to trigger overflow
BOC_CONTENT_THRESH    = float(os.getenv("BOC_CONTENT_THRESH", "0.15")) # fraction of mid-gray to mark as content
BOC_MIN_REMAIN_RATIO  = float(os.getenv("BOC_MIN_REMAIN_RATIO","0.20"))# min fraction of original dim to keep
BOC_MIN_REMAIN_PX     = int(os.getenv("BOC_MIN_REMAIN_PX",    "150"))  # absolute minimum px after crop
