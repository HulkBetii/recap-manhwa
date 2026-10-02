"""
Thumbnail overlay text — the LLM proposes, code disposes (same model as titles and chapters).

Why: concept templates carried ~15 hard-coded overlays, many longer than the 15-character mobile
limit; the old cap cut them at a word boundary and appended "!", shipping "YOU'RE!" and
"THE COLOSSAL!". Several also claimed things the story never showed ("IMMUNITY AWAKENED",
"ONE SHOT ELIMINATION"). Overlays are now drafted per concept from the Hook Sheet and must pass
length, grounding, claim and title-overlap checks; nothing is ever truncated.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from title_engine import (
    CLAIM_TERM_MIN_MENTIONS,
    CLAIM_TERMS_REQUIRING_EVIDENCE,
    NUMBER_RE,
    STOPWORDS,
    UNGROUNDED_OK_WORDS,
    WORD_RE,
    HookSheet,
    strip_suffix,
)

logger = logging.getLogger(__name__)

OVERLAY_MAX_CHARS = 15      # readable at phone thumbnail size (SEO doc §1.5: 3-4 big words)
OVERLAY_MAX_WORDS = 3
OVERLAY_OPTIONS_PER_CONCEPT = 2
OVERLAY_CONCEPTS = 3        # the kit presents the top 3 concepts
TITLE_OVERLAP_MAX = 0.5     # SEO doc §1.3: thumbnail text should complement, not repeat, the title

# Short punchy words an overlay may use without literal narration evidence.
OVERLAY_GENERIC_OK = UNGROUNDED_OK_WORDS | {
    "boss", "fight", "war", "run", "dead", "alive", "help", "trap", "gone", "doom", "over",
    "game", "begins", "real", "danger", "warning", "escape", "chaos", "panic", "hunt", "rise",
    "falling", "fall", "deadly", "final", "stand", "secret", "truth", "impossible", "insane",
}


def _content_words(text: str) -> List[str]:
    return [
        w.lower() for w in WORD_RE.findall(text)
        if len(w) >= 4 and w.lower() not in OVERLAY_GENERIC_OK and w.lower() not in STOPWORDS
    ]


# =============================================================================
# Prompt
# =============================================================================

def concept_brief(concept: Dict[str, Any]) -> Dict[str, str]:
    return {
        "id": str(concept.get("id", "")),
        "scene": f"{concept.get('name', '')} — {concept.get('composition', '')}",
    }


def build_overlay_prompt(sheet: HookSheet, title: str, concepts: Sequence[Dict[str, Any]]) -> str:
    numbers = "\n".join(f"- {f.phrase}" for f in sheet.numeric_facts) or "- (none)"
    beats = "\n".join(f"- {b}" for b in sheet.story_beats) or "- (none)"
    scenes = "\n".join(f'- "{c["id"]}": {c["scene"]}' for c in map(concept_brief, concepts))
    return f"""You write the big overlay text for YouTube thumbnails of an English manhwa recap.

VIDEO TITLE (do NOT repeat its words): "{strip_suffix(title)}"

STORY FACTS (the ONLY facts you may use):
- Setting: {sheet.setting or "(unknown)"}
- Numbers that literally appear in the narration:
{numbers}
- Story beats:
{beats}

THUMBNAIL SCENES:
{scenes}

For EACH scene write {OVERLAY_OPTIONS_PER_CONCEPT} options. Each option has:
- "main": 1-{OVERLAY_MAX_WORDS} words, at most {OVERLAY_MAX_CHARS} characters including punctuation, ALL CAPS.
- "sub":  1-{OVERLAY_MAX_WORDS} words, at most {OVERLAY_MAX_CHARS} characters including punctuation, ALL CAPS.
Rules: complete phrases only (never cut words), only facts from the list, no character names,
no words already in the title, no power ranks or genre claims the facts do not show.

Return ONLY a JSON object: {{"<scene id>": [{{"main": "...", "sub": "..."}}, ...], ...}}
"""


def parse_overlay_options(text: str) -> Dict[str, List[Tuple[str, str]]]:
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
    options: Dict[str, List[Tuple[str, str]]] = {}
    for concept_id, items in data.items():
        pairs = []
        for item in items if isinstance(items, list) else [items]:
            if isinstance(item, dict) and item.get("main") and item.get("sub"):
                pairs.append((str(item["main"]).strip().upper(), str(item["sub"]).strip().upper()))
        if pairs:
            options[str(concept_id)] = pairs
    return options


async def generate_llm_overlay_options(
    sheet: HookSheet,
    title: str,
    concepts: Sequence[Dict[str, Any]],
    llm_text_call: Callable[[str], Awaitable[Optional[str]]],
) -> Dict[str, List[Tuple[str, str]]]:
    """One LLM call for the top concepts. Returns {} on failure so templates are validated instead."""
    if not sheet.has_story or not concepts:
        return {}
    try:
        raw = await llm_text_call(build_overlay_prompt(sheet, title, concepts[:OVERLAY_CONCEPTS]))
    except Exception as err:
        logger.warning("Thumbnail overlay LLM call failed: %s", err)
        return {}
    return parse_overlay_options(raw or "")


# =============================================================================
# Validation & application
# =============================================================================

class OverlayCheck(BaseModel):
    main: str
    sub: str
    source: str
    passed: bool
    reasons: List[str] = Field(default_factory=list)


class OverlayValidator:
    def __init__(self, sheet: HookSheet, title: str, character_names: Sequence[str] = ()):
        self.sheet = sheet
        self.title_words = set(_content_words(strip_suffix(title)))
        corpus = " ".join(sheet.corpus)
        corpus_words = WORD_RE.findall(corpus.lower())
        self.prefixes = {w[:5] for w in corpus_words}
        self.counts: Dict[str, int] = {}
        for w in corpus_words:
            self.counts[w] = self.counts.get(w, 0) + 1
        self.numbers = {n.replace(",", "") for n in NUMBER_RE.findall(corpus)}
        self.names = [n for n in character_names if len(n) >= 2]
        self.lexical = sheet.language in ("en", "english") and bool(sheet.corpus)

    def _line_reasons(self, label: str, text: str) -> List[str]:
        reasons = []
        if not text:
            reasons.append(f"{label}_empty")
            return reasons
        if len(text) > OVERLAY_MAX_CHARS:
            reasons.append(f"{label}_too_long:{len(text)}")
        if len(WORD_RE.findall(text)) > OVERLAY_MAX_WORDS:
            reasons.append(f"{label}_too_many_words")
        return reasons

    def check(self, main: str, sub: str, source: str) -> OverlayCheck:
        main, sub = main.strip().upper(), sub.strip().upper()
        reasons = self._line_reasons("main", main) + self._line_reasons("sub", sub)
        both = f"{main} {sub}"

        if any(re.search(rf"\b{re.escape(n.upper())}\b", both) for n in self.names):
            reasons.append("character_name")
        invented = {n.replace(",", "") for n in NUMBER_RE.findall(both)} - self.numbers
        if invented and self.sheet.corpus:
            reasons.append(f"numbers_not_in_story:{','.join(sorted(invented))}")

        if self.lexical:
            words = [w.lower() for w in WORD_RE.findall(both)]
            claims = sorted({
                w for w in words
                if w in CLAIM_TERMS_REQUIRING_EVIDENCE
                and self.counts.get(w, 0) + self.counts.get(w + "s", 0) < CLAIM_TERM_MIN_MENTIONS
            })
            if claims:
                reasons.append(f"claim_not_in_story:{','.join(claims)}")
            content = _content_words(both)
            grounded = [w for w in content if w[:5] in self.prefixes]
            # A few words carry the whole promise: with 1-2 content words, one invented word
            # ("IMMUNITY!") is already a false claim, so allow at most one per three words.
            if len(content) - len(grounded) > len(content) // 3:
                reasons.append(f"low_grounding:{len(grounded)}/{len(content)}")
            if content and self.title_words:
                overlap = len(set(content) & self.title_words) / len(set(content))
                if overlap >= TITLE_OVERLAP_MAX:
                    reasons.append("repeats_title")

        return OverlayCheck(main=main, sub=sub, source=source, passed=not reasons, reasons=reasons)


def _split_overlay(concept: Dict[str, Any]) -> Tuple[str, str]:
    main, _, sub = str(concept.get("thumbnail_text", "")).partition(" / ")
    return main.strip(), sub.strip()


def _replace_overlay(concept: Dict[str, Any], old: Tuple[str, str], new: Tuple[str, str]) -> Dict[str, Any]:
    updated = dict(concept)
    for field in ("gpt_prompt", "text_style"):
        value = str(updated.get(field, ""))
        for o, n in zip(old, new):
            if o:
                value = value.replace(f"'{o}'", f"'{n}'")
        updated[field] = value
    updated["thumbnail_text"] = f"{new[0]} / {new[1]}"
    return updated


def apply_overlays(
    concepts: Sequence[Dict[str, Any]],
    options: Dict[str, List[Tuple[str, str]]],
    validator: OverlayValidator,
) -> Tuple[List[Dict[str, Any]], List[OverlayCheck]]:
    """
    Per concept: first valid option among the LLM drafts and the template's own text.
    A concept with no valid option keeps its template text and is flagged overlay_valid=False
    (surfaced by the pre-publish gate) — text is never truncated.
    """
    result: List[Dict[str, Any]] = []
    checks: List[OverlayCheck] = []
    for concept in concepts:
        current = _split_overlay(concept)
        candidates = [("llm", pair) for pair in options.get(str(concept.get("id")), [])]
        candidates.append(("template", current))
        chosen: Optional[Tuple[str, str]] = None
        for source, pair in candidates:
            check = validator.check(pair[0], pair[1], source)
            checks.append(check)
            if check.passed:
                chosen = (check.main, check.sub)
                break
        if chosen is None:
            updated = dict(concept)
            updated["overlay_valid"] = False
        else:
            updated = _replace_overlay(concept, current, chosen)
            updated["overlay_valid"] = True
        result.append(updated)
    return result, checks
