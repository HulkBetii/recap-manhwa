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
    assert "Badass Survivor Voice" in prompt
    assert "NEVER start with greetings" in prompt
    # Pillar 1 Safety Filter
    assert "YouTube Monetization & Advertiser Safety" in prompt
    assert "Veteran of the Apocalypse" in prompt
    assert "<page_number> - <English narration sentence>.#" in prompt
    # Visual Panel Selection & Anti-Filler Filter
    assert "POINT SCORE HARD REQUIREMENT" in prompt
    assert f"Point >= {market.point_score_threshold}" in prompt
    assert "FORBIDDEN PAGES" in prompt
    assert "LEVEL A — DIRECT VISUAL" in prompt


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

    assert "title" in meta
    assert "title_options" in meta
    assert len(meta["title_options"]) >= 4
    assert "description" in meta
    assert "00:00 - Episode 1" in meta["description"]
    assert "12:35 - Episode 2" in meta["description"]
    assert "Copyright Disclaimer" in meta["description"]
    assert "tags" in meta
    assert "apocalypse manhwa" in meta["tags"]
    assert "veteran of the apocalypse" in meta["tags"]


def test_us_apocalypse_prompt_delegation():
    p_us = generate_gemini_prompt("Veteran of the Apocalypse", 1, 30, market_id="us_apocalypse")
    assert "EPISODE 1 HIGH-RETENTION HOOK" in p_us
    assert "Badass Survivor Voice" in p_us


def test_bgm_assets_exist():
    bgm_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "bgm", "apocalypse")
    assert os.path.isdir(bgm_dir), f"BGM dir missing: {bgm_dir}"
    files = os.listdir(bgm_dir)
    assert "01_dark_wasteland_ambient.mp3" in files
    assert "02_apocalypse_crisis_tension.mp3" in files
    assert "03_survival_action_comeback.mp3" in files
    for fname in ["01_dark_wasteland_ambient.mp3", "02_apocalypse_crisis_tension.mp3", "03_survival_action_comeback.mp3"]:
        fpath = os.path.join(bgm_dir, fname)
        assert os.path.getsize(fpath) > 10000, f"BGM file {fname} is too small"


def test_public_artifacts_keys():
    assert "youtube_upload_kit_url" in PUBLIC_ARTIFACT_KEYS
    assert "chapters" in PUBLIC_ARTIFACT_KEYS


def test_thumbnail_prompt_6_layers_gpt():
    market = markets.get_market("us_apocalypse")
    meta = market.generate_youtube_metadata("Ultimate Shut-in", 1, 85)

    assert "thumbnail_concepts" in meta
    concepts = meta["thumbnail_concepts"]
    assert len(concepts) == 5

    concept_ids = [c["id"] for c in concepts]
    assert "concept_sovereign_climax" in concept_ids
    assert "concept_intimate_proximity" in concept_ids
    assert "concept_enemy_humiliation" in concept_ids
    assert "concept_resource_contrast" in concept_ids
    assert "concept_system_defiance" in concept_ids

    for concept in concepts:
        assert "prompt" in concept
        assert "gpt_prompt" in concept
        assert "name" in concept
        assert "thumbnail_text" in concept
        assert "text_overlay" in concept
        assert "text_style" in concept
        assert "characters" in concept
        assert len(concept["characters"]) >= 2

        prompt = concept["prompt"]
        # Verify mandatory 6-Layer GPT Image Prompt structure
        assert "[IMAGE MEDIUM, ART STYLE & ASPECT RATIO]" in prompt
        assert "[CHARACTER REFERENCES & SUBJECT ANCHORS]" in prompt
        assert "[SPATIAL COMPOSITION & CAMERA FRAMING]" in prompt
        assert "[SCENE ENVIRONMENT, 2.5D LIGHTING & COLOR PALETTE]" in prompt
        assert "[YOUTUBE CLICKBAIT GRAPHIC DESIGN & TYPOGRAPHY OVERLAYS]" in prompt
        assert "[TECHNICAL QUALITY & ANATOMY GUARDRAILS]" in prompt

        # Verify manhwa 2.5D visual aesthetic
        assert "Modern Korean Webtoon (Manhwa 2.5D)" in prompt
        assert "Redice Studio" in prompt

        # Verify clickbait text overlay is present
        assert len(concept["text_overlay"]) > 0


