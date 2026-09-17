from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PRIORITY_SUM_TOLERANCE = 0.02


class RecapImage(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    page: int = Field(ge=1)
    priority: float = Field(gt=0.0, le=1.0)

    @field_validator("priority")
    @classmethod
    def priority_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("priority must be finite")
        return value


HANGING_END_WORDS = {
    # Prepositions
    "in", "on", "at", "to", "for", "with", "from", "by", "of", "about", "into", "through",
    "across", "towards", "toward", "upon", "against", "along", "under", "over", "behind",
    "between", "without", "onto", "off", "near", "above", "below",
    # Conjunctions
    "and", "but", "or", "so", "because", "while", "as", "that", "which", "when", "although",
    "though", "if", "unless", "since", "after", "before", "whether", "whereas",
    # Determiners / Articles / Possessives
    "a", "an", "the", "their", "his", "her", "its", "my", "our", "your", "this", "that", "these", "those",
    "every", "each", "some", "any", "no",
    # Relative / Interrogative pronouns
    "who", "whom", "whose", "which", "where", "why", "how",
    # Incomplete transitive / linking / auxiliary verbs
    "is", "was", "are", "were", "been", "be", "being", "drops", "drop", "lays", "lay",
    "turns", "turn", "reaches", "reach", "takes", "take", "gives", "give", "makes", "make",
    "finds", "find", "sees", "see", "holds", "hold", "starts", "start", "begins", "begin",
    "awakens", "awaken", "seems", "seem", "looks", "look", "becomes", "become", "has", "have", "had",
}

CONTINUATION_START_WORDS = {
    "and", "but", "or", "so", "because", "which", "while", "as", "that", "although", "whereas",
    "lays", "shuts", "drops", "rushes", "reveals", "obliterates", "charges", "enters", "notices",
    "watches", "steps", "takes", "draws", "fires", "unleashes", "kicks", "punches", "slams",
    "locks", "grabs", "pulls", "opens", "decides", "realizes", "dispatches", "orders", "brings",
    "abilities", "powers", "skills", "weapons", "supplies", "rations", "territory", "bunker",
}


def sanitize_recap_speech(speech: str, is_first_segment: bool = False) -> str:
    """
    Sanitizes narration speech text by:
    1. Stripping unwanted manga OCR dialogue prefixes (e.g. 'Sir,', 'Ah,', 'Ugh,', 'Wait,', 'Hey,').
    2. Stripping hallucinated double-title words like 'Sir Panic' -> 'Panic'.
    3. Filtering leaked single-letter placeholders (e.g. 'Meanwhile, A turns...' -> 'Meanwhile, he turns...').
    4. Sanitizing first-person slips in narration ('I had to' -> 'He had to').
    5. Ensuring proper sentence capitalization.
    6. Normalizing ending punctuation: replacing trailing ',' or ':' with '.'.
    7. Ensuring the opening hook (first segment) is a complete, well-formed sentence.
    """
    if not speech or not isinstance(speech, str):
        return ""

    s = speech.strip()

    # 1. Strip dialogue vocatives / OCR speech bubble prefixes at start
    s = re.sub(r"^(?:Sir|Ah|Ugh|Wait|Hey|Look|Listen|Damn|Wait a minute|Um|Oh)\s*[,:\-]\s*", "", s, flags=re.IGNORECASE)

    # 2. Fix known OCR text glitch: "Sir Panic" -> "Panic"
    s = re.sub(r"\bSir\s+Panic\b", "Panic", s, flags=re.IGNORECASE)

    # 3. Strip any leftover brackets or markdown artifacts
    s = re.sub(r"[\*\_`]", "", s).strip()

    if not s:
        return ""

    # 4. Filter single-letter character placeholder leaks (e.g. "Meanwhile, A turns..." -> "Meanwhile, he turns...")
    s = re.sub(
        r"\b((?:Meanwhile|Then|Suddenly|Next|Soon|Afterwards|However|Later|Instantly|Quickly|Quietly|Slowly),\s+)A\s+(?=(?:turns|looks|steps|draws|fires|moves|grabs|holds|strikes|attacks|runs|walks|discovers|finds|decides|realizes|is|was|has|had|orders|reaches|confronts)\b)",
        r"\1he ",
        s,
    )
    s = re.sub(
        r"^A\s+(?=(?:turns|looks|steps|draws|fires|moves|grabs|holds|strikes|attacks|runs|walks|discovers|finds|decides|realizes|is|was|has|had|orders|reaches|confronts)\b)",
        "He ",
        s,
    )
    s = re.sub(
        r"\bA\s+(?=(?:turns|steps|draws|fires|grabs|strikes|attacks|discovers|realizes)\b)",
        "he ",
        s,
    )

    # 5. Sanitize first-person POV slips in narration
    s = re.sub(r"\bI\s+(?:can\'t|cannot)\s+afford\b", "he cannot afford", s, flags=re.IGNORECASE)
    s = re.sub(r"\bI\s+(?:couldn\'t|could\s+not)\s+afford\b", "he could not afford", s, flags=re.IGNORECASE)
    s = re.sub(r"\bI\s+(?:have|need)\s+to\b", "he has to", s, flags=re.IGNORECASE)
    s = re.sub(r"\bI\s+(?:had|needed)\s+to\b", "he had to", s, flags=re.IGNORECASE)
    s = re.sub(r"\bI\s+(?:realize|realized)\b", "he realized", s, flags=re.IGNORECASE)
    s = re.sub(r"\bI\s+(?:think|thought)\b", "he thought", s, flags=re.IGNORECASE)

    # 6. Capitalize first character
    s = s[0].upper() + s[1:]

    # 7. Normalize trailing punctuation
    if s.endswith(",") or s.endswith(":"):
        s = s[:-1].strip() + "."
    elif not any(s.endswith(p) for p in [".", "!", "?", '"', "'", "…", "..."]):
        s = s + "."

    return s


def _extract_image_dicts(images: Any) -> list[dict[str, Any]]:
    res = []
    if not isinstance(images, list):
        return res
    for img in images:
        if isinstance(img, dict) and "page" in img:
            res.append({"page": int(img["page"]), "priority": float(img.get("priority", 1.0))})
        elif hasattr(img, "page"):
            res.append({"page": int(getattr(img, "page")), "priority": float(getattr(img, "priority", 1.0))})
    return res


def _get_speech_words(speech: str) -> list[str]:
    cleaned = re.sub(r"[^\w\s]", " ", speech)
    return [w for w in cleaned.split() if w]


def is_fragmented_pair(s_prev: dict[str, Any], s_curr: dict[str, Any]) -> bool:
    speech1 = str(s_prev.get("speech", "")).strip()
    speech2 = str(s_curr.get("speech", "")).strip()
    if not speech1 or not speech2:
        return False

    words1 = _get_speech_words(speech1)
    words2 = _get_speech_words(speech2)
    if not words1 or not words2:
        return False

    last_word1 = words1[-1].lower()
    first_word2 = words2[0].lower()

    # 1. Last word of previous segment is a hanging word (preposition, conjunction, article, possessive, or dangling verb)
    if last_word1 in HANGING_END_WORDS:
        return True

    # 2. Next segment starts with a lowercase letter in raw string
    if speech2[0].islower():
        return True

    # 3. Next segment starts with continuation conjunction or subjectless 3rd-person singular verb
    if first_word2 in CONTINUATION_START_WORDS and (len(words1) <= 6 or not any(speech1.endswith(p) for p in [".", "!", "?", '"'])):
        return True

    return False


def _merge_fragmented_speeches(speech1: str, speech2: str) -> str:
    s1 = speech1.strip()
    s2 = speech2.strip()
    
    # Strip trailing punctuation from s1
    s1_clean = re.sub(r"[\.,;:!\?\-\s]+$", "", s1)
    
    words1 = _get_speech_words(s1_clean)
    last_word1 = words1[-1].lower() if words1 else ""
    
    words2 = _get_speech_words(s2)
    first_word2 = words2[0].lower() if words2 else ""
    
    if last_word1 in {"drops", "drop", "stops", "stop", "turns", "turn"} and first_word2 in CONTINUATION_START_WORDS:
        connector = " and "
    else:
        connector = " "
        
    if s2 and s2[0].isupper() and (first_word2 in CONTINUATION_START_WORDS or last_word1 in HANGING_END_WORDS):
        s2_clean = s2[0].lower() + s2[1:]
    else:
        s2_clean = s2

    merged = f"{s1_clean}{connector}{s2_clean}".strip()
    return sanitize_recap_speech(merged)


def stitch_fragmented_recap_segments(
    segments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Auto-heals fragmented sentences / enjambments across recap segments by stitching
    incomplete clauses with their continuations and merging image page specs.
    """
    if not isinstance(segments, list) or len(segments) < 2:
        return segments

    stitched = []
    i = 0
    while i < len(segments):
        curr = dict(segments[i])
        
        while i + 1 < len(segments) and is_fragmented_pair(curr, segments[i + 1]):
            nxt = segments[i + 1]
            merged_speech = _merge_fragmented_speeches(
                str(curr.get("speech", "")),
                str(nxt.get("speech", ""))
            )
            
            imgs_curr = _extract_image_dicts(curr.get("images", []))
            imgs_nxt = _extract_image_dicts(nxt.get("images", []))
            
            seen_pages = set()
            combined_imgs = []
            for img in imgs_curr + imgs_nxt:
                p = img["page"]
                if p not in seen_pages:
                    seen_pages.add(p)
                    combined_imgs.append(img)
            
            normalized_imgs = normalize_recap_priorities(combined_imgs) if combined_imgs else imgs_curr
            
            curr["speech"] = merged_speech
            curr["images"] = normalized_imgs
            i += 1
            
        stitched.append(curr)
        i += 1
        
    return stitched


class RecapSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    speech: str = Field(min_length=1)
    images: list[RecapImage] = Field(min_length=1)

    @field_validator("speech")
    @classmethod
    def speech_must_not_be_blank(cls, value: str) -> str:
        sanitized = sanitize_recap_speech(value)
        if not sanitized:
            raise ValueError("speech must not be blank")
        return sanitized

    @model_validator(mode="after")
    def validate_images(self) -> "RecapSegment":
        pages = [image.page for image in self.images]
        if len(pages) != len(set(pages)):
            raise ValueError("image pages must be unique within a segment")
        total = sum(image.priority for image in self.images)
        if not math.isfinite(total) or round(abs(total - 1.0), 10) > PRIORITY_SUM_TOLERANCE:
            raise ValueError("image priorities must sum to 1.0")
        return self


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _extract_segment_pages(seg: Any) -> list[int]:
    """Helper to extract integer page numbers from dict or RecapSegment."""
    if isinstance(seg, dict):
        images = seg.get("images", [])
        pages = []
        for img in images:
            if isinstance(img, dict) and "page" in img:
                try:
                    pages.append(int(img["page"]))
                except (ValueError, TypeError):
                    pass
        return pages
    elif hasattr(seg, "images"):
        pages = []
        for img in getattr(seg, "images", []):
            if hasattr(img, "page"):
                try:
                    pages.append(int(getattr(img, "page")))
                except (ValueError, TypeError):
                    pass
        return pages
    return []


def detect_recap_loop(segments: list[Any], *, max_page: int | None = None) -> tuple[bool, int | None]:
    """
    Detects if the recap contains a chronological loop / restart
    (where the story reached a high page, then suddenly resets back to early pages <= 3
    and continues climbing, indicating an AI repetition loop).
    Returns (has_loop, loop_start_index).
    """
    if not isinstance(segments, list) or len(segments) < 8:
        return False, None

    peak_page = 0
    min_peak = 12 if max_page is None else max(10, int(max_page * 0.35))

    for idx, seg in enumerate(segments):
        pages = _extract_segment_pages(seg)
        if not pages:
            continue
        cur_min = min(pages)
        cur_max = max(pages)

        # Check if story already progressed to substantial page depth
        # and current segment abruptly plunges back to beginning (<= 3)
        if idx >= 6 and peak_page >= min_peak and cur_min <= 3:
            # Confirm sequence: check subsequent segments to differentiate from a 1-shot flashback
            subsequent_indices = range(idx, min(len(segments), idx + 3))
            subsequent_pages = []
            for sub_idx in subsequent_indices:
                subsequent_pages.extend(_extract_segment_pages(segments[sub_idx]))

            if subsequent_pages and (
                max(subsequent_pages) <= 8
                or (sum(subsequent_pages) / len(subsequent_pages)) <= 6.0
            ):
                return True, idx

        if cur_max > peak_page:
            peak_page = cur_max

    return False, None


def prune_recap_loops(
    segments: list[dict[str, Any]], *, max_page: int | None = None
) -> tuple[list[dict[str, Any]], bool]:
    """
    Auto-heals recaps containing detected narrative loops.
    If a loop is detected at index i:
      - If the first portion (0 to i-1) has >= 10 segments and represents substantial progress,
        prunes the duplicate tail and cleans any concatenated syntax at the boundary.
      - Returns (sanitized_segments, was_pruned).
    """
    has_loop, loop_idx = detect_recap_loop(segments, max_page=max_page)
    if not has_loop or loop_idx is None:
        return segments, False

    primary_portion = [dict(s) for s in segments[:loop_idx]]
    if len(primary_portion) >= 10:
        # Sanitize trailing speech on the boundary segment if it contains leaked prompt/segment syntax
        last_seg = primary_portion[-1]
        speech = str(last_seg.get("speech", ""))
        cleaned_speech = re.sub(r"\s*\[\s*\d+\s*(?:,\s*\d+\s*)*\s*\]\s*[\-:].*$", "", speech).strip()
        if cleaned_speech:
            last_seg["speech"] = cleaned_speech
        return primary_portion, True

    return segments, False


def parse_recap_data(
    value: Any, *, max_page: int | None = None, allow_loops: bool = False
) -> list[RecapSegment]:
    if not isinstance(value, list) or not value:
        raise ValueError("recap must be a non-empty list")
    if all(isinstance(item, dict) for item in value):
        value = stitch_fragmented_recap_segments(value)
    segments = [RecapSegment.model_validate(item) for item in value]
    if max_page is not None:
        if max_page < 1:
            raise ValueError("max_page must be positive")
        for segment in segments:
            for image in segment.images:
                if image.page > max_page:
                    raise ValueError(f"page {image.page} exceeds available page count {max_page}")

    if not allow_loops:
        has_loop, loop_idx = detect_recap_loop(segments, max_page=max_page)
        if has_loop:
            raise ValueError(f"Recap contains a detected narrative loop/repetition at segment {loop_idx}")

    return segments


def load_recap(path: str | Path, *, max_page: int | None = None) -> list[RecapSegment]:
    recap_path = Path(path)
    raw = recap_path.read_text(encoding="utf-8")
    value = json.loads(raw, parse_constant=_reject_non_finite)
    return parse_recap_data(value, max_page=max_page)


def load_recap_dicts(path: str | Path, *, max_page: int | None = None) -> list[dict[str, Any]]:
    return [segment.model_dump(mode="json") for segment in load_recap(path, max_page=max_page)]


def validate_recap_file(path: str | Path, *, max_page: int | None = None) -> bool:
    try:
        load_recap(path, max_page=max_page)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return True


def normalize_recap_priorities(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normalizes a list of image dicts [{"page": p, "priority": ...}]
    guaranteeing that priorities strictly sum to 1.0 (v1.8.0).
    """
    if not images:
        return []
    n = len(images)
    if n == 1:
        return [{"page": int(images[0]["page"]), "priority": 1.0}]
    p_val = round(1.0 / n, 2)
    res = [{"page": int(img["page"]), "priority": p_val} for img in images[:-1]]
    res.append({"page": int(images[-1]["page"]), "priority": round(1.0 - p_val * (n - 1), 2)})
    return res

