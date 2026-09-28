# -*- coding: utf-8 -*-
"""
Tests for Stage 12 Chapter Grounding Patch V1 (Tests 150-155).
Validates:
- Never invent timestamps: timestamps MUST originate from Stage 11 arc milestones.
- Episode range MUST originate from episode_range field.
- CTR title rewriting preserves underlying event meaning.
- Missing Stage 11 timestamps block chapter creation and emit UNGROUNDED_CHAPTER_BLOCKED.
- Audit output schema: {chapter_title, timestamp, source_episode_range, grounded}.
- Hard fail-closed audit gating on ungrounded chapters.
- Full ingestion of stage11_timeline_and_chapter_markers.json.
"""
from __future__ import annotations

import json
import os
import sys
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from markets.us_apocalypse.metadata import (
    build_narrative_story_chapters,
    validate_packaging_consistency,
    generate_us_apocalypse_metadata,
    EvidenceIndex,
    _build_resource_contrast_concepts,
)


# =============================================================================
# TEST 150: Stage 11 Timestamp Grounding Exact Match (Never Invent Timestamps)
# =============================================================================

def test_stage11_timestamp_grounding_exact_match():
    """
    Test 150: Verifies that timestamps in narrative_chapters strictly originate
    from Stage 11 chapter markers without synthetic calculation or offset invention.
    """
    stage11_milestones = [
        {"timestamp": "00:00", "title": "The Outbreak & Grounded Survival Lens (Ep 1–14)", "episode_range": "1-14", "start_episode": 1, "end_episode": 14},
        {"timestamp": "01:32:56", "title": "Tae Roars The Execution Signal (Ep 15–29)", "episode_range": "15-29", "start_episode": 15, "end_episode": 29},
        {"timestamp": "03:16:04", "title": "Tae Spots Panicked Survivors Clamoring (Ep 30–43)", "episode_range": "30-43", "start_episode": 30, "end_episode": 43},
        {"timestamp": "04:39:58", "title": "Tae Plants His Feet (Ep 44–57)", "episode_range": "44-57", "start_episode": 44, "end_episode": 57},
        {"timestamp": "06:01:33", "title": "Tae Keeps That Frosty Gaze Locked (Ep 58–72)", "episode_range": "58-72", "start_episode": 58, "end_episode": 72},
        {"timestamp": "07:24:31", "title": "Tae Stares In Utter Disbelief (Ep 73–86)", "episode_range": "73-86", "start_episode": 73, "end_episode": 86},
        {"timestamp": "08:26:02", "title": "Tae Pulls The Trigger Point-Blank (Ep 87–100)", "episode_range": "87-100", "start_episode": 87, "end_episode": 100},
        {"timestamp": "09:34:00", "title": "Tae Evaluates The Situation (Ep 101–114)", "episode_range": "101-114", "start_episode": 101, "end_episode": 114},
        {"timestamp": "10:40:16", "title": "Security Checkpoint Lock Down (Ep 115–129)", "episode_range": "115-129", "start_episode": 115, "end_episode": 129},
        {"timestamp": "11:54:50", "title": "The Final Defense Operation (Ep 130–143)", "episode_range": "130-143", "start_episode": 130, "end_episode": 143},
    ]

    narrative = build_narrative_story_chapters(
        chapters=stage11_milestones,
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=143,
    )

    assert len(narrative) == len(stage11_milestones)
    for i, expected in enumerate(stage11_milestones):
        assert narrative[i]["timestamp"] == expected["timestamp"], (
            f"Chapter {i} timestamp mismatch: expected {expected['timestamp']}, got {narrative[i]['timestamp']}"
        )
        assert narrative[i]["grounded"] is True


# =============================================================================
# TEST 151: Episode Range Grounding from episode_range Field
# =============================================================================

def test_stage11_episode_range_grounding():
    """
    Test 151: Verifies that source_episode_range field is preserved directly from
    Stage 11 episode_range.
    """
    stage11_milestones = [
        {"timestamp": "00:00", "title": "The Outbreak (Ep 1–14)", "episode_range": "1-14", "start_episode": 1, "end_episode": 14},
        {"timestamp": "01:32:56", "title": "Counterattack (Ep 15–29)", "episode_range": "15-29", "start_episode": 15, "end_episode": 29},
    ]

    narrative = build_narrative_story_chapters(
        chapters=stage11_milestones,
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=29,
    )

    assert len(narrative) == 2
    assert narrative[0]["source_episode_range"] == "1-14"
    assert narrative[1]["source_episode_range"] == "15-29"
    assert narrative[0]["episode"] == 1
    assert narrative[0]["end_episode"] == 14
    assert narrative[1]["episode"] == 15
    assert narrative[1]["end_episode"] == 29


# =============================================================================
# TEST 152: Ungrounded Chapter (Missing Timestamp) Blocked Fail-Closed
# =============================================================================

def test_ungrounded_chapter_missing_timestamp_blocked():
    """
    Test 152: When chapter input lacks Stage 11 timestamp, build_narrative_story_chapters
    must NOT invent timestamps and must fail closed with UNGROUNDED_CHAPTER_BLOCKED.
    """
    ungrounded_input = [
        {"title": "Episode 1", "episode": 1},  # missing timestamp
        {"title": "Episode 2", "episode": 2},  # missing timestamp
    ]

    narrative = build_narrative_story_chapters(
        chapters=ungrounded_input,
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=2,
    )
    assert narrative == [], "build_narrative_story_chapters must return [] for ungrounded inputs lacking timestamps"

    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=2,
        chapters=ungrounded_input,
    )

    assert meta["narrative_chapters"] == []
    warnings_str = " ".join(meta["prepublish_audit"]["chapter_warnings"])
    assert "UNGROUNDED_CHAPTER_BLOCKED" in warnings_str
    assert meta["prepublish_audit"]["passed"] is False


# =============================================================================
# TEST 153: Stage 12 Chapter Audit Schema Verification
# =============================================================================

def test_chapter_audit_output_schema():
    """
    Test 153: Verifies that prepublish_audit['chapter_audit'] conforms strictly
    to the mandated schema: { chapter_title, timestamp, source_episode_range, grounded }.
    """
    stage11_input = [
        {"timestamp": "00:00", "title": "Outbreak Alpha", "episode_range": "1-10", "start_episode": 1, "end_episode": 10},
        {"timestamp": "00:45:00", "title": "Sector Defense", "episode_range": "11-20", "start_episode": 11, "end_episode": 20},
    ]

    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=20,
        chapters=stage11_input,
        story_memory={"protagonist_name": "Tae"},
    )

    audit = meta["prepublish_audit"]
    assert "chapter_audit" in audit
    chapter_audit = audit["chapter_audit"]
    assert len(chapter_audit) == 2

    for ch_record in chapter_audit:
        assert "chapter_title" in ch_record
        assert "timestamp" in ch_record
        assert "source_episode_range" in ch_record
        assert "grounded" in ch_record
        assert isinstance(ch_record["chapter_title"], str) and len(ch_record["chapter_title"]) > 0
        assert isinstance(ch_record["timestamp"], str) and len(ch_record["timestamp"]) > 0
        assert isinstance(ch_record["source_episode_range"], str) and len(ch_record["source_episode_range"]) > 0
        assert ch_record["grounded"] is True


# =============================================================================
# TEST 154: Packaging Audit Fails When Chapter is Ungrounded
# =============================================================================

def test_packaging_audit_fails_on_ungrounded_chapter():
    """
    Test 154: If any chapter in narrative_chapters is marked ungrounded or has
    an empty timestamp, validate_packaging_consistency must FAIL with UNGROUNDED_CHAPTER_BLOCKED.
    """
    evidence = EvidenceIndex("Zombie Revelation 82-08", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts(
        "Zombie Revelation 82-08", "zombie_apocalypse", "Tae", {"disaster": "Zombie Outbreak"}, evidence
    )

    corrupted_chapters = [
        {"timestamp": "00:00", "title": "Outbreak & Patient Zero (Ep 1)", "episode": 1, "end_episode": 1, "source_episode_range": "1", "grounded": True},
        {"timestamp": "", "title": "Ungrounded Chapter (Ep 2)", "episode": 2, "end_episode": 2, "source_episode_range": "2", "grounded": False},
    ]

    result = validate_packaging_consistency(
        title="When Zombie Outbreak Strikes, Tae Fights To Survive | Manhwa Recap",
        thumbnail_concepts=concepts,
        description="When zombie outbreak strikes, Tae fights to survive.\nOriginal scripted narration.",
        narrative_chapters=corrupted_chapters,
        tags=["manhwa recap", "zombie manhwa", "apocalypse manhwa"],
        archetype="zombie_apocalypse",
        evidence_index=evidence,
    )

    assert result["checks"]["chapters_grounded"] is False
    assert result["is_consistent"] is False
    warnings_str = " ".join(result["warnings"])
    assert "UNGROUNDED_CHAPTER_BLOCKED" in warnings_str


# =============================================================================
# TEST 155: Full Stage 11 JSON Ingestion End-to-End
# =============================================================================

def test_full_stage11_json_ingestion_end_to_end():
    """
    Test 155: Loads stage11_timeline_and_chapter_markers.json directly and generates
    100% grounded Stage 12 YouTube metadata with passing pre-publish audit.
    """
    json_path = os.path.join(PROJECT_ROOT, "stage11_timeline_and_chapter_markers.json")
    if not os.path.isfile(json_path):
        pytest.skip(f"stage11_timeline_and_chapter_markers.json not found at {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        stage11_data = json.load(f)

    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=143,
        chapters=stage11_data,
        story_memory={"protagonist_name": "Tae"},
    )

    narrative = meta["narrative_chapters"]
    assert len(narrative) == 10, f"Expected 10 arc milestone chapters, got {len(narrative)}"
    assert narrative[0]["timestamp"] == "00:00"
    assert narrative[1]["timestamp"] == "01:32:56"
    assert narrative[9]["timestamp"] == "11:54:50"

    # Verify audit compliance
    audit = meta["prepublish_audit"]
    assert audit["chapters_grounded"] is True
    assert audit["first_chapter_is_zero"] is True
    assert len(audit["chapter_audit"]) == 10
    assert all(ch["grounded"] is True for ch in audit["chapter_audit"])
    assert audit["passed"] is True
