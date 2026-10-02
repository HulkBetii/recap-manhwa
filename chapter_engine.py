"""
Chapter Engine — story-grounded YouTube chapter names: the LLM proposes, code disposes.

Why: chapter names used to come from (a) a registry hand-written for one comic, (b) the first
sentence of an episode cut to 5-7 words ("Tae Plants His Feet Against The") and (c) archetype
boilerplate that could claim events the story never had. Two different comics even shipped
identical chapters. Names are now drafted per arc from that arc's own episode summaries and
must pass format, grounding and duplicate checks; otherwise a neutral "Part N" is used.

Arc boundaries and timestamps still come from youtube_metadata.build_narrative_story_chapters;
this module only names them.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

from pydantic import BaseModel, Field

from title_engine import (
    CLAIM_TERMS_REQUIRING_EVIDENCE,
    STOPWORDS,
    UNGROUNDED_OK_WORDS,
    WORD_RE,
    jaccard,
)

logger = logging.getLogger(__name__)

CHAPTER_MIN_WORDS = 2
CHAPTER_MAX_WORDS = 6
CHAPTER_MAX_CHARS = 45
OPTIONS_PER_ARC = 2
MIN_GROUNDED_RATIO = 0.6
NEAR_DUPLICATE_JACCARD = 0.6
DIGEST_MAX_CHARS = 1500
DIGEST_SEGMENTS_PER_EPISODE = 3

DANGLING_LAST_WORDS = STOPWORDS | {
    "with", "from", "into", "onto", "over", "under", "against", "after", "before", "until",
    "than", "his", "her", "their", "its", "our", "your", "my", "this", "that", "these", "those",
}
# The "(Ep X–Y)" label is appended automatically; numbering inside the name is redundant.
FORBIDDEN_CHAPTER_TOKENS = {"ep", "eps", "episode", "episodes", "arc", "part", "chapter"}
FORBIDDEN_CHAPTER_CHARS_RE = re.compile(r"[|()\[\]{}—:#]|\d")
# Abstract event words a chapter may use without literal evidence ("Siege", "Showdown").
CHAPTER_GENERIC_OK = UNGROUNDED_OK_WORDS | {
    "battle", "fight", "brawl", "clash", "siege", "showdown", "escape", "arrival", "return", "rise",
    "fall", "falls", "final", "stand", "begins", "beginning", "aftermath", "breaking", "point",
    "turning", "deal", "trap", "storm", "night", "dawn", "chaos", "secret", "truth", "plan",
}


def arc_key(start_ep: int, end_ep: int) -> str:
    return f"{start_ep}-{end_ep}"


# =============================================================================
# Arc digests & prompt
# =============================================================================

class ArcInput(BaseModel):
    key: str
    index: int
    start_ep: int
    end_ep: int
    digest: str


def _episode_digest(ep: int, story_memory: Optional[Dict[str, Any]], narration: Dict[int, List[str]]) -> str:
    episodes = (story_memory or {}).get("episodes") if isinstance(story_memory, dict) else None
    if isinstance(episodes, dict):
        info = episodes.get(str(ep))
        if isinstance(info, dict) and info.get("summary"):
            return str(info["summary"])
    segs = narration.get(ep, [])
    if not segs:
        return ""
    picks = segs[:DIGEST_SEGMENTS_PER_EPISODE - 1] + segs[-1:]
    return " ".join(picks)


def build_arc_inputs(
    narrative_chapters: Sequence[Dict[str, Any]],
    narration: Dict[int, List[str]],
    story_memory: Optional[Dict[str, Any]] = None,
) -> List[ArcInput]:
    """One digest per arc, sampled evenly across its episodes and capped in size."""
    arcs: List[ArcInput] = []
    for i, ch in enumerate(narrative_chapters):
        start_ep = int(ch.get("episode", 0))
        end_ep = int(ch.get("end_episode", start_ep))
        eps = list(range(start_ep, end_ep + 1))
        per_ep = max(120, DIGEST_MAX_CHARS // max(1, len(eps)))
        parts = []
        for ep in eps:
            text = _episode_digest(ep, story_memory, narration)
            if text:
                parts.append(f"Ep {ep}: {text[:per_ep]}")
        digest = "\n".join(parts)[:DIGEST_MAX_CHARS]
        if digest:
            arcs.append(ArcInput(key=arc_key(start_ep, end_ep), index=i, start_ep=start_ep, end_ep=end_ep, digest=digest))
    return arcs


def build_chapter_prompt(arcs: Sequence[ArcInput], character_names: Sequence[str]) -> str:
    blocks = "\n\n".join(f'ARC "{a.key}" (episodes {a.start_ep}-{a.end_ep}):\n{a.digest}' for a in arcs)
    cast = ", ".join(character_names) or "(none confirmed)"
    return f"""You name YouTube video chapters for an English (US) manhwa recap.

Confirmed character names (the only names you may use): {cast}

{blocks}

For EACH arc, write {OPTIONS_PER_ARC} alternative chapter names.

RULES:
1. {CHAPTER_MIN_WORDS}-{CHAPTER_MAX_WORDS} words, max {CHAPTER_MAX_CHARS} characters, Title Case.
2. Name the arc's key event using words from that arc's text (a viewer scanning chapters should know what happens).
3. No numbers, no "Ep"/"Episode"/"Arc"/"Part", no colons, dashes or brackets.
4. Never end on "The", "A", "Of", "With", "Against" or any other dangling word.
5. Every chapter name must be different from the others.
6. Only use character names from the confirmed list; otherwise describe by role.

Return ONLY a JSON object mapping each arc id to a list of {OPTIONS_PER_ARC} names, e.g.
{{"{arcs[0].key if arcs else '1-5'}": ["Martial Law Falls", "The City Goes Dark"]}}
"""


def parse_chapter_options(text: str) -> Dict[str, List[str]]:
    if not text:
        return {}
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    options: Dict[str, List[str]] = {}
    for key, value in data.items():
        names = value if isinstance(value, list) else [value]
        options[str(key)] = [str(n).strip().strip("\"'") for n in names if str(n).strip()]
    return options


async def generate_llm_chapter_options(
    arcs: Sequence[ArcInput],
    character_names: Sequence[str],
    llm_text_call: Callable[[str], Awaitable[Optional[str]]],
) -> Dict[str, List[str]]:
    """One LLM call for all arcs. Returns {} on failure so callers fall back deterministically."""
    if not arcs:
        return {}
    try:
        raw = await llm_text_call(build_chapter_prompt(arcs, character_names))
    except Exception as err:
        logger.warning("Chapter LLM call failed: %s", err)
        return {}
    return parse_chapter_options(raw or "")


# =============================================================================
# Validation
# =============================================================================

class ChapterNameCheck(BaseModel):
    name: str
    passed: bool
    reasons: List[str] = Field(default_factory=list)
    grounded_words: List[str] = Field(default_factory=list)


class ChapterNameValidator:
    def __init__(
        self,
        narration: Dict[int, List[str]],
        placeholder_names: Iterable[str] = (),
        other_video_chapters: Iterable[str] = (),
        language: str = "en",
    ):
        self.narration = narration
        self.placeholders = [p for p in placeholder_names if p]
        self.other_video_chapters = {c.strip().casefold() for c in other_video_chapters if c}
        self.lexical_grounding = (language or "en").lower() in ("en", "english")
        self._arc_cache: Dict[str, tuple] = {}

    def _arc_vocab(self, start_ep: int, end_ep: int) -> tuple:
        key = arc_key(start_ep, end_ep)
        if key not in self._arc_cache:
            words = [
                w.lower()
                for ep in range(start_ep, end_ep + 1)
                for seg in self.narration.get(ep, [])
                for w in WORD_RE.findall(seg)
            ]
            counts: Dict[str, int] = {}
            for w in words:
                counts[w] = counts.get(w, 0) + 1
            self._arc_cache[key] = ({w[:5] for w in words}, counts)
        return self._arc_cache[key]

    def check(self, name: str, start_ep: int, end_ep: int, accepted: Sequence[str] = ()) -> ChapterNameCheck:
        name = re.sub(r"\s+", " ", name).strip().strip(".!?,;")
        words = WORD_RE.findall(name)
        reasons: List[str] = []

        if not CHAPTER_MIN_WORDS <= len(words) <= CHAPTER_MAX_WORDS:
            reasons.append(f"word_count:{len(words)}")
        if len(name) > CHAPTER_MAX_CHARS:
            reasons.append(f"too_long:{len(name)}")
        if FORBIDDEN_CHAPTER_CHARS_RE.search(name) or any(w.lower() in FORBIDDEN_CHAPTER_TOKENS for w in words):
            reasons.append("numbering_or_symbols")
        if words and words[-1].lower() in DANGLING_LAST_WORDS:
            reasons.append(f"dangling_last_word:{words[-1]}")
        if any(re.search(rf"\b{re.escape(p)}\b", name) for p in self.placeholders):
            reasons.append("placeholder_name")

        grounded: List[str] = []
        has_story = any(self.narration.get(ep) for ep in range(start_ep, end_ep + 1))
        if self.lexical_grounding and has_story:
            prefixes, counts = self._arc_vocab(start_ep, end_ep)
            content = [w.lower() for w in words if len(w) >= 4 and w.lower() not in CHAPTER_GENERIC_OK]
            grounded = [w for w in content if w[:5] in prefixes]
            if content and (not grounded or len(grounded) / len(content) < MIN_GROUNDED_RATIO):
                reasons.append(f"low_grounding:{len(grounded)}/{len(content)}")
            missing_claims = [
                w.lower() for w in words
                if w.lower() in CLAIM_TERMS_REQUIRING_EVIDENCE and counts.get(w.lower(), 0) == 0
            ]
            if missing_claims:
                reasons.append(f"claim_not_in_arc:{','.join(missing_claims)}")

        if any(name.casefold() == a.casefold() or jaccard(name, a) >= NEAR_DUPLICATE_JACCARD for a in accepted):
            reasons.append("duplicate_in_video")
        if name.casefold() in self.other_video_chapters:
            reasons.append("duplicate_of_other_video")

        return ChapterNameCheck(name=name, passed=not reasons, reasons=reasons, grounded_words=grounded)


# =============================================================================
# Application
# =============================================================================

class ChapterNamingAudit(BaseModel):
    llm_named: int = 0
    kept_existing: int = 0
    fallback_part: int = 0
    rejected: List[ChapterNameCheck] = Field(default_factory=list)


def _ep_label(start_ep: int, end_ep: int) -> str:
    return f"Ep {start_ep}" if start_ep == end_ep else f"Ep {start_ep}–{end_ep}"


def apply_chapter_names(
    narrative_chapters: Sequence[Dict[str, Any]],
    options_by_arc: Dict[str, List[str]],
    validator: ChapterNameValidator,
) -> tuple[List[Dict[str, Any]], ChapterNamingAudit]:
    """
    Picks, per arc, the first valid name among: LLM options, the existing theme.
    Falls back to "Part N" so a chapter is never truncated, duplicated or invented.
    """
    audit = ChapterNamingAudit()
    accepted: List[str] = []
    result: List[Dict[str, Any]] = []

    for i, ch in enumerate(narrative_chapters):
        start_ep = int(ch.get("episode", 0))
        end_ep = int(ch.get("end_episode", start_ep))
        candidates = [("llm", n) for n in options_by_arc.get(arc_key(start_ep, end_ep), [])]
        existing = str(ch.get("theme") or "").strip()
        if existing and not re.fullmatch(r"Part \d+", existing):
            candidates.append(("existing", existing))

        chosen, chosen_source, evidence = None, "", []
        for source, name in candidates:
            check = validator.check(name, start_ep, end_ep, accepted)
            if check.passed:
                chosen, chosen_source, evidence = check.name, source, check.grounded_words
                break
            audit.rejected.append(check)

        if chosen is None:
            chosen, chosen_source = f"Part {i + 1}", "fallback"
        if chosen_source == "llm":
            audit.llm_named += 1
        elif chosen_source == "existing":
            audit.kept_existing += 1
        else:
            audit.fallback_part += 1

        accepted.append(chosen)
        updated = dict(ch)
        updated["theme"] = chosen
        updated["title"] = f"{chosen} ({_ep_label(start_ep, end_ep)})"
        updated["naming_source"] = chosen_source
        updated["evidence"] = [{"assertion": "grounded_words", "words": evidence}] if evidence else []
        result.append(updated)
    return result, audit
