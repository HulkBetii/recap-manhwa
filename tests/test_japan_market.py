import pytest
from fastapi.testclient import TestClient
import markets
from markets.base_market import BaseMarketProfile
from markets.japan_isekai_territory import JapanIsekaiTerritoryMarket, JAPAN_ISEKAI_TERRITORY_MARKET
from app import app, generate_gemini_prompt


def test_japan_market_registration():
    market = markets.get_market("japan_isekai_territory")
    assert market is not None
    assert isinstance(market, JapanIsekaiTerritoryMarket)
    assert market.id == "japan_isekai_territory"
    assert market.language == "ja"
    assert "KeitaNeural" in market.default_voice_id
    assert market.voice_rate == "+8%"
    assert market.voice_pitch == "-1Hz"

    all_markets = markets.list_markets()
    ids = [m["id"] for m in all_markets]
    assert "japan_isekai_territory" in ids


def test_japan_isekai_prompt_generation_ep1():
    market = markets.get_market("japan_isekai_territory")
    prompt = market.get_gemini_prompt("追放された領主", ep=1, total_pages=30)
    
    assert "EPISODE 1 HIGH-RETENTION HOOK" in prompt
    assert "異世界転生 × 領地経営 × 成り上がり" in prompt
    assert "追放" in prompt
    assert "現代知識" in prompt
    assert "です・ます調" in prompt
    assert "<ページ番号> - <日本語ナレーション文章>.#" in prompt
    assert "追放された領主" in prompt


def test_japan_isekai_prompt_generation_ep2():
    market = markets.get_market("japan_isekai_territory")
    prompt = market.get_gemini_prompt("追放された領主", ep=2, total_pages=30)
    
    assert "EPISODE CONTINUATION" in prompt
    assert "EPISODE 1 HIGH-RETENTION HOOK" not in prompt
    assert "クリフハンガー" in prompt


def test_japan_isekai_metadata_generation():
    market = markets.get_market("japan_isekai_territory")
    meta = market.generate_youtube_metadata("追放された領主", 1, 40)
    
    assert "title" in meta
    assert "【異世界漫画】" in meta["title"]
    assert "1話~40話" in meta["title"]
    assert "description" in meta
    assert "#異世界漫画" in meta["description"]
    assert "#領地経営" in meta["description"]
    assert "tags" in meta
    assert "異世界漫画" in meta["tags"]
    assert "領地経営" in meta["tags"]
    assert "ざまぁ" in meta["tags"]


def test_generate_gemini_prompt_delegation_japan():
    p_ja = generate_gemini_prompt("Isekai Lord", 1, 20, market_id="japan_isekai_territory")
    assert "異世界転生 × 領地経営 × 成り上がり" in p_ja
    assert "EPISODE 1 HIGH-RETENTION HOOK" in p_ja


def test_api_markets_endpoint_includes_japan():
    with TestClient(app, base_url="http://127.0.0.1") as client:
        home = client.get("/")
        assert home.status_code == 200
        
        response = client.get("/api/markets")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        ids = [item["id"] for item in data]
        assert "japan_isekai_territory" in ids
