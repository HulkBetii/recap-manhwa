from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BaseMarketProfile:
    id: str
    name: str
    description: str
    language: str = 'en'
    default_voice_id: str = 'clone_andrew'
    voice_rate: str = '+0%'
    voice_pitch: str = '+0Hz'
    preferred_fonts: List[str] = field(default_factory=list)
    point_score_threshold: int = 65

    def get_gemini_prompt(
        self,
        comic_title: str,
        ep: int,
        total_pages: int,
        glossary: Optional[str] = None,
        previous_context: Optional[dict] = None,
    ) -> str:
        raise NotImplementedError('Subclasses must implement get_gemini_prompt')

    def generate_youtube_metadata(
        self,
        comic_title: str,
        from_ep: int,
        to_ep: int,
        chapters: Optional[list] = None,
        story_memory: Optional[dict] = None,
        download_dir: Optional[str] = None,
        **kwargs,
    ) -> dict:
        ep_range = f"Ep {from_ep}~{to_ep}" if from_ep != to_ep else f"Ep {from_ep}"
        default_title = f"{comic_title} [{ep_range}] | Manhwa Recap"
        desc = f"English manhwa recap of {comic_title} ({ep_range}).\n\nOriginal narration and commentary.\n\n#ManhwaRecap #WebtoonRecap"
        return {
            'title': default_title,
            'title_variants': {
                'variant_a_conflict': default_title,
                'variant_b_paradox': default_title,
                'variant_c_scale': default_title,
            },
            'description': desc,
            'tags': ['manhwa recap', comic_title.lower(), f"{comic_title.lower()} recap"],
            'pinned_comment': f"📌 {comic_title} ({ep_range})\n\n👉 Like & Subscribe for more recaps!",
            'narrative_chapters': chapters or [{'timestamp': '00:00', 'title': f'Chapter {from_ep}', 'episode': from_ep}],
            'thumbnail_concepts': [],
            'compliance_flags': {
                'title_length_ok': len(default_title) <= 100,
                'desc_bytes_ok': len(desc.encode('utf-8')) <= 5000,
                'tag_count_ok': True,
                'hashtag_count_ok': True,
                'first_chapter_is_zero': True,
            }
        }

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'language': self.language,
            'default_voice_id': self.default_voice_id,
            'voice_rate': self.voice_rate,
            'voice_pitch': self.voice_pitch,
            'preferred_fonts': self.preferred_fonts,
        }
