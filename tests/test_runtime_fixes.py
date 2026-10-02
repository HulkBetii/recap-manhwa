import asyncio
import wave

import pytest
from fastapi.testclient import TestClient


def test_media_duration_without_ffprobe(tmp_path):
    """The ref-audio trim guard used `ffprobe` and `json` (never imported): it never ran."""
    from tts_provider import _media_duration_seconds

    path = tmp_path / "ref.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000 * 3)  # 3 seconds of silence
    assert abs(_media_duration_seconds(str(path)) - 3.0) < 0.05


@pytest.mark.parametrize("voice_id, expected", [
    ("ko-KR-InJoonNeural", "ko-KR-InJoonNeural"),        # config DEFAULT_KR_VOICE_ID (bare name)
    ("edge-tts_ja-JP-KeitaNeural", "ja-JP-KeitaNeural"),  # UI preset form
])
def test_edge_voice_names_never_reach_omnivoice(monkeypatch, tmp_path, voice_id, expected):
    """A bare EdgeTTS name used to fall through to OmniVoice and fail Stage 8 for Korean comics."""
    import tts_provider

    calls = []

    async def fake_edge(text, audio, srt, voice_name="en-US-ChristopherNeural", rate="+0%", pitch="+0Hz"):
        calls.append(voice_name)
        return True

    def no_omnivoice():
        raise AssertionError("OmniVoice must not be used for an EdgeTTS voice")

    monkeypatch.setattr(tts_provider, "generate_edge_tts", fake_edge)
    monkeypatch.setattr(tts_provider, "get_omnivoice_model", no_omnivoice)
    ok = asyncio.run(tts_provider.generate_tts("안녕하세요.", str(tmp_path / "a.mp3"), str(tmp_path / "a.srt"), voice_id=voice_id))
    assert ok and calls == [expected]


def test_version_endpoint_does_not_crash():
    from app import app

    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.get("/")  # establishes the session cookie, like the UI
        res = client.get("/api/version")
    assert res.status_code == 200
    assert res.json()["app"]
