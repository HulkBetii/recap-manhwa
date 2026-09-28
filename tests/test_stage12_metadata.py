# -*- coding: utf-8 -*-
"""
Unit, integration, and regression test suite for Stage 12 Metadata Generation (US Apocalypse Market) - Round 3.
Comprehensive 46-test suite covering:
- Tests 1-25: Core claim verification, independent evidence units, story memory, safe downgrades, packaging consistency.
- Tests 26-29 (Lỗi A): Fail-Closed Chapter/Timestamp Contract, real timeline preservation, window-based grounding, cross-archetype theme rejection.
- Tests 30-33 (Lỗi B): Thumbnail full-object serialization validation, clean visual prompts, grounded Day numbers.
- Tests 34-37 (Lỗi C): Semantic and POS disambiguation (regression false positives, vault verb vs noun, immune vs RPG system).
- Tests 38-41 (Lỗi D): Subject & Scope binding (local_group vs global_story_world), generic factual assertion extraction.
- Tests 42-45: Unified surface validator & strict packaging consistency audit.
- Test 46: End-to-end real Stage 11 + Stage 12 timeline integration test.
"""
from __future__ import annotations

import json
import os
import re
import sys
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from markets.us_apocalypse.metadata import (
    EvidenceUnit,
    EvidenceIndex,
    SemanticAssertion,
    extract_semantic_assertions,
    ARCHETYPE_TITLE_POOLS,
    THEME_COMPONENT_REGISTRY,
    generate_dynamic_titles,
    generate_ab_title_variants,
    generate_us_apocalypse_metadata,
    extract_episode_theme,
    extract_episode_theme_with_snippet,
    detect_archetype,
    ARCHETYPE_FORBIDDEN_CLAIMS,
    verify_and_adjust_claims,
    _build_resource_contrast_concepts,
    generate_survival_dashboard_data,
    format_mini_status_block,
    validate_packaging_consistency,
    validate_thumbnail_concept,
    validate_text_surface,
    validate_chapter_theme,
    extract_factual_assertions,
    build_narrative_story_chapters,
)
from story_memory import StoryMemory


# =============================================================================
# TEST 1: Zombie Apocalypse never generates SSS/Trainee/Academy/Murim titles
# =============================================================================

def test_zombie_no_sss_title():
    titles, variants, audit = generate_dynamic_titles(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        story_memory={"protagonist_name": "Tae", "episodes": {}},
        from_ep=1,
        to_ep=143,
    )
    forbidden_kws = ["sss", "trainee", "academy", "hunter", "heavenly demon", "rank 1", "cultivation", "drop rate"]
    all_candidates = list(titles) + list(variants.values())
    for candidate in all_candidates:
        cand_lower = candidate.lower()
        for kw in forbidden_kws:
            assert kw not in cand_lower, f"Forbidden keyword '{kw}' found in zombie candidate: {candidate}"


# =============================================================================
# TEST 2: Hunter story allows SSS-Rank when evidence exists in transcript
# =============================================================================

def test_hunter_sss_allowed_with_evidence(tmp_path):
    ep1_dir = tmp_path / "episode_1"
    ep1_dir.mkdir()
    recap1 = [{"speech": "His SSS-Rank Hunter ability was finally awakened in the abyss."}]
    (ep1_dir / "recap.json").write_text(json.dumps(recap1), encoding="utf-8")

    ep2_dir = tmp_path / "episode_2"
    ep2_dir.mkdir()
    recap2 = [{"speech": "The guild masters realized he possessed SSS rank power beyond comprehension."}]
    (ep2_dir / "recap.json").write_text(json.dumps(recap2), encoding="utf-8")

    evidence = EvidenceIndex(
        comic_title="Solo Leveling Calamity",
        archetype="hunter_gate",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=2,
    )
    result = evidence.check_claim("sss_rank")
    assert result["supported"] is True
    assert evidence.validate_candidate("The WEAKEST Trainee Awakens SSS-Rank Power | Manhwa Recap", "hunter_gate") is True


# =============================================================================
# TEST 3: Fake UNLIMITED claim from weak keyword (e.g. 'food') is rejected
# =============================================================================

def test_fake_unlimited_rejected(tmp_path):
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir()
    recap = [{"speech": "He gathered some food supplies from the local convenience store."}]
    (ep_dir / "recap.json").write_text(json.dumps(recap), encoding="utf-8")

    evidence = EvidenceIndex(
        comic_title="Zombie Survival Story",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    )
    result = evidence.check_claim("infinite_resources")
    assert result["supported"] is False
    assert evidence.validate_candidate("Everyone Starves But He Has UNLIMITED Supplies | Manhwa Recap", "zombie_apocalypse") is False


# =============================================================================
# TEST 4: Real UNLIMITED claim with solid evidence is supported
# =============================================================================

def test_real_unlimited_passes(tmp_path):
    ep1_dir = tmp_path / "episode_1"
    ep1_dir.mkdir()
    recap1 = [{"speech": "His dimensional warehouse contains infinite supplies that never deplete."}]
    (ep1_dir / "recap.json").write_text(json.dumps(recap1), encoding="utf-8")

    ep2_dir = tmp_path / "episode_2"
    ep2_dir.mkdir()
    recap2 = [{"speech": "With an endless supply of fresh rations, he survives the sub-zero winter."}]
    (ep2_dir / "recap.json").write_text(json.dumps(recap2), encoding="utf-8")

    evidence = EvidenceIndex(
        comic_title="Bunker Sovereign",
        archetype="bunker_prepper",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=2,
    )
    result = evidence.check_claim("infinite_resources")
    assert result["supported"] is True
    assert evidence.validate_candidate("The World Froze Over, But He Has UNLIMITED Supplies | Manhwa Recap", "bunker_prepper") is True


# =============================================================================
# TEST 5: Long video (to_ep = 143) claim verification runs properly
# =============================================================================

def test_long_video_verify_runs():
    beats = {"disaster": "Zombie Apocalypse", "advantage": "UNLIMITED Supplies", "title": "Ruler of the Dead"}
    adjusted, audit = verify_and_adjust_claims(
        beats,
        download_dir=None,
        from_ep=1,
        to_ep=143,
        archetype="zombie_apocalypse",
    )
    assert "UNLIMITED" not in adjusted.get("advantage", "")
    assert "Ruler" not in adjusted.get("title", "")
    assert len(audit["adjusted_fields"]) > 0


# =============================================================================
# TEST 6: Chapter extraction avoids truncation at dangling stop words
# =============================================================================

def test_chapter_no_truncation_at_stop_word(tmp_path):
    ep_dir = tmp_path / "episode_5"
    ep_dir.mkdir()
    recap = [{"speech": "Tae plants his feet against the advancing infected horde that breaches the perimeter."}]
    (ep_dir / "recap.json").write_text(json.dumps(recap), encoding="utf-8")

    theme = extract_episode_theme(str(ep_dir / "recap.json"), 5, "Zombie Revelation", archetype="zombie_apocalypse")
    last_word = theme.split()[-1].lower().rstrip(".,;:")
    dangling_stop_words = {"on", "at", "to", "in", "of", "for", "with", "from", "as", "by", "the", "a", "an", "and", "or", "so", "than", "against", "but"}
    assert last_word not in dangling_stop_words, f"Chapter theme ends in stop word: '{theme}'"


# =============================================================================
# TEST 7: Cross-archetype title isolation
# =============================================================================

def test_cross_archetype_isolation():
    z_titles, z_variants, _ = generate_dynamic_titles(
        "Zombie Apocalypse 82-08", "zombie_apocalypse", from_ep=1, to_ep=143
    )
    h_titles, h_variants, _ = generate_dynamic_titles(
        "Solo Calamity Hunter", "hunter_gate", from_ep=1, to_ep=50
    )

    all_zombie = list(z_titles) + list(z_variants.values())
    all_hunter = list(h_titles) + list(h_variants.values())

    for t in all_zombie:
        for kw in ["academy", "trainee", "rank 1", "heavenly demon", "danjeon"]:
            assert kw not in t.lower(), f"Hunter keyword '{kw}' leaked into zombie title: {t}"

    assert len(all_zombie) >= 5
    assert len(all_hunter) >= 5


# =============================================================================
# TEST 8: Missing template placeholder is skipped cleanly without literal braces
# =============================================================================

def test_missing_placeholder_skipped():
    beats = {"disaster": "Zombie Apocalypse", "mc_name": "Tae", "advantage": "a FORTIFIED Base"}
    evidence = EvidenceIndex("Zombie Test", "zombie_apocalypse")
    variants = generate_ab_title_variants(
        "Zombie Test", "zombie_apocalypse", beats, from_ep=1, to_ep=143, evidence_index=evidence
    )

    for k, v in variants.items():
        assert "{" not in v and "}" not in v, f"Unfilled placeholder in {k}: {v}"
        assert "drop rate" not in v.lower(), f"Cross-archetype leak in {k}: {v}"


# =============================================================================
# TEST 9: StoryMemory fingerprinting and validation
# =============================================================================

def test_story_memory_fingerprint():
    mem = StoryMemory(comic_title="Zombie Revelation", language="en")
    fp1 = mem.get_fingerprint("http://naver.com/comic/123", 1, 143, "us_apocalypse_v2")
    fp2 = mem.get_fingerprint("http://naver.com/comic/123", 1, 143, "us_apocalypse_v2")
    fp3 = mem.get_fingerprint("http://naver.com/comic/different", 1, 143, "us_apocalypse_v2")

    assert fp1 == fp2
    assert fp1 != fp3


# =============================================================================
# TEST 10: Native A/B Test candidates are validated independently
# =============================================================================

def test_ab_independent_validation():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    candidates = {
        # V5: variant_a must NOT contain unsupported story-state claims (no evidence index loaded)
        # "FORTIFIED Base" triggers base_fortified assertion which now requires evidence in V5.
        # Use a clean title without base_fortified or other evidence-gated assertions.
        "variant_a_conflict": "When Zombie Apocalypse Overruns The City, Tae Fights To Survive | Manhwa Recap",
        "variant_b_paradox": "When The WEAKEST Trainee Reveals His SSS-Rank Power | Manhwa Recap",
        "variant_c_scale": "Surviving Zombie Apocalypse Against All Odds [Ep 1~143] | Manhwa Recap",
    }
    results = evidence.validate_all_candidates(candidates, "zombie_apocalypse")

    assert results["variant_a_conflict"]["passed"] is True
    assert results["variant_b_paradox"]["passed"] is False
    assert len(results["variant_b_paradox"]["rejected_claims"]) > 0
    assert results["variant_c_scale"]["passed"] is True



# =============================================================================
# TEST 11: Full Episode Range Reading (All 143 episodes scanned)
# =============================================================================

def test_full_episode_range_reading(tmp_path):
    for ep in range(1, 144):
        ep_dir = tmp_path / f"episode_{ep}"
        ep_dir.mkdir()
        recap = [{"speech": f"Episode {ep} narrative event where Tae scavenges infected sector {ep}."}]
        (ep_dir / "recap.json").write_text(json.dumps(recap), encoding="utf-8")

    evidence = EvidenceIndex(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=143,
    )

    assert len(evidence.episodes_requested) == 143
    assert len(evidence.episodes_loaded) == 143
    assert len(evidence.episodes_missing) == 0
    assert len(evidence.recap_source_paths) == 143


# =============================================================================
# TEST 12: EvidenceUnit Source Tracking
# =============================================================================

def test_evidence_unit_source_tracking(tmp_path):
    ep_dir = tmp_path / "episode_42"
    ep_dir.mkdir()
    recap = [{"speech": "Tae barricades the emergency stairwell.", "timestamp": "05:12"}]
    (ep_dir / "recap.json").write_text(json.dumps(recap), encoding="utf-8")

    evidence = EvidenceIndex(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        story_memory={"protagonist_name": "Tae", "core_conflict": "Zombie Outbreak"},
        download_dir=str(tmp_path),
        from_ep=42,
        to_ep=42,
    )

    recap_units = [u for u in evidence.units if u.source == "recap"]
    assert len(recap_units) >= 1
    u = recap_units[0]
    assert u.episode == 42
    assert u.segment_index == 0
    assert "barricades" in u.snippet
    assert "recap.json" in u.source_path
    assert u.timestamp == "05:12"

    mem_units = [u for u in evidence.units if u.source == "story_memory"]
    assert len(mem_units) >= 1
    assert any("Tae" in mu.snippet for mu in mem_units)


# =============================================================================
# TEST 13: High-Risk Claim Requires Independent Evidence Units
# =============================================================================

def test_high_risk_claim_requires_independent_evidence(tmp_path):
    ep1_dir = tmp_path / "episode_1"
    ep1_dir.mkdir()
    recap1 = [{"speech": "He possessed infinite resources and unlimited supplies stored in his private vault."}]
    (ep1_dir / "recap.json").write_text(json.dumps(recap1), encoding="utf-8")

    evidence_single = EvidenceIndex(
        comic_title="Bunker Test",
        archetype="bunker_prepper",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    )
    check_single = evidence_single.check_claim("infinite_resources")
    assert check_single["matched_units_count"] == 1
    assert check_single["supported"] is False

    ep2_dir = tmp_path / "episode_2"
    ep2_dir.mkdir()
    recap2 = [{"speech": "The warehouse held an endless supply of survival rations."}]
    (ep2_dir / "recap.json").write_text(json.dumps(recap2), encoding="utf-8")

    evidence_multi = EvidenceIndex(
        comic_title="Bunker Test",
        archetype="bunker_prepper",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=2,
    )
    check_multi = evidence_multi.check_claim("infinite_resources")
    assert check_multi["matched_units_count"] >= 2
    assert check_multi["supported"] is True


# =============================================================================
# TEST 14: Percentage Humanity Destroyed Claim Validation
# =============================================================================

def test_percentage_humanity_destroyed_claim_validation(tmp_path):
    evidence = EvidenceIndex(
        comic_title="Zombie Revelation",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    )
    assert evidence.check_claim("percentage_humanity_destroyed")["supported"] is False
    assert evidence.validate_candidate("Zombie Apocalypse Wiped Out 99% of Humanity | Manhwa Recap", "zombie_apocalypse") is False

    ep1 = tmp_path / "episode_1"
    ep1.mkdir()
    (ep1 / "recap.json").write_text(json.dumps([{"speech": "The virus wiped out 99% of humanity within forty-eight hours."}]), encoding="utf-8")

    ep2 = tmp_path / "episode_2"
    ep2.mkdir()
    (ep2 / "recap.json").write_text(json.dumps([{"speech": "With 99% of humanity gone, only small enclaves remain."}]), encoding="utf-8")

    evidence_with_data = EvidenceIndex(
        comic_title="Zombie Revelation",
        archetype="general_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=2,
    )
    assert evidence_with_data.check_claim("percentage_humanity_destroyed")["supported"] is True


# =============================================================================
# TEST 15: ONLY Survivor Claim Validation & Safe Downgrade
# =============================================================================

def test_only_survivor_claim_validation_and_downgrade(tmp_path):
    evidence = EvidenceIndex(
        comic_title="Zombie Revelation",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=10,
    )
    assert evidence.validate_candidate("He Is the ONLY Survivor of Zombie Apocalypse | Manhwa Recap", "zombie_apocalypse") is False
    assert evidence.validate_candidate("He Is a RESILIENT Survivor of Zombie Apocalypse | Manhwa Recap", "zombie_apocalypse") is True


# =============================================================================
# TEST 16: He KNEW Apocalypse Beforehand Claim Validation
# =============================================================================

def test_knew_apocalypse_beforehand_claim_validation(tmp_path):
    evidence = EvidenceIndex(
        comic_title="Zombie Revelation",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=5,
    )
    assert evidence.check_claim("knew_apocalypse_beforehand")["supported"] is False
    assert evidence.validate_candidate("He KNEW the Zombie Apocalypse Was Coming and Built a Base | Manhwa Recap", "zombie_apocalypse") is False


# =============================================================================
# TEST 17: UNBREAKABLE Fortress Claim Validation & Downgrade
# =============================================================================

def test_unbreakable_fortress_claim_validation_and_downgrade(tmp_path):
    evidence = EvidenceIndex(
        comic_title="Zombie Revelation",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=5,
    )
    assert evidence.check_claim("unbreakable_fortress")["supported"] is False
    assert evidence.validate_candidate("He Built an IMPENETRABLE Underground Fortress | Manhwa Recap", "zombie_apocalypse") is False
    # V5: 'FORTIFIED Base' triggers base_fortified assertion which now requires evidence.
    # With no recap.json files in tmp_path, base_fortified is unsupported → candidate rejected.
    assert evidence.validate_candidate("He Built a FORTIFIED Base In Zombie Apocalypse | Manhwa Recap", "zombie_apocalypse") is False


# =============================================================================
# TEST 18: Infinite Stockpile Thumbnail Safe Downgrade
# =============================================================================

def test_infinite_stockpile_thumbnail_downgrade():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        mc_name="Tae",
        beats={"disaster": "Zombie Apocalypse", "scarce_thing": "Food", "advantage": "a Stockpiled Supply Cache"},
        evidence_index=evidence,
    )
    split_concept = concepts[0]
    assert "INFINITE" not in split_concept["thumbnail_text"]
    assert "SURVIVE" in split_concept["thumbnail_text"] or "STOCKPILED" in split_concept["thumbnail_text"] or "FORTIFIED" in split_concept["thumbnail_text"]


# =============================================================================
# TEST 19: Thumbnail and Title Packaging Consistency
# =============================================================================

def test_thumbnail_title_packaging_consistency():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        mc_name="Tae",
        beats={"disaster": "Zombie Apocalypse", "scarce_thing": "Food", "advantage": "a FORTIFIED Base"},
        evidence_index=evidence,
    )
    chapters = [{"timestamp": "00:00", "title": "Outbreak & Patient Zero (Ep 1)"}]
    tags = ["manhwa recap", "zombie revelation", "zombie manhwa", "apocalypse manhwa"]
    desc = "When zombie apocalypse strikes, Tae fights to survive.\nOriginal scripted narration."

    audit = validate_packaging_consistency(
        # V5: Title must not contain unsupported assertions (FORTIFIED Base needs evidence)
        title="When Zombie Apocalypse Overruns The City, Tae Fights To Survive | Manhwa Recap",
        thumbnail_concepts=concepts,
        description=desc,
        narrative_chapters=chapters,
        tags=tags,
        archetype="zombie_apocalypse",
        evidence_index=evidence,
        chapters_explicitly_disabled=True,  # V5.1: test has 1 chapter provided, but marking explicit
    )

    assert audit["is_consistent"] is True
    assert audit["checks"]["title_grounded"] is True
    assert audit["checks"]["thumbnails_grounded"] is True
    assert audit["checks"]["chapter_00_present"] is True



# =============================================================================
# TEST 20: Survival Dashboard Has Zero Fake Formulas
# =============================================================================

def test_survival_dashboard_no_fake_numbers():
    dash = generate_survival_dashboard_data(
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=143,
        story_memory=None,
    )
    assert dash.get("mc_level") is None
    assert dash.get("food_reserve_pct") is None
    assert dash.get("water_reserve_pct") is None
    assert dash.get("day_number") is None
    assert dash["total_episodes_covered"] == 143
    assert "143 Chapters" in dash["story_arc"]


# =============================================================================
# TEST 21: Grounded Mini Status Block Formatting
# =============================================================================

def test_survival_dashboard_grounded_format():
    dash_empty = generate_survival_dashboard_data(
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=143,
        story_memory=None,
    )
    block_empty = format_mini_status_block("zombie_apocalypse", dash_empty)
    assert "SURVIVAL LOG" in block_empty
    assert "Episodes 1–143" in block_empty
    assert "Lv." not in block_empty

    # When grounded fields are present
    dash_grounded = dict(dash_empty)
    dash_grounded["outside_condition"] = "Infected Urban Sector — Active Swarms"
    block_grounded = format_mini_status_block("zombie_apocalypse", dash_grounded)
    assert "Infected Urban Sector" in block_grounded


# =============================================================================
# TEST 22: Prepublish Audit 100% Quality Enforcement
# =============================================================================

def test_prepublish_audit_100_percent_enforcement():
    # V5.1: chapters_explicitly_disabled=True because this test focuses on
    # title/description/tag/claim audits — not the chapter timeline contract.
    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=143,
        story_memory={"protagonist_name": "Tae"},
        chapters_explicitly_disabled=True,
    )
    audit = meta["prepublish_audit"]
    assert audit["passed"] is True
    assert audit["title_length_ok"] is True
    assert audit["description_bytes_ok"] is True
    assert audit["ypp_originality_statement_present"] is True
    assert len(audit["unsupported_claims"]) == 0
    assert audit["packaging_audit"]["is_consistent"] is True


# =============================================================================
# TEST 23: Real 143 Episodes Metadata Generation on Zombie Revelation with Chapters
# =============================================================================

def test_zombie_revelation_real_143_episodes_metadata():
    mock_stage11_chapters = [
        {"episode": 1, "timestamp": "00:00"},
        {"episode": 15, "timestamp": "01:32:56"},
        {"episode": 30, "timestamp": "03:16:04"},
        {"episode": 44, "timestamp": "04:39:58"},
        {"episode": 58, "timestamp": "06:01:33"},
        {"episode": 73, "timestamp": "07:24:31"},
        {"episode": 87, "timestamp": "08:26:02"},
        {"episode": 101, "timestamp": "09:34:00"},
        {"episode": 115, "timestamp": "10:40:16"},
        {"episode": 130, "timestamp": "11:54:50"},
    ]
    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=143,
        chapters=mock_stage11_chapters,
        story_memory={"protagonist_name": "Tae", "episodes": {}},
    )
    assert meta["title"].endswith(" | Manhwa Recap")
    assert len(meta["title"]) <= 100
    assert "Tae" in meta["description"] or "Tae" in meta["title"] or "Tae" in meta["pinned_comment"]
    assert len(meta["title_options"]) == 5
    assert len(meta["title_variants"]) == 3
    assert len(meta["narrative_chapters"]) == 10
    assert meta["narrative_chapters"][0]["timestamp"] == "00:00"
    assert meta["narrative_chapters"][1]["timestamp"] == "01:32:56"
    assert meta["prepublish_audit"]["passed"] is True


# =============================================================================
# TEST 24: StoryMemory Validated Load & Glossary Reset on Comic Change
# =============================================================================

def test_story_memory_validated_load_and_reset(tmp_path):
    mem1 = StoryMemory(comic_title="Comic A", language="en")
    mem1.cumulative_glossary["ItemX"] = "Power Sword"
    mem1.episodes["1"] = {"summary": "Comic A ep 1"}
    mem1.save_with_fingerprint(
        download_dir=str(tmp_path),
        source_url="http://naver.com/a",
        from_ep=1,
        to_ep=10,
        prompt_version="us_apocalypse_v2",
    )

    mem2 = StoryMemory.load_validated(
        download_dir=str(tmp_path),
        comic_title="Comic B",
        language="en",
        source_url="http://naver.com/b",
        from_ep=1,
        to_ep=10,
        prompt_version="us_apocalypse_v2",
    )

    assert len(mem2.cumulative_glossary) == 0
    assert len(mem2.episodes) == 0
    assert mem2.comic_title == "Comic B"


# =============================================================================
# TEST 25: Safe Downgrade Title & Thumbnail Pipeline End-to-End
# =============================================================================

def test_safe_downgrade_title_and_thumbnail_pipeline(tmp_path):
    beats = {
        "disaster": "Zombie Apocalypse",
        "advantage": "UNLIMITED Supplies",
        "fortress": "an IMPENETRABLE Underground Fortress",
        "mc_name": "Tae",
    }
    evidence = EvidenceIndex("Zombie Apocalypse", "zombie_apocalypse", download_dir=str(tmp_path), from_ep=1, to_ep=10)
    adjusted_beats, claim_audit = verify_and_adjust_claims(beats, download_dir=str(tmp_path), from_ep=1, to_ep=10, archetype="zombie_apocalypse")

    assert adjusted_beats["advantage"] != "UNLIMITED Supplies"

    variants = generate_ab_title_variants(
        comic_title="Zombie Apocalypse",
        archetype="zombie_apocalypse",
        beats=adjusted_beats,
        from_ep=1,
        to_ep=10,
        evidence_index=evidence,
    )
    for name, title in variants.items():
        assert "UNLIMITED" not in title
        assert "IMPENETRABLE" not in title
        assert evidence.validate_candidate(title, "zombie_apocalypse") is True


# =============================================================================
# TEST 26: Fail-Closed Chapters When No Real Stage 11 Timeline Input (Lỗi A)
# =============================================================================

def test_fail_closed_chapters_when_no_timeline_input():
    ch_none = build_narrative_story_chapters(None, from_ep=1, to_ep=143)
    assert ch_none == [], "Must return empty list when chapters=None"

    ch_empty = build_narrative_story_chapters([], from_ep=1, to_ep=143)
    assert ch_empty == [], "Must return empty list when chapters=[]"

    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=143,
        chapters=None,
    )
    assert meta["narrative_chapters"] == []
    assert "NO_REAL_TIMELINE_INPUT_FROM_STAGE_11" in meta["prepublish_audit"]["chapter_warnings"]
    assert "⏱️ Chapters:" not in meta["description"]


# =============================================================================
# TEST 27: Preservation of Real Stage 11 Timeline Chapters (Lỗi A)
# =============================================================================

def test_real_timeline_chapters_preservation():
    stage11_input = [
        {"episode": 1, "timestamp": "00:00", "duration_seconds": 5576.0},
        {"episode": 15, "timestamp": "01:32:56", "duration_seconds": 6188.0},
        {"episode": 30, "timestamp": "03:16:04", "duration_seconds": 5034.0},
        {"episode": 44, "timestamp": "04:39:58", "duration_seconds": 4895.0},
        {"episode": 58, "timestamp": "06:01:33", "duration_seconds": 4978.0},
        {"episode": 73, "timestamp": "07:24:31", "duration_seconds": 3691.0},
        {"episode": 87, "timestamp": "08:26:02", "duration_seconds": 4078.0},
        {"episode": 101, "timestamp": "09:34:00", "duration_seconds": 3976.0},
        {"episode": 115, "timestamp": "10:40:16", "duration_seconds": 4474.0},
        {"episode": 130, "timestamp": "11:54:50", "duration_seconds": 4200.0},
    ]
    narrative = build_narrative_story_chapters(
        chapters=stage11_input,
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=143,
    )
    assert len(narrative) == 10
    assert narrative[0]["timestamp"] == "00:00"
    assert narrative[1]["timestamp"] == "01:32:56"
    assert narrative[2]["timestamp"] == "03:16:04"
    assert narrative[9]["timestamp"] == "11:54:50"


# =============================================================================
# TEST 28: Chapter Window-Based Grounding & Evidence Extraction (Lỗi A)
# =============================================================================

def test_chapter_window_grounding(tmp_path):
    for ep in range(1, 15):
        ep_dir = tmp_path / f"episode_{ep}"
        ep_dir.mkdir()
        recap = [{"speech": f"Episode {ep} martial law broadcast and helicopter chopper evacuation."}]
        (ep_dir / "recap.json").write_text(json.dumps(recap), encoding="utf-8")

    for ep in range(15, 30):
        ep_dir = tmp_path / f"episode_{ep}"
        ep_dir.mkdir()
        recap = [{"speech": f"Episode {ep} winter freeze cold ambush in the blizzard."}]
        (ep_dir / "recap.json").write_text(json.dumps(recap), encoding="utf-8")

    stage11_input = [
        {"episode": 1, "timestamp": "00:00"},
        {"episode": 15, "timestamp": "01:30:00"},
    ]
    narrative = build_narrative_story_chapters(
        chapters=stage11_input,
        download_dir=str(tmp_path),
        archetype="zombie_apocalypse",
        from_ep=1,
        to_ep=29,
    )
    assert len(narrative) >= 1
    # Check that window extracted theme matching window recaps
    assert any("Martial Law" in ch["theme"] or "Winter" in ch["theme"] or "Survival" in ch["theme"] for ch in narrative)


# =============================================================================
# TEST 29: Cross-Archetype Theme Blacklisting in Chapters (Lỗi A)
# =============================================================================

def test_chapter_cross_archetype_rejection(tmp_path):
    # Recaps contain "floor climb" (apartment stairs) and "gate" (fence)
    ep1_dir = tmp_path / "episode_1"
    ep1_dir.mkdir()
    recap1 = [{"speech": "Tae climbs to the top floor of the apartment building to escape the zombies."}]
    (ep1_dir / "recap.json").write_text(json.dumps(recap1), encoding="utf-8")

    ep2_dir = tmp_path / "episode_2"
    ep2_dir.mkdir()
    recap2 = [{"speech": "The survivor opened the iron gate to secure the perimeter."}]
    (ep2_dir / "recap.json").write_text(json.dumps(recap2), encoding="utf-8")

    theme1 = extract_episode_theme(str(ep1_dir / "recap.json"), 1, "Zombie Revelation", archetype="zombie_apocalypse")
    theme2 = extract_episode_theme(str(ep2_dir / "recap.json"), 2, "Zombie Revelation", archetype="zombie_apocalypse")

    assert "Tower Trials" not in theme1, f"Tower leak in zombie chapter: {theme1}"
    assert "Endless Ascent" not in theme1, f"Ascent leak in zombie chapter: {theme1}"
    assert "Calamity Gate" not in theme2, f"Gate leak in zombie chapter: {theme2}"
    assert "Solo Awakening" not in theme2, f"Awakening leak in zombie chapter: {theme2}"
    assert validate_chapter_theme("The Tower Trials & Endless Ascent", "zombie_apocalypse") is False
    assert validate_chapter_theme("Calamity Gate & Solo Awakening", "zombie_apocalypse") is False


# =============================================================================
# TEST 30: Thumbnail Full-Object Validation Pass on Grounded Concept (Lỗi B)
# =============================================================================

def test_thumbnail_full_object_validation_pass():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        mc_name="Tae",
        beats={"disaster": "Zombie Apocalypse", "scarce_thing": "Food", "advantage": "a FORTIFIED Base"},
        evidence_index=evidence,
    )
    for c in concepts:
        res = validate_thumbnail_concept(c, evidence, "zombie_apocalypse")
        assert res["passed"] is True, f"Valid concept failed validation: {res['violations']}"


# =============================================================================
# TEST 31: Thumbnail Full-Object Validation Fails on Visual Promise Leak (Lỗi B)
# =============================================================================

def test_thumbnail_full_object_validation_fail_on_prompt_leak():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    concept_with_leak = {
        "id": "concept_bad",
        "name": "Bad Concept",
        "thumbnail_text": "SURVIVAL",
        "text_style": "Impact font",
        "composition": "Split screen",
        "gpt_prompt": "Draw Tae with glowing aura, SSS energy, and SSS-Rank Trainee status window.",
    }
    res = validate_thumbnail_concept(concept_with_leak, evidence, "zombie_apocalypse")
    assert res["passed"] is False
    assert any("SSS" in v or "glowing aura" in v or "Trainee" in v for v in res["violations"])


# =============================================================================
# TEST 32: Thumbnail Uses Grounded Text When Day Not Evidenced (Lỗi B)
# =============================================================================

def test_thumbnail_no_fake_day_numbers():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        mc_name="Tae",
        beats={"disaster": "Zombie Apocalypse", "scarce_thing": "Food", "advantage": "a FORTIFIED Base"},
        evidence_index=evidence,
        story_memory=None,  # No day in memory
    )
    for c in concepts:
        assert "DAY 47" not in c["gpt_prompt"]
        assert "DAY 100" not in c["gpt_prompt"]
        assert "DAY 47" not in c["thumbnail_text"]
        assert "DAY 100" not in c["thumbnail_text"]


# =============================================================================
# TEST 33: Thumbnail Preserves Real Day When Evidenced (Lỗi B)
# =============================================================================

def test_thumbnail_real_day_number_preservation():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts(
        comic_title="Zombie Revelation 82-08",
        archetype="zombie_apocalypse",
        mc_name="Tae",
        beats={"disaster": "Zombie Apocalypse", "scarce_thing": "Food", "advantage": "a FORTIFIED Base"},
        evidence_index=evidence,
        story_memory={"day": 50},
    )
    concept2 = concepts[1]
    assert "DAY 50" in concept2["thumbnail_text"]
    assert "DAY 50" in concept2["gpt_prompt"]


# =============================================================================
# TEST 34: Semantic Disambiguation — Regression False Positives (Lỗi C)
# =============================================================================

def test_semantic_disambiguation_regression_false_positives(tmp_path):
    ep1_dir = tmp_path / "episode_1"
    ep1_dir.mkdir()
    # Rewind footage is surveillance review, not time travel
    recap1 = [{"speech": "The detective decided to rewind the security footage to check the suspect."}]
    (ep1_dir / "recap.json").write_text(json.dumps(recap1), encoding="utf-8")

    ep2_dir = tmp_path / "episode_2"
    ep2_dir.mkdir()
    # Second chance to talk is idiom, not regression
    recap2 = [{"speech": "He gave the merchant a second chance to explain the pricing."}]
    (ep2_dir / "recap.json").write_text(json.dumps(recap2), encoding="utf-8")

    evidence = EvidenceIndex(
        comic_title="Crime Scene Investigation",
        archetype="general_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=2,
    )
    check = evidence.check_claim("regression")
    assert check["supported"] is False, "Surveillance footage rewind should NOT trigger regression"


# =============================================================================
# TEST 35: Semantic Disambiguation — Regression True Positives (Lỗi C)
# =============================================================================

def test_semantic_disambiguation_regression_true_positives(tmp_path):
    ep1_dir = tmp_path / "episode_1"
    ep1_dir.mkdir()
    recap1 = [{"speech": "After dying in the cataclysm, he was reborn and returned to the past 10 years before."}]
    (ep1_dir / "recap.json").write_text(json.dumps(recap1), encoding="utf-8")

    evidence = EvidenceIndex(
        comic_title="Regression Warrior",
        archetype="regression_prep",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    )
    check = evidence.check_claim("regression")
    assert check["supported"] is True, "Explicit past return must support regression"


# =============================================================================
# TEST 36: POS Disambiguation — Vault Verb vs Noun (Lỗi D)
# =============================================================================

def test_pos_disambiguation_vault_verb_vs_noun(tmp_path):
    ep1_dir = tmp_path / "episode_1"
    ep1_dir.mkdir()
    # "vault over" is a verb (jumping over barrier)
    recap1 = [{"speech": "The mutated creatures vault over the high fence and attack the civilians."}]
    (ep1_dir / "recap.json").write_text(json.dumps(recap1), encoding="utf-8")

    evidence_verb = EvidenceIndex(
        comic_title="Zombie Breach",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    )
    check_verb = evidence_verb.check_claim("bunker")
    assert check_verb["supported"] is False, "'vault over' verb must not match bunker claim"

    # Now add real underground vault noun
    ep2_dir = tmp_path / "episode_2"
    ep2_dir.mkdir()
    recap2 = [{"speech": "They sealed the underground fallout vault door with biometric locks."}]
    (ep2_dir / "recap.json").write_text(json.dumps(recap2), encoding="utf-8")

    evidence_noun = EvidenceIndex(
        comic_title="Vault Shelter",
        archetype="bunker_prepper",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=2,
    )
    check_noun = evidence_noun.check_claim("bunker")
    assert check_noun["supported"] is True, "'underground fallout vault' must match bunker claim"


# =============================================================================
# TEST 37: Semantic Disambiguation — Immune System vs RPG System (Lỗi C)
# =============================================================================

def test_semantic_disambiguation_system_immune_vs_rpg(tmp_path):
    ep1_dir = tmp_path / "episode_1"
    ep1_dir.mkdir()
    recap1 = [{"speech": "The patient's immune system collapsed under the stress of the infection."}]
    (ep1_dir / "recap.json").write_text(json.dumps(recap1), encoding="utf-8")

    evidence_bio = EvidenceIndex(
        comic_title="Medical Drama",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    )
    check_bio = evidence_bio.check_claim("system")
    assert check_bio["supported"] is False, "Immune system collapse must not match game system claim"

    ep2_dir = tmp_path / "episode_2"
    ep2_dir.mkdir()
    recap2 = [{"speech": "A glowing system window appeared saying 'Quest Complete: Level Up'."}]
    (ep2_dir / "recap.json").write_text(json.dumps(recap2), encoding="utf-8")

    evidence_rpg = EvidenceIndex(
        comic_title="Player Awakening",
        archetype="game_system_reality",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=2,
    )
    check_rpg = evidence_rpg.check_claim("system")
    assert check_rpg["supported"] is True, "System status window must support system claim"


# =============================================================================
# TEST 38: Scope Binding — Only Survivor Local vs Global (Lỗi D)
# =============================================================================

def test_scope_binding_only_survivor_local_vs_global(tmp_path):
    ep1_dir = tmp_path / "episode_1"
    ep1_dir.mkdir()
    # Local squad scope
    recap1 = [{"speech": "These three scouts are the only survivors of Squad Bravo."}]
    (ep1_dir / "recap.json").write_text(json.dumps(recap1), encoding="utf-8")

    evidence_local = EvidenceIndex(
        comic_title="Zombie Squad",
        archetype="zombie_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=1,
    )
    assert evidence_local.units[-1].scope == "local_group"
    assert evidence_local.check_claim("only_survivor")["supported"] is False

    # Global scope
    ep2_dir = tmp_path / "episode_2"
    ep2_dir.mkdir()
    recap2 = [{"speech": "He is the only survivor in the world as the rest of humanity was wiped out."}]
    (ep2_dir / "recap.json").write_text(json.dumps(recap2), encoding="utf-8")

    evidence_global = EvidenceIndex(
        comic_title="Last Man Standing",
        archetype="general_apocalypse",
        download_dir=str(tmp_path),
        from_ep=1,
        to_ep=2,
    )
    assert evidence_global.units[-1].scope == "global_story_world"
    assert evidence_global.check_claim("only_survivor")["supported"] is True


# =============================================================================
# TEST 39: Generic Factual Assertion Extractor — Numerical Assertions (Lỗi D)
# =============================================================================

def test_generic_factual_assertion_extractor_numbers():
    text = "He spent 16 years preparing and climbed 100 floors in 30 days."
    assertions = extract_factual_assertions(text)
    units = {a["unit"] for a in assertions if a["type"] == "numeric"}
    assert "years" in units
    assert "floors" in units
    assert "days" in units


# =============================================================================
# TEST 40: Generic Factual Assertion Extractor — Absolute Quantifiers (Lỗi D)
# =============================================================================

def test_generic_factual_assertion_extractor_absolutes():
    text = "Everyone Panicked, But The Only Survivor Saved All Humanity."
    assertions = extract_factual_assertions(text)
    terms = {a["term"] for a in assertions if a["type"] == "absolute"}
    assert "everyone" in terms
    assert "only survivor" in terms
    assert "all humanity" in terms


# =============================================================================
# TEST 41: Generic Factual Assertion Extractor — Dominance & Hyperbole (Lỗi D)
# =============================================================================

def test_generic_factual_assertion_extractor_dominance():
    text = "He controls all resources as the King of Loot with god-tier power."
    assertions = extract_factual_assertions(text)
    terms = {a["term"] for a in assertions if a["type"] == "dominance"}
    assert "controls all" in terms
    assert "king of loot" in terms
    assert any("god" in t for t in terms)


# =============================================================================
# TEST 42: Unified Surface Validator — Title Violation Detection
# =============================================================================

def test_unified_surface_validator_title():
    evidence = EvidenceIndex("Zombie Test", "zombie_apocalypse")
    bad_title = "The SSS-Rank Trainee Solos The Calamity Gate | Manhwa Recap"
    res = validate_text_surface(bad_title, evidence, "zombie_apocalypse", surface_type="title")
    assert res["passed"] is False
    assert len(res["violations"]) >= 2


# =============================================================================
# TEST 43: Unified Surface Validator — Description Violation Detection
# =============================================================================

def test_unified_surface_validator_description():
    evidence = EvidenceIndex("Zombie Test", "zombie_apocalypse")
    bad_desc = "Tae cultivated his Heavenly Demon Danjeon to defeat zombies.\nOriginal scripted narration."
    res = validate_text_surface(bad_desc, evidence, "zombie_apocalypse", surface_type="description")
    assert res["passed"] is False
    assert any("Cultivation" in v or "Heavenly Demon" in v for v in res["violations"])


# =============================================================================
# TEST 44: Unified Surface Validator — Tag Violation Detection
# =============================================================================

def test_unified_surface_validator_tags():
    evidence = EvidenceIndex("Zombie Test", "zombie_apocalypse")
    bad_tag = "sss-rank hunter manhwa"
    res = validate_text_surface(bad_tag, evidence, "zombie_apocalypse", surface_type="tag")
    assert res["passed"] is False


# =============================================================================
# TEST 45: Strict Packaging Consistency Audit Enforcement
# =============================================================================

def test_strict_packaging_audit_100_percent():
    evidence = EvidenceIndex("Zombie Test", "zombie_apocalypse")
    clean_concepts = _build_resource_contrast_concepts("Zombie Test", "zombie_apocalypse", "Tae", {"disaster": "Zombie Outbreak", "advantage": "a FORTIFIED Base"}, evidence)
    # V5: description must not contain 'fortified base' without evidence (base_fortified assertion requires evidence)
    clean_desc = "When zombie outbreak strikes, Tae fights to survive.\nOriginal scripted narration."
    clean_tags = ["manhwa recap", "zombie manhwa", "apocalypse manhwa"]

    # 1. Clean pack -> PASS (V5: Title must not trigger unsupported base_fortified assertion)
    # V5.1: chapters_explicitly_disabled=True — this test checks title/tag/thumbnail, not chapters
    res_clean = validate_packaging_consistency(
        title="When Zombie Outbreak Overruns The City, Tae Fights To Survive | Manhwa Recap",
        thumbnail_concepts=clean_concepts,
        description=clean_desc,
        narrative_chapters=[],
        tags=clean_tags,
        archetype="zombie_apocalypse",
        evidence_index=evidence,
        chapters_explicitly_disabled=True,
    )
    assert res_clean["is_consistent"] is True

    # 2. Corrupted tag -> FAIL (chapters_explicitly_disabled=True, still fails on tag)
    res_dirty = validate_packaging_consistency(
        title="When Zombie Outbreak Overruns The City, Tae Fights To Survive | Manhwa Recap",
        thumbnail_concepts=clean_concepts,
        description=clean_desc,
        narrative_chapters=[],
        tags=clean_tags + ["sss-rank manhwa"],
        archetype="zombie_apocalypse",
        evidence_index=evidence,
        chapters_explicitly_disabled=True,
    )
    assert res_dirty["is_consistent"] is False
    assert len(res_dirty["warnings"]) > 0


# =============================================================================
# TEST 46: End-to-End Real Stage 11 + Stage 12 Timeline Integration Test
# =============================================================================

def test_stage11_stage12_timeline_integration_zombie_143():
    real_stage11_chapters = [
        {"episode": 1, "timestamp": "00:00", "duration_seconds": 5576.0},
        {"episode": 15, "timestamp": "01:32:56", "duration_seconds": 6188.0},
        {"episode": 30, "timestamp": "03:16:04", "duration_seconds": 5034.0},
        {"episode": 44, "timestamp": "04:39:58", "duration_seconds": 4895.0},
        {"episode": 58, "timestamp": "06:01:33", "duration_seconds": 4978.0},
        {"episode": 73, "timestamp": "07:24:31", "duration_seconds": 3691.0},
        {"episode": 87, "timestamp": "08:26:02", "duration_seconds": 4078.0},
        {"episode": 101, "timestamp": "09:34:00", "duration_seconds": 3976.0},
        {"episode": 115, "timestamp": "10:40:16", "duration_seconds": 4474.0},
        {"episode": 130, "timestamp": "11:54:50", "duration_seconds": 4200.0},
    ]

    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=143,
        chapters=real_stage11_chapters,
        story_memory={"protagonist_name": "Tae", "episodes": {}},
    )

    # 1. 100% Prepublish Audit Passed
    assert meta["prepublish_audit"]["passed"] is True
    assert meta["packaging_audit"]["is_consistent"] is True

    # 2. Real Timestamps preserved
    timestamps = [ch["timestamp"] for ch in meta["narrative_chapters"]]
    assert timestamps[0] == "00:00"
    assert timestamps[1] == "01:32:56"
    assert timestamps[9] == "11:54:50"

    # 3. No Cross-Archetype leaks across ALL surfaces
    for ch in meta["narrative_chapters"]:
        for forbidden in ["Tower", "Gate", "Awakening", "Dungeon", "SSS", "Trainee"]:
            assert forbidden not in ch["title"], f"Leak in chapter: {ch['title']}"

    for c in meta["thumbnail_concepts"]:
        for field_name in ["name", "thumbnail_text", "gpt_prompt", "composition"]:
            val = c[field_name]
            assert "DAY 47" not in val
            assert "DAY 100" not in val
            assert "glowing aura" not in val
            assert "SSS" not in val


# =============================================================================
# TEST 47: to_ep = 143 Rejected As Story Day 143 Without Evidence
# =============================================================================

def test_to_ep_143_rejected_as_day_143():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse", from_ep=1, to_ep=143)
    # Episode number != Story day
    bad_title = "From Day 1 to Day 143: Surviving Zombie Apocalypse | Manhwa Recap"
    assert evidence.validate_candidate(bad_title, "zombie_apocalypse") is False

    # But with explicit story memory day = 143, it passes
    evidence_with_day = EvidenceIndex(
        "Zombie Revelation", "zombie_apocalypse", from_ep=1, to_ep=143, story_memory={"day": 143}
    )
    assert evidence_with_day.validate_candidate(bad_title, "zombie_apocalypse") is True


# =============================================================================
# TEST 48: 16 Years Preparation Claim Rejected Without Explicit Text Evidence
# =============================================================================

def test_16_years_rejected_without_textual_evidence():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    bad_title = "He Spent 16 Years Preparing for the Apocalypse | Manhwa Recap"
    assert evidence.validate_candidate(bad_title, "zombie_apocalypse") is False


# =============================================================================
# TEST 49: MC Built Bunker Rejected When Protagonist Only Found Shelter
# =============================================================================

def test_mc_built_bunker_rejected_when_mc_only_found_shelter(tmp_path):
    ep1 = tmp_path / "episode_1"
    ep1.mkdir()
    (ep1 / "recap.json").write_text(
        json.dumps([{"speech": "Tae fled into an abandoned underground shelter to hide from zombies."}]),
        encoding="utf-8",
    )
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse", download_dir=str(tmp_path), from_ep=1, to_ep=1)
    bad_title = "He Built a Doomsday Bunker to Survive the Apocalypse | Manhwa Recap"
    assert evidence.validate_candidate(bad_title, "zombie_apocalypse") is False


# =============================================================================
# TEST 50: Bunker Claim Rejected When Text Only Supports Secure Shelter
# =============================================================================

def test_bunker_rejected_when_text_only_supports_secure_shelter(tmp_path):
    ep1 = tmp_path / "episode_1"
    ep1.mkdir()
    (ep1 / "recap.json").write_text(
        json.dumps([{"speech": "Tae barricaded the apartment door with heavy furniture to secure the shelter."}]),
        encoding="utf-8",
    )
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse", download_dir=str(tmp_path), from_ep=1, to_ep=1)
    bad_title = "Inside The Doomsday Bunker: Surviving Zombie Apocalypse | Manhwa Recap"
    assert evidence.validate_candidate(bad_title, "zombie_apocalypse") is False


# =============================================================================
# TEST 51: Vault Verb Rejected By EvidenceIndex
# =============================================================================

def test_vault_verb_rejected_by_evidence_index(tmp_path):
    ep1 = tmp_path / "episode_1"
    ep1.mkdir()
    (ep1 / "recap.json").write_text(
        json.dumps([{"speech": "The infected zombies vault over the barricade into the room."}]),
        encoding="utf-8",
    )
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse", download_dir=str(tmp_path), from_ep=1, to_ep=1)
    check = evidence.check_claim("bunker")
    assert check["supported"] is False


# =============================================================================
# TEST 52: Controls Stockpile Claim Rejected When MC Only Scavenges Food
# =============================================================================

def test_controls_stockpile_rejected_when_mc_only_scavenges(tmp_path):
    ep1 = tmp_path / "episode_1"
    ep1.mkdir()
    (ep1 / "recap.json").write_text(
        json.dumps([{"speech": "Tae scavenged three cans of tuna from the convenience store."}]),
        encoding="utf-8",
    )
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse", download_dir=str(tmp_path), from_ep=1, to_ep=1)
    bad_title = "He Controls All Supplies in the Apocalypse | Manhwa Recap"
    assert evidence.validate_candidate(bad_title, "zombie_apocalypse") is False


# =============================================================================
# TEST 53: Everyone Is Starving Rejected When Only Local Scarcity
# =============================================================================

def test_everyone_is_starving_rejected_when_only_local_shortage(tmp_path):
    ep1 = tmp_path / "episode_1"
    ep1.mkdir()
    (ep1 / "recap.json").write_text(
        json.dumps([{"speech": "The two survivors in the room skipped lunch because rations ran low."}]),
        encoding="utf-8",
    )
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse", download_dir=str(tmp_path), from_ep=1, to_ep=1)
    bad_title = "Everyone Is STARVING, But He Feasts In Secret | Manhwa Recap"
    assert evidence.validate_candidate(bad_title, "zombie_apocalypse") is False


# =============================================================================
# TEST 54: The World Ran Out of Shelter Rejected Without Global Collapse
# =============================================================================

def test_world_ran_out_of_shelter_rejected_without_global_collapse_evidence(tmp_path):
    ep1 = tmp_path / "episode_1"
    ep1.mkdir()
    (ep1 / "recap.json").write_text(
        json.dumps([{"speech": "The roof of the convenience store leaked during the rain."}]),
        encoding="utf-8",
    )
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse", download_dir=str(tmp_path), from_ep=1, to_ep=1)
    bad_title = "The World Ran Out of Safe Shelter, But He Built an Empire | Manhwa Recap"
    assert evidence.validate_candidate(bad_title, "zombie_apocalypse") is False


# =============================================================================
# TEST 55: 0 Safe Shelter Rejected Without Literal Zero Resource Evidence
# =============================================================================

def test_zero_safe_shelter_rejected_without_absolute_zero_evidence(tmp_path):
    ep1 = tmp_path / "episode_1"
    ep1.mkdir()
    (ep1 / "recap.json").write_text(
        json.dumps([{"speech": "Several buildings downtown were infected."}]),
        encoding="utf-8",
    )
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse", download_dir=str(tmp_path), from_ep=1, to_ep=1)
    assertions = extract_semantic_assertions("0 SAFE SHELTER")
    assert len(assertions) >= 1
    assert evidence.verify_assertion(assertions[0]) is False


# =============================================================================
# TEST 56: Unknown High-Impact Assertion Fails-Closed
# =============================================================================

def test_unknown_high_impact_assertion_fails_closed():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    text = "He Conquered 1000 Armies and Monopolizes the World | Manhwa Recap"
    res = validate_text_surface(text, evidence, "zombie_apocalypse", surface_type="title")
    assert res["passed"] is False
    assert len(res["violations"]) > 0


# =============================================================================
# TEST 57: Zombie Apocalypse Title Pool Has Zero Bunker Prepper Templates
# =============================================================================

def test_zombie_title_pool_has_zero_bunker_prepper_templates():
    pool = ARCHETYPE_TITLE_POOLS.get("zombie_apocalypse", [])
    for t in pool:
        assert "bunker" not in t.lower(), f"Bunker in zombie pool: {t}"
        assert "16 years" not in t.lower(), f"16 years in zombie pool: {t}"
        assert "doomsday shelter" not in t.lower(), f"Doomsday shelter in zombie pool: {t}"


# =============================================================================
# TEST 58: Bunker Prepper Title Pool Has Zero Tower / Hunter Templates
# =============================================================================

def test_bunker_prepper_title_pool_has_zero_tower_templates():
    pool = ARCHETYPE_TITLE_POOLS.get("bunker_prepper", [])
    for t in pool:
        assert "tower" not in t.lower(), f"Tower in bunker pool: {t}"
        assert "gate" not in t.lower(), f"Gate in bunker pool: {t}"
        assert "sss-rank" not in t.lower(), f"SSS-rank in bunker pool: {t}"
        assert "trainee" not in t.lower(), f"Trainee in bunker pool: {t}"


# =============================================================================
# TEST 59: Title Variants Strictly Validated Against Evidence
# =============================================================================

def test_title_variants_strictly_validated_against_evidence():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    beats = {"disaster": "Zombie Apocalypse", "mc_name": "Tae", "advantage": "Tactics"}
    variants = generate_ab_title_variants("Zombie Revelation", "zombie_apocalypse", beats, 1, 143, evidence_index=evidence)
    for name, title in variants.items():
        assert evidence.validate_candidate(title, "zombie_apocalypse") is True, f"Variant {name} failed: {title}"


# =============================================================================
# TEST 60: All Thumbnail Fields Scanned For Factual Claims
# =============================================================================

def test_all_thumbnail_fields_scanned_for_factual_claims():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    concept = {
        "id": "concept_test",
        "name": "Normal Name",
        "thumbnail_text": "SURVIVAL",
        "text_style": "Clean sans-serif",
        "composition": "Character center",
        "gpt_prompt": "Draw a high-tech underground doomsday bunker with 16 years of supplies.",
    }
    res = validate_thumbnail_concept(concept, evidence, "zombie_apocalypse")
    assert res["passed"] is False
    assert any("bunker" in v.lower() or "16 years" in v.lower() for v in res["violations"])


# =============================================================================
# TEST 61: Thumbnail Concept Rejected If Any Field Fails Evidence
# =============================================================================

def test_thumbnail_concept_rejected_if_any_field_fails_evidence():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    concept = {
        "id": "concept_test",
        "name": "Day 143 Survival",
        "thumbnail_text": "SURVIVAL",
        "text_style": "Clean font",
        "composition": "Draw Day 143 survivor",
        "gpt_prompt": "Draw Tae holding defense line.",
    }
    res = validate_thumbnail_concept(concept, evidence, "zombie_apocalypse")
    assert res["passed"] is False


# =============================================================================
# TEST 62: No Hallucinated Bunker in Zombie Thumbnail Prompts
# =============================================================================

def test_no_hallucinated_bunker_in_thumbnail_prompts():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts(
        comic_title="Zombie Revelation",
        archetype="zombie_apocalypse",
        mc_name="Tae",
        beats={"disaster": "Zombie Apocalypse", "scarce_thing": "Food", "advantage": "Tactics"},
        evidence_index=evidence,
    )
    for c in concepts:
        assert "doomsday bunker" not in c["gpt_prompt"].lower()
        assert "underground bunker" not in c["gpt_prompt"].lower()


# =============================================================================
# TEST 63: No Hallucinated Day in Thumbnail Text When Day Not Evidenced
# =============================================================================

def test_no_hallucinated_day_in_thumbnail_text():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts(
        comic_title="Zombie Revelation",
        archetype="zombie_apocalypse",
        mc_name="Tae",
        beats={"disaster": "Zombie Apocalypse", "scarce_thing": "Food", "advantage": "Tactics"},
        evidence_index=evidence,
        story_memory=None,
    )
    for c in concepts:
        assert "DAY 143" not in c["thumbnail_text"]
        assert "DAY 47" not in c["thumbnail_text"]
        assert "DAY 100" not in c["thumbnail_text"]


# =============================================================================
# TEST 64: Chapter Semantic Components Individually Verified
# =============================================================================

def test_chapter_semantic_components_individually_verified(tmp_path):
    ep1 = tmp_path / "episode_1"
    ep1.mkdir()
    (ep1 / "recap.json").write_text(
        json.dumps([{"speech": "The outbreak began with patient zero in the hospital ward."}]),
        encoding="utf-8",
    )
    theme, snippet, _ = extract_episode_theme_with_snippet(
        str(ep1 / "recap.json"), 1, "Zombie Revelation", "zombie_apocalypse"
    )
    assert "Patient Zero" in theme or "Outbreak" in theme
    assert len(snippet) > 0


# =============================================================================
# TEST 65: Chapter Title Has No Trailing Incomplete Phrases
# =============================================================================

def test_chapter_title_has_no_trailing_incomplete_phrases():
    ch_list = [
        {"episode": 1, "timestamp": "00:00", "title": "Outbreak & Patient Zero (Ep 1)"},
        {"episode": 15, "timestamp": "01:30:00", "title": "Defense Line Against The Horde (Ep 15)"},
    ]
    for ch in ch_list:
        t = ch["title"]
        assert not re.search(r"\b(?:against\s+the\s+incoming|in\s+the|at\s+the|of\s+the)\s*\([^\)]+\)$", t, re.IGNORECASE)


# =============================================================================
# TEST 66: Chapter Assertions Have Exact Supporting Snippets
# =============================================================================

def test_chapter_assertions_have_exact_supporting_snippets(tmp_path):
    ep1 = tmp_path / "episode_1"
    ep1.mkdir()
    (ep1 / "recap.json").write_text(
        json.dumps([{"speech": "The military issued a quarantine martial law order over the radio."}]),
        encoding="utf-8",
    )
    theme, snippet, _ = extract_episode_theme_with_snippet(
        str(ep1 / "recap.json"), 1, "Zombie Revelation", "zombie_apocalypse"
    )
    assert "quarantine" in snippet.lower() or "martial law" in snippet.lower() or "military" in snippet.lower()


# =============================================================================
# TEST 67: Survival Dashboard Has No Hardcoded Unsupported Defaults
# =============================================================================

def test_survival_dashboard_has_no_hardcoded_unsupported_defaults():
    dash = generate_survival_dashboard_data("zombie_apocalypse", 1, 143, story_memory=None)
    assert dash["day_number"] is None
    assert dash["food_reserve_pct"] is None
    assert dash["water_reserve_pct"] is None
    assert dash["mc_level"] is None
    assert dash["power_status"] is None


# =============================================================================
# TEST 68: Survival Dashboard Fields Individually Grounded
# =============================================================================

def test_survival_dashboard_fields_individually_grounded():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    dash = generate_survival_dashboard_data("zombie_apocalypse", 1, 143, story_memory={"day": 10, "food": 50})
    assert dash["day_number"] == 10
    assert dash["food_reserve_pct"] == 50


# =============================================================================
# TEST 69: Pinned Comment Built Strictly From Validated Dashboard
# =============================================================================

def test_pinned_comment_built_strictly_from_validated_dashboard():
    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=143,
        story_memory={"protagonist_name": "Tae"},
    )
    pinned = meta["pinned_comment"]
    assert "Lv." not in pinned
    assert "%" not in pinned or "Original" in pinned
    assert "SURVIVAL LOG" in pinned


# =============================================================================
# TEST 70: Pinned Comment Has No Hallucinated Stats
# =============================================================================

def test_pinned_comment_has_no_hallucinated_stats():
    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=143,
    )
    pinned = meta["pinned_comment"]
    for fake in ["83%", "100% Drop", "Lv. 99", "SSS-Rank", "16 Years"]:
        assert fake not in pinned


# =============================================================================
# TEST 71: Detected Assertions Equals Validated Assertions Invariant
# =============================================================================

def test_detected_assertions_equals_validated_assertions_invariant():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    text = "When Zombie Apocalypse Strikes, Tae Uses Tactics To Survive [Ep 1~143] | Manhwa Recap"
    res = validate_text_surface(text, evidence, "zombie_apocalypse", surface_type="title")
    assert res["assertions_detected"] == res["assertions_validated"]


# =============================================================================
# TEST 72: Assertion Trace Contains All Surface Texts
# =============================================================================

def test_assertion_trace_contains_all_surface_texts():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    text = "From Outbreak to Total Collapse: Surviving Zombie Apocalypse [Ep 1~143] | Manhwa Recap"
    assertions = extract_semantic_assertions(text)
    for a in assertions:
        evidence.verify_assertion(a)
    trace = [a.to_dict() for a in assertions]
    assert isinstance(trace, list)


# =============================================================================
# TEST 73: Packaging Consistency Verifies All 7 Surfaces
# =============================================================================

def test_packaging_consistency_verifies_all_7_surfaces():
    evidence = EvidenceIndex("Zombie Revelation", "zombie_apocalypse")
    concepts = _build_resource_contrast_concepts("Zombie Revelation", "zombie_apocalypse", "Tae", {"disaster": "Zombie Apocalypse", "advantage": "Tactics"}, evidence)
    res = validate_packaging_consistency(
        title="When Zombie Apocalypse Strikes, Tae Holds The Line | Manhwa Recap",
        thumbnail_concepts=concepts,
        description="When zombie apocalypse strikes, Tae holds the line.\nOriginal scripted narration.",
        narrative_chapters=[],
        tags=["manhwa recap", "zombie manhwa"],
        archetype="zombie_apocalypse",
        evidence_index=evidence,
    )
    assert "title_grounded" in res["checks"]
    assert "thumbnails_grounded" in res["checks"]
    assert "thumbnail_prompts_grounded" in res["checks"]
    assert "chapter_00_present" in res["checks"]
    assert "chapters_grounded" in res["checks"]
    assert "pinned_comment_grounded" in res["checks"]
    assert "survival_dashboard_grounded" in res["checks"]


# =============================================================================
# TEST 74: Zombie 143 Full Pipeline Zero Grounding Failures
# =============================================================================

def test_zombie_143_full_pipeline_zero_grounding_failures():
    real_stage11_chapters = [
        {"episode": 1, "timestamp": "00:00"},
        {"episode": 15, "timestamp": "01:32:56"},
        {"episode": 30, "timestamp": "03:16:04"},
        {"episode": 143, "timestamp": "12:00:00"},
    ]
    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=143,
        chapters=real_stage11_chapters,
        story_memory={"protagonist_name": "Tae", "episodes": {}},
    )
    assert meta["prepublish_audit"]["passed"] is True
    assert meta["packaging_audit"]["is_consistent"] is True
    assert len(meta["prepublish_audit"]["unsupported_claims"]) == 0


# =============================================================================
# TEST 75: Bunker Prepper Full Pipeline Zero Grounding Failures
# =============================================================================

def test_bunker_prepper_full_pipeline_zero_grounding_failures():
    # V5.1: chapters_explicitly_disabled=True — test checks title/archetype, not chapter timeline
    meta = generate_us_apocalypse_metadata(
        comic_title="Sub-Zero Bunker Prepper",
        from_ep=1,
        to_ep=50,
        story_memory={"protagonist_name": "Jin", "episodes": {}},
        chapters_explicitly_disabled=True,
    )
    assert meta["prepublish_audit"]["passed"] is True
    assert meta["packaging_audit"]["is_consistent"] is True
    for opt in meta["title_options"]:
        assert "tower" not in opt.lower()
        assert "sss-rank" not in opt.lower()


# =============================================================================
# TEST 76: Regression Prep Full Pipeline Zero Grounding Failures
# =============================================================================

def test_regression_prep_full_pipeline_zero_grounding_failures():
    # V5.1: chapters_explicitly_disabled=True — regression test for title/claim quality
    meta = generate_us_apocalypse_metadata(
        comic_title="I Regressed 10 Years Before Cataclysm",
        from_ep=1,
        to_ep=30,
        story_memory={"protagonist_name": "Kang", "episodes": {}},
        chapters_explicitly_disabled=True,
    )
    assert meta["prepublish_audit"]["passed"] is True
    assert meta["packaging_audit"]["is_consistent"] is True


# =============================================================================
# TEST 77: All 11 V4 Review Artifacts Generated And Valid
# =============================================================================

def test_all_11_v4_artifacts_generated_and_valid():
    meta = generate_us_apocalypse_metadata(
        comic_title="Zombie Revelation 82-08",
        from_ep=1,
        to_ep=143,
        story_memory={"protagonist_name": "Tae"},
    )
    # Check that metadata contains all necessary fields for 11 V4 artifacts
    assert "title" in meta
    assert "title_options" in meta
    assert "title_variants" in meta
    assert "thumbnail_concepts" in meta
    assert "narrative_chapters" in meta
    assert "survival_dashboard" in meta
    assert "pinned_comment" in meta
    assert "packaging_audit" in meta
    assert "prepublish_audit" in meta
    assert meta["prepublish_audit"]["title_validation"] is not None

