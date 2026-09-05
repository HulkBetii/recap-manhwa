from __future__ import annotations

from typing import Optional
from markets.base_market import BaseMarketProfile
from markets.korea_apocalypse.prompt import get_korea_apocalypse_prompt
from markets.korea_apocalypse.tts import (
    DEFAULT_KR_VOICE_ID,
    DEFAULT_KR_VOICE_RATE,
    DEFAULT_KR_VOICE_PITCH,
    PREFERRED_KR_FONTS,
)
from markets.korea_apocalypse.metadata import generate_korea_apocalypse_metadata


class KoreaApocalypseMarket(BaseMarketProfile):
    def __init__(self):
        super().__init__(
            id="korea_apocalypse",
            name="Hàn Quốc: Sinh tồn · Tận thế (종말 · 생존 몰아보기)",
            description="Recap Webtoon dài tập tiếng Hàn ngách Tận thế / Sinh tồn / 각성 kịch tính, nhịp nhanh.",
            language="ko",
            default_voice_id=DEFAULT_KR_VOICE_ID,
            voice_rate=DEFAULT_KR_VOICE_RATE,
            voice_pitch=DEFAULT_KR_VOICE_PITCH,
            preferred_fonts=PREFERRED_KR_FONTS,
        )

    def get_gemini_prompt(
        self,
        comic_title: str,
        ep: int,
        total_pages: int,
        glossary: Optional[str] = None,
    ) -> str:
        return get_korea_apocalypse_prompt(comic_title, ep, total_pages, glossary)

    def generate_youtube_metadata(
        self,
        comic_title: str,
        from_ep: int,
        to_ep: int,
    ) -> dict:
        return generate_korea_apocalypse_metadata(comic_title, from_ep, to_ep)


KOREA_APOCALYPSE_MARKET = KoreaApocalypseMarket()
