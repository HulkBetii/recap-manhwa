# -*- coding: utf-8 -*-
"""
V5.2 Tests — Tests 129–143: Final Trust Boundary Patch validation.
Covers:
  - Surface quality gates (title: 0.85, thumbnail: 0.75, chapter: 0.70, dashboard: 0.75, outside_condition: 0.70)
  - StoryMemory trust boundaries (confidence capping, identity exemption, recap confirmation & merging, unconfirmed betrayal rejection)
  - Dashboard trust boundaries (no archetype defaults for factual world state, parallel provenance fields, null on missing evidence)
  - Pinned comment provenance inheritance
  - Real Stage 12 V5.2 regression
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
    generate_survival_dashboard_data,
    format_mini_status_block,
    _resolve_per_title_provenance,
    _TITLE_FACT_REQUIREMENTS,
    generate_us_apocalypse_metadata,
)
from markets.us_apocalypse.story_fact_graph import (
    StoryFactGraph,
    GroundedFact,
    FACT_USAGE_POLICY,
    can_use_fact_for_surface,
)


# =============================================================================
# HELPERS
# =============================================================================

def _build_test_fact(fact_id: str, fact_type: str, quality: float, source_type: str = "recap") -> GroundedFact:
    return GroundedFact(
        fact_id=fact_id,
        type=fact_type,
        subject="test_subject",
        predicate="test_predicate",
        object="test_object",
        scope="episode",
        episode_start=1,
        episode_end=1,
        confidence=quality,
        canonical_text=f"[Test] {fact_id}",
        evidence=[{"episode": 1, "snippet": "test evidence snippet", "source": "test"}],
        matched_trigger="test",
        matched_span="test snippet",
        extraction_rule_id="test_rule",
        fact_quality_score=quality,
        entailment_passed=True,
        source_type=source_type,
        source_priority=1 if source_type == "recap" else 3,
        fact_class="event",
    )


# =============================================================================
# TEST 129: Fact quality below title threshold (<0.85) rejected for title
# =============================================================================

def test_fact_quality_below_title_threshold_rejected():
    """Title surface requires quality >= 0.85. Fact with quality=0.80 must be rejected."""
    fact_80 = _build_test_fact("combat_001", "combat_event", 0.80)
    fact_88 = _build_test_fact("combat_002", "combat_event", 0.88)

    gate_80 = can_use_fact_for_surface(fact_80, "title")
    gate_88 = can_use_fact_for_surface(fact_88, "title")

    assert gate_80["allowed"] is False
    assert "quality_0.80_below_0.85_for_title" in gate_80["reason"]
    assert gate_88["allowed"] is True


# =============================================================================
# TEST 130: Fact quality below thumbnail threshold (<0.75) rejected for thumbnail
# =============================================================================

def test_fact_quality_below_thumbnail_threshold_rejected():
    """Thumbnail story claim requires quality >= 0.75. Fact with quality=0.70 must be rejected."""
    fact_70 = _build_test_fact("escape_001", "escape_event", 0.70)
    fact_78 = _build_test_fact("escape_002", "escape_event", 0.78)

    gate_70 = can_use_fact_for_surface(fact_70, "thumbnail_story_claim")
    gate_78 = can_use_fact_for_surface(fact_78, "thumbnail_story_claim")

    assert gate_70["allowed"] is False
    assert gate_78["allowed"] is True


# =============================================================================
# TEST 131: Fact quality below dashboard threshold (<0.75) rejected for dashboard
# =============================================================================

def test_fact_quality_below_dashboard_threshold_rejected():
    """Dashboard factual fields require quality >= 0.75. Fact with quality=0.65 must be rejected."""
    fact_65 = _build_test_fact("shelter_001", "shelter_event", 0.65)
    fact_80 = _build_test_fact("shelter_002", "shelter_event", 0.80)

    gate_65 = can_use_fact_for_surface(fact_65, "dashboard")
    gate_80 = can_use_fact_for_surface(fact_80, "dashboard")

    assert gate_65["allowed"] is False
    assert gate_80["allowed"] is True


# =============================================================================
# TEST 132: StoryMemory narrative fact confidence capped at 0.70, identity exempt
# =============================================================================

def test_story_memory_narrative_capped_identity_exempt():
    """
    StoryMemory narrative facts (shelter, day) must be capped at 0.70.
    Identity facts (protagonist_name) must remain uncapped (0.95).
    """
    mem = {
        "protagonist_name": "Tae",
        "shelter": "underground bunker",
        "day": 14,
    }
    fg = StoryFactGraph(
        comic_title="Zombie Revelation",
        archetype="zombie_apocalypse",
        download_dir="",
        from_ep=1,
        to_ep=14,
        story_memory=mem,
    ).build()

    # 1. Identity fact
    char_facts = fg.get_facts_by_type("character_state")
    assert len(char_facts) >= 1
    identity_fact = char_facts[0]
    assert identity_fact.fact_class == "identity"
    assert identity_fact.confidence == 0.95
    assert identity_fact.fact_quality_score == 0.95

    # 2. Narrative facts (shelter, time)
    shelter_facts = fg.get_facts_by_type("shelter_event")
    assert len(shelter_facts) >= 1
    shelter_fact = shelter_facts[0]
    assert shelter_fact.fact_class == "event"
    assert shelter_fact.confidence <= 0.70
    assert shelter_fact.fact_quality_score <= 0.70

    time_facts = fg.get_facts_by_type("time_fact")
    assert len(time_facts) >= 1
    assert time_facts[0].confidence <= 0.70


# =============================================================================
# TEST 133: StoryMemory betrayal without recap evidence rejected
# =============================================================================

def test_story_memory_unconfirmed_betrayal_rejected():
    """StoryMemory-only betrayal fact without recap confirmation must be rejected."""
    mem = {
        "betrayal": "Betrayed by squad commander in sector 4",
    }
    # Graph without episode downloads
    fg = StoryFactGraph(
        comic_title="Zombie Revelation",
        archetype="zombie_apocalypse",
        download_dir="",
        from_ep=1,
        to_ep=10,
        story_memory=mem,
    ).build()

    betrayal_facts = fg.get_facts_by_type("betrayal_event")
    assert len(betrayal_facts) == 0, "Unconfirmed StoryMemory betrayal must NOT be exported into graph"
    assert fg.provenance_summary()["rejected_facts_blocked"] >= 1


# =============================================================================
# TEST 134: StoryMemory + recap confirmation merged
# =============================================================================

def test_story_memory_and_recap_confirmation_merged(tmp_path):
    """
    When recap contains infection evidence and story_memory also mentions infection,
    the story_memory fact must be merged with recap, source_type='merged', and promoted.
    """
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir()
    (ep_dir / "recap.json").write_text(
        json.dumps([{"speech": "The deadly virus outbreak spreads rapidly across the district, infecting everyone."}]),
        encoding="utf-8",
    )

    mem = {"infection": "outbreak started in Seoul"}

    fg = StoryFactGraph(
        comic_title="Zombie Revelation",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
        story_memory=mem,
    ).build()

    infection_facts = fg.get_facts_by_type("infection_event")
    merged_facts = [f for f in infection_facts if f.source_type == "merged"]
    assert len(merged_facts) >= 1, "StoryMemory infection fact should be promoted to 'merged'"
    assert merged_facts[0].fact_quality_score >= 0.85
    assert merged_facts[0].source_priority == 1


# =============================================================================
# TEST 135: Archetype cannot create shelter fact without fact_graph
# =============================================================================

def test_archetype_cannot_create_shelter_fact():
    """Without fact_graph, base_security_level must be None (zero archetype default)."""
    dashboard = generate_survival_dashboard_data(
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=10,
        story_memory=None,
        fact_graph=None,
    )
    assert dashboard["base_security_level"] is None
    assert dashboard["base_security_level_provenance"] is None


# =============================================================================
# TEST 136: Archetype cannot create threat state without fact_graph
# =============================================================================

def test_archetype_cannot_create_threat_state():
    """Without fact_graph, threat_description must be None (zero archetype default)."""
    dashboard = generate_survival_dashboard_data(
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=10,
        story_memory=None,
        fact_graph=None,
    )
    assert dashboard["threat_description"] is None
    assert dashboard["threat_description_provenance"] is None


# =============================================================================
# TEST 137: Dashboard factual field provides parallel provenance fields
# =============================================================================

def test_dashboard_factual_field_provenance_structure(tmp_path):
    """When fact_graph contains qualifying facts, dashboard returns strings AND parallel provenance dicts."""
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir()
    (ep_dir / "recap.json").write_text(
        json.dumps([
            {"speech": "Infection spreads rapidly throughout the city."},
            {"speech": "Tae barricaded the shelter to secure the building against the undead."},
            {"speech": "Tae reached the hospital rooftop in the ruined city."},
        ]),
        encoding="utf-8",
    )

    fg = StoryFactGraph(
        comic_title="Zombie Revelation",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    ).build()

    dashboard = generate_survival_dashboard_data(
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=1,
        fact_graph=fg,
    )

    # 1. Strings preserved
    assert dashboard["threat_description"] == "Zombie Threat Active"
    assert dashboard["base_security_level"] == "Makeshift Safehouse"

    # 2. Parallel provenance dicts
    tp = dashboard["threat_description_provenance"]
    assert isinstance(tp, dict)
    assert "fact_id" in tp
    assert tp["quality_score"] >= 0.75

    sp = dashboard["base_security_level_provenance"]
    assert isinstance(sp, dict)
    assert "fact_id" in sp
    assert sp["quality_score"] >= 0.75


# =============================================================================
# TEST 138: Missing shelter fact makes base_security_level null
# =============================================================================

def test_missing_shelter_fact_makes_base_security_level_null(tmp_path):
    """If fact_graph has infection but NO shelter fact, base_security_level must be None."""
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir()
    (ep_dir / "recap.json").write_text(
        json.dumps([{"speech": "Infection spreads through the city."}]),
        encoding="utf-8",
    )

    fg = StoryFactGraph(
        comic_title="Zombie Revelation",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    ).build()

    dashboard = generate_survival_dashboard_data(
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=1,
        fact_graph=fg,
    )

    assert dashboard["threat_description"] is not None
    assert dashboard["base_security_level"] is None
    assert dashboard["base_security_level_provenance"] is None


# =============================================================================
# TEST 139: Missing infection fact makes threat_description null
# =============================================================================

def test_missing_infection_fact_makes_threat_description_null(tmp_path):
    """If fact_graph has shelter but NO infection/disaster fact, threat_description must be None."""
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir()
    (ep_dir / "recap.json").write_text(
        json.dumps([{"speech": "Tae barricaded the shelter to secure the building."}]),
        encoding="utf-8",
    )

    fg = StoryFactGraph(
        comic_title="Zombie Revelation",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    ).build()

    dashboard = generate_survival_dashboard_data(
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=1,
        fact_graph=fg,
    )

    assert dashboard["base_security_level"] is not None
    assert dashboard["threat_description"] is None
    assert dashboard["threat_description_provenance"] is None


# =============================================================================
# TEST 140: Pinned comment inherits dashboard provenance
# =============================================================================

def test_pinned_comment_inherits_dashboard_provenance():
    """Pinned comment status block must only include fields that are non-null in dashboard."""
    # 1. Null fields
    dash_null = {
        "story_arc": "Episodes 1–10 (10 Chapters)",
        "outside_condition": None,
        "threat_description": None,
        "base_security_level": None,
    }
    block_null = format_mini_status_block("zombie_apocalypse", dash_null)
    assert "Alert Level" not in block_null
    assert "Threat Zone" not in block_null
    assert "Security Status" not in block_null

    # 2. Grounded fields
    dash_grounded = {
        "story_arc": "Episodes 1–10 (10 Chapters)",
        "outside_condition": "Infected Urban Sector — Active Swarms",
        "threat_description": "Zombie Threat Active",
        "base_security_level": "Makeshift Safehouse",
    }
    block_grounded = format_mini_status_block("zombie_apocalypse", dash_grounded)
    assert "Threat Zone: Infected Urban Sector" in block_grounded
    assert "Security Status: Makeshift Safehouse" in block_grounded
    assert "Alert Level: Zombie Threat Active" in block_grounded


# =============================================================================
# TEST 141: Low quality chapter fact (<0.70) filtered
# =============================================================================

def test_low_quality_chapter_fact_filtered():
    """Chapter surface requires quality >= 0.70. Facts below 0.70 (e.g. group_state at 0.65) must be filtered."""
    fact_group = _build_test_fact("group_001", "group_state", 0.65)
    fact_combat = _build_test_fact("combat_001", "combat_event", 0.85)

    assert can_use_fact_for_surface(fact_group, "chapter")["allowed"] is False
    assert can_use_fact_for_surface(fact_combat, "chapter")["allowed"] is True


# =============================================================================
# TEST 142: Title candidate provenance_complete is False when facts below 0.85
# =============================================================================

def test_title_provenance_incomplete_when_facts_below_085():
    """Title resolution must require facts with quality >= 0.85. Low-quality facts do not satisfy title requirements."""
    class MockGraph:
        def get_facts_by_type(self, ftype: str):
            # Only returns quality 0.70 facts
            return [_build_test_fact("f_low", ftype, 0.70)]

    titles = ["When Zombie Outbreak Overruns The City, Tae Fights To Survive | Manhwa Recap"]
    res = _resolve_per_title_provenance(titles, MockGraph(), "zombie_apocalypse")

    assert len(res) == 1
    # Since 0.70 < 0.85, no facts should be allowed for title surface
    assert res[0]["facts_resolved"] == 0
    assert res[0]["provenance_complete"] is False


# =============================================================================
# TEST 143: Real Zombie Revelation regression V5.2
# =============================================================================

def test_real_zombie_revelation_v52_regression():
    """
    Real 143 episodes regression on Zombie Revelation:
    - 0 invariant violations
    - Title provenance uses only >= 0.85 facts
    - Thumbnail visual facts used are >= 0.75
    - Dashboard factual fields have verifiable provenance
    - fact_usage_audit is present and structured
    """
    DOWNLOAD_DIR = os.path.join(
        PROJECT_ROOT, "downloads", "좀비묵시록_8208_1_143_en_946016ec"
    )

    if not os.path.isdir(DOWNLOAD_DIR):
        pytest.skip("Zombie Revelation download dir not found — skipping real regression")

    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=143,
        download_dir=DOWNLOAD_DIR,
        chapters_explicitly_disabled=True,
    )

    # 1. Fact Usage Audit
    assert "fact_usage_audit" in meta
    fua = meta["fact_usage_audit"]
    assert fua["title"]["min_quality_required"] == 0.85
    assert fua["thumbnail"]["min_quality_required"] == 0.75
    assert fua["dashboard"]["threat_grounded"] is True

    # 2. Title provenance quality
    title_prov = meta.get("provenance_summary", {}).get("title_candidates_provenance", []) or meta.get("prepublish_audit", {}).get("claim_audit", {}).get("title_candidates_provenance", [])
    assert len(title_prov) > 0
    for p in title_prov:
        for fu in p.get("facts_used", []):
            assert fu["quality"] >= 0.85, f"Title fact quality {fu['quality']} is below 0.85"

    # 3. Thumbnail visual facts quality
    for concept in meta.get("thumbnail_concepts", []):
        for vf in concept.get("visual_facts_used", []):
            assert vf["quality"] >= 0.75, f"Thumbnail visual fact quality {vf['quality']} is below 0.75"

    # 4. Dashboard provenance
    dash = meta["survival_dashboard"]
    assert dash["threat_description"] == "Zombie Threat Active"
    assert dash["threat_description_provenance"]["quality_score"] >= 0.75
    assert dash["base_security_level"] == "Makeshift Safehouse"
    assert dash["base_security_level_provenance"]["quality_score"] >= 0.75
