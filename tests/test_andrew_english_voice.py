import os
import pytest
import config
from tts_provider import get_ref_audio_text
from markets.us_apocalypse import US_APOCALYPSE_MARKET
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

def test_us_market_default_voice_is_clone_andrew():
    assert US_APOCALYPSE_MARKET.default_voice_id == "clone_andrew"
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
