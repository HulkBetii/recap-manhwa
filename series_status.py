"""
Series release status — is the comic still running, on hiatus or completed, and what is its latest episode?

Why: the outro must not tell viewers "the story continues" for a finished comic, or "the end" for one that
is still running. Stage 1 reads the status from the series page; this module only interprets the texts so it
can be tested without a browser. It is deliberately conservative: when the evidence is unclear the state is
"unknown" and the outro stays neutral.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Iterable, Literal, Optional, Sequence

from pydantic import BaseModel

logger = logging.getLogger(__name__)

ReleaseState = Literal["ongoing", "hiatus", "completed", "unknown"]
RELEASE_STATUS_FILENAME = "release_status.json"

# Info-area texts (webtoons ".day_info", Naver's first ContentMetaInfo block, MagaPoke ".p-episode__update-txt" /
# ".p-episode__new_update": "次回更新は10/23(金曜)予定です。") are specific to the series,
# so every marker may be used there. Checked in priority order: a completed series may still show a schedule.
INFO_AREA_PATTERNS: Sequence[tuple] = (
    ("completed", re.compile(r"^\s*COMPLETED\s*$|\bstatus\s*:?\s*(completed|finished)\b|완결|完結", re.IGNORECASE)),
    ("hiatus", re.compile(r"\bstatus\s*:?\s*(on\s+)?hiatus\b|\bhiatus\b|휴재|休載", re.IGNORECASE)),
    ("ongoing", re.compile(
        r"\bUP\s+EVERY\s+\w+|\bEVERY\s+\w+DAY\b|\bstatus\s*:?\s*(ongoing|releasing)\b|[월화수목금토일]요웹툰|連載中|次回更新|最新話更新",
        re.IGNORECASE,
    )),
)
# Whole-page text also holds recommendation blocks for other series, so only a labelled "Status" field
# counts there, and only its first occurrence (the series' own info block comes first).
PAGE_STATUS_RE = re.compile(
    r"\bstatus\s*:?\s*(ongoing|releasing|completed|finished|on\s+hiatus|hiatus|dropped)\b", re.IGNORECASE
)
PAGE_STATUS_STATES = {
    "ongoing": "ongoing", "releasing": "ongoing", "completed": "completed", "finished": "completed",
    "hiatus": "hiatus", "on hiatus": "hiatus",
}
EPISODE_HREF_RE = re.compile(r"[?&](?:episode_no|no)=(\d+)\b")
# Explicit episode totals in the info area ("261화 완결", "全120話", "141 episodes").
EPISODE_TOTAL_RE = re.compile(r"(\d+)\s*화\s*완결|全\s*(\d+)\s*話|(\d+)\s+(?:episodes|chapters)\b", re.IGNORECASE)
# List pages show newest episodes first only while a series is running; completed series list the
# oldest first (Naver "여신강림": page 1 ends at 19 of 261), so their first page says nothing about the total.
NEWEST_FIRST_STATES = ("ongoing", "hiatus")
MAX_EVIDENCE_CHARS = 80


class ReleaseStatus(BaseModel):
    state: ReleaseState = "unknown"
    latest_episode: Optional[int] = None
    evidence: str = ""


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def latest_episode_from_hrefs(hrefs: Iterable[Optional[str]]) -> Optional[int]:
    """Highest episode number linked from a series list page (webtoons episode_no=, Naver no=)."""
    numbers = [int(m.group(1)) for h in hrefs if h for m in [EPISODE_HREF_RE.search(h)] if m]
    return max(numbers) if numbers else None


def _explicit_total(texts: Sequence[str]) -> Optional[int]:
    for text in texts:
        match = EPISODE_TOTAL_RE.search(_squash(text))
        if match:
            return int(next(g for g in match.groups() if g))
    return None


def _detect_state(info_texts: Sequence[str], page_text: str) -> tuple:
    for text in info_texts:
        squashed = _squash(text)
        for state, pattern in INFO_AREA_PATTERNS:
            if pattern.search(squashed):
                return state, squashed[:MAX_EVIDENCE_CHARS]
    match = PAGE_STATUS_RE.search(page_text or "")
    if match:
        return PAGE_STATUS_STATES.get(_squash(match.group(1)).lower(), "unknown"), _squash(match.group(0))
    return "unknown", ""


def detect_release_status(
    info_texts: Sequence[str],
    page_text: str = "",
    listed_latest: Optional[int] = None,
    full_list_latest: Optional[int] = None,
) -> ReleaseStatus:
    """`listed_latest`: highest episode linked on the list page (only its first page is loaded).
    `full_list_latest`: highest chapter of a source whose page lists every chapter (Asura, comix...).
    The latest episode is None when no source is trustworthy, so the outro never claims an ending."""
    state, evidence = _detect_state(info_texts, page_text)
    latest = _explicit_total(info_texts) or full_list_latest
    if latest is None and state in NEWEST_FIRST_STATES:
        latest = listed_latest
    return ReleaseStatus(state=state, latest_episode=latest, evidence=evidence)


def save_release_status(download_dir: str, status: ReleaseStatus) -> None:
    """Kept beside the episodes so a later Stage 11/12 re-run on the folder still knows the status."""
    path = os.path.join(download_dir, RELEASE_STATUS_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(status.model_dump(), f, ensure_ascii=False, indent=2)


def load_release_status(download_dir: str, artifacts: Optional[dict] = None) -> ReleaseStatus:
    """Task artifacts first (same run), then the saved file; unknown when neither exists."""
    raw = (artifacts or {}).get("release_status")
    if not raw and download_dir:
        path = os.path.join(download_dir, RELEASE_STATUS_FILENAME)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, ValueError) as err:
                logger.warning("Unreadable %s: %s", path, err)
    try:
        return ReleaseStatus.model_validate(raw) if raw else ReleaseStatus()
    except ValueError as err:
        logger.warning("Invalid release status %r: %s", raw, err)
        return ReleaseStatus()
