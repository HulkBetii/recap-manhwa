import os
import torch

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

# Default reference audio for OmniVoice voice cloning (Vietnamese & General default)
USER_DEFAULT_REF_AUDIO = r"C:\Users\HulkBeoti\Downloads\jessa - easygoing and effortless.mp3"
STATIC_DEFAULT_REF_AUDIO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "jessa - easygoing and effortless.mp3")
DEFAULT_REF_AUDIO_PATH = os.getenv(
    "DEFAULT_REF_AUDIO_PATH",
    USER_DEFAULT_REF_AUDIO if os.path.exists(USER_DEFAULT_REF_AUDIO) else STATIC_DEFAULT_REF_AUDIO
)

# Default Vietnamese TTS Voice Configuration (OmniVoice Voice Cloning: Jessa - Easygoing and Effortless)
DEFAULT_VI_VOICE = os.getenv("DEFAULT_VI_VOICE", "jessa - easygoing and effortless")
DEFAULT_VI_VOICE_ID = os.getenv("DEFAULT_VI_VOICE_ID", "clone")
DEFAULT_VI_REF_AUDIO = os.getenv("DEFAULT_VI_REF_AUDIO", DEFAULT_REF_AUDIO_PATH)
DEFAULT_VI_VOICE_RATE = os.getenv("DEFAULT_VI_VOICE_RATE", "+0%")
DEFAULT_VI_VOICE_PITCH = os.getenv("DEFAULT_VI_VOICE_PITCH", "+0Hz")

# Flash-Forward Intro Policy: Disabled by default per user request (Cold Open / Direct Start)
ENABLE_FLASH_FORWARD_INTRO = os.getenv("ENABLE_FLASH_FORWARD_INTRO", "false").lower() in ("true", "1", "yes")



