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
