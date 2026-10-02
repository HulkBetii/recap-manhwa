import wave

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


def test_version_endpoint_does_not_crash():
    from app import app

    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.get("/")  # establishes the session cookie, like the UI
        res = client.get("/api/version")
    assert res.status_code == 200
    assert res.json()["app"]
