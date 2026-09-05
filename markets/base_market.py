from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BaseMarketProfile:
    id: str
    name: str
    description: str
    language: str = 'en'
    default_voice_id: str = 'ai33pro'
    voice_rate: str = '+0%'
    voice_pitch: str = '+0Hz'
    preferred_fonts: List[str] = field(default_factory=list)

    def get_gemini_prompt(
        self,
        comic_title: str,
        ep: int,
        total_pages: int,
        glossary: Optional[str] = None,
    ) -> str:
        raise NotImplementedError('Subclasses must implement get_gemini_prompt')

    def generate_youtube_metadata(
        self,
        comic_title: str,
        from_ep: int,
        to_ep: int,
    ) -> dict:
        return {
            'title': f'[{self.name}] {comic_title} Ep {from_ep}~{to_ep}',
            'description': f'Recap of {comic_title} from episode {from_ep} to {to_ep}.',
            'tags': [],
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
