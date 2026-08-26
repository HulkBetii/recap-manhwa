import json
import inspect
from types import SimpleNamespace

from artifact_cache import EpisodeStageCache, source_hash, stage_fingerprint, validate_mp4_file
from workflow_stages_1 import Stage5_GeminiAutomation


def task(url="https://example.com/story", **config):
    payload = {
        "language": "en",
        "voice_id": "voice-a",
        "logo_path": None,
        "overlay_path": None,
        "remove_text": True,
        "remove_text_conf": 0.3,
        "remove_text_radius": 3,
        "fps": 30,
        "vlm_provider": "gemini",
    }
    payload.update(config)
    return SimpleNamespace(comic_url=url, payload=payload)


def write(path, content=b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def valid_mp4_bytes():
    return b"\x00\x00\x00\x18ftypisom" + b"video-data" + b"moov"


def test_gemini_cache_is_checked_before_browser_initialization():
    source = inspect.getsource(Stage5_GeminiAutomation.execute)
    cache_check = source.index("cache.is_current")
    browser_initialization = source.index("get_local_context()", cache_check)
    assert cache_check < browser_initialization
    assert "force_check=True" not in source


def test_source_hash_changes_and_legacy_outputs_are_not_reused(tmp_path):
    assert source_hash("https://example.com/a") != source_hash("https://example.com/b")
    episode_dir = tmp_path / "legacy" / "episode_1"
    images = episode_dir / "images"
    write(images / "001.jpg")
    cache = EpisodeStageCache(episode_dir)
    fingerprint = stage_fingerprint(task(), "image_crawl", 1)
    assert not cache.is_current(stage="image_crawl", fingerprint=fingerprint, outputs=[images])
    assert not images.exists()


def test_source_or_prompt_change_invalidates_gemini_and_downstream_only(tmp_path):
    episode_dir = tmp_path / "episode_1"
    pdf = write(episode_dir / "pdf" / "chapter.pdf", b"%PDF-valid")
    raw = write(episode_dir / "raw_gemini_response.txt")
    recap = write(episode_dir / "recap.json")
    narration = write(episode_dir / "narration.txt")
    audio = write(episode_dir / "audio.mp3")
    video = write(episode_dir / "video.mp4", valid_mp4_bytes())
    original = task()
    cache = EpisodeStageCache(episode_dir)
    fingerprint = stage_fingerprint(original, "gemini", 1, input_paths=[pdf], extra="prompt-a")
    cache.commit(stage="gemini", fingerprint=fingerprint, outputs=[raw, recap])

    changed = task(url="https://example.com/other")
    changed_fingerprint = stage_fingerprint(changed, "gemini", 1, input_paths=[pdf], extra="prompt-b")
    assert not cache.is_current(stage="gemini", fingerprint=changed_fingerprint, outputs=[raw, recap])
    assert pdf.exists()
    assert not raw.exists()
    assert not recap.exists()
    assert not narration.exists()
    assert not audio.exists()
    assert not video.exists()


def test_env_voice_change_invalidates_tts_and_video_but_preserves_narration(tmp_path, monkeypatch):
    episode_dir = tmp_path / "episode_1"
    narration = write(episode_dir / "narration.txt")
    audio = write(episode_dir / "audio.mp3")
    srt = write(episode_dir / "transcript.srt", b"1\n00:00:00,000 --> 00:00:01,000\nTest\n")
    config = write(episode_dir / "tts_config.json")
    video = write(episode_dir / "video.mp4", valid_mp4_bytes())
    monkeypatch.setenv("AI33PRO_VOICE_ID", "elevenlabs_voice_a")
    original = task(voice_id="ai33pro")
    cache = EpisodeStageCache(episode_dir)
    fingerprint = stage_fingerprint(original, "tts", 1, input_paths=[narration])
    cache.commit(stage="tts", fingerprint=fingerprint, outputs=[audio, config])

    monkeypatch.setenv("AI33PRO_VOICE_ID", "elevenlabs_voice_b")
    changed = task(voice_id="ai33pro")
    changed_fingerprint = stage_fingerprint(changed, "tts", 1, input_paths=[narration])
    assert not cache.is_current(stage="tts", fingerprint=changed_fingerprint, outputs=[audio, config])
    assert narration.exists()
    assert not audio.exists()
    assert not srt.exists()
    assert not video.exists()


def test_manifest_uses_relative_outputs_and_safe_stage_metadata(tmp_path):
    episode_dir = tmp_path / "episode_1"
    narration = write(episode_dir / "narration.txt")
    audio = write(episode_dir / "audio.mp3")
    config = write(episode_dir / "tts_config.json")
    current_task = task(voice_id="ai33pro")
    fingerprint = stage_fingerprint(current_task, "tts", 1, input_paths=[narration])
    cache = EpisodeStageCache(episode_dir)
    cache.commit(stage="tts", fingerprint=fingerprint, outputs=[audio, config])

    manifest = cache.data["stages"]["tts"]
    assert set(manifest["outputs"]) == {"audio.mp3", "tts_config.json"}
    assert manifest["source_identity"]["episode"] == 1
    assert manifest["source_identity"]["source_hash"]
    assert manifest["input_fingerprint"]
    assert manifest["config"]["voice_id"] == "ai33pro"
    assert "elevenlabs_" not in json.dumps(manifest)


def test_logo_content_change_invalidates_video_only(tmp_path):
    episode_dir = tmp_path / "episode_1"
    audio = write(episode_dir / "audio.mp3")
    logo = write(tmp_path / "logo.png", b"one")
    video = write(episode_dir / "video.mp4", valid_mp4_bytes())
    current_task = task(logo_path=str(logo))
    cache = EpisodeStageCache(episode_dir)
    fingerprint = stage_fingerprint(current_task, "video", 1, input_paths=[audio, logo])
    cache.commit(stage="video", fingerprint=fingerprint, outputs=[video])

    logo.write_bytes(b"two")
    changed_fingerprint = stage_fingerprint(current_task, "video", 1, input_paths=[audio, logo])
    assert not cache.is_current(stage="video", fingerprint=changed_fingerprint, outputs=[video])
    assert audio.exists()
    assert not video.exists()


def test_partial_mp4_is_not_valid_or_cached(tmp_path):
    episode_dir = tmp_path / "episode_1"
    video = write(episode_dir / "video.mp4", valid_mp4_bytes())
    cache = EpisodeStageCache(episode_dir)
    fingerprint = stage_fingerprint(task(), "video", 1)
    cache.commit(stage="video", fingerprint=fingerprint, outputs=[video])
    video.write_bytes(b"partial")

    assert not validate_mp4_file(video)
    assert not cache.is_current(
        stage="video",
        fingerprint=fingerprint,
        outputs=[video],
        validate=lambda: validate_mp4_file(video),
    )
    assert not video.exists()
