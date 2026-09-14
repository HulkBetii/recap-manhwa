from __future__ import annotations

from typing import Optional
from markets.base_market import BaseMarketProfile
from markets.us_apocalypse.prompt import get_us_apocalypse_prompt
from markets.us_apocalypse.tts import (
    DEFAULT_US_VOICE_ID,
    DEFAULT_US_VOICE_RATE,
    DEFAULT_US_VOICE_PITCH,
    PREFERRED_US_FONTS,
)
from markets.us_apocalypse.metadata import generate_us_apocalypse_metadata


class USApocalypseMarket(BaseMarketProfile):
    def __init__(self):
        super().__init__(
            id="us_apocalypse",
            name="US: Apocalypse & Prepper Survival (Doomsday Manhwa Recap)",
            description="US YouTube Manhwa Recap market profile tailored for Apocalypse, Bunker Prepper, Ice Age, and Survival genres with Cold Open Hooks and Badass pacing.",
            language="en",
            default_voice_id=DEFAULT_US_VOICE_ID,
            voice_rate=DEFAULT_US_VOICE_RATE,
            voice_pitch=DEFAULT_US_VOICE_PITCH,
            preferred_fonts=PREFERRED_US_FONTS,
        )

    def get_gemini_prompt(
        self,
        comic_title: str,
        ep: int,
        total_pages: int,
        glossary: Optional[str] = None,
        previous_context: Optional[dict] = None,
    ) -> str:
        return get_us_apocalypse_prompt(
            comic_title, ep, total_pages, glossary,
            point_score_threshold=self.point_score_threshold,
            previous_context=previous_context,
        )

    def generate_youtube_metadata(
        self,
        comic_title: str,
        from_ep: int,
        to_ep: int,
        chapters: Optional[list] = None,
        **kwargs,
    ) -> dict:
        return generate_us_apocalypse_metadata(comic_title, from_ep, to_ep, chapters=chapters, **kwargs)


US_APOCALYPSE_MARKET = USApocalypseMarket()
