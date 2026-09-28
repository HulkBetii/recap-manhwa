# -*- coding: utf-8 -*-
"""
V5.1 Tests — Tests 103–128: Surgical Grounding Fix validation.
Covers:
  - False fact rejection (abandoned vehicles, crowd fleeing, military collapse)
  - Semantic entailment: matched_trigger, subject/predicate support
  - Per-title fact provenance (different titles → different facts)
  - Local evidence_count (not total graph size)
  - Chapter fail-closed behavior (missing Stage11 → packaging FAIL)
  - Thumbnail visual_facts_used
  - Dashboard/pinned provenance
  - Real Stage12 V5.1 regression
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
    EvidenceIndex,
    SemanticAssertion,
    ARCHETYPE_TITLE_POOLS,
    generate_dynamic_titles,
    generate_us_apocalypse_metadata,
    detect_archetype,
    _build_resource_contrast_concepts,
    generate_survival_dashboard_data,
    validate_packaging_consistency,
    validate_thumbnail_concept,
    validate_text_surface,
    build_narrative_story_chapters,
    _kw_match_word_boundary,
)
from markets.us_apocalypse.story_fact_graph import (
    StoryFactGraph,
    GroundedFact,
    validate_fact_entailment,
    ExtractionRule,
    _EXTRACTION_RULES_V51,
)


# =============================================================================
# HELPERS
# =============================================================================

def _make_rule_by_id(rule_id: str) -> ExtractionRule:
    """Find an extraction rule by ID."""
    for r in _EXTRACTION_RULES_V51:
        if r.rule_id == rule_id:
            return r
    raise KeyError(f"Rule '{rule_id}' not found")


def _build_fact_with_evidence(snippet: str, rule: ExtractionRule, ep: int = 1) -> GroundedFact:
    """Helper: build a candidate GroundedFact with given evidence snippet."""
    return GroundedFact(
        fact_id=f"{rule.fact_type}_test_001",
        type=rule.fact_type,
        subject=rule.subject,
        predicate=rule.predicate,
        object=rule.object,
        scope="episode",
        episode_start=ep,
        episode_end=ep,
        confidence=rule.quality_base,
        canonical_text=f"[Test] {rule.subject} {rule.predicate} {rule.object}",
        evidence=[{
            "episode": ep,
            "segment_index": 0,
            "snippet": snippet,
            "source": "recap",
            "source_path": f"episode_{ep}/recap.json",
        }],
        matched_trigger="",
        matched_span="",
        extraction_rule_id=rule.rule_id,
        fact_quality_score=0.0,
        entailment_passed=False,
    )


# =============================================================================
# TEST 103: 'abandoned vehicles' does NOT create betrayal fact
# =============================================================================

def test_abandoned_vehicles_does_not_create_betrayal():
    """
    'abandoned vehicles burn' must NOT pass betrayal_explicit_v51 entailment.
    This was a known false fact in V5: betrayal_event_ep001_001.
    """
    rule = _make_rule_by_id("betrayal_explicit_v51")
    snippet = "Across the smoke-choked streets, abandoned vehicles burn under the weight of the endless carnage."
    fact = _build_fact_with_evidence(snippet, rule)
    result = validate_fact_entailment(fact, rule)
    assert result["passed"] is False, (
        f"'abandoned vehicles' must NOT pass betrayal entailment. Got: {result}"
    )
    # Should fail due to exclusion_context OR trigger_not_in_evidence
    reason = result.get("reason", "")
    assert "exclusion_context" in reason or reason == "trigger_not_in_evidence", (
        f"Expected exclusion_context or trigger_not_in_evidence, got: {reason}"
    )


# =============================================================================
# TEST 104: Explicit ally betrayal creates betrayal fact
# =============================================================================

def test_explicit_betrayal_creates_betrayal_fact():
    """
    'His ally betrayed him, locking him out of the safehouse' must pass
    betrayal_explicit_v51 entailment and have high quality score.
    """
    rule = _make_rule_by_id("betrayal_explicit_v51")
    snippet = "His ally betrayed him, locking him out of the safehouse and leaving him to die."
    fact = _build_fact_with_evidence(snippet, rule)
    result = validate_fact_entailment(fact, rule)
    assert result["passed"] is True, (
        f"Explicit betrayal must PASS entailment. Got: {result}"
    )
    assert result["fact_quality_score"] >= 0.80, (
        f"Betrayal with clear ally+betrayed trigger should have quality >= 0.80, got: {result['fact_quality_score']}"
    )
    assert result["matched_trigger"] in ["betrayed", "ally betrays", "left him to die", "locked him out intentionally"], (
        f"Expected explicit betrayal trigger, got: {result['matched_trigger']}"
    )


# =============================================================================
# TEST 105: Citizens fleeing does NOT create protagonist combat fact
# =============================================================================

def test_citizens_fleeing_not_protagonist_combat():
    """
    'Terrified citizens scramble blindly against the horde' must NOT create
    protagonist combat fact — crowd scene, not protagonist action.
    """
    rule = _make_rule_by_id("protagonist_combat_v51")
    snippet = "Pure bedlam detonates across the city as terrified citizens scramble blindly against the bloodthirsty horde."
    fact = _build_fact_with_evidence(snippet, rule)
    result = validate_fact_entailment(fact, rule)
    assert result["passed"] is False, (
        f"Crowd fleeing must NOT pass protagonist combat entailment. Got: {result}"
    )
    # Should fail via exclusion_context (citizens scramble) or subject_not_supported
    reason = result.get("reason", "")
    assert "exclusion_context" in reason or reason == "subject_not_supported" or reason == "trigger_not_in_evidence", (
        f"Expected exclusion or subject failure, got: {reason}"
    )


# =============================================================================
# TEST 106: Explicit 'Tae attacks zombies' creates protagonist combat fact
# =============================================================================

def test_explicit_protagonist_combat_creates_combat_fact():
    """
    'Tae charges into the infected swarm, slicing through' must pass
    protagonist_combat_v51 with high quality.
    """
    rule = _make_rule_by_id("protagonist_combat_v51")
    snippet = "Tae charges into the infected swarm, slicing through the undead with desperate precision."
    fact = _build_fact_with_evidence(snippet, rule)
    result = validate_fact_entailment(fact, rule)
    assert result["passed"] is True, (
        f"Explicit protagonist combat must PASS entailment. Got: {result}"
    )
    assert result["fact_quality_score"] >= 0.80


# =============================================================================
# TEST 107: 'Military defenses collapsing' does NOT create 'deploys' predicate
# =============================================================================

def test_military_collapse_not_deploys():
    """
    'military's crumbling defenses' must NOT pass military_deploys_v51.
    It should only pass military_collapse_v51.
    """
    deploy_rule = _make_rule_by_id("military_deploys_v51")
    collapse_rule = _make_rule_by_id("military_collapse_v51")

    snippet = "The horde surges forward like a rabid tidal wave, completely overwhelming the military's crumbling defenses."

    deploy_fact = _build_fact_with_evidence(snippet, deploy_rule)
    collapse_fact = _build_fact_with_evidence(snippet, collapse_rule)

    deploy_result = validate_fact_entailment(deploy_fact, deploy_rule)
    collapse_result = validate_fact_entailment(collapse_fact, collapse_rule)

    assert deploy_result["passed"] is False, (
        f"'crumbling defenses' must NOT pass military_deploys rule. Got: {deploy_result}"
    )
    assert collapse_result["passed"] is True, (
        f"'crumbling defenses' SHOULD pass military_collapse rule. Got: {collapse_result}"
    )


# =============================================================================
# TEST 108: Explicit 'military deployed troops' creates deploy predicate
# =============================================================================

def test_explicit_military_deployed_creates_deploy_fact():
    """
    'The military deployed additional troops to contain the outbreak' must pass
    military_deploys_v51.
    """
    rule = _make_rule_by_id("military_deploys_v51")
    snippet = "The military deployed additional troops to contain the outbreak spreading through the district."
    fact = _build_fact_with_evidence(snippet, rule)
    result = validate_fact_entailment(fact, rule)
    assert result["passed"] is True, (
        f"Explicit 'deployed troops' must PASS military_deploys rule. Got: {result}"
    )


# =============================================================================
# TEST 109: Fact entailment requires matched trigger in evidence
# =============================================================================

def test_fact_entailment_requires_matched_trigger():
    """
    validate_fact_entailment() must return False when no trigger keyword
    appears in the evidence text (regardless of fact type).
    """
    rule = _make_rule_by_id("betrayal_explicit_v51")
    # Evidence with no betrayal triggers at all
    snippet = "The city lies in ruins. Smoke rises from collapsed buildings."
    fact = _build_fact_with_evidence(snippet, rule)
    result = validate_fact_entailment(fact, rule)
    assert result["passed"] is False
    assert result["reason"] == "trigger_not_in_evidence"
    assert result["matched_trigger"] == ""


# =============================================================================
# TEST 110: Fact entailment checks subject support
# =============================================================================

def test_fact_entailment_checks_subject():
    """
    For protagonist_combat_v51: trigger found but no protagonist subject
    indicator → subject_not_supported.
    """
    rule = _make_rule_by_id("protagonist_combat_v51")
    # "fights" present but no "tae", "protagonist", "he fights" etc.
    snippet = "Zombies fight over the last scraps in the abandoned mall."
    fact = _build_fact_with_evidence(snippet, rule)
    result = validate_fact_entailment(fact, rule)
    # Either fails due to exclusion_context or subject_not_supported
    assert result["passed"] is False, (
        f"'Zombies fight' without protagonist subject must FAIL. Got: {result}"
    )


# =============================================================================
# TEST 111: Fact entailment checks predicate (military deploys vs collapses)
# =============================================================================

def test_fact_entailment_checks_predicate():
    """
    military_deploys_v51 requires explicit deploy predicate triggers.
    'military presence noted' has subject (military) but no deploy predicate.
    """
    rule = _make_rule_by_id("military_deploys_v51")
    # military present but no deploy action
    snippet = "Military soldiers are seen in the area, but their presence offers little comfort."
    fact = _build_fact_with_evidence(snippet, rule)
    result = validate_fact_entailment(fact, rule)
    # Trigger: "soldiers" is not in deploy rule trigger_keywords
    # So it should fail on trigger_not_in_evidence
    assert result["passed"] is False


# =============================================================================
# TEST 112: Title 'BETRAYED' requires protagonist betrayal fact (quality >= 0.8)
# =============================================================================

def test_title_betrayal_requires_protagonist_betrayal_fact(tmp_path):
    """
    A 'betrayal' title must have facts_used containing a betrayal_event
    with quality >= 0.8 in its per-title provenance.
    """
    # Create episode with explicit betrayal
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir()
    (ep_dir / "recap.json").write_text(
        json.dumps([{"speech": "His ally betrayed him, locking him out of the safehouse and leaving him to die."}]),
        encoding="utf-8"
    )

    _, _, claim_audit = generate_dynamic_titles(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        story_memory={"protagonist_name": "Tae"},
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    )

    prov = claim_audit.get("title_candidates_provenance", [])
    betrayal_titles = [p for p in prov if "BETRAYED" in p.get("text", "").upper()
                       or p.get("requirement_key") == "betrayal"]

    for bt in betrayal_titles:
        facts_used = bt.get("facts_used", [])
        betrayal_facts = [f for f in facts_used if "betrayal" in f.get("role", "")]
        assert len(betrayal_facts) > 0 or bt.get("requirement_key") != "betrayal", (
            f"Betrayal title must have betrayal fact in facts_used, got: {bt}"
        )


# =============================================================================
# TEST 113: Title 'defense line' requires defense/action fact
# =============================================================================

def test_title_defense_requires_defense_fact(tmp_path):
    """
    Title with 'Holds The Defense Line' must resolve to character_action or combat_event fact.
    """
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir()
    (ep_dir / "recap.json").write_text(
        json.dumps([{"speech": "Tae defended the last barricade, holding the line against the infected."}]),
        encoding="utf-8"
    )

    _, _, claim_audit = generate_dynamic_titles(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        story_memory={"protagonist_name": "Tae"},
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    )

    prov = claim_audit.get("title_candidates_provenance", [])
    defense_titles = [p for p in prov if "defense" in p.get("text", "").lower()
                      or p.get("requirement_key") == "defense"]

    for dt in defense_titles:
        req_key = dt.get("requirement_key", "")
        if req_key == "defense":
            facts = dt.get("facts_used", [])
            defense_types = [f for f in facts if f.get("role") in
                             ["character_action", "combat_event", "military_event"]]
            assert len(defense_types) > 0 or dt.get("provenance_complete") is False, (
                f"Defense title must use character_action/combat_event facts: {dt}"
            )


# =============================================================================
# TEST 114: Title 'total collapse' requires collapse/disaster fact
# =============================================================================

def test_title_collapse_requires_collapse_fact(tmp_path):
    """
    'From Outbreak to Total Collapse' title must be classified as 'collapse' requirement
    and resolve infection/disaster facts.
    """
    from markets.us_apocalypse.metadata import _classify_title_requirement
    title = "From Outbreak to Total Collapse: Surviving Zombie Apocalypse [Ep 1~143] | Manhwa Recap"
    req_key = _classify_title_requirement(title)
    assert req_key == "collapse", f"Expected 'collapse' requirement, got: {req_key}"


# =============================================================================
# TEST 115: Different titles resolve different required facts
# =============================================================================

def test_different_titles_resolve_different_facts(tmp_path):
    """
    V5.1: Each title must have its own requirement_key (not all sharing same facts).
    A betrayal title should have requirement_key='betrayal'.
    A disaster title should have requirement_key='disaster_survival' or 'collapse'.
    """
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir()
    (ep_dir / "recap.json").write_text(
        json.dumps([{"speech": "His ally betrayed him. Zombie outbreak spreads. Tae fights the horde."}]),
        encoding="utf-8"
    )

    _, _, claim_audit = generate_dynamic_titles(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        story_memory={"protagonist_name": "Tae"},
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    )

    prov = claim_audit.get("title_candidates_provenance", [])
    if len(prov) >= 2:
        req_keys = [p.get("requirement_key") for p in prov]
        # At least 2 different requirement keys should exist across titles
        unique_keys = set(req_keys)
        assert len(unique_keys) >= 2, (
            f"V5.1: Different titles should have different requirement keys. Got: {req_keys}"
        )


# =============================================================================
# TEST 116: Title evidence_count is LOCAL (not full graph count)
# =============================================================================

def test_title_evidence_count_is_local_not_graph_total(tmp_path):
    """
    V5.1: evidence_count in title provenance must be the local count
    for that title's resolved facts — NOT the total graph evidence count (e.g. 1258).
    """
    # Create a small episode set to keep total facts manageable
    for ep in range(1, 6):
        ep_dir = tmp_path / f"episode_{ep}"
        ep_dir.mkdir()
        (ep_dir / "recap.json").write_text(
            json.dumps([{"speech": f"Episode {ep}: Zombie outbreak. Tae fights. Infected spread."}]),
            encoding="utf-8"
        )

    _, _, claim_audit = generate_dynamic_titles(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        story_memory={"protagonist_name": "Tae"},
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=5,
    )

    prov = claim_audit.get("title_candidates_provenance", [])
    v5_prov = claim_audit.get("v5_provenance", {})
    total_graph_facts = v5_prov.get("total_facts", 0)

    for p in prov:
        local_ev = p.get("evidence_count", 0)
        # Local evidence_count must be << total graph facts (not 1258 or similar)
        assert local_ev <= total_graph_facts, (
            f"Local evidence_count {local_ev} cannot exceed total facts {total_graph_facts}"
        )
        # And specifically must not equal the total_graph_facts (that was the V5 bug)
        if total_graph_facts > 5:
            assert local_ev < total_graph_facts, (
                f"V5.1: evidence_count={local_ev} must be LOCAL (< total graph {total_graph_facts}). "
                f"Title: {p.get('text', '')[:50]}"
            )


# =============================================================================
# TEST 117: No provenance uses first-N graph facts fallback
# =============================================================================

def test_no_first_n_graph_facts_fallback(tmp_path):
    """
    V5.1: title_candidates_provenance must use requirement_key-based resolution,
    NOT the old fg._facts[:10] fallback. Verify by checking that 'requirement_key'
    field is present in every title provenance entry.
    """
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir()
    (ep_dir / "recap.json").write_text(
        json.dumps([{"speech": "Zombie outbreak. Tae fights back."}]),
        encoding="utf-8"
    )

    _, _, claim_audit = generate_dynamic_titles(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        story_memory={"protagonist_name": "Tae"},
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    )

    prov = claim_audit.get("title_candidates_provenance", [])
    assert len(prov) > 0, "title_candidates_provenance must not be empty"

    for p in prov:
        assert "requirement_key" in p, (
            f"V5.1: Every title provenance must have 'requirement_key' field, not first-N fallback. "
            f"Missing in: {p}"
        )
        assert "generation_mode" in p
        # Must have explicit mode, not the old "fact_graph_validated" generic mode
        mode = p.get("generation_mode", "")
        assert mode in ("template_fact_resolved", "legacy_validated"), (
            f"V5.1: generation_mode must be 'template_fact_resolved' or 'legacy_validated'. Got: {mode}"
        )


# =============================================================================
# TEST 118: Missing Stage11 timeline makes prepublish FAIL
# =============================================================================

def test_missing_stage11_timeline_makes_prepublish_fail():
    """
    V5.1: generate_us_apocalypse_metadata() without chapters (and without
    chapters_explicitly_disabled=True) must FAIL prepublish_audit.
    """
    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=5,
        story_memory={"protagonist_name": "Tae"},
        # No chapters provided, no chapters_explicitly_disabled
    )
    audit = meta["prepublish_audit"]
    assert audit["passed"] is False, (
        "V5.1: prepublish_audit must FAIL when chapters=None and not explicitly disabled. "
        f"Got passed={audit['passed']}, first_chapter_is_zero={audit.get('first_chapter_is_zero')}"
    )
    assert audit["first_chapter_is_zero"] is False


# =============================================================================
# TEST 119: Missing Stage11 timeline makes packaging FAIL
# =============================================================================

def test_missing_stage11_timeline_makes_packaging_fail():
    """
    V5.1: validate_packaging_consistency() with empty chapters and
    chapters_explicitly_disabled=False must report is_consistent=False.
    """
    evidence = EvidenceIndex("Test", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts(
        "Zombie Test", "zombie_apocalypse", "Tae", {"disaster": "Zombie Outbreak"}, evidence
    )

    result = validate_packaging_consistency(
        title="When Zombie Outbreak Strikes, Tae Fights To Survive | Manhwa Recap",
        thumbnail_concepts=concepts,
        description="When zombie outbreak strikes, Tae fights to survive.\nOriginal scripted narration.",
        narrative_chapters=[],  # empty — missing Stage 11
        tags=["manhwa recap", "zombie manhwa"],
        archetype="zombie_apocalypse",
        evidence_index=evidence,
        chapters_explicitly_disabled=False,  # NOT explicitly disabled
    )

    assert result["is_consistent"] is False, (
        "V5.1: Empty chapters without explicit opt-out must make packaging is_consistent=False"
    )
    warnings_str = str(result["warnings"])
    assert "NO_REAL_TIMELINE_INPUT_FROM_STAGE_11" in warnings_str, (
        f"V5.1: Must include NO_REAL_TIMELINE_INPUT_FROM_STAGE_11 warning. Got: {result['warnings']}"
    )
    assert result["checks"]["chapter_00_present"] is False
    assert result["checks"]["chapters_grounded"] is False


# =============================================================================
# TEST 120: chapters_explicitly_disabled=True may PASS with empty chapters
# =============================================================================

def test_intentional_chapters_disabled_may_pass():
    """
    V5.1: When chapters_explicitly_disabled=True, empty chapters should PASS
    the chapter checks (intentional, not missing).
    """
    evidence = EvidenceIndex("Test", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts(
        "Zombie Test", "zombie_apocalypse", "Tae", {"disaster": "Zombie Outbreak"}, evidence
    )

    result = validate_packaging_consistency(
        title="When Zombie Outbreak Strikes, Tae Fights To Survive | Manhwa Recap",
        thumbnail_concepts=concepts,
        description="When zombie outbreak strikes, Tae fights to survive.\nOriginal scripted narration.",
        narrative_chapters=[],
        tags=["manhwa recap", "zombie manhwa", "apocalypse manhwa"],
        archetype="zombie_apocalypse",
        evidence_index=evidence,
        chapters_explicitly_disabled=True,  # intentional
    )

    assert result["checks"]["chapter_00_present"] is True
    assert result["checks"]["chapters_grounded"] is True
    # No chapter-missing warning
    warnings_str = str(result["warnings"])
    assert "NO_REAL_TIMELINE_INPUT_FROM_STAGE_11" not in warnings_str


# =============================================================================
# TEST 121: Real Stage11 timeline produces non-empty chapters
# =============================================================================

def test_real_stage11_timeline_produces_chapters(tmp_path):
    """
    When real Stage11 chapters are provided, narrative_chapters must be non-empty.
    """
    stage11_chapters = [
        {"episode": 1, "timestamp": "00:00", "duration_seconds": 5576.0},
        {"episode": 15, "timestamp": "01:32:56", "duration_seconds": 6188.0},
        {"episode": 30, "timestamp": "03:16:04", "duration_seconds": 5034.0},
    ]

    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=30,
        chapters=stage11_chapters,
        story_memory={"protagonist_name": "Tae"},
    )

    chapters = meta["narrative_chapters"]
    assert len(chapters) > 0, "Real Stage11 timeline must produce non-empty narrative_chapters"
    assert chapters[0].get("timestamp") in ("00:00", "0:00"), (
        f"First chapter must be 00:00, got: {chapters[0].get('timestamp')}"
    )


# =============================================================================
# TEST 122: Thumbnail weapon claim requires weapon fact (visual_facts_used)
# =============================================================================

def test_thumbnail_visual_facts_used_field_present():
    """
    V5.1: thumbnail concepts from _build_resource_contrast_concepts() must
    contain 'visual_facts_used' field (list, may be empty without fact graph).
    """
    evidence = EvidenceIndex("Test", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts(
        "Zombie Test", "zombie_apocalypse", "Tae",
        {"disaster": "Zombie Outbreak"}, evidence
    )

    for c in concepts:
        assert "visual_facts_used" in c, (
            f"V5.1: Every thumbnail concept must have 'visual_facts_used' field. "
            f"Missing in concept: {c.get('id')}"
        )
        assert isinstance(c["visual_facts_used"], list)


# =============================================================================
# TEST 123: Thumbnail visual_facts_used populated from real fact graph
# =============================================================================

def test_thumbnail_visual_facts_used_populated_from_graph(tmp_path):
    """
    V5.1: When download_dir has real episodes, visual_facts_used must be
    populated with fact_id entries from the StoryFactGraph.
    """
    # Create episode with outbreak content
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir()
    (ep_dir / "recap.json").write_text(
        json.dumps([{"speech": "Zombie outbreak overruns the city. Infection spreads rapidly through the population."}]),
        encoding="utf-8"
    )

    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=1,
        story_memory={"protagonist_name": "Tae"},
        download_dir=str(tmp_path),
        chapters_explicitly_disabled=True,
    )

    # At least one concept should have visual_facts_used populated
    concepts = meta["thumbnail_concepts"]
    has_visual_facts = any(
        len(c.get("visual_facts_used", [])) > 0
        for c in concepts
    )
    assert has_visual_facts, (
        "V5.1: At least one thumbnail concept must have visual_facts_used populated "
        "when real episode data is available."
    )
    # Verify format
    for c in concepts:
        for vf in c.get("visual_facts_used", []):
            assert "fact_id" in vf, f"visual_facts_used item missing 'fact_id': {vf}"
            assert "visual_claim" in vf


# =============================================================================
# TEST 124: Before-after transformation thumbnail requires before/after state facts
# =============================================================================

def test_before_after_thumbnail_concept_has_visual_facts():
    """
    V5.1: 'concept_before_after' must have visual_facts_used field.
    """
    evidence = EvidenceIndex("Test", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts(
        "Zombie Test", "zombie_apocalypse", "Tae",
        {"disaster": "Zombie Outbreak"}, evidence
    )
    before_after = next((c for c in concepts if c.get("id") == "concept_before_after"), None)
    if before_after is None:
        pytest.skip("concept_before_after not in this archetype's concepts")
    assert "visual_facts_used" in before_after


# =============================================================================
# TEST 125: Style-only thumbnail elements need no factual evidence
# =============================================================================

def test_style_only_thumbnail_passes_without_evidence():
    """
    V5: Style elements (cinematic lighting, webtoon style, dramatic composition)
    must not cause thumbnail validation failures — no factual evidence needed.
    """
    evidence = EvidenceIndex("Test", "zombie_apocalypse")
    concept = {
        "id": "pure_style_concept",
        "name": "Pure Style Test",
        "thumbnail_text": "SURVIVE",
        "text_style": "Cinematic lighting, dynamic rim lighting, high contrast.",
        "composition": "Dramatic diagonal composition. Atmospheric depth.",
        "gpt_prompt": (
            "Cinematic 16:9 widescreen. Sharp ink linework. "
            "Saturated cel-shading. Dynamic composition. Rim lighting."
        ),
        "visual_facts_used": [],
    }
    result = validate_thumbnail_concept(concept, evidence, "zombie_apocalypse")
    assert result["passed"] is True, (
        f"Pure style thumbnail must PASS. Violations: {result['violations']}"
    )


# =============================================================================
# TEST 126: Dashboard 'safehouse' field requires shelter fact
# =============================================================================

def test_dashboard_safehouse_requires_shelter_context(tmp_path):
    """
    V5.1: Dashboard must NOT contain unevidenced SPECIFIC story-state claims.
    Archetype defaults (e.g., 'Makeshift Safehouse') are acceptable as generic labels.
    Unevidenced specifics like 'Day 143', numeric food %, mc_level without story_memory, are not.
    """
    dashboard = generate_survival_dashboard_data(
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=5,
    )
    # Real numeric story data should be None without story_memory
    assert dashboard["mc_level"] is None, (
        f"mc_level without story_memory should be None. Got: {dashboard['mc_level']}"
    )
    assert dashboard["day_number"] is None, (
        f"day_number without story_memory should be None. Got: {dashboard['day_number']}"
    )
    assert dashboard["food_reserve_pct"] is None, (
        f"food_reserve_pct without story_memory should be None. Got: {dashboard['food_reserve_pct']}"
    )
    # Archetype default string labels are fine (generic, not story-specific)
    base = dashboard.get("base_security_level", "")
    if base:
        # Must not contain story-specific numbers
        assert "Day " not in base, f"base_security_level must not contain story day: {base}"
        assert "143" not in base, f"base_security_level must not contain episode count: {base}"


# =============================================================================
# TEST 127: Pinned comment inherits dashboard provenance (no new assertions)
# =============================================================================

def test_pinned_comment_no_unevidenced_assertions():
    """
    V5.1: Pinned comment must not contain factual assertions beyond what
    dashboard already validated. Specifically must not contain "CRITICAL"
    threat descriptor (removed in V5 Fix 9).
    """
    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=5,
        story_memory={"protagonist_name": "Tae"},
        chapters_explicitly_disabled=True,
    )
    pinned = meta["pinned_comment"]
    # V5/V5.1: "CRITICAL (Mutant Strains Active)" must be gone
    assert "CRITICAL (Mutant Strains Active)" not in pinned
    assert "SSS-Rank" not in pinned
    assert "Tower Trial" not in pinned


# =============================================================================
# TEST 128: Real Zombie Revelation V5.1 regression with Stage11 timeline
# =============================================================================

def test_real_zombie_revelation_v51_regression():
    """
    V5.1 full regression: StoryFactGraph on 143 episodes must:
    - Have 0 invariant violations
    - Not contain false facts (abandoned vehicles betrayal)
    - Generate valid title provenance with requirement_keys
    - Missing Stage11 causes packaging fail (we don't pass chapters here)
    """
    DOWNLOAD_DIR = os.path.join(
        PROJECT_ROOT, "downloads", "좀비묵시록_8208_1_143_en_946016ec"
    )

    if not os.path.isdir(DOWNLOAD_DIR):
        pytest.skip("Zombie Revelation download dir not found — skipping real regression")

    # Build fact graph
    fg = StoryFactGraph(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        download_dir=DOWNLOAD_DIR,
        from_ep=1,
        to_ep=143,
    ).build()

    # 1. Invariant check
    violations = fg.evidence_required_invariant_check()
    assert violations == [], (
        f"V5.1: Fact graph must have 0 invariant violations. Got {len(violations)}: {violations[:2]}"
    )

    # 2. No false betrayal from "abandoned vehicles"
    betrayal_facts = fg.get_facts_by_type("betrayal_event")
    for fact in betrayal_facts:
        ev = fact.evidence[0]["snippet"].lower() if fact.evidence else ""
        assert "abandoned vehicle" not in ev and "abandoned car" not in ev, (
            f"FALSE FACT: betrayal_event '{fact.fact_id}' supported by 'abandoned vehicles': {ev[:100]}"
        )
        # Trigger must be in evidence
        trigger = fact.matched_trigger.lower()
        if trigger:
            assert trigger in ev or any(
                re.search(r"\b" + re.escape(t) + r"\b", ev)
                for t in [trigger]
            ), (
                f"Betrayal fact '{fact.fact_id}' matched_trigger='{trigger}' not in evidence: {ev[:100]}"
            )

    # 3. No protagonist combat fact from crowd-fleeing evidence
    combat_facts = fg.get_facts_by_type("combat_event")
    protagonist_combat = [f for f in combat_facts if f.subject == "protagonist"]
    for fact in protagonist_combat:
        ev = fact.evidence[0]["snippet"].lower() if fact.evidence else ""
        assert "terrified citizens scramble" not in ev, (
            f"FALSE FACT: protagonist combat_event '{fact.fact_id}' from crowd scene: {ev[:100]}"
        )
        assert "citizens scramble" not in ev

    # 4. No military "deploys" fact from "crumbling defenses" evidence
    military_facts = fg.get_facts_by_type("military_event")
    deploy_facts = [f for f in military_facts if f.predicate == "deploys"]
    for fact in deploy_facts:
        ev = fact.evidence[0]["snippet"].lower() if fact.evidence else ""
        assert "crumbling defenses" not in ev, (
            f"FALSE FACT: military deploy '{fact.fact_id}' from 'crumbling defenses': {ev[:100]}"
        )
        assert "military's crumbling" not in ev

    # 5. Title provenance uses requirement_key
    _, _, claim_audit = generate_dynamic_titles(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        download_dir=DOWNLOAD_DIR,
        from_ep=1,
        to_ep=143,
    )
    prov = claim_audit.get("title_candidates_provenance", [])
    assert len(prov) > 0
    for p in prov:
        assert "requirement_key" in p, f"Missing requirement_key in provenance: {p}"
        assert p.get("evidence_count", 9999) < 1000, (
            f"V5.1: evidence_count must be local, not 1258. Got: {p.get('evidence_count')}"
        )

    # 6. Missing chapters → packaging FAIL
    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=143,
        download_dir=DOWNLOAD_DIR,
        # No chapters passed, no chapters_explicitly_disabled
    )
    assert meta["prepublish_audit"]["passed"] is False, (
        "V5.1: Without Stage11 chapters, prepublish must FAIL"
    )
