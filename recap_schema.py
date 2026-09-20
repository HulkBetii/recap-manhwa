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


class RecapSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    speech: str = Field(min_length=15, description="Minimum 15 chars to prevent truncated fragments")
    images: list[RecapImage] = Field(min_length=1)

    @field_validator("speech")
    @classmethod
    def speech_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("speech must not be blank")
        if len(stripped) < 15:
            raise ValueError(f"speech is too short ({len(stripped)} chars); likely a truncated fragment")
        # Warn but do not reject if missing sentence-ending punctuation (LLM may omit sometimes)
        return stripped


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
        # and current segment abruptly plunges back to beginning or early pages
        restart_threshold = max(8, int(peak_page * 0.20))
        if idx >= 6 and peak_page >= min_peak and cur_min <= restart_threshold and (peak_page - cur_min) >= 12:
            # Confirm sequence: check subsequent segments to differentiate from a 1-shot flashback
            subsequent_indices = range(idx, min(len(segments), idx + 4))
            subsequent_pages = []
            for sub_idx in subsequent_indices:
                subsequent_pages.extend(_extract_segment_pages(segments[sub_idx]))

            if subsequent_pages and (
                max(subsequent_pages) <= restart_threshold + 8
                or (sum(subsequent_pages) / len(subsequent_pages)) <= (restart_threshold + 5.0)
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
    If a loop is detected at index loop_idx:
      - Evaluates part_a (0 to loop_idx-1) and part_b (loop_idx to end).
      - Selects the superior portion based on maximum page coverage and segment count.
      - Sanitizes boundary syntax and bracket weights.
      - Returns (sanitized_segments, was_pruned).
    """
    has_loop, loop_idx = detect_recap_loop(segments, max_page=max_page)
    if not has_loop or loop_idx is None:
        return segments, False

    part_a = [dict(s) for s in segments[:loop_idx]]
    part_b = [dict(s) for s in segments[loop_idx:]]

    def get_max_page(segs: list[dict[str, Any]]) -> int:
        max_p = 0
        for s in segs:
            for p in _extract_segment_pages(s):
                if p > max_p:
                    max_p = p
        return max_p

    max_p_a = get_max_page(part_a)
    max_p_b = get_max_page(part_b)

    # If Part B has substantially higher page coverage or more segments, Part B is the full re-run
    if max_p_b > max_p_a or (max_p_b == max_p_a and len(part_b) >= len(part_a)):
        chosen = part_b
    elif len(part_a) >= 10:
        chosen = part_a
    else:
        chosen = part_b if len(part_b) > len(part_a) else part_a

    # Sanitize trailing speech on the boundary segment if it contains leaked prompt/segment syntax
    if chosen:
        last_seg = chosen[-1]
        speech = str(last_seg.get("speech", ""))
        cleaned_speech = re.sub(r"\s*\[\s*\d+\s*(?:[:%,\d\s]*)*\s*\]\s*[\-:].*$", "", speech).strip()
        cleaned_speech = re.sub(r'\[\s*\d+\s*(?::\s*\d+%?)?(?:\s*,\s*\d+\s*(?::\s*\d+%?)?)*\s*\]', '', cleaned_speech).strip()
        if cleaned_speech:
            last_seg["speech"] = cleaned_speech

    return chosen, True


def parse_recap_data(
    value: Any, *, max_page: int | None = None, allow_loops: bool = False
) -> list[RecapSegment]:
    if not isinstance(value, list) or not value:
        raise ValueError("recap must be a non-empty list")
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


def auto_split_long_segments(
    segments: list[dict[str, Any]], *, max_words: int = 20
) -> list[dict[str, Any]]:
    """
    Intelligently splits long narration segments (> max_words) into concise, punchy segments
    (8-14 words) at natural semantic boundaries (periods, em-dashes, semicolons, coordinating conjunctions).
    Allocates multi-panel images across the split segments to preserve optimal visual pacing.
    """
    if not isinstance(segments, list) or not segments:
        return segments

    new_segments: list[dict[str, Any]] = []

    for seg in segments:
        speech = str(seg.get("speech", "")).strip()
        words = speech.split()
        if len(words) <= max_words:
            new_segments.append(dict(seg))
            continue

        # Strategy 1: Split at explicit sentence terminators ('. ', '! ', '? ')
        parts = re.split(r"(?<=[.!?])\s+", speech)
        parts = [p.strip() for p in parts if p.strip()]

        # Strategy 2: If it's a single compound run-on sentence, split at conjunctions / dashes / semicolons / commas
        if len(parts) == 1:
            split_patterns = [
                r"\s*(?:—|–|--|―|\u2010|\u2013|\u2014)\s*",
                r"\s*;\s*",
                r",\s+(?:but|and|while|as|before|after|yet|where|then)\s+",
                r",\s+(?=[A-Z])",
                r",\s+",
            ]
            for pat in split_patterns:
                sub_parts = re.split(pat, speech, maxsplit=1)
                if len(sub_parts) == 2 and len(sub_parts[0].split()) >= 4 and len(sub_parts[1].split()) >= 4:
                    p1 = sub_parts[0].strip()
                    p2 = sub_parts[1].strip()
                    if not p1.endswith((".", "!", "?", "—")):
                        p1 += "."
                    if p2 and p2[0].islower():
                        p2 = p2[0].upper() + p2[1:]
                    if not p2.endswith((".", "!", "?")):
                        p2 += "."
                    parts = [p1, p2]
                    break

        if len(parts) >= 2:
            images = seg.get("images", [])
            # Split images between parts if multiple images exist
            if len(images) >= len(parts):
                for idx, part in enumerate(parts):
                    new_seg = dict(seg)
                    new_seg["speech"] = part
                    assigned_img = dict(images[idx])
                    assigned_img["priority"] = 1.0
                    new_seg["images"] = [assigned_img]
                    new_segments.append(new_seg)
            elif len(images) == 2 and len(parts) == 2:
                for idx, part in enumerate(parts):
                    new_seg = dict(seg)
                    new_seg["speech"] = part
                    assigned_img = dict(images[idx])
                    assigned_img["priority"] = 1.0
                    new_seg["images"] = [assigned_img]
                    new_segments.append(new_seg)
            else:
                for part in parts:
                    new_seg = dict(seg)
                    new_seg["speech"] = part
                    new_segments.append(new_seg)
        else:
            new_segments.append(dict(seg))

    return new_segments


def enforce_monotonic_page_order(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Enforces monotonically non-decreasing page ordering across all segments.
    Prevents sudden backward page jumps (e.g. Page 15 -> Page 8 -> Page 16)
    which cause camera timeline rewinds in video assembly.
    """
    if not isinstance(segments, list) or not segments:
        return segments

    sanitized: list[dict[str, Any]] = []
    highest_page = 1

    for seg in segments:
        seg_copy = dict(seg)
        images = seg_copy.get("images", [])
        if isinstance(images, list):
            new_images = []
            for img in images:
                if isinstance(img, dict) and "page" in img:
                    p = int(img["page"])
                    if p < highest_page:
                        # Auto-clamp backward jump to current monotonic peak
                        img_copy = dict(img)
                        img_copy["page"] = highest_page
                        new_images.append(img_copy)
                    else:
                        highest_page = p
                        new_images.append(img)
                else:
                    new_images.append(img)
            seg_copy["images"] = new_images
        sanitized.append(seg_copy)

    return sanitized


def validate_recap_file(path: str | Path, *, max_page: int | None = None) -> bool:
    try:
        load_recap(path, max_page=max_page)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return True
