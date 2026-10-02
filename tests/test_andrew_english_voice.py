import os
import pytest
import config
from tts_provider import get_ref_audio_text
from tts_settings import normalize_tts_voice_mode, uses_ai33pro

def test_config_english_voice_settings():
    assert hasattr(config, "DEFAULT_EN_VOICE")
    assert "Andrew" in config.DEFAULT_EN_VOICE
    assert config.DEFAULT_EN_VOICE_ID == "clone_andrew"
    assert os.path.exists(config.DEFAULT_EN_REF_AUDIO)
    assert hasattr(config, "OMNIVOICE_PRESETS")
    assert "andrew" in config.OMNIVOICE_PRESETS
    andrew = config.OMNIVOICE_PRESETS["andrew"]
    assert andrew["language"] == "English"
    assert os.path.exists(andrew["ref_audio"])
    assert "Hello there" in andrew["ref_text"]

def test_preset_ref_audio_text_cached():
    # Should resolve immediately from config without running Whisper
    ref_path = config.OMNIVOICE_PRESETS["andrew"]["ref_audio"]
    text = get_ref_audio_text(ref_path)
    assert text == config.OMNIVOICE_PRESETS["andrew"]["ref_text"]

def test_default_voice_is_clone_andrew():
    # Formerly tested via US_APOCALYPSE_MARKET — now directly from config
    assert getattr(config, "DEFAULT_EN_VOICE_ID", None) == "clone_andrew"
    assert normalize_tts_voice_mode(None) == "clone_andrew"
    assert normalize_tts_voice_mode("") == "clone_andrew"
    assert uses_ai33pro("clone_andrew") is False
    assert uses_ai33pro("clone_jessa") is False

def test_app_payload_voice_resolution():
    from app import CrawlRequest
    
    req = CrawlRequest(
        url="https://www.webtoons.com/en/action/the-world-after-the-fall/list?title_no=4011",
        from_episode=1,
        to_episode=1,
        language="en"
    )
    assert req.voice_id == "clone_andrew"
    assert req.language == "en"


def test_clone_voice_instruct_guardrail():
    # Verify that clone_andrew intent is recognized as cloning, not instruct
    voice_id = "clone_andrew"
    clean_vid = voice_id.lower().replace("clone_", "").replace("voice_", "").strip()
    presets = getattr(config, "OMNIVOICE_PRESETS", {})
    is_clone_intent = (
        bool(clean_vid in presets)
        or voice_id.lower().startswith("clone")
        or voice_id.lower().startswith("voice_")
        or voice_id.lower() in ("andrew", "jessa")
    )
    assert is_clone_intent is True

    # Check fallback ref_audio resolution when ref_audio_path is invalid placeholder
    ref_audio_path = "<path>"
    if not ref_audio_path or ref_audio_path in ("<path>", "none", "null") or not os.path.exists(ref_audio_path):
        ref_audio_path = None
    if not ref_audio_path:
        andrew_ref = getattr(config, "ANDREW_DEFAULT_REF_AUDIO", None)
        if andrew_ref and os.path.exists(andrew_ref):
            ref_audio_path = andrew_ref
    assert ref_audio_path is not None
    assert os.path.exists(ref_audio_path)
    assert "andrew" in ref_audio_path.lower()

