import asyncio

import pytest
from pydantic import ValidationError

import app as app_module
from app import CrawlRequest

# Mirrors the JSON body built by static/app.js startCrawl().
UI_BODY = {
    "url": "https://www.webtoons.com/en/action/veteran-of-the-apocalypse/list?title_no=9675",
    "from_episode": 1,
    "to_episode": 3,
    "safe_mode": False,
    "nsfw_threshold": 0.3,
    "nsfw_mode": "mask",
    "timeout": 160,
    "retry_count": 5,
    "concurrency": 2,
    "image_quality": 20,
    "pdf_quality": 20,
    "language": "en",
    "vlm_provider": "gemini",
    "voice_id": "clone_andrew",
    "ref_audio_path": None,
    "logo_path": None,
    "overlay_path": None,
    "burn_subtitles": False,
    "remove_text": True,
    "remove_text_conf": 0.3,
    "remove_text_radius": 3,
    "comix_group_id": None,
    "market_id": None,
    "enable_flash_forward_intro": False,
    "enable_premise_pitch": True,
    "protagonist_name": None,
    "playlist_url": None,
}


def test_ui_body_is_accepted():
    """Regression: market_id from the UI used to make every crawl request fail with 422."""
    CrawlRequest(**UI_BODY)


def test_blank_strings_become_none_and_bad_urls_are_rejected():
    req = CrawlRequest(**{**UI_BODY, "protagonist_name": "  ", "playlist_url": ""})
    assert req.protagonist_name is None and req.playlist_url is None
    with pytest.raises(ValidationError):
        CrawlRequest(**{**UI_BODY, "playlist_url": "javascript:alert(1)"})


def test_crawl_forwards_new_options_to_the_workflow(monkeypatch):
    captured = {}

    async def fake_queue_task(title, url, from_ep, to_ep, config):
        captured.update(config)
        return "task-1"

    async def fake_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(app_module.workflow_manager, "queue_task", fake_queue_task)
    monkeypatch.setattr(app_module.sse_logger, "log", fake_log)

    body = {
        **UI_BODY,
        "market_id": "us_apocalypse",
        "protagonist_name": "Kang Seongho",
        "enable_premise_pitch": False,
        "enable_outro": False,
        "regenerate_drafts": True,
        "playlist_url": "https://www.youtube.com/playlist?list=PLabc",
    }
    result = asyncio.run(app_module.crawl(CrawlRequest(**body)))

    assert result["task_id"] == "task-1"
    assert captured["market_id"] == "us_apocalypse"
    assert captured["protagonist_name"] == "Kang Seongho"
    assert captured["enable_premise_pitch"] is False
    assert captured["enable_outro"] is False
    assert captured["regenerate_drafts"] is True
    assert captured["playlist_url"] == "https://www.youtube.com/playlist?list=PLabc"


def test_remove_text_defaults_to_false():
    req = CrawlRequest(url="https://example.com/comic/list?title_no=123", from_episode=1, to_episode=1)
    assert req.remove_text is False


def test_outro_defaults_to_on():
    req = CrawlRequest(url="https://example.com/comic/list?title_no=123", from_episode=1, to_episode=1)
    assert req.enable_outro is True
    assert req.regenerate_drafts is False

