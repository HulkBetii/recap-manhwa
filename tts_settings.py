from __future__ import annotations

import os


DEFAULT_AI33PRO_VOICE_ID = "elevenlabs_tnSpp4vdxKPjI9w0GnoV"
AI33PRO_VOICE_PREFIXES = (
    "elevenlabs_",
    "minimax_",
    "clone_",
    "edge_",
    "kokoro_",
    "vbee_",
    "fishaudio_",
)


def get_ai33pro_voice_id() -> str:
    return os.getenv("AI33PRO_VOICE_ID", DEFAULT_AI33PRO_VOICE_ID).strip() or DEFAULT_AI33PRO_VOICE_ID


def uses_ai33pro(voice_id: str | None) -> bool:
    value = (voice_id or "").strip()
    return value == "ai33pro" or value.startswith(AI33PRO_VOICE_PREFIXES)


def normalize_tts_voice_mode(voice_id: str | None, *, default: str = "ai33pro") -> str:
    value = (voice_id or "").strip() or default
    return "ai33pro" if uses_ai33pro(value) else value
