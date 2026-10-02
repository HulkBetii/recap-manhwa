# -*- coding: utf-8 -*-
"""
CHANNEL PROFILE & BRANDING CONFIGURATION
Houses channel identity, subscribe links, target niche, persona, and competitor network
for automated YouTube SEO metadata and script generation.
"""

from typing import Dict, Any

CHANNEL_PROFILE: Dict[str, Any] = {
    "channel_name": "Jaehwan Manhwa",
    "channel_handle": "@JaehwanManhwa",
    "channel_url": "https://www.youtube.com/@JaehwanManhwa",
    "sub_link": "https://www.youtube.com/@JaehwanManhwa?sub_confirmation=1",
    "primary_niche": "apocalypse_and_survival",
    "persona": "Sarcastic Bro-Commentary",
    "target_audience": "US / Global English",
    "video_format": "long_form_full_story",
    # Benchmarked 2026-10-02. Dystopia Manhwa is the closest peer (similar size, pure apocalypse
    # niche, 10-25h videos); the others are large references for title/packaging patterns.
    "competitors": [
        {"name": "Dystopia Manhwa", "handle": "@DystopiaManhwa", "url": "https://www.youtube.com/@DystopiaManhwa"},
        {"name": "Manhwa Fresh", "handle": "@Manhwa_Fresh", "url": "https://www.youtube.com/@Manhwa_Fresh"},
        {"name": "Manhwa Outpost", "handle": "@ManhwaOutpost", "url": "https://www.youtube.com/@ManhwaOutpost"},
        {"name": "Tobs Manhwa", "handle": "@TobsManhwa", "url": "https://www.youtube.com/@TobsManhwa"},
        {"name": "Mamoru Manhwa", "handle": "@MamoruManhwa", "url": "https://www.youtube.com/@MamoruManhwa"},
        {"name": "Donalds_Manhwa", "handle": "@DonaldsManhwa", "url": "https://www.youtube.com/@DonaldsManhwa"},
    ],
    "brand_tags": [
        "jaehwan manhwa",
        "jaehwan",
        "jaehwan manhwa recap",
    ],
    "niche_core_tags": [
        "apocalypse manhwa",
        "survival manhwa",
        "zombie survival manhwa",
        "apocalypse manhwa recap",
    ],
}


def get_channel_profile() -> Dict[str, Any]:
    """Returns the active channel branding profile."""
    return CHANNEL_PROFILE
