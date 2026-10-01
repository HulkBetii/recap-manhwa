# -*- coding: utf-8 -*-
"""
V5.3 Tests — Tests 144–149: Stage 5 Narration Retention & Protagonist Bootstrap Patch.
Covers:
  - Test 144: Few-shot prompt sanitization (zero hardcoded 'Paran' leakage)
  - Test 145: Confirmed protagonist identity box injection (authoritative anchoring)
  - Test 146: Character-first opening override directive (0-15s hook guarantee)
  - Test 147: Protagonist entity normalization helper (Paran -> canonical name)
  - Test 148: Infer protagonist name stopword exclusion ('Paran' in stopwords)
  - Test 149: StoryMemory binge continuity and recap sanitization (no propagation)
"""
from __future__ import annotations

import os
import sys
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import generate_gemini_prompt
from story_memory import StoryMemory
# get_character_names removed with market system


# =============================================================================
# TESTS: V5.3 RETENTION & PROTAGONIST BOOTSTRAP (Tests 144–149)
# =============================================================================

def test_144_few_shot_prompt_sanitization():
    """
    Test 144: Verify that few-shot output examples don't contain hardcoded 'Paran'.
    The instruction hint section may still reference 'Paran' as an example name.
    """
    prompt_cold = generate_gemini_prompt(
        comic_title="Zombie Revelation 82-08",
        ep=1,
        total_pages=50,
        previous_context=None,
    )
    # Examples section should not contain hardcoded Paran (it should be "the protagonist")
    # Note: The instruction hint section may say "such as 'Paran', 'Jinwoo'" — that's OK
    assert "{example_protagonist_name}" not in prompt_cold, "Template variables must be formatted!"
    # The output examples should not hardcode Paran (since no previous_context was given)
    examples_section = prompt_cold.split("Examples:")[-1] if "Examples:" in prompt_cold else ""
    # Only check the few-shot example lines, not the instruction text
    example_lines = [l for l in examples_section.splitlines() if l.strip().startswith(("5 -", "[12", "[14", "24 -"))]
    paran_in_examples = any("Paran" in l for l in example_lines)
    assert not paran_in_examples, f"Few-shot example lines must not contain 'Paran'! Found in: {example_lines}"

    prompt_with_mc = generate_gemini_prompt(
        comic_title="Zombie Revelation 82-08",
        ep=1,
        total_pages=50,
        previous_context={"protagonist_name": "Tae", "protagonist_gender": "male"},
    )
    assert "Tae" in prompt_with_mc, "Prompt should contain the confirmed protagonist name in examples!"


def test_145_confirmed_protagonist_identity_box():
    """
    Test 145: Verify that when previous_context has confirmed protagonist info,
    the CONFIRMED PROTAGONIST IDENTITY authoritative box is rendered into the prompt.
    """
    prompt = generate_gemini_prompt(
        comic_title="Zombie Revelation 82-08",
        ep=1,
        total_pages=50,
        previous_context={
            "protagonist_name": "Tae",
            "protagonist_gender": "male",
            "unique_hook": "Underground Bunker Prepper",
        },
    )
    assert "CONFIRMED PROTAGONIST IDENTITY:" in prompt
    assert "Name: Tae" in prompt
    assert "Gender: Male" in prompt
    assert 'You MUST explicitly introduce "Tae" in Segment 1 or 2!' in prompt
    assert "This identity is authoritative." in prompt
    assert 'IP CONTEXT & HOOK ELEMENT: "Underground Bunker Prepper"' in prompt


def test_146_character_first_hook_override_directive():
    """
    Test 146: Verify that Episode 1 prompt contains the CHARACTER-FIRST OPENING OVERRIDE directive
    ensuring 0-15s protagonist establishment even when opening art is pure environmental disaster.
    """
    prompt = generate_gemini_prompt(
        comic_title="Zombie Revelation 82-08",
        ep=1,
        total_pages=50,
        previous_context={"protagonist_name": "Tae"},
    )
    assert "CHARACTER-FIRST OPENING OVERRIDE (CRITICAL FOR RETENTION):" in prompt
    assert "Even if the opening comic pages (Pages 1-5) depict only:" in prompt
    assert "city destruction / smoke / rubble" in prompt
    assert "You MUST narrate the event through the protagonist's survival lens from Line 1!" in prompt
    assert "Segment 1 or Segment 2 (0-15s) must communicate:" in prompt


def test_147_normalize_protagonist_entities():
    """
    Test 147: Verify that StoryMemory.normalize_protagonist_entities replaces
    both 'Paran' and 'Paran\'s' with the canonical protagonist name while preserving other text.
    """
    raw_text = "Paran slammed the door shut. Paran's heart was racing as paranoid raiders approached."
    normalized = StoryMemory.normalize_protagonist_entities(raw_text, "Tae")
    assert normalized == "Tae slammed the door shut. Tae's heart was racing as paranoid raiders approached."
    assert "paranoid" in normalized, "Substrings like 'paranoid' must not be corrupted!"
    assert "Paran" not in normalized


def test_148_infer_protagonist_name_stopwords():
    """
    Test 148: Verify that 'Paran' is excluded from being inferred as a protagonist name
    even if it appears frequently at the beginning or middle of segments.
    """
    recap_data = [
        {"speech": "Paran dashed across the ruins and shouted to the survivors."},
        {"speech": "Seeing the zombies, Paran loaded the rifle immediately."},
        {"speech": "The danger grew as Paran secured the shelter."},
    ]
    inferred = StoryMemory.infer_protagonist_name(recap_data)
    assert inferred != "Paran", "StoryMemory must not infer 'Paran' as protagonist name!"


def test_149_binge_continuity_and_story_memory_sanitization():
    """
    Test 149: Verify that StoryMemory cleanses hallucinated entities when storing episode recaps
    and correctly feeds canonical context to subsequent episodes.
    """
    memory = StoryMemory(comic_title="Zombie Revelation 82-08", language="en", protagonist_name="Tae")
    ep1_recap = [
        {"speech": "Paran watched the apocalypse unfold from the fortified bunker door."},
        {"speech": "Tae gathered the remaining medical supplies in haste."},
        {"speech": "Paran's radio suddenly emitted a strange high-frequency static signal."},
    ]
    memory.add_episode_recap(1, ep1_recap, language="en", protagonist_name="Tae")

    ep1_stored = memory.episodes["1"]
    assert "Paran" not in ep1_stored["opening"], "Episode 1 opening must be normalized to canonical MC name!"
    assert "Tae watched the apocalypse unfold" in ep1_stored["opening"]
    assert "Paran" not in ep1_stored["closing_cliffhanger"]
    assert "Tae's radio" in ep1_stored["closing_cliffhanger"]

    ctx = memory.get_previous_context(2)
    assert ctx is not None
    assert ctx["protagonist_name"] == "Tae"
    assert "Tae's radio" in ctx["closing_cliffhanger"]
