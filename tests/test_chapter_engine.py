import asyncio
import json

from chapter_engine import (
    ChapterNameValidator,
    apply_chapter_names,
    arc_key,
    build_arc_inputs,
    generate_llm_chapter_options,
    parse_chapter_options,
)
from prepublish_gate import check_chapter_naming
from title_engine import TitleRegistry
from youtube_metadata import build_narrative_story_chapters, generate_youtube_metadata

NARRATION = {
    1: ["Martial law hits Seoul as soldiers seal the bridges.", "Tae spots the first infected at the checkpoint."],
    2: ["The mob boss Mingu demands payment in the restaurant.", "Tae breaks the thug's jaw with one punch."],
    3: ["The convoy races through the frozen highway.", "Raiders ambush the convoy for the fuel canisters."],
}
CHAPTERS = [
    {"episode": 1, "end_episode": 1, "timestamp": "00:00", "theme": "Part 1"},
    {"episode": 2, "end_episode": 2, "timestamp": "45:10", "theme": "Part 2"},
    {"episode": 3, "end_episode": 3, "timestamp": "01:31:02", "theme": "Part 3"},
]


def _validator(**kwargs):
    return ChapterNameValidator(NARRATION, placeholder_names=["Paran"], **kwargs)


# --- Validator: every defect seen on the channel -----------------------------

def test_published_chapter_defects_are_rejected():
    v = _validator()
    assert any(r.startswith("dangling_last_word") for r in v.check("Tae Plants His Feet Against The", 1, 1).reasons)
    assert "numbering_or_symbols" in v.check("Arc 1: Nightmare Tower & The Rejected Regression", 1, 1).reasons
    assert "numbering_or_symbols" in v.check("Survival Operation (Eps 1–14)", 1, 1).reasons
    assert "placeholder_name" in v.check("Paran Holds The Checkpoint", 1, 1).reasons


def test_grounding_is_scoped_to_the_arc():
    v = _validator()
    assert v.check("Convoy Ambush On The Highway", 3, 3).passed
    wrong_arc = v.check("Convoy Ambush On The Highway", 1, 1)
    assert any(r.startswith("low_grounding") for r in wrong_arc.reasons)


def test_genre_promise_needs_evidence_in_arc():
    check = _validator().check("Martial Law Trainee Awakening", 1, 1)
    assert any(r.startswith("claim_not_in_arc") for r in check.reasons)


def test_duplicates_within_video_and_across_videos():
    v = _validator(other_video_chapters=["Martial Law Falls"])
    assert "duplicate_of_other_video" in v.check("Martial Law Falls", 1, 1).reasons
    assert "duplicate_in_video" in v.check("Mingu Demands Payment", 2, 2, accepted=["Mingu Demands Payment Now"]).reasons


# --- Application -------------------------------------------------------------

def test_apply_prefers_llm_then_existing_then_part_fallback():
    chapters = [dict(CHAPTERS[0]), {**CHAPTERS[1], "theme": "The Restaurant Brawl"}, dict(CHAPTERS[2])]
    options = {
        arc_key(1, 1): ["Martial Law Hits Seoul"],
        arc_key(2, 2): ["Tower Floor Hundred"],          # ungrounded -> existing theme wins
        arc_key(3, 3): ["The Last Stand Against The"],   # dangling -> no existing -> Part 3
    }
    named, audit = apply_chapter_names(chapters, options, _validator())
    assert [c["theme"] for c in named] == ["Martial Law Hits Seoul", "The Restaurant Brawl", "Part 3"]
    assert [c["naming_source"] for c in named] == ["llm", "existing", "fallback"]
    assert named[0]["title"] == "Martial Law Hits Seoul (Ep 1)"
    assert (audit.llm_named, audit.kept_existing, audit.fallback_part) == (1, 1, 1)
    assert not check_chapter_naming(named).passed  # generic "Part 3" is surfaced as a warning


def test_two_comics_cannot_ship_identical_chapters():
    registry = TitleRegistry(path="unused.json")
    stage11_name = "Nightmare Tower & The Rejected Regression"
    narration = {1: ["The nightmare tower appears and everyone rejected regression except him."]}
    shipped = []
    for comic in ("Comic A", "Comic B"):
        v = ChapterNameValidator(narration, other_video_chapters=registry.chapter_names_for_dedup(comic))
        named, _ = apply_chapter_names([{"episode": 1, "end_episode": 1, "timestamp": "00:00", "theme": stage11_name}], {}, v)
        shipped.append(named[0]["theme"])
        registry.record_kit_title(f"{comic} title", comic, 1, 1, chapters=[named[0]["theme"]])
    assert shipped == [stage11_name, "Part 1"]


# --- Arc digests & LLM parsing -----------------------------------------------

def test_arc_digest_prefers_story_memory_summaries():
    memory = {"episodes": {"2": {"summary": "Tae humiliates the mob boss."}}}
    arcs = build_arc_inputs(CHAPTERS, NARRATION, memory)
    assert [a.key for a in arcs] == ["1-1", "2-2", "3-3"]
    assert "Tae humiliates the mob boss." in arcs[1].digest
    assert "Martial law hits Seoul" in arcs[0].digest  # narration fallback


def test_parse_chapter_options_and_llm_failure():
    raw = '```json\n{"1-1": ["Martial Law Hits Seoul", "Checkpoint Panic"], "2-2": "Restaurant Brawl"}\n```'
    assert parse_chapter_options(raw) == {"1-1": ["Martial Law Hits Seoul", "Checkpoint Panic"], "2-2": ["Restaurant Brawl"]}

    async def failing(_prompt):
        raise RuntimeError("quota")

    arcs = build_arc_inputs(CHAPTERS, NARRATION)
    assert asyncio.run(generate_llm_chapter_options(arcs, ["Tae"], failing)) == {}


# --- No more hardcoded / truncated themes ------------------------------------

def test_builder_never_invents_archetype_boilerplate(tmp_path):
    for ep, segs in NARRATION.items():
        d = tmp_path / f"episode_{ep}"
        d.mkdir()
        (d / "recap.json").write_text(json.dumps([{"speech": s} for s in segs]), encoding="utf-8")
    raw = [{"episode": ep, "timestamp": ts, "title": f"Episode {ep}"} for ep, ts in [(1, "00:00"), (2, "45:10"), (3, "01:31:02")]]
    chapters = build_narrative_story_chapters(raw, download_dir=str(tmp_path), archetype="zombie_apocalypse", from_ep=1, to_ep=3)
    assert [c["theme"] for c in chapters] == ["Part 1", "Part 2", "Part 3"]


def test_metadata_description_uses_validated_llm_chapter_names(tmp_path):
    for ep, segs in NARRATION.items():
        d = tmp_path / f"episode_{ep}"
        d.mkdir()
        (d / "recap.json").write_text(
            json.dumps([{"speech": s, "images": [{"page": 1, "priority": 1.0}]} for s in segs]), encoding="utf-8"
        )
    raw = [{"episode": ep, "timestamp": ts, "title": f"Episode {ep}"} for ep, ts in [(1, "00:00"), (2, "45:10"), (3, "01:31:02")]]
    meta = generate_youtube_metadata(
        "Zombie Revelation 82-08", 1, 3, chapters=raw, download_dir=str(tmp_path),
        llm_chapter_options={"1-1": ["Martial Law Hits Seoul"], "2-2": ["Mingu Demands Payment"], "3-3": ["Convoy Ambush On The Highway"]},
    )
    desc = meta["description"]
    assert "00:00 - Martial Law Hits Seoul (Ep 1)" in desc
    assert "01:31:02 - Convoy Ambush On The Highway (Ep 3)" in desc
    assert meta["prepublish_audit"]["claim_audit"]["chapter_engine"]["llm_named"] == 3
