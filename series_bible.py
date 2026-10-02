"""
Series Bible — single source of truth for character names across the pipeline.

Why it exists: Stage 5 narrates episodes in parallel, so episode N often starts before
episode N-1 has produced any rolling context. Without a cast fixed up-front, the VLM
invents or leaks placeholder names (e.g. "Paran") and the protagonist's name drifts
between episodes, intro, chapters and YouTube metadata.

Lifecycle:
  1. Bootstrap once, sequentially, before Stage 5 dispatches episodes
     (user-provided identity > LLM cast extraction from the first PDFs > inference).
  2. Inject `render_prompt_block()` into every Stage 5 prompt.
  3. Run `normalize_segments()` + `observe_episode()` on every new recap.json.
  4. Reuse `normalize_text()` / `load_bible()` for intro hooks and metadata.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

BIBLE_FILENAME = "series_bible.json"

# Names the VLM has been observed to emit when it does not know the protagonist.
DEFAULT_PLACEHOLDER_NAMES = ["Paran"]

# Bracketed template leaks such as "[MC name]" or "[Protagonist]".
BRACKET_PLACEHOLDER_RE = re.compile(
    r"\[\s*(?:mc|main character|protagonist|hero)(?:\s*name)?\s*\]", re.IGNORECASE
)

# Promotion thresholds for names discovered in narration after bootstrap.
OBSERVED_MIN_MENTIONS = 5
OBSERVED_MIN_EPISODES = 2

# An episode is flagged as drifting when the protagonist is never named but an
# unknown name dominates the narration at least this many times.
DRIFT_MIN_RIVAL_MENTIONS = 5

MAX_BOOTSTRAP_CHARACTERS = 12
MAX_PROMPT_OBSERVED_NAMES = 10

# Capitalized words that commonly appear mid-sentence but are not character names.
NON_NAME_TOKENS = {
    "I", "I'm", "I'll", "I've", "I'd", "OK", "TV", "SSS", "S-Rank",
    "Mr", "Mrs", "Ms", "Sir", "Madam", "Dr", "God", "Lord", "Lady", "King", "Queen",
    "Prince", "Princess", "President", "General", "Commander", "Captain", "Colonel",
    "Major", "Lieutenant", "Sergeant", "Officer", "Professor", "Doctor", "Chairman",
    "Director", "Chief", "Boss", "Minister", "Agent", "Detective", "Master", "Elder",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
    "Earth", "Korea", "Korean", "Seoul", "Japan", "Japanese", "China", "Chinese",
    "America", "American", "Eurasia", "Asia", "Europe",
    "Zombie", "Zombies", "Apocalypse", "System", "Level", "Rank", "Hunter", "Hunters",
    "Guild", "Gate", "Dungeon", "Tower", "Floor", "Day", "Night",
    "Corporal", "Private", "Soldier", "Soldiers", "Army", "Navy", "Police", "Group", "Team",
    "Squad", "Unit", "Base", "Garrison", "Station", "Shelter", "Hospital", "Church", "Mall",
    "Olympic", "Kevlar",
    "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
}

# A capitalized token preceded by a lowercase word, digit or clause punctuation is
# almost always a proper noun in English narration (sentence starts are excluded).
MID_SENTENCE_NAME_RE = re.compile(r"(?<=[a-z0-9,;:] )([A-Z][a-z]{2,}(?:-[A-Z]?[a-z]+)?)\b")

def name_key(name: str) -> str:
    """Spelling-insensitive key: romanizations vary in hyphens/spaces ("Min-gu" == "Mingu")."""
    return re.sub(r"[\s\-']", "", name).casefold()


def _spelling_variant_pattern(name: str) -> re.Pattern:
    """Matches `name` with optional hyphens/spaces between letters, keeping the first letter's case."""
    chars = re.sub(r"[\s\-']", "", name)
    # First letter stays case-sensitive so common words ("will", "hope") never match names.
    parts = [re.escape(chars[0])] + [
        f"[{c.lower()}{c.upper()}]" if c.isalpha() else re.escape(c) for c in chars[1:]
    ]
    return re.compile(r"\b" + r"[\-\s]?".join(parts) + r"\b")


Gender = Literal["male", "female", "unknown"]
EntrySource = Literal["user", "llm_bootstrap", "inferred", "observed"]


class CharacterEntry(BaseModel):
    name: str = Field(min_length=2)
    aliases: List[str] = Field(default_factory=list)
    role: str = ""
    gender: Gender = "unknown"
    source: EntrySource = "inferred"
    locked: bool = False


class ObservedName(BaseModel):
    mentions: int = 0
    episodes: List[int] = Field(default_factory=list)


class EpisodeNameReport(BaseModel):
    episode: int
    protagonist_mentions: int = 0
    top_unknown_name: Optional[str] = None
    top_unknown_mentions: int = 0
    placeholders_replaced: int = 0
    promoted_names: List[str] = Field(default_factory=list)

    @property
    def mc_drift(self) -> bool:
        return self.protagonist_mentions == 0 and self.top_unknown_mentions >= DRIFT_MIN_RIVAL_MENTIONS


class SeriesBible(BaseModel):
    series_title: str
    setting: str = ""
    protagonist: Optional[CharacterEntry] = None
    characters: List[CharacterEntry] = Field(default_factory=list)
    terms: List[str] = Field(default_factory=list)
    placeholder_blocklist: List[str] = Field(default_factory=lambda: list(DEFAULT_PLACEHOLDER_NAMES))
    observed_names: Dict[str, ObservedName] = Field(default_factory=dict)
    version: int = 1

    @property
    def protagonist_name(self) -> str:
        return self.protagonist.name if self.protagonist else ""

    @property
    def protagonist_gender(self) -> str:
        if not self.protagonist or self.protagonist.gender == "unknown":
            return "auto"
        return self.protagonist.gender

    def known_names(self) -> set[str]:
        """All canonical names and aliases as spelling-insensitive keys (see `name_key`)."""
        names: set[str] = set()
        for entry in self._all_entries():
            names.add(name_key(entry.name))
            names.update(name_key(a) for a in entry.aliases)
            # Multi-word names are also referenced by each part ("Kang Seongho" -> "Seongho").
            names.update(name_key(part) for part in entry.name.split() if len(part) > 2)
        return names

    def first_female_character(self) -> Optional[CharacterEntry]:
        return next((c for c in self.characters if c.gender == "female"), None)

    def _all_entries(self) -> List[CharacterEntry]:
        return ([self.protagonist] if self.protagonist else []) + list(self.characters)


# =============================================================================
# Persistence
# =============================================================================

def bible_path(download_dir: str) -> str:
    return os.path.join(download_dir, BIBLE_FILENAME)


def load_bible(download_dir: Optional[str], comic_title: str = "") -> Optional[SeriesBible]:
    """Loads the bible for this download dir; returns None if absent, corrupt or for another comic."""
    if not download_dir:
        return None
    path = bible_path(download_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            bible = SeriesBible.model_validate(json.load(f))
    except (OSError, json.JSONDecodeError, ValidationError) as err:
        logger.warning("Ignoring unreadable series bible at %s: %s", path, err)
        return None
    if comic_title and bible.series_title.strip().casefold() != comic_title.strip().casefold():
        logger.warning(
            "Ignoring series bible for '%s' (current comic: '%s')", bible.series_title, comic_title
        )
        return None
    return bible


def save_bible(bible: SeriesBible, download_dir: str) -> str:
    """Atomically writes the bible and returns its path."""
    os.makedirs(download_dir, exist_ok=True)
    path = bible_path(download_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(bible.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return path


# =============================================================================
# Bootstrap
# =============================================================================

def _normalize_gender(value: Any) -> Gender:
    v = str(value or "").strip().lower()
    if v in {"male", "m", "man", "boy"}:
        return "male"
    if v in {"female", "f", "woman", "girl"}:
        return "female"
    return "unknown"


def _clean_name(value: Any) -> str:
    name = re.sub(r"\s+", " ", str(value or "")).strip().strip("\"'")
    if len(name) < 2 or BRACKET_PLACEHOLDER_RE.fullmatch(name):
        return ""
    if name.casefold() in {"protagonist", "mc", "unknown", "none", "n/a", "the protagonist"}:
        return ""
    return name


def new_bible(comic_title: str) -> SeriesBible:
    return SeriesBible(series_title=comic_title.strip())


def apply_user_identity(
    bible: SeriesBible,
    ip_context: Optional[Dict[str, Any]] = None,
    protagonist_name: str = "",
    protagonist_gender: str = "",
) -> bool:
    """Applies user-supplied protagonist identity as a locked entry. Returns True if applied."""
    ctx = ip_context if isinstance(ip_context, dict) else {}
    name = _clean_name(ctx.get("protagonist_name") or protagonist_name)
    if not name:
        return False
    gender = _normalize_gender(ctx.get("protagonist_gender") or protagonist_gender)
    bible.protagonist = CharacterEntry(
        name=name, role="protagonist", gender=gender, source="user", locked=True
    )
    setting = str(ctx.get("unique_hook") or ctx.get("setting") or "").strip()
    if setting and not bible.setting:
        bible.setting = setting
    return True


def apply_inferred_protagonist(bible: SeriesBible, name: str, gender: str = "") -> bool:
    """Last-resort protagonist from heuristic inference (e.g. StoryMemory). Never overrides an existing one."""
    clean = _clean_name(name)
    if bible.protagonist is not None or not clean or clean in bible.placeholder_blocklist:
        return False
    bible.protagonist = CharacterEntry(
        name=clean, role="protagonist", gender=_normalize_gender(gender), source="inferred"
    )
    return True


def build_bootstrap_prompt(comic_title: str) -> str:
    """Prompt for a one-shot cast extraction from an episode PDF. Output is JSON only."""
    return f"""You are building a character reference sheet for a narrated recap of the comic "{comic_title}".
Read the attached comic pages and list the cast.

Return ONLY a JSON object, no Markdown, with this exact shape:
{{
  "protagonist": {{"name": "", "aliases": [], "gender": "male|female|unknown"}},
  "characters": [{{"name": "", "aliases": [], "role": "", "gender": "male|female|unknown"}}],
  "setting": "one sentence: era, place and core premise",
  "terms": ["recurring in-world terms such as factions, powers or code names"]
}}

Rules:
- Use names exactly as written in the comic's English text. If names only appear in Korean/Japanese/Chinese, romanize them (Revised Romanization for Korean).
- NEVER invent a name. If the protagonist's name is not shown on these pages, return "" for protagonist.name.
- Characters without a visible name must be omitted (do not list "Soldier 1" or "the mob boss").
- At most {MAX_BOOTSTRAP_CHARACTERS} characters, most important first.
- "role" is a short label such as "best friend", "rival", "mob boss", "squad leader".
"""


def parse_bootstrap_response(text: str) -> Optional[Dict[str, Any]]:
    """Extracts the first JSON object from an LLM response; returns None if none parses."""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def merge_bootstrap(bible: SeriesBible, data: Dict[str, Any]) -> None:
    """Merges an LLM cast extraction into the bible without overriding locked entries."""
    proto = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    proto_name = _clean_name(proto.get("name"))
    if proto_name and proto_name not in bible.placeholder_blocklist:
        if bible.protagonist is None or not bible.protagonist.locked:
            bible.protagonist = CharacterEntry(
                name=proto_name,
                aliases=[a for a in (_clean_name(x) for x in proto.get("aliases") or []) if a],
                role="protagonist",
                gender=_normalize_gender(proto.get("gender")),
                source="llm_bootstrap",
            )

    known = bible.known_names()
    raw_chars = data.get("characters") if isinstance(data.get("characters"), list) else []
    for raw in raw_chars[:MAX_BOOTSTRAP_CHARACTERS]:
        if not isinstance(raw, dict):
            continue
        name = _clean_name(raw.get("name"))
        if not name or name_key(name) in known or name in bible.placeholder_blocklist:
            continue
        bible.characters.append(CharacterEntry(
            name=name,
            aliases=[a for a in (_clean_name(x) for x in raw.get("aliases") or []) if a],
            role=str(raw.get("role") or "").strip()[:60],
            gender=_normalize_gender(raw.get("gender")),
            source="llm_bootstrap",
        ))
        known = bible.known_names()

    setting = str(data.get("setting") or "").strip()
    if setting and not bible.setting:
        bible.setting = setting[:300]

    for term in data.get("terms") or []:
        term_s = str(term).strip()
        if term_s and term_s not in bible.terms:
            bible.terms.append(term_s[:60])


LlmCall = Callable[[str, str, int], Awaitable[Optional[str]]]  # (pdf_path, prompt, episode) -> text
WarnCallback = Callable[[str, int], Awaitable[None]]           # (message, episode)


async def bootstrap_bible(
    comic_title: str,
    download_dir: str,
    episodes: List[int],
    resolve_pdf: Callable[[int], Optional[str]],
    llm_call: LlmCall,
    ip_context: Optional[Dict[str, Any]] = None,
    protagonist_name: str = "",
    max_episodes: int = 3,
    on_warning: Optional[WarnCallback] = None,
) -> Tuple[SeriesBible, bool]:
    """
    Builds the bible before any episode is narrated. Returns (bible, reused_existing).

    Order of authority: existing bible with a protagonist > user identity (locked) >
    LLM cast extraction from the first episode PDFs. Does not save; the caller persists
    after reconciling with StoryMemory.
    """
    existing = load_bible(download_dir, comic_title)
    if existing and existing.protagonist_name:
        return existing, True

    bible = existing or new_bible(comic_title)
    apply_user_identity(bible, ip_context, protagonist_name)

    async def warn(msg: str, ep: int) -> None:
        if on_warning is not None:
            await on_warning(msg, ep)
        else:
            logger.warning(msg)

    for ep in episodes[:max_episodes]:
        pdf_path = resolve_pdf(ep)
        if not pdf_path:
            continue
        try:
            text = await llm_call(pdf_path, build_bootstrap_prompt(comic_title), ep)
        except Exception as err:
            await warn(f"Series Bible: cast extraction failed for episode {ep}: {err}", ep)
            continue
        data = parse_bootstrap_response(text or "")
        if data is None:
            await warn(f"Series Bible: episode {ep} returned no valid JSON; skipped.", ep)
            continue
        merge_bootstrap(bible, data)
        if bible.protagonist_name and bible.characters:
            break
    return bible, False


# =============================================================================
# Prompt injection
# =============================================================================

def render_prompt_block(bible: Optional[SeriesBible]) -> str:
    """Renders the CAST BIBLE section injected into every Stage 5 prompt."""
    if bible is None:
        return ""
    lines: List[str] = []
    if bible.protagonist:
        p = bible.protagonist
        gender = {"male": "male (he/him)", "female": "female (she/her)"}.get(p.gender, "unspecified")
        alias_txt = f"; also called {', '.join(p.aliases)}" if p.aliases else ""
        lines.append(f'- PROTAGONIST: "{p.name}" — {gender}{alias_txt}')
    for c in bible.characters:
        if c.source == "observed":
            continue
        role = f" ({c.role})" if c.role else ""
        alias_txt = f"; also called {', '.join(c.aliases)}" if c.aliases else ""
        lines.append(f'- "{c.name}"{role}{alias_txt}')
    observed = [c.name for c in bible.characters if c.source == "observed"][:MAX_PROMPT_OBSERVED_NAMES]
    if observed:
        # Auto-discovered: may be people or places, so only spelling is enforced.
        lines.append(f"- RECURRING PROPER NOUNS (keep this exact spelling): {', '.join(observed)}")
    if bible.setting:
        lines.append(f"- SETTING: {bible.setting}")
    if bible.terms:
        lines.append(f"- RECURRING TERMS: {', '.join(bible.terms[:15])}")
    if not lines:
        return ""

    blocked = ", ".join(f'"{n}"' for n in bible.placeholder_blocklist)
    return (
        "CAST BIBLE (AUTHORITATIVE — applies to every episode):\n"
        + "\n".join(lines)
        + "\nNAMING RULES:\n"
        "- Use these names with exactly this spelling. Never rename or re-spell a listed character.\n"
        "- A character whose name is not listed and not shown on the page must be described by role "
        "(e.g. \"the squad leader\"), never given an invented name.\n"
        f"- Forbidden placeholder names: {blocked}.\n"
    )


# =============================================================================
# Normalization & observation
# =============================================================================

def normalize_text(text: str, bible: Optional[SeriesBible]) -> tuple[str, int]:
    """Replaces placeholder names and listed aliases with canonical names. Returns (text, replacements)."""
    if not text or bible is None:
        return text, 0
    replacements = 0
    mc = bible.protagonist_name

    if mc:
        for placeholder in bible.placeholder_blocklist:
            if placeholder.casefold() == mc.casefold():
                continue
            text, n = re.subn(rf"\b{re.escape(placeholder)}\b", mc, text)
            replacements += n
        text, n = BRACKET_PLACEHOLDER_RE.subn(mc, text)
        replacements += n

    for entry in bible._all_entries():
        for alias in entry.aliases:
            if alias.casefold() == entry.name.casefold():
                continue
            text, n = re.subn(rf"\b{re.escape(alias)}\b", entry.name, text)
            replacements += n

        # Romanization drift: "Min-gu" / "Min Gu" -> canonical "Mingu"
        variant_hits = 0

        def _to_canonical(m: re.Match, canonical: str = entry.name) -> str:
            nonlocal variant_hits
            if m.group(0) == canonical:
                return canonical
            variant_hits += 1
            return canonical

        text = _spelling_variant_pattern(entry.name).sub(_to_canonical, text)
        replacements += variant_hits
    return text, replacements


def normalize_segments(segments: List[Dict[str, Any]], bible: Optional[SeriesBible]) -> tuple[List[Dict[str, Any]], int]:
    """Normalizes the `speech` field of recap segments. Returns (segments, total replacements)."""
    if bible is None:
        return segments, 0
    total = 0
    result: List[Dict[str, Any]] = []
    for seg in segments:
        if isinstance(seg, dict) and isinstance(seg.get("speech"), str):
            new_speech, n = normalize_text(seg["speech"], bible)
            total += n
            seg = {**seg, "speech": new_speech}
        result.append(seg)
    return result, total


def extract_name_candidates(texts: Iterable[str]) -> Counter:
    """Counts capitalized mid-sentence tokens that look like proper names."""
    counts: Counter = Counter()
    for text in texts:
        for match in MID_SENTENCE_NAME_RE.findall(text or ""):
            if match not in NON_NAME_TOKENS:
                counts[match] += 1
    return counts


def _count_mentions(texts: List[str], names: Iterable[str]) -> int:
    total = 0
    for name in names:
        if not name:
            continue
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        total += sum(len(pattern.findall(t)) for t in texts)
    return total


def _scan_names(bible: SeriesBible, texts: List[str]) -> Tuple[int, Counter]:
    """Returns (protagonist mentions, counts of proper names unknown to the bible)."""
    mc_mentions = 0
    if bible.protagonist:
        mc_names = [bible.protagonist.name, *bible.protagonist.aliases]
        mc_names += [p for p in bible.protagonist.name.split() if len(p) > 2]
        mc_mentions = _count_mentions(texts, set(mc_names))

    known = bible.known_names()
    blocked = {name_key(n) for n in bible.placeholder_blocklist}
    unknown_counts = Counter({
        name: n for name, n in extract_name_candidates(texts).items()
        if name_key(name) not in known and name_key(name) not in blocked
    })
    return mc_mentions, unknown_counts


def observe_episode(
    bible: SeriesBible,
    episode: int,
    segments: List[Dict[str, Any]],
    placeholders_replaced: int = 0,
) -> EpisodeNameReport:
    """
    Records proper names seen in an episode, promotes recurring ones into the bible and
    reports protagonist drift. Mutates `bible`; caller is responsible for locking and saving.
    """
    texts = [s.get("speech", "") for s in segments if isinstance(s, dict)]
    report = EpisodeNameReport(episode=episode, placeholders_replaced=placeholders_replaced)

    report.protagonist_mentions, unknown_counts = _scan_names(bible, texts)
    if unknown_counts:
        top_name, top_n = unknown_counts.most_common(1)[0]
        report.top_unknown_name, report.top_unknown_mentions = top_name, top_n

    for name, n in unknown_counts.items():
        obs = bible.observed_names.setdefault(name, ObservedName())
        obs.mentions += n
        if episode not in obs.episodes:
            obs.episodes.append(episode)
        if obs.mentions >= OBSERVED_MIN_MENTIONS and len(obs.episodes) >= OBSERVED_MIN_EPISODES:
            bible.characters.append(CharacterEntry(name=name, source="observed"))
            report.promoted_names.append(name)

    for name in report.promoted_names:
        bible.observed_names.pop(name, None)
    return report


class NameAudit(BaseModel):
    """Read-only name consistency verdict over the final narration (used by the pre-publish gate)."""
    protagonist: str = ""
    episodes_checked: int = 0
    placeholder_hits: Dict[str, int] = Field(default_factory=dict)
    drift_episodes: List[int] = Field(default_factory=list)


def audit_names(bible: Optional[SeriesBible], episodes: Dict[int, List[str]]) -> NameAudit:
    """Counts leaked placeholder names and protagonist-drift episodes without mutating the bible."""
    audit = NameAudit(protagonist=bible.protagonist_name if bible else "")
    placeholders = list(bible.placeholder_blocklist) if bible else list(DEFAULT_PLACEHOLDER_NAMES)
    placeholders = [p for p in placeholders if p.casefold() != audit.protagonist.casefold()]

    for ep, texts in sorted(episodes.items()):
        audit.episodes_checked += 1
        for p in placeholders:
            hits = _count_mentions(texts, [p])
            if hits:
                audit.placeholder_hits[p] = audit.placeholder_hits.get(p, 0) + hits
        bracket_hits = sum(len(BRACKET_PLACEHOLDER_RE.findall(t)) for t in texts)
        if bracket_hits:
            audit.placeholder_hits["[MC name]"] = audit.placeholder_hits.get("[MC name]", 0) + bracket_hits

        if bible is not None and bible.protagonist:
            mc_mentions, unknown_counts = _scan_names(bible, texts)
            top_n = unknown_counts.most_common(1)[0][1] if unknown_counts else 0
            if mc_mentions == 0 and top_n >= DRIFT_MIN_RIVAL_MENTIONS:
                audit.drift_episodes.append(ep)
    return audit
