"""
Title Engine — story-specific YouTube titles: the LLM proposes, deterministic code disposes.

Why: archetype template pools produced the same title for different comics and promises the
story never delivered (e.g. "SSS-Rank Trainee" on a 1982 zombie story). Titles are now drafted
from a Hook Sheet of real narration facts, then every candidate must pass grounding, niche,
format and duplicate checks before it can reach the upload kit.

Usage:
    sheet = build_hook_sheet(comic_title, download_dir, from_ep, to_ep, story_memory, bible)
    raw = await llm_text_call(build_title_prompt(sheet))
    validator = TitleValidator(sheet, registry_titles=registry.titles_for_dedup(comic_title), ...)
    selection = select_titles(llm_hooks=parse_title_candidates(raw), template_hooks=[...], validator=validator)

CLI:
    python title_engine.py import-studio-csv "<Studio Content export folder or Table data.csv>"
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import re
import sys
import time
from collections import Counter
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TITLE_SUFFIX = " | Manhwa Recap"
TITLE_HARD_MAX = 100
HOOK_MAX_CHARS = 60          # YouTube mobile shows ~55-60 chars before truncation
HOOK_MIN_CHARS = 20
NICHE_KEYWORD_WINDOW = 50    # niche keyword must appear within the first N chars
MAX_CAPS_WORDS = 3
MIN_GROUNDED_RATIO = 0.75
DUPLICATE_JACCARD = 0.6      # >= this vs a published/other-comic title -> rejected
VARIANT_MAX_JACCARD = 0.5    # A/B variants must differ at least this much
LLM_TITLE_COUNT = 10
MAX_HOOK_SHEET_NUMBERS = 12
MAX_HOOK_SHEET_BEATS = 8
# A number can carry a title only if it is central to the story: repeated, early, or official.
# (Veteran 1-33 shipped "His 105 Points KEEP Him Alive!" from one line in episode 22 of 33.)
CENTRAL_NUMBER_MIN_MENTIONS = 2
EARLY_EPISODE_SHARE = 0.25
NUMBER_SCORE = 3.0
PREMISE_SCORE = 2.0          # title states the publisher's core premise (gate, hideout, ...)
PREMISE_PREFIX = 5
PREMISE_MIN_STEMS = 2
# Synopsis words too vague to show a title is about the premise ("Doom STRIKES" is not "he opens gates").
PREMISE_FILLER_WORDS = {
    "time", "thing", "things", "about", "order", "other", "others", "worse", "final", "doom", "become",
    "becomes", "expects", "having", "while", "there", "more", "very", "life", "lives", "days", "years",
    "suddenly", "begins", "starts", "story", "must", "will", "would", "could", "should", "what", "your",
    # common verbs: every story "hits", "turns" or "finds" something
    "hits", "turns", "takes", "makes", "gets", "goes", "comes", "finds", "tries", "wants", "knows", "sees",
    "uses", "gives", "keeps", "leaves", "runs", "falls", "rises", "works", "logs", "rushes", "lands",
}

REGISTRY_FILENAME = "channel_registry.json"
DEFAULT_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), REGISTRY_FILENAME)

# Umbrella terms for the channel's niche; at least one must appear early in the title.
NICHE_KEYWORDS = [
    "apocalypse", "apocalyptic", "zombie", "zombies", "outbreak", "infected", "undead", "plague",
    "end of the world", "doomsday", "survival", "survive", "survives", "survived", "survivor",
    "survivors", "bunker", "shelter", "frozen", "freeze", "froze", "wasteland", "collapse",
    "extinction", "catastrophe", "disaster", "monster", "monsters", "tower", "dungeon", "regress",
]

# Words a title may use without narration evidence (grammar, pronouns, niche umbrella terms).
UNGROUNDED_OK_WORDS = {
    "when", "while", "after", "before", "until", "then", "than", "with", "without", "into",
    "from", "over", "under", "only", "just", "even", "every", "everyone", "everybody", "nobody",
    "none", "they", "them", "their", "theirs", "this", "that", "these", "those", "what",
    "which", "where", "whole", "entire", "still", "never", "ever", "also", "again", "here",
    "there", "have", "has", "had", "gets", "got", "becomes", "became", "turns", "turned",
    "people", "world", "humanity", "man", "guy", "boy", "everything", "nothing", "something",
    "himself", "alone", "first", "last", "next", "most", "more", "less", "much", "many",
    "apocalypse", "apocalyptic", "survival", "survive", "survives", "survived", "survivor",
    "survivors", "end", "doomsday", "manhwa", "recap", "real", "true", "finally", "secretly",
}

# Genre/power promises that must appear verbatim in the narration. Prefix grounding alone is
# too lenient on 10h+ corpora ("train" from "training" would excuse "Trainee").
CLAIM_TERMS_REQUIRING_EVIDENCE = {
    "sss", "ss", "trainee", "weakest", "strongest", "regress", "regressed", "regression",
    "regressor", "academy", "cultivation", "cultivator", "dungeon", "guild", "hunter",
    "awakens", "awakened", "awakening", "system", "mana", "skill", "necromancer", "villainess",
    "reincarnated", "reincarnation", "isekai", "god-tier", "unlimited", "infinite",
}
CLAIM_TERM_MIN_MENTIONS = 3

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at", "for", "by", "as",
    "is", "was", "are", "were", "be", "he", "his", "him", "she", "her", "it", "its", "who",
}

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
NUMERIC_FACT_RE = re.compile(
    r"\b(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(%|percent\b|x\b)?\s*([A-Za-z][A-Za-z\-]{2,})?"
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z']*")

SUB_NICHE_SIGNALS: Dict[str, List[str]] = {
    "zombie outbreak": ["zombie", "infected", "undead", "horde"],
    "frozen apocalypse": ["frozen", "freeze", "blizzard", "ice age", "sub-zero"],
    "bunker / hoarding": ["bunker", "shelter", "stockpile", "hoard", "supplies"],
    "regression / second chance": ["regress", "past life", "second chance", "went back in time", "returned to the past"],
    "system / leveling": ["system", "level up", "skill", "awaken"],
    "monster invasion": ["monster", "beast", "dungeon", "gate"],
    "tower climbing": ["tower", "floor"],
}

TitleSource = Literal["llm", "template"]


# =============================================================================
# Hook Sheet — the only facts the LLM is allowed to build titles from
# =============================================================================

class NumericFact(BaseModel):
    phrase: str
    mentions: int
    central: bool = True  # build_hook_sheet marks one-off late numbers False


class HookSheet(BaseModel):
    comic_title: str
    language: str = "en"
    protagonist: str = ""
    setting: str = ""
    synopsis: str = ""  # official publisher synopsis (Series Bible): the story's core premise
    sub_niches: List[str] = Field(default_factory=list)
    numeric_facts: List[NumericFact] = Field(default_factory=list)
    story_beats: List[str] = Field(default_factory=list)
    character_names: List[str] = Field(default_factory=list)
    corpus: List[str] = Field(default_factory=list, exclude=True)  # narration segments, not serialized

    @property
    def has_story(self) -> bool:
        return bool(self.corpus)

    @property
    def central_facts(self) -> List[NumericFact]:
        return [f for f in self.numeric_facts if f.central]

    @property
    def central_numbers(self) -> set[str]:
        return {n.replace(",", "") for f in self.central_facts for n in NUMBER_RE.findall(f.phrase)}


def premise_stem(word: str) -> str:
    """'Gates' and 'gate' share a stem; prefixes keep 'dimensional' ~ 'dimension'."""
    w = word.lower()
    if len(w) > 4 and w.endswith("s"):
        w = w[:-1]
    return w[:PREMISE_PREFIX]


def premise_prefixes(sheet: HookSheet) -> set[str]:
    """Word stems that make the official premise specific (gate, realm, hideout), without the niche
    umbrella terms every title carries anyway (zombie, apocalypse), filler words or the series title."""
    if not sheet.synopsis:
        return set()
    generic = {w.lower() for k in NICHE_KEYWORDS for w in k.split()} | UNGROUNDED_OK_WORDS | PREMISE_FILLER_WORDS
    generic |= {w.lower() for w in WORD_RE.findall(sheet.comic_title or "")}
    generic |= {w.lower() for n in sheet.character_names for w in WORD_RE.findall(n)}
    # Lowercase words only: names and places ("Seoul", "Survival Life") are context, not the hook itself.
    words = [w for w in WORD_RE.findall(sheet.synopsis) if w.islower()]
    return {premise_stem(w) for w in words if len(w) >= 4 and w not in generic and w not in STOPWORDS}


def premise_matches(text: str, prefixes: set[str]) -> int:
    """Distinct premise stems used in `text`."""
    return len({premise_stem(w) for w in WORD_RE.findall(text or "") if len(w) >= 4} & prefixes)


def states_premise(text: str, sheet: HookSheet) -> bool:
    """True when `text` uses at least PREMISE_MIN_STEMS distinct words of the official premise.

    One shared word is not enough: a generic verb ("SAVES", "PREPARES") also appears in synopses.
    """
    return premise_matches(text, premise_prefixes(sheet)) >= PREMISE_MIN_STEMS


def load_narration(download_dir: Optional[str], from_ep: int, to_ep: int) -> List[str]:
    """Returns every narration segment (`speech`) for the episode range, in order."""
    by_episode = load_narration_by_episode(download_dir, from_ep, to_ep)
    return [seg for ep in sorted(by_episode) for seg in by_episode[ep]]


def load_narration_by_episode(download_dir: Optional[str], from_ep: int, to_ep: int) -> Dict[int, List[str]]:
    """Narration segments keyed by episode; episodes without a readable recap.json are omitted."""
    result: Dict[int, List[str]] = {}
    if not download_dir or not os.path.isdir(download_dir):
        return result
    for ep in range(from_ep, to_ep + 1):
        path = os.path.join(download_dir, f"episode_{ep}", "recap.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as err:
            logger.warning("Skipping unreadable recap %s: %s", path, err)
            continue
        if isinstance(data, list):
            result[ep] = [str(s.get("speech", "")) for s in data if isinstance(s, dict) and s.get("speech")]
    return result


def _numeric_facts(by_episode: Dict[int, List[str]], synopsis: str = "") -> List[NumericFact]:
    """Numeric phrases of the narration; a fact is central when its number is mentioned at least
    twice, appears in the first quarter of the episodes, or appears in the official synopsis."""
    episodes = sorted(by_episode)
    early = set(episodes[:max(1, math.ceil(len(episodes) * EARLY_EPISODE_SHARE))])
    counts: Counter = Counter()
    number_mentions: Counter = Counter()
    early_numbers: set = set()
    for ep in episodes:
        for seg in by_episode[ep]:
            for num in NUMBER_RE.findall(seg):
                number_mentions[num.replace(",", "")] += 1
                if ep in early:
                    early_numbers.add(num.replace(",", ""))
            for num, unit_sym, unit_word in NUMERIC_FACT_RE.findall(seg):
                unit = (unit_sym or unit_word or "").strip().lower()
                phrase = f"{num}{'%' if unit in ('%', 'percent') else ''}"
                if unit and unit not in ("%", "percent"):
                    phrase = f"{num} {unit}"
                counts[phrase] += 1
    official = {n.replace(",", "") for n in NUMBER_RE.findall(synopsis or "")}

    def central(phrase: str) -> bool:
        nums = [n.replace(",", "") for n in NUMBER_RE.findall(phrase)]
        return any(
            number_mentions[n] >= CENTRAL_NUMBER_MIN_MENTIONS or n in early_numbers or n in official for n in nums
        )

    return [
        NumericFact(phrase=p, mentions=n, central=central(p))
        for p, n in counts.most_common(MAX_HOOK_SHEET_NUMBERS)
    ]


def _sub_niches(corpus: Sequence[str]) -> List[str]:
    text = " ".join(corpus).lower()
    scores = {
        label: sum(text.count(sig) for sig in signals)
        for label, signals in SUB_NICHE_SIGNALS.items()
    }
    ranked = sorted((s, label) for label, s in scores.items() if s > 0)
    return [label for _, label in reversed(ranked)][:2]


def _story_beats(story_memory: Optional[Dict[str, Any]], corpus: Sequence[str], from_ep: int, to_ep: int) -> List[str]:
    beats: List[str] = []
    episodes = (story_memory or {}).get("episodes") if isinstance(story_memory, dict) else None
    if isinstance(episodes, dict):
        in_range = sorted(
            (int(k), v) for k, v in episodes.items()
            if str(k).isdigit() and from_ep <= int(k) <= to_ep and isinstance(v, dict) and v.get("summary")
        )
        if in_range:
            step = max(1, len(in_range) // MAX_HOOK_SHEET_BEATS)
            for ep, info in in_range[::step][:MAX_HOOK_SHEET_BEATS]:
                beats.append(f"Ep {ep}: {str(info['summary'])[:220]}")
    if not beats and corpus:
        picks = list(corpus[:3]) + list(corpus[len(corpus) // 2:len(corpus) // 2 + 2]) + list(corpus[-3:])
        beats = [p[:220] for p in picks]
    return beats


def build_hook_sheet(
    comic_title: str,
    download_dir: Optional[str],
    from_ep: int,
    to_ep: int,
    story_memory: Optional[Dict[str, Any]] = None,
    bible: Any = None,
    language: str = "en",
) -> HookSheet:
    """Collects grounded facts for title drafting. `bible` is a series_bible.SeriesBible or None."""
    by_episode = load_narration_by_episode(download_dir, from_ep, to_ep)
    corpus = [seg for ep in sorted(by_episode) for seg in by_episode[ep]]
    protagonist = ""
    names: List[str] = []
    setting = ""
    synopsis = ""
    if bible is not None:
        protagonist = getattr(bible, "protagonist_name", "") or ""
        setting = getattr(bible, "setting", "") or ""
        synopsis = getattr(bible, "synopsis", "") or ""
        names = [n for n in [protagonist] + [c.name for c in getattr(bible, "characters", [])] if n]
    if not protagonist and isinstance(story_memory, dict):
        protagonist = str(story_memory.get("protagonist_name", "") or "")
        if protagonist:
            names.append(protagonist)
    return HookSheet(
        comic_title=comic_title,
        language=(language or "en").lower(),
        protagonist=protagonist,
        setting=setting,
        synopsis=synopsis,
        sub_niches=_sub_niches(corpus),
        numeric_facts=_numeric_facts(by_episode, synopsis),
        story_beats=_story_beats(story_memory, corpus, from_ep, to_ep),
        character_names=names,
        corpus=corpus,
    )


def build_title_prompt(sheet: HookSheet, count: int = LLM_TITLE_COUNT) -> str:
    """Prompt for drafting title hooks (the part before ' | Manhwa Recap')."""
    numbers = "\n".join(f"- {f.phrase} (mentioned {f.mentions}x)" for f in sheet.central_facts) or "- (none)"
    beats = "\n".join(f"- {b}" for b in sheet.story_beats) or "- (none)"
    niches = ", ".join(sheet.sub_niches) or "apocalypse survival"
    premise = ""
    premise_rule = ""
    if sheet.synopsis:
        premise = f'- OFFICIAL PREMISE (publisher synopsis, the story\'s core hook): "{sheet.synopsis}"\n'
        premise_rule = (
            "\n8. At least half of the hooks must state the core premise from the OFFICIAL PREMISE (the protagonist's "
            "defining power, situation or plan), not a side detail from one scene."
        )
    return f"""You write YouTube titles for an English (US) apocalypse/survival manhwa recap channel.

STORY FACTS (the ONLY facts you may use):
{premise}- Setting: {sheet.setting or "(unknown)"}
- Sub-niche: {niches}
- Numbers central to the story (repeated, early, or official); the only numbers you may use:
{numbers}
- Story beats:
{beats}

Write {count} different title hooks for this video.

PROVEN FORMULA (top channels in this niche):
[underdog or extreme situation] + [apocalypse/zombie/survival keyword] + [one concrete number or resource] + [payoff]
Examples of the FORMAT only (do not copy the facts):
- "99% STARVED In The Apocalypse But His Space Held 60,000 TONS Of Supplies!"
- "The World FROZE But He Is the ONLY One With a HOT Base!"

HARD RULES:
1. Max {HOOK_MAX_CHARS} characters per hook. Do NOT add "| Manhwa Recap" (it is appended automatically).
2. Put an apocalypse/zombie/survival keyword within the first {NICHE_KEYWORD_WINDOW} characters.
3. Every claim must be true to the STORY FACTS. Numbers may ONLY come from the numbers list above.
4. No character names and no comic title. Refer to the protagonist as "He".
5. At most {MAX_CAPS_WORDS} words in ALL CAPS.
6. No power-rank or genre words the facts do not support (e.g. no "SSS-Rank", "System", "Trainee" unless in the facts).
7. Cover three angles across the list: underdog contrast, concrete number/resource, threat/stakes. A number
   is optional; never build a title on a number that is not in the list above.{premise_rule}

Return ONLY a JSON array of {count} strings, no Markdown.
"""


def parse_title_candidates(text: str) -> List[str]:
    """Parses a JSON array of hooks (tolerates fences, numbering and stray suffixes)."""
    if not text:
        return []
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    start, end = cleaned.find("["), cleaned.rfind("]")
    items: List[str] = []
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start:end + 1])
            if isinstance(data, list):
                items = [str(x) for x in data if isinstance(x, (str, int, float))]
        except json.JSONDecodeError:
            items = []
    if not items:
        items = [re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", line) for line in cleaned.splitlines() if line.strip()]
    hooks: List[str] = []
    for item in items:
        hook = strip_suffix(item.strip().strip("\"'"))
        if hook and hook not in hooks:
            hooks.append(hook)
    return hooks


async def generate_llm_hooks(sheet: HookSheet, llm_text_call: Callable[[str], Awaitable[Optional[str]]]) -> List[str]:
    """Drafts hooks with the LLM. Returns [] when there is no narration to ground on or the call fails."""
    if not sheet.has_story:
        return []
    try:
        raw = await llm_text_call(build_title_prompt(sheet))
    except Exception as err:
        logger.warning("Title LLM call failed: %s", err)
        return []
    return parse_title_candidates(raw or "")


# =============================================================================
# Validation
# =============================================================================

def strip_suffix(title: str) -> str:
    """Removes a trailing '| Manhwa Recap' / '- Manhwa Recap' to get the hook."""
    return re.sub(r"\s*[\|\-–—]\s*manhwa recap\s*$", "", title.strip(), flags=re.IGNORECASE).strip()


def content_tokens(text: str) -> set[str]:
    return {w.lower() for w in WORD_RE.findall(text) if len(w) >= 3 and w.lower() not in STOPWORDS}


def jaccard(a: str, b: str) -> float:
    ta, tb = content_tokens(a), content_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class TitleCheck(BaseModel):
    hook: str
    title: str
    source: TitleSource
    passed: bool
    reasons: List[str] = Field(default_factory=list)
    score: float = 0.0
    grounded_ratio: Optional[float] = None
    numbers: List[str] = Field(default_factory=list)


class TitleValidator:
    """Deterministic gate every title must pass, regardless of who drafted it."""

    def __init__(
        self,
        sheet: HookSheet,
        registry_titles: Iterable[str] = (),
        alt_titles: Iterable[str] = (),
        evidence_check: Optional[Callable[[str], bool]] = None,
    ):
        self.sheet = sheet
        self.registry_hooks = [strip_suffix(t) for t in registry_titles if t]
        self.forbidden_phrases = [t.casefold() for t in [sheet.comic_title, *alt_titles] if t and len(t) >= 4]
        # Case-sensitive so names like "Will" or "Hope" do not match ordinary words.
        self.name_patterns = [re.compile(rf"\b{re.escape(n)}\b") for n in sheet.character_names if len(n) >= 2]
        self.evidence_check = evidence_check
        corpus_text = " ".join(sheet.corpus)
        # The official synopsis is publisher text about this story, so it grounds titles like narration does.
        self.corpus_numbers = {n.replace(",", "") for n in NUMBER_RE.findall(f"{corpus_text} {sheet.synopsis}")}
        corpus_words = WORD_RE.findall(corpus_text.lower())
        self.corpus_prefixes = {self._prefix(w) for w in corpus_words + WORD_RE.findall(sheet.synopsis.lower())}
        self.central_numbers = sheet.central_numbers
        self.premise_prefixes = premise_prefixes(sheet)
        self.corpus_word_counts = Counter(corpus_words)
        # Lexical grounding only makes sense when narration and titles share a language.
        self.lexical_grounding = sheet.language in ("en", "english") and bool(sheet.corpus)

    @staticmethod
    def _prefix(word: str) -> str:
        return word[:5]

    def _mentions(self, word: str) -> int:
        """Exact-word count including the simple plural/singular form."""
        counts = self.corpus_word_counts
        other = word[:-1] if word.endswith("s") else word + "s"
        return counts.get(word, 0) + counts.get(other, 0)

    def _grounded_ratio(self, hook: str) -> Optional[float]:
        words = [w.lower() for w in WORD_RE.findall(hook)]
        content = [w for w in words if len(w) >= 4 and w not in UNGROUNDED_OK_WORDS and w not in STOPWORDS]
        if not content:
            return None
        grounded = sum(1 for w in content if self._prefix(w) in self.corpus_prefixes)
        return grounded / len(content)

    def check(self, hook: str, source: TitleSource) -> TitleCheck:
        hook = re.sub(r"\s+", " ", strip_suffix(hook)).strip()
        title = f"{hook}{TITLE_SUFFIX}"
        reasons: List[str] = []

        if len(hook) > HOOK_MAX_CHARS:
            reasons.append(f"hook_too_long:{len(hook)}>{HOOK_MAX_CHARS}")
        if len(hook) < HOOK_MIN_CHARS:
            reasons.append(f"hook_too_short:{len(hook)}")
        if len(title) > TITLE_HARD_MAX:
            reasons.append("title_over_100_chars")
        if re.search(r"[\[\]{}]", hook):
            reasons.append("template_artifact")

        window = hook[:NICHE_KEYWORD_WINDOW].lower()
        if not any(re.search(rf"\b{re.escape(k)}\b", window) for k in NICHE_KEYWORDS):
            reasons.append("no_niche_keyword_early")

        caps = [w for w in WORD_RE.findall(hook) if len(w) >= 2 and w.isupper()]
        if len(caps) > MAX_CAPS_WORDS:
            reasons.append(f"too_many_caps_words:{len(caps)}")

        if any(p in hook.casefold() for p in self.forbidden_phrases):
            reasons.append("contains_comic_title")
        if any(p.search(hook) for p in self.name_patterns):
            reasons.append("contains_character_name")

        numbers = [n.replace(",", "") for n in NUMBER_RE.findall(hook)]
        ungrounded_numbers = [n for n in numbers if n not in self.corpus_numbers]
        if ungrounded_numbers and self.sheet.corpus:
            reasons.append(f"ungrounded_numbers:{','.join(ungrounded_numbers)}")

        ratio = self._grounded_ratio(hook) if self.lexical_grounding else None
        if ratio is not None and ratio < MIN_GROUNDED_RATIO:
            reasons.append(f"low_grounding:{ratio:.2f}")
        if self.lexical_grounding:
            missing = sorted({
                w for w in (t.lower() for t in WORD_RE.findall(hook))
                if w in CLAIM_TERMS_REQUIRING_EVIDENCE and self._mentions(w) < CLAIM_TERM_MIN_MENTIONS
            })
            if missing:
                reasons.append(f"claim_not_in_story:{','.join(missing)}")

        if self.evidence_check is not None and not self.evidence_check(title):
            reasons.append("unsupported_claim")

        for published in self.registry_hooks:
            if hook.casefold() == published.casefold() or jaccard(hook, published) >= DUPLICATE_JACCARD:
                reasons.append(f"duplicate_of_published:{published[:40]}")
                break

        passed = not reasons
        return TitleCheck(
            hook=hook,
            title=title,
            source=source,
            passed=passed,
            reasons=reasons,
            score=self._score(hook, numbers, caps, source) if passed else 0.0,
            grounded_ratio=ratio,
            numbers=numbers,
        )

    def _score(self, hook: str, numbers: List[str], caps: List[str], source: TitleSource) -> float:
        score = 0.0
        # Concrete numbers are the strongest pattern in niche winners, but only story-central ones:
        # a one-off number from one late scene promises something the video is not about.
        if any(n in self.central_numbers for n in numbers):
            score += NUMBER_SCORE
        if premise_matches(hook, self.premise_prefixes) >= PREMISE_MIN_STEMS:
            score += PREMISE_SCORE
        if any(re.search(rf"\b{re.escape(k)}\b", hook[:30].lower()) for k in NICHE_KEYWORDS):
            score += 2.0
        if 40 <= len(hook) <= HOOK_MAX_CHARS:
            score += 1.0
        if 1 <= len(caps) <= 2:
            score += 1.0
        if source == "llm":
            score += 1.0  # story-specific beats generic templates on equal footing
        return score


# =============================================================================
# Selection
# =============================================================================

class TitleSelection(BaseModel):
    titles: List[str]                       # ranked, validated full titles (max 5)
    variants: Dict[str, str]                # A/B/C hypotheses for Test & Compare
    checks: List[TitleCheck]                # every candidate with its verdict (audit trail)
    status: Literal["validated", "no_valid_candidates"]


VARIANT_KEYS = ("variant_a_conflict", "variant_b_paradox", "variant_c_scale")


def select_titles(
    llm_hooks: Sequence[str],
    template_hooks: Sequence[str],
    validator: TitleValidator,
    max_titles: int = 5,
) -> TitleSelection:
    """Validates all candidates, ranks the survivors and picks diverse A/B/C variants."""
    checks: List[TitleCheck] = []
    seen: set[str] = set()
    for source, hooks in (("llm", llm_hooks), ("template", template_hooks)):
        for raw in hooks:
            key = strip_suffix(raw).casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            checks.append(validator.check(raw, source))  # type: ignore[arg-type]

    # Stable sort keeps LLM order as the tie-breaker.
    passed = sorted((c for c in checks if c.passed), key=lambda c: -c.score)

    ranked: List[TitleCheck] = []
    for c in passed:
        if all(jaccard(c.hook, r.hook) < DUPLICATE_JACCARD for r in ranked):
            ranked.append(c)

    variants_pool: List[TitleCheck] = []
    for c in ranked:
        if all(jaccard(c.hook, v.hook) < VARIANT_MAX_JACCARD for v in variants_pool):
            variants_pool.append(c)
        if len(variants_pool) == len(VARIANT_KEYS):
            break
    # Not enough diverse candidates: fill remaining slots with the best ranked ones.
    for c in ranked:
        if len(variants_pool) == len(VARIANT_KEYS):
            break
        if c not in variants_pool:
            variants_pool.append(c)

    variants = {key: variants_pool[i].title for i, key in enumerate(VARIANT_KEYS) if i < len(variants_pool)}
    return TitleSelection(
        titles=[c.title for c in ranked[:max_titles]],
        variants=variants,
        checks=checks,
        status="validated" if ranked else "no_valid_candidates",
    )


# =============================================================================
# Published-title registry
# =============================================================================

class RegistryEntry(BaseModel):
    title: str
    comic_title: str = ""            # "" = imported from Studio, series unknown
    from_ep: Optional[int] = None
    to_ep: Optional[int] = None
    video_id: str = ""
    source: Literal["studio_csv", "upload_kit"] = "upload_kit"
    recorded_at: str = ""
    chapters: List[str] = Field(default_factory=list)  # chapter names shipped with this kit


class TitleRegistry(BaseModel):
    entries: List[RegistryEntry] = Field(default_factory=list)
    path: str = Field(default=DEFAULT_REGISTRY_PATH, exclude=True)

    @classmethod
    def load(cls, path: str = DEFAULT_REGISTRY_PATH) -> "TitleRegistry":
        if not os.path.isfile(path):
            return cls(path=path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            registry = cls.model_validate(data)
        except (OSError, json.JSONDecodeError, ValueError) as err:
            # Refuse to silently start empty: that would disable duplicate protection.
            raise RuntimeError(f"Title registry at {path} is unreadable: {err}") from err
        registry.path = path
        return registry

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def titles_for_dedup(self, comic_title: str) -> List[str]:
        """Titles a new video must not duplicate: everything except this comic's own kit drafts."""
        own = comic_title.strip().casefold()
        return [
            e.title for e in self.entries
            if not (e.source == "upload_kit" and e.comic_title.strip().casefold() == own)
        ]

    def chapter_names_for_dedup(self, comic_title: str) -> List[str]:
        """Chapter names shipped with other comics' kits (two stories once shared identical chapters)."""
        own = comic_title.strip().casefold()
        return [c for e in self.entries if e.comic_title.strip().casefold() != own for c in e.chapters]

    def record_kit_title(
        self, title: str, comic_title: str, from_ep: int, to_ep: int, chapters: Sequence[str] = (),
    ) -> None:
        """Stores the chosen kit title, replacing earlier drafts for the same comic and range."""
        self.entries = [
            e for e in self.entries
            if not (e.source == "upload_kit" and e.comic_title == comic_title
                    and e.from_ep == from_ep and e.to_ep == to_ep)
        ]
        self.entries.append(RegistryEntry(
            title=title, comic_title=comic_title, from_ep=from_ep, to_ep=to_ep,
            source="upload_kit", recorded_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            chapters=list(chapters),
        ))

    def import_studio_csv(self, csv_path: str) -> int:
        """Imports published titles from a YouTube Studio 'Content' export. Returns new entries count."""
        if os.path.isdir(csv_path):
            csv_path = os.path.join(csv_path, "Table data.csv")
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "Video title" not in reader.fieldnames:
                raise ValueError(f"{csv_path} has no 'Video title' column (expected a Studio Content export)")
            existing = {(e.video_id, e.title) for e in self.entries}
            added = 0
            for row in reader:
                title = (row.get("Video title") or "").strip()
                video_id = (row.get("Content") or "").strip()
                if not title or video_id.lower() == "total" or (video_id, title) in existing:
                    continue
                self.entries.append(RegistryEntry(
                    title=title, video_id=video_id, source="studio_csv",
                    recorded_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                ))
                existing.add((video_id, title))
                added += 1
        return added


def _main(argv: List[str]) -> int:
    if len(argv) == 2 and argv[0] == "import-studio-csv":
        registry = TitleRegistry.load()
        added = registry.import_studio_csv(argv[1])
        registry.save()
        print(f"Imported {added} published titles into {registry.path} (total {len(registry.entries)}).")
        return 0
    print('Usage: python title_engine.py import-studio-csv "<Studio Content export folder or Table data.csv>"')
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
