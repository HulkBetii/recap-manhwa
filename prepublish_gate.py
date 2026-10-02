"""
Pre-publish gate — one PASS / WARN / FAIL verdict for the YouTube upload kit.

Why: the old audit reported `passed: True` while the kit carried a truncated title
("...One Lone!"), a title the story never delivered, and chapters YouTube silently ignored.
Each check here maps to a defect actually shipped on the channel. FAIL means "do not upload
until fixed"; WARN means "review before upload".
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from chapter_engine import DANGLING_LAST_WORDS
from title_engine import NUMBER_RE, STOPWORDS, UNGROUNDED_OK_WORDS, WORD_RE, strip_suffix

Severity = Literal["fail", "warn"]
GateStatus = Literal["PASS", "WARN", "FAIL"]

MIN_CHAPTERS = 3
OPENING_SEGMENTS = 15            # ~first 1-2 minutes of narration
MIN_PROMISE_COVERAGE = 0.5       # share of the title's key words echoed by the opening
TIMESTAMP_LINE_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?\s")
# Placeholders the description generator emits when a link is unknown, including the
# synthesized playlist URL (".../playlist?list=<slug>-full-recap") which is not a real playlist.
DESCRIPTION_PLACEHOLDER_RE = re.compile(
    r"\[(?:Coming Soon[^\]]*|Watch Ep [^\]]*)\]|https://www\.youtube\.com/playlist\?list=[a-z0-9\-]+-full-recap"
)


class GateCheck(BaseModel):
    id: str
    severity: Severity
    passed: bool
    detail: str = ""


class GateReport(BaseModel):
    status: GateStatus
    checks: List[GateCheck] = Field(default_factory=list)

    @property
    def failures(self) -> List[GateCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "fail"]

    @property
    def warnings(self) -> List[GateCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "warn"]


# =============================================================================
# Individual checks
# =============================================================================

def check_title(title_engine_audit: Dict[str, Any], primary_title_reasons: Sequence[str]) -> List[GateCheck]:
    status = title_engine_audit.get("status", "missing")
    validated = status == "validated"
    duplicate = any(r.startswith("duplicate_of_published") for r in primary_title_reasons)
    detail = "" if validated else f"title engine status '{status}'; primary title issues: {', '.join(primary_title_reasons) or 'n/a'}"
    return [
        GateCheck(id="title_validated", severity="fail", passed=validated, detail=detail),
        GateCheck(
            id="title_not_duplicate", severity="fail", passed=not duplicate,
            detail="primary title matches an already published title" if duplicate else "",
        ),
    ]


def check_names(name_audit: Optional[Any]) -> GateCheck:
    """`name_audit` is a series_bible.NameAudit (protagonist "" when no bible exists)."""
    if name_audit is None:
        return GateCheck(id="names_consistent", severity="warn", passed=False, detail="no narration to audit")
    problems = []
    if name_audit.placeholder_hits:
        problems.append("placeholder names in narration: " + ", ".join(f"{k}x{v}" for k, v in name_audit.placeholder_hits.items()))
    if name_audit.drift_episodes:
        problems.append(f"protagonist '{name_audit.protagonist}' missing while another name dominates in episodes {name_audit.drift_episodes[:10]}")
    if problems:
        return GateCheck(id="names_consistent", severity="fail", passed=False, detail="; ".join(problems))
    if not name_audit.protagonist:
        return GateCheck(
            id="names_consistent", severity="warn", passed=False,
            detail="no Series Bible protagonist: drift between episodes could not be verified",
        )
    return GateCheck(id="names_consistent", severity="fail", passed=True)


def check_chapters(
    narrative_chapters: Sequence[Dict[str, Any]],
    description: str,
    chapters_explicitly_disabled: bool,
) -> GateCheck:
    if chapters_explicitly_disabled:
        return GateCheck(id="chapters_valid", severity="fail", passed=True, detail="chapters disabled on purpose")
    problems: List[str] = []
    if len(narrative_chapters) < MIN_CHAPTERS:
        problems.append(f"{len(narrative_chapters)} chapters (YouTube needs >= {MIN_CHAPTERS})")
    elif narrative_chapters[0].get("timestamp") not in ("00:00", "0:00"):
        problems.append("first chapter does not start at 00:00")

    seen: set[str] = set()
    for ch in narrative_chapters:
        theme = str(ch.get("theme") or ch.get("title") or "").strip()
        key = theme.casefold()
        if key in seen:
            problems.append(f"duplicate chapter '{theme}'")
        seen.add(key)
        words = WORD_RE.findall(theme)
        if words and words[-1].lower() in DANGLING_LAST_WORDS:
            problems.append(f"truncated chapter '{theme}'")

    ts_lines = [ln for ln in description.splitlines() if TIMESTAMP_LINE_RE.match(ln)]
    if any("—" in ln for ln in ts_lines):
        problems.append("em dash in timestamp lines (YouTube ignores these chapters)")
    return GateCheck(id="chapters_valid", severity="fail", passed=not problems, detail="; ".join(problems))


def check_chapter_naming(narrative_chapters: Sequence[Dict[str, Any]]) -> GateCheck:
    """Generic "Part N" names are valid for YouTube but tell viewers nothing about the arc."""
    generic = [str(ch.get("theme")) for ch in narrative_chapters if ch.get("naming_source") == "fallback"]
    return GateCheck(
        id="chapters_descriptive", severity="warn", passed=not generic,
        detail=f"{len(generic)} chapter(s) fell back to generic names: {', '.join(generic[:5])}" if generic else "",
    )


def check_legacy_compliance(flags: Dict[str, bool]) -> GateCheck:
    """Hard YouTube limits and channel policy already computed by the metadata generator."""
    failed = [name for name, ok in flags.items() if not ok]
    return GateCheck(id="youtube_limits", severity="fail", passed=not failed, detail=", ".join(failed))


def check_title_promise_in_opening(primary_title: str, opening_segments: Sequence[str]) -> GateCheck:
    """
    Viewers who click must hear the title's promise early; a mismatch drove the channel's
    0:30-7:50 collapse. Blocking since the premise pitch exists to satisfy it.
    """
    hook = strip_suffix(primary_title)
    key_words = [
        w.lower() for w in WORD_RE.findall(hook)
        if len(w) >= 4 and w.lower() not in UNGROUNDED_OK_WORDS and w.lower() not in STOPWORDS
    ] + [n.replace(",", "") for n in NUMBER_RE.findall(hook)]
    if not key_words or not opening_segments:
        return GateCheck(id="title_promise_in_opening", severity="fail", passed=False,
                         detail="no opening narration or title key words to compare")
    opening = " ".join(opening_segments[:OPENING_SEGMENTS]).lower()
    opening_prefixes = {w[:5] for w in WORD_RE.findall(opening)}
    opening_numbers = {n.replace(",", "") for n in NUMBER_RE.findall(opening)}
    echoed = [w for w in key_words if (w[:5] in opening_prefixes if not w[0].isdigit() else w in opening_numbers)]
    coverage = len(echoed) / len(key_words)
    missing = [w for w in key_words if w not in echoed]
    return GateCheck(
        id="title_promise_in_opening", severity="fail", passed=coverage >= MIN_PROMISE_COVERAGE,
        detail="" if coverage >= MIN_PROMISE_COVERAGE else
        f"only {coverage:.0%} of the title's key words appear in the first {OPENING_SEGMENTS} segments (missing: {', '.join(missing[:6])})",
    )


def check_description_placeholders(description: str) -> GateCheck:
    hits = DESCRIPTION_PLACEHOLDER_RE.findall(description)
    return GateCheck(
        id="description_placeholders", severity="warn", passed=not hits,
        detail=f"replace before upload: {', '.join(hits)}" if hits else "",
    )


# =============================================================================
# Gate
# =============================================================================

def run_prepublish_gate(
    *,
    primary_title: str,
    title_engine_audit: Dict[str, Any],
    primary_title_reasons: Sequence[str],
    name_audit: Optional[Any],
    narrative_chapters: Sequence[Dict[str, Any]],
    description: str,
    chapters_explicitly_disabled: bool,
    legacy_flags: Dict[str, bool],
    opening_segments: Sequence[str],
) -> GateReport:
    checks: List[GateCheck] = []
    checks.extend(check_title(title_engine_audit, primary_title_reasons))
    checks.append(check_names(name_audit))
    checks.append(check_chapters(narrative_chapters, description, chapters_explicitly_disabled))
    if not chapters_explicitly_disabled:
        checks.append(check_chapter_naming(narrative_chapters))
    checks.append(check_legacy_compliance(legacy_flags))
    checks.append(check_title_promise_in_opening(primary_title, opening_segments))
    checks.append(check_description_placeholders(description))

    if any(not c.passed and c.severity == "fail" for c in checks):
        status: GateStatus = "FAIL"
    elif any(not c.passed for c in checks):
        status = "WARN"
    else:
        status = "PASS"
    return GateReport(status=status, checks=checks)


def render_gate_banner(report: GateReport) -> List[str]:
    """Kit header lines; placed first so a failing kit cannot be mistaken for a ready one."""
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[report.status]
    lines = [
        "=" * 80,
        f"{icon} PRE-PUBLISH STATUS: {report.status} "
        f"({len(report.failures)} blocking, {len(report.warnings)} warnings)",
    ]
    for c in report.failures:
        lines.append(f"  ✗ [BLOCKING] {c.id}: {c.detail}")
    for c in report.warnings:
        lines.append(f"  ! [REVIEW]   {c.id}: {c.detail}")
    if report.status == "FAIL":
        lines.append("  → DO NOT UPLOAD until every BLOCKING item is fixed (re-run Stage 12 after fixing).")
    lines.append("=" * 80)
    return lines
