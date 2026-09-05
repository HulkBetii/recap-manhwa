from __future__ import annotations

from typing import Optional
from markets.base_market import BaseMarketProfile
from markets.japan_isekai_territory.prompt import get_japan_isekai_prompt
from markets.japan_isekai_territory.tts import (
    DEFAULT_JA_VOICE_ID,
    DEFAULT_JA_VOICE_RATE,
    DEFAULT_JA_VOICE_PITCH,
    PREFERRED_JA_FONTS,
)
from markets.japan_isekai_territory.metadata import generate_japan_isekai_metadata


class JapanIsekaiTerritoryMarket(BaseMarketProfile):
    def __init__(self):
        super().__init__(
            id="japan_isekai_territory",
            name="Nhật Bản: 異世界転生 × 領地経営 × 成り上がり",
            description="Recap Manga/Webtoon dài tập tiếng Nhật ngách Isekai Reincarnation, Territory Building & Rise to Power (Chuyển sinh, Khai hoang lãnh địa, Bá chủ).",
            language="ja",
            default_voice_id=DEFAULT_JA_VOICE_ID,
            voice_rate=DEFAULT_JA_VOICE_RATE,
            voice_pitch=DEFAULT_JA_VOICE_PITCH,
            preferred_fonts=PREFERRED_JA_FONTS,
        )

    def get_gemini_prompt(
        self,
        comic_title: str,
        ep: int,
        total_pages: int,
        glossary: Optional[str] = None,
    ) -> str:
        return get_japan_isekai_prompt(comic_title, ep, total_pages, glossary)

    def generate_youtube_metadata(
        self,
        comic_title: str,
        from_ep: int,
        to_ep: int,
    ) -> dict:
        return generate_japan_isekai_metadata(comic_title, from_ep, to_ep)


JAPAN_ISEKAI_TERRITORY_MARKET = JapanIsekaiTerritoryMarket()
