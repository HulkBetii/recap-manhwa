"""
Premise Pitch — a 30-45s spoken opening that delivers the title's promise before the story starts.

Why: on the channel's 13h video, 98% of viewers were still watching at 0:30 but only 7.5% at
7:50. Episode 1 narrated the comic's slow setup (briefings, a farewell dinner) while the title
promised something else. Niche winners open with a 25-48s pitch that restates the title's
promise with concrete numbers, then cut into the story. This module drafts that pitch from the
whole-story Hook Sheet and the shipped title, and rejects drafts that invent numbers, names or
genre claims, greet the viewer, or fail to echo the title.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, List, Optional

from pydantic import BaseModel, Field

from prepublish_gate import check_title_promise_in_opening
from series_bible import extract_name_candidates, name_key, normalize_text
from title_engine import (
    CLAIM_TERM_MIN_MENTIONS,
    CLAIM_TERMS_REQUIRING_EVIDENCE,
    NUMBER_RE,
    WORD_RE,
    HookSheet,
    premise_prefixes,
    states_premise,
    strip_suffix,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
# ~150 spoken words/min in English -> 24-46s. Vietnamese counts syllables as words, so it runs longer.
WORD_BOUNDS = {"en": (60, 115), "vi": (75, 150)}
DEFAULT_WORD_BOUNDS = (60, 130)
GREETING_RE = re.compile(
    r"\b(welcome|today we|in this video|in today's|let's dive|hey guys|what's up|chào mừng|hôm nay chúng ta)\b",
    re.IGNORECASE,
)
LANGUAGE_NAMES = {"en": "English", "vi": "Vietnamese"}
# Capitalized only because they open a sentence; never treated as names.
SENTENCE_START_COMMON = {
    "when", "while", "within", "once", "now", "then", "soon", "still", "even", "yet", "but",
    "and", "so", "it", "he", "she", "they", "his", "her", "their", "this", "that", "there",
    "here", "what", "who", "every", "only", "just", "after", "before", "in", "on", "at", "for",
    "from", "with", "without", "as", "if", "because", "until", "since", "nobody", "everyone",
    "nothing", "all", "one", "two", "three", "no", "not", "the",
}
SENTENCE_START_RE = re.compile(r"(?:^|[.!?]\s+)([A-Z][a-z]{2,})\b")
# Adverbs and participles that open sentences ("Fortunately", "Suddenly", "Facing"); a Veteran 1-33 pitch was
# rejected twice for "Fortunately". Short tokens ("Ming", "Jing") may still be names, so length matters.
OPENER_SUFFIXES = ("ly", "ing", "ed")
OPENER_MIN_LENGTH = 6


def _looks_like_sentence_opener(token: str) -> bool:
    return len(token) >= OPENER_MIN_LENGTH and token.lower().endswith(OPENER_SUFFIXES)


class PitchCheck(BaseModel):
    text: str
    passed: bool
    reasons: List[str] = Field(default_factory=list)
    word_count: int = 0


class PitchResult(BaseModel):
    text: Optional[str] = None           # validated pitch, None if every attempt failed
    attempts: List[PitchCheck] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.text is not None


def _lang(language: str) -> str:
    return (language or "en").lower()[:2]


def build_pitch_prompt(sheet: HookSheet, title: str, language: str = "en", feedback: Optional[List[str]] = None) -> str:
    lo, hi = WORD_BOUNDS.get(_lang(language), DEFAULT_WORD_BOUNDS)
    numbers = "\n".join(f"- {f.phrase}" for f in sheet.central_facts) or "- (none)"
    beats = "\n".join(f"- {b}" for b in sheet.story_beats) or "- (none)"
    mc = sheet.protagonist or "he"
    retry = ""
    if feedback:
        retry = "\nYOUR PREVIOUS DRAFT WAS REJECTED FOR: " + "; ".join(feedback) + ". Fix every point.\n"
    premise = ""
    premise_rule = ""
    if sheet.synopsis:
        premise = f'- OFFICIAL PREMISE (publisher synopsis): "{sheet.synopsis}"\n'
        premise_rule = (
            "- Build the stakes on the OFFICIAL PREMISE (his defining power, situation or plan). Never present a "
            "side detail or a number as the one thing that keeps him alive.\n"
        )
    return f"""You write the spoken cold-open for a long manhwa recap video.

VIDEO TITLE (the promise viewers clicked on): "{strip_suffix(title)}"

STORY FACTS (the ONLY facts you may use):
{premise}- Setting: {sheet.setting or "(unknown)"}
- Numbers central to the story (optional; use no other numbers):
{numbers}
- Story beats across the whole video:
{beats}
{retry}
Write ONE premise pitch in {LANGUAGE_NAMES.get(_lang(language), language)}, {lo}-{hi} words, to be read aloud before the story starts.

STRUCTURE (proven by the top channels in this niche):
1. First sentence: state the title's promise concretely, reusing the title's key words.
2. Next 2-3 sentences: the stakes, using at most two numbers from the list above (numbers are optional).
3. One sentence on why the protagonist is different (his edge, choice or situation).
4. Last sentence: hand off into the story ("It all begins..." / "And it starts...").

RULES:
{premise_rule}- The protagonist is "{mc}"; never invent other names. Unnamed characters are described by role.
- No greetings, no "in this video", no channel mentions, no questions to the viewer.
- Do not reveal the final outcome of the video.
- Plain spoken prose only: no lists, no Markdown, no quotation marks.

Return ONLY the pitch text.
"""


def validate_pitch(
    text: str,
    title: str,
    sheet: HookSheet,
    bible: Any = None,
    language: str = "en",
) -> PitchCheck:
    """`bible` is a series_bible.SeriesBible or None."""
    text = re.sub(r"\s+", " ", (text or "").strip().strip("\"'"))
    words = WORD_RE.findall(text) if _lang(language) == "en" else text.split()
    lo, hi = WORD_BOUNDS.get(_lang(language), DEFAULT_WORD_BOUNDS)
    reasons: List[str] = []

    if not lo <= len(words) <= hi:
        reasons.append(f"word_count {len(words)} outside {lo}-{hi}")
    if GREETING_RE.search(text):
        reasons.append("greeting or channel talk")
    if re.search(r"^\s*[-*#\d]+[.)]?\s", text, re.MULTILINE):
        reasons.append("list or Markdown formatting")

    corpus_text = " ".join(sheet.corpus)
    corpus_numbers = {n.replace(",", "") for n in NUMBER_RE.findall(corpus_text)}
    invented = sorted({n.replace(",", "") for n in NUMBER_RE.findall(text)} - corpus_numbers)
    if invented and sheet.corpus:
        reasons.append(f"numbers not in the story: {', '.join(invented)}")

    if bible is not None:
        blocked = [p for p in getattr(bible, "placeholder_blocklist", []) if p != getattr(bible, "protagonist_name", "")]
        if any(re.search(rf"\b{re.escape(p)}\b", text) for p in blocked):
            reasons.append("placeholder name")
        if getattr(bible, "protagonist_name", ""):
            known = bible.known_names()
            candidates = set(extract_name_candidates([text]))
            # Short pitches often open a sentence with a name, which mid-sentence detection misses.
            lowercase_words = {w.lower() for w in WORD_RE.findall(corpus_text)} | {
                w for w in WORD_RE.findall(text) if w.islower()
            }
            candidates |= {
                tok for tok in SENTENCE_START_RE.findall(text)
                if tok.lower() not in SENTENCE_START_COMMON and tok.lower() not in lowercase_words
                and not _looks_like_sentence_opener(tok)
            }
            # Places and minor characters from the narration are fine; names found nowhere are invented.
            invented_names = sorted(
                n for n in candidates
                if name_key(n) not in known and not re.search(rf"\b{re.escape(n)}\b", corpus_text)
            )
            if invented_names:
                reasons.append(f"names not in the story: {', '.join(invented_names)}")

    if _lang(language) == "en" and sheet.corpus:
        counts: dict = {}
        for w in WORD_RE.findall(corpus_text.lower()):
            counts[w] = counts.get(w, 0) + 1
        missing = sorted({
            w.lower() for w in WORD_RE.findall(text)
            if w.lower() in CLAIM_TERMS_REQUIRING_EVIDENCE and counts.get(w.lower(), 0) < CLAIM_TERM_MIN_MENTIONS
        })
        if missing:
            reasons.append(f"genre claims not in the story: {', '.join(missing)}")
        promise = check_title_promise_in_opening(title, [text])
        if not promise.passed:
            reasons.append(f"does not echo the title: {promise.detail}")
        # With an official synopsis, the pitch must carry its core premise, not only a side detail.
        if premise_prefixes(sheet) and not states_premise(text, sheet):
            reasons.append("does not state the official premise (the synopsis' core power or situation)")

    return PitchCheck(text=text, passed=not reasons, reasons=reasons, word_count=len(words))


async def generate_premise_pitch(
    sheet: HookSheet,
    title: str,
    llm_text_call: Callable[[str], Awaitable[Optional[str]]],
    bible: Any = None,
    language: str = "en",
) -> PitchResult:
    """Drafts, normalizes names and validates; retries once with the rejection reasons."""
    result = PitchResult()
    if not sheet.has_story:
        return result
    feedback: Optional[List[str]] = None
    for _ in range(MAX_ATTEMPTS):
        try:
            raw = await llm_text_call(build_pitch_prompt(sheet, title, language, feedback))
        except Exception as err:
            logger.warning("Premise pitch LLM call failed: %s", err)
            result.attempts.append(PitchCheck(text="", passed=False, reasons=[f"llm_error: {err}"]))
            break
        draft, _ = normalize_text(raw or "", bible)
        check = validate_pitch(draft, title, sheet, bible, language)
        result.attempts.append(check)
        if check.passed:
            result.text = check.text
            break
        feedback = check.reasons
    return result
