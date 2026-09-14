import os
import torch

APP_NAME = "Recap Comics Automation"
APP_VERSION = "1.5.0"

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




