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

    speech: str = Field(min_length=1)
    images: list[RecapImage] = Field(min_length=1)

    @field_validator("speech")
    @classmethod
    def speech_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("speech must not be blank")
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

