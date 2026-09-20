import os
import pytest
from fastapi.testclient import TestClient
import markets
from markets.base_market import BaseMarketProfile
from markets.us_apocalypse import USApocalypseMarket, US_APOCALYPSE_MARKET
from app import app, generate_gemini_prompt
from security_utils import PUBLIC_ARTIFACT_KEYS


def test_us_market_registration():
    market = markets.get_market("us_apocalypse")
    assert market is not None
    assert isinstance(market, USApocalypseMarket)
    assert market.id == "us_apocalypse"
    assert market.language == "en"
    assert market.default_voice_id == "clone_andrew"
    assert market.voice_rate == "+0%"
    assert market.voice_pitch == "+0Hz"

    all_markets = markets.list_markets()
    ids = [m["id"] for m in all_markets]
    assert "us_apocalypse" in ids


def test_us_apocalypse_prompt_generation_ep1():
    market = markets.get_market("us_apocalypse")
    prompt = market.get_gemini_prompt("Veteran of the Apocalypse", ep=1, total_pages=30)

    # Pillar 1 Cold Open Hook
    assert "EPISODE 1 HIGH-RETENTION HOOK" in prompt
    assert "0-15s GOLDEN HOOK RULE" in prompt
    # New 5 Golden Rules architecture
    assert "5 GOLDEN RULES" in prompt
    assert "PERSONALITY FIRST" in prompt
    assert "RHYTHM VARIATION" in prompt
    assert "NEVER start with greetings" in prompt
    # Pillar 1 Safety Filter
    assert "YOUTUBE SAFETY" in prompt or "YouTube Monetization" in prompt or "YOUTUBE" in prompt
    assert "Veteran of the Apocalypse" in prompt
    assert "<page_number> - <English narration sentence>.#" in prompt
    # Visual Panel Selection & Anti-Filler Filter
    assert "POINT SCORE HARD REQUIREMENT" in prompt
    assert "Point >= 65" in prompt
    assert "FORBIDDEN PAGES" in prompt
    assert "LEVEL A" in prompt



def test_us_apocalypse_prompt_generation_ep2():
    market = markets.get_market("us_apocalypse")
    prompt = market.get_gemini_prompt("Veteran of the Apocalypse", ep=2, total_pages=30)

    assert "EPISODE CONTINUATION" in prompt
    assert "EPISODE 1 HIGH-RETENTION HOOK" not in prompt
    assert "Start immediately in media res" in prompt


def test_us_apocalypse_metadata_generation():
    market = markets.get_market("us_apocalypse")
    chapters = [
        {"episode": 1, "timestamp": "00:00", "title": "Episode 1"},
        {"episode": 2, "timestamp": "12:35", "title": "Episode 2"},
    ]
    meta = market.generate_youtube_metadata("Veteran of the Apocalypse", 1, 2, chapters=chapters)

    # Core fields
    assert "title" in meta
    assert "title_options" in meta
    assert len(meta["title_options"]) >= 4
    assert "description" in meta

    # Timestamps use em-dash format
    assert "00:00" in meta["description"]

    # Creation statement replaces Section 107 disclaimer (research-driven)
    assert "original scripted narration" in meta["description"]
    assert "Copyright Disclaimer" not in meta["description"]

    # Tags: radical simplification (5-8 tags, YouTube says tags are minimal)
    assert "tags" in meta
    assert "apocalypse manhwa" in meta["tags"] or "survival manhwa" in meta["tags"]
    assert "veteran of the apocalypse" in meta["tags"]
    assert len(meta["tags"]) <= 8

    # New research-driven fields
    assert "engagement_question" in meta
    assert len(meta["engagement_question"]) > 10
    assert "survival_dashboard" in meta
    assert "day_number" in meta["survival_dashboard"]
    assert "food_reserve_pct" in meta["survival_dashboard"]
    assert "thumbnail_concepts" in meta
    assert len(meta["thumbnail_concepts"]) >= 2
    assert "pinned_comment" in meta
    assert "STORY PROGRESSION" not in meta["pinned_comment"]
    assert "• 00:00 —" not in meta["pinned_comment"]
    assert "STATUS" in meta["pinned_comment"]
    assert meta["engagement_question"] in meta["pinned_comment"]
    assert "formatted_kit" in meta

    # Title length: research target 80-95 chars (hard max 100)
    for t in meta["title_options"]:
        assert len(t) <= 100, f"Title exceeds 100 chars: {t} ({len(t)} chars)"


def test_us_apocalypse_prompt_delegation():
    p_us = generate_gemini_prompt("Veteran of the Apocalypse", 1, 30, market_id="us_apocalypse")
    assert "EPISODE 1 HIGH-RETENTION HOOK" in p_us
    assert "5 GOLDEN RULES" in p_us
    assert "PERSONALITY FIRST" in p_us



def test_public_artifacts_keys():
    assert "youtube_upload_kit_url" in PUBLIC_ARTIFACT_KEYS
    assert "chapters" in PUBLIC_ARTIFACT_KEYS
