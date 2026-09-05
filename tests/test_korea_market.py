import pytest
from fastapi.testclient import TestClient
import markets
from markets.base_market import BaseMarketProfile
from markets.korea_apocalypse import KoreaApocalypseMarket, KOREA_APOCALYPSE_MARKET
from app import app, generate_gemini_prompt


def test_korea_market_registration():
    market = markets.get_market("korea_apocalypse")
    assert market is not None
    assert isinstance(market, KoreaApocalypseMarket)
    assert market.id == "korea_apocalypse"
    assert market.language == "ko"
    assert "InJoonNeural" in market.default_voice_id
    assert market.voice_rate == "+12%"
    assert market.voice_pitch == "-2Hz"

    all_markets = markets.list_markets()
    ids = [m["id"] for m in all_markets]
    assert "korea_apocalypse" in ids


def test_korea_apocalypse_prompt_generation_ep1():
    market = markets.get_market("korea_apocalypse")
    prompt = market.get_gemini_prompt("멸망한 세계", ep=1, total_pages=25)
    
    assert "EPISODE 1 HIGH-RETENTION HOOK" in prompt
    assert "종말 · 아포칼립스 · 생존" in prompt
    assert "~하는데요" in prompt
    assert "~하게 됩니다" in prompt
    assert "<페이지번호> - <한국어 나레이션 문장>.#" in prompt
    assert "멸망한 세계" in prompt


def test_korea_apocalypse_prompt_generation_ep2():
    market = markets.get_market("korea_apocalypse")
    prompt = market.get_gemini_prompt("멸망한 세계", ep=2, total_pages=25)
    
    assert "EPISODE CONTINUATION" in prompt
    assert "EPISODE 1 HIGH-RETENTION HOOK" not in prompt
    assert "클리프행어" in prompt


def test_korea_apocalypse_metadata_generation():
    market = markets.get_market("korea_apocalypse")
    meta = market.generate_youtube_metadata("멸망한 세계", 1, 20)
    
    assert "title" in meta
    assert "[웹툰 몰아보기]" in meta["title"]
    assert "1화~20화" in meta["title"]
    assert "description" in meta
    assert "#웹툰몰아보기" in meta["description"]
    assert "tags" in meta
    assert "아포칼립스웹툰" in meta["tags"]
    assert "생존웹툰" in meta["tags"]


def test_generate_gemini_prompt_delegation():
    # Without market_id (default behavior)
    p_default = generate_gemini_prompt("Default Comic", 1, 20, target_language="en")
    assert "ROLE:" in p_default
    assert "English" in p_default

    # With korea_apocalypse market_id
    p_kr = generate_gemini_prompt("Default Comic", 1, 20, market_id="korea_apocalypse")
    assert "종말 · 아포칼립스 · 생존" in p_kr
    assert "~하는데요" in p_kr


def test_api_markets_endpoint():
    with TestClient(app, base_url="http://127.0.0.1") as client:
        # Establish authenticated session
        home = client.get("/")
        assert home.status_code == 200
        
        response = client.get("/api/markets")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        ids = [item["id"] for item in data]
        assert "korea_apocalypse" in ids
