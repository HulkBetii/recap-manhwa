"""
Episode-to-episode narration continuity for Stage 5.

1. Episodes are narrated in contiguous chunks (one per worker), each in order, so every episode except a
   chunk's first one is written knowing how the previous episode ended (StoryMemory).
2. A chunk's first episode is narrated blind. Once the previous episode is ready, the LLM rewrites at
   most its first two lines so they pick up where the previous episode stopped ("bridge"). Code keeps
   the rewrite only if it changes nothing else (segment count, pages), stays close in length, adds no
   names and stays grounded in the two episodes' narration; otherwise the original lines stay.

Bridging happens before the episode is queued for TTS, so no audio is ever produced twice.

CLI: python seam_bridge.py report <download_dir>   (prints every seam for review)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

PREVIOUS_TAIL_LINES = 3          # last lines of episode N-1 shown to the LLM
HEAD_WINDOW_LINES = 3            # first lines of episode N shown to the LLM
MAX_BRIDGE_LINES = 2             # lines of episode N that may be rewritten
MAX_ATTEMPTS = 2
LENGTH_TOLERANCE = 0.4           # rewritten line length within +-40% of the original
MAX_LINE_WORDS = 20              # Stage 5 splits narration into segments of <= 20 words
MIN_GROUNDED_RATIO = 0.6
GROUNDING_PREFIX = 5             # "charging" ~ "charge": same stem, as in title grounding
SEAM_FILE = "seam.json"
RECAP_FILE = "recap.json"
RECAP_LOOKBACK_RE = re.compile(
    r"\b(previously|last time|in the last (chapter|episode)|as we saw|recap|welcome back|"
    r"ở tập trước|tập trước|lần trước)\b",
    re.IGNORECASE,
)
LANGUAGE_NAMES = {"en": "English", "vi": "Vietnamese"}

LlmCall = Callable[[str], Awaitable[Optional[str]]]


def partition_contiguous(episodes: Sequence[int], workers: int) -> List[List[int]]:
    """Splits `episodes` into at most `workers` contiguous, non-empty chunks of near-equal size."""
    if workers < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")
    episodes = list(episodes)
    n = min(workers, len(episodes))
    if n == 0:
        return []
    size, extra = divmod(len(episodes), n)
    chunks, start = [], 0
    for i in range(n):
        end = start + size + (1 if i < extra else 0)
        chunks.append(episodes[start:end])
        start = end
    return chunks


# =============================================================================
# Validation
# =============================================================================

class BridgeCheck(BaseModel):
    lines: List[str]
    passed: bool
    reasons: List[str] = Field(default_factory=list)


class BridgeResult(BaseModel):
    status: Literal["bridged", "kept", "skipped"]
    reasons: List[str] = Field(default_factory=list)
    original: List[str] = Field(default_factory=list)
    rewritten: List[str] = Field(default_factory=list)
    attempts: List[BridgeCheck] = Field(default_factory=list)


def _lang(language: str) -> str:
    return (language or "en").lower()[:2]


def _words(text: str, language: str) -> List[str]:
    from title_engine import WORD_RE
    return WORD_RE.findall(text) if _lang(language) == "en" else text.split()


def _tokens(text: str, language: str) -> set[str]:
    if _lang(language) == "en":
        from title_engine import content_tokens
        return content_tokens(text)
    return {w.lower().strip(".,!?;:\"'") for w in text.split() if len(w) >= 2}


def _grounded_ratio(tokens: set[str], source: set[str]) -> float:
    if not tokens:
        return 1.0
    stems = {t[:GROUNDING_PREFIX] for t in source}
    return sum(1 for t in tokens if t in source or t[:GROUNDING_PREFIX] in stems) / len(tokens)


def _invented_names(text: str, corpus: str, bible: Any) -> List[str]:
    """Mid-sentence proper names in `text` that appear nowhere in the two episodes and are unknown to the bible.

    Sentence-initial capitals are not checked: bridges open with "Facing…", "Far from…", "Away from…" far more
    often than with a new name, and an invented opener is still caught by the grounding-ratio rule.
    """
    from series_bible import extract_name_candidates, name_key

    candidates = set(extract_name_candidates([text]))
    known = bible.known_names() if bible is not None else set()
    return sorted(
        n for n in candidates
        if name_key(n) not in known and not re.search(rf"\b{re.escape(n)}\b", corpus)
    )


def validate_bridge(
    lines: List[str],
    original: List[str],
    previous_tail: List[str],
    corpus: str,
    bible: Any = None,
    language: str = "en",
) -> BridgeCheck:
    """`original` are the episode's first lines being replaced 1:1; `corpus` is both episodes' narration."""
    lines = [re.sub(r"\s+", " ", (l or "").strip().strip("\"'")) for l in lines]
    reasons: List[str] = []
    if len(lines) != len(original):
        return BridgeCheck(lines=lines, passed=False, reasons=[f"expected {len(original)} lines, got {len(lines)}"])

    for i, (new, old) in enumerate(zip(lines, original), 1):
        if not new:
            reasons.append(f"line {i} is empty")
            continue
        n_new, n_old = len(_words(new, language)), max(1, len(_words(old, language)))
        limit = max(MAX_LINE_WORDS, n_old)
        if n_new > limit or abs(n_new - n_old) > LENGTH_TOLERANCE * n_old:
            reasons.append(f"line {i} has {n_new} words (original {n_old}, max {limit})")

    text = " ".join(lines)
    if RECAP_LOOKBACK_RE.search(text):
        reasons.append("recap / 'previously' phrasing")
    from premise_pitch import GREETING_RE
    if GREETING_RE.search(text):
        reasons.append("greeting or channel talk")
    if _lang(language) == "en":
        invented = _invented_names(text, corpus, bible)
        if invented:
            reasons.append(f"names not in the story: {', '.join(invented)}")
    source = _tokens(" ".join(original + previous_tail), language)
    ratio = _grounded_ratio(_tokens(text, language), source)
    if ratio < MIN_GROUNDED_RATIO:
        reasons.append(f"only {ratio:.0%} of the words come from the two episodes (min {MIN_GROUNDED_RATIO:.0%})")
    return BridgeCheck(lines=lines, passed=not reasons, reasons=reasons)


# =============================================================================
# Prompt
# =============================================================================

def build_bridge_prompt(
    previous_tail: List[str],
    head: List[str],
    rewrite_count: int,
    cast_block: str = "",
    language: str = "en",
    feedback: Optional[List[str]] = None,
) -> str:
    tail = "\n".join(f"{i}. {t}" for i, t in enumerate(previous_tail, 1))
    opening = "\n".join(f"{i}. {t}" for i, t in enumerate(head, 1))
    retry = ""
    if feedback:
        retry = "\nYOUR PREVIOUS ANSWER WAS REJECTED FOR: " + "; ".join(feedback) + ". Fix every point.\n"
    cast = f"\n{cast_block.strip()}\n" if cast_block.strip() else ""
    return f"""You edit the narration of a long manhwa recap video where chapters play back to back.
{cast}
END OF THE PREVIOUS CHAPTER (already narrated, the viewer just heard it):
{tail}

START OF THE NEXT CHAPTER (written without knowing the lines above):
{opening}
{retry}
Rewrite ONLY lines 1-{rewrite_count} of the next chapter so the video flows as one story:
- If the next chapter continues the same scene, line 1 picks up exactly from the situation the previous chapter left (same place, threat and action).
- If the next chapter opens in a different time or place (flashback, memory, cutaway, time skip), keep that scene, but make line 1 an explicit transition out of the previous situation (e.g. "Face to face with the beast, his mind flashes back to ...") so the viewer knows the scene changed.
- Never repeat or paraphrase events from the previous chapter's lines.
- Keep the facts, names and events of the original lines; you may only change how they are connected and phrased.
- Each line stays about as long as the line it replaces (max {MAX_LINE_WORDS} words), {LANGUAGE_NAMES.get(_lang(language), language)}.
- No "previously", no recap phrasing, no greetings, no new names.
- If a line already flows, return it unchanged.

Return ONLY a JSON array of exactly {rewrite_count} strings.
"""


def parse_bridge_response(text: Optional[str]) -> List[str]:
    if not text:
        return []
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [str(x) for x in data] if isinstance(data, list) else []


# =============================================================================
# Episode I/O
# =============================================================================

def _recap_path(download_dir: str, ep: int) -> str:
    return os.path.join(download_dir, f"episode_{ep}", RECAP_FILE)


def _seam_path(download_dir: str, ep: int) -> str:
    return os.path.join(download_dir, f"episode_{ep}", SEAM_FILE)


def _load_segments(path: str) -> Optional[List[Dict[str, Any]]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, list) and data else None


def _speech(seg: Dict[str, Any]) -> str:
    return str(seg.get("speech", "")).strip()


def _write_json_atomic(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _tail_hash(previous_tail: List[str]) -> str:
    return hashlib.sha256("\n".join(previous_tail).encode("utf-8")).hexdigest()[:16]


async def bridge_episode(
    download_dir: str,
    ep: int,
    llm_call: LlmCall,
    bible: Any = None,
    language: str = "en",
) -> BridgeResult:
    """Bridges episode `ep` onto episode `ep - 1` in place (recap.json + seam.json)."""
    prev = _load_segments(_recap_path(download_dir, ep - 1))
    segments = _load_segments(_recap_path(download_dir, ep))
    if prev is None or segments is None:
        return BridgeResult(status="skipped", reasons=["missing recap.json"])

    previous_tail = [s for s in (_speech(seg) for seg in prev[-PREVIOUS_TAIL_LINES:]) if s]
    rewrite_count = min(MAX_BRIDGE_LINES, len(segments))
    original = [_speech(seg) for seg in segments[:rewrite_count]]
    tail_hash = _tail_hash(previous_tail)

    # Idempotent: the same previous ending was already handled and the opening is still what we left.
    seam_path = _seam_path(download_dir, ep)
    if os.path.exists(seam_path):
        try:
            with open(seam_path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            expected = stored.get("rewritten") if stored.get("status") == "bridged" else stored.get("original")
            if stored.get("previous_tail_hash") == tail_hash and expected == original:
                return BridgeResult(status="skipped", reasons=[f"already {stored.get('status')}"], original=original)
            if stored.get("status") == "bridged" and stored.get("original"):
                original = stored["original"]  # re-bridge from the blind original, not from our own edit
        except (OSError, json.JSONDecodeError) as err:
            logger.warning("Ignoring unreadable %s: %s", seam_path, err)

    from series_bible import render_prompt_block
    head = original + [_speech(seg) for seg in segments[rewrite_count:HEAD_WINDOW_LINES]]
    corpus = " ".join(_speech(s) for s in prev + segments)
    result = BridgeResult(status="kept", original=original)
    feedback: Optional[List[str]] = None
    for _ in range(MAX_ATTEMPTS):
        prompt = build_bridge_prompt(previous_tail, head, rewrite_count, render_prompt_block(bible), language, feedback)
        try:
            raw = await llm_call(prompt)
        except Exception as err:
            logger.warning("Seam bridge LLM call failed for episode %s: %s", ep, err)
            result.reasons = [f"llm_error: {err}"]
            break
        check = validate_bridge(parse_bridge_response(raw), original, previous_tail, corpus, bible, language)
        result.attempts.append(check)
        if check.passed:
            result.status, result.rewritten, result.reasons = "bridged", check.lines, []
            break
        feedback = result.reasons = check.reasons

    if result.status == "bridged" and result.rewritten == original:
        result.status, result.reasons = "kept", ["opening already flows"]
    final_lines = result.rewritten if result.status == "bridged" else original
    for seg, line in zip(segments, final_lines):
        seg["speech"] = line
    _write_json_atomic(_recap_path(download_dir, ep), segments)
    _write_json_atomic(seam_path, {
        "episode": ep,
        "status": result.status,
        "previous_tail_hash": tail_hash,
        "previous_tail": previous_tail,
        "original": original,
        "rewritten": result.rewritten,
        "reasons": result.reasons,
        "attempts": [a.model_dump() for a in result.attempts],
    })
    return result


# =============================================================================
# Review CLI
# =============================================================================

def seam_report(download_dir: str) -> str:
    eps = sorted(
        int(d.split("_", 1)[1]) for d in os.listdir(download_dir)
        if d.startswith("episode_") and d.split("_", 1)[1].isdigit()
    )
    out: List[str] = []
    for ep in eps[1:]:
        prev, cur = _load_segments(_recap_path(download_dir, ep - 1)), _load_segments(_recap_path(download_dir, ep))
        if prev is None or cur is None:
            continue
        status = "no seam.json (narrated with context, or before bridging existed)"
        if os.path.exists(_seam_path(download_dir, ep)):
            with open(_seam_path(download_dir, ep), "r", encoding="utf-8") as f:
                seam = json.load(f)
            status = seam.get("status", "?") + (f" ({'; '.join(seam['reasons'])})" if seam.get("reasons") else "")
        out.append(f"=== Episode {ep - 1} -> {ep}: {status}")
        out.extend(f"  [{ep - 1}] {_speech(s)}" for s in prev[-2:])
        out.extend(f"  [{ep}] {_speech(s)}" for s in cur[:2])
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "report":
        print("Usage: python seam_bridge.py report <download_dir>", file=sys.stderr)
        sys.exit(2)
    sys.stdout.reconfigure(encoding="utf-8")  # Vietnamese narration on a Windows console
    print(seam_report(sys.argv[2]))
