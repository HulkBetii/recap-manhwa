import asyncio
import json

from title_engine import HookSheet
from thumbnail_text import (
    OverlayValidator,
    apply_overlays,
    generate_llm_overlay_options,
    parse_overlay_options,
)
from youtube_metadata import _cap_overlay_text, generate_youtube_metadata

TITLE = "The Zombie Apocalypse HIT But His Room Holds a Gate! | Manhwa Recap"
CORPUS = [
    "A massive asteroid named Eunjambi burns toward Earth as the countdown ticks.",
    "Gimbaplover opens a pulsing dimensional gate inside his bedroom.",
    "An enormous Owl Bear charges out of the dark forest and the mutants scatter.",
]


def _sheet():
    return HookSheet(comic_title="Veteran of the Apocalypse", corpus=CORPUS, character_names=["Gimbaplover"])


def _concept(cid, main, sub):
    return {
        "id": cid,
        "name": "Scene",
        "composition": "close-up",
        "thumbnail_text": f"{main} / {sub}",
        "text_style": f"Upper-left: ('{main}'). Lower-right: ('{sub}').",
        "gpt_prompt": f"Upper-left text '{main}'. Lower-right text '{sub}'.",
    }


def test_cap_no_longer_cuts_phrases():
    """Regression: 'YOU'RE CORNERED!' used to ship as "YOU'RE!"."""
    assert _cap_overlay_text("YOU'RE CORNERED!") == "YOU'RE CORNERED!"


def test_validator_rejects_long_ungrounded_and_title_echo():
    v = OverlayValidator(_sheet(), TITLE, character_names=["Gimbaplover"])
    assert v.check("SKY IS FALLING!", "OWL BEAR!", "llm").passed
    assert any(r.startswith("sub_too_long") for r in v.check("SKY IS FALLING!", "OWL BEAR ATTACK!", "t").reasons)  # 16 chars
    assert any(r.startswith("sub_too_long") for r in v.check("SKY IS FALLING!", "IMMUNITY AWAKENED!", "t").reasons)
    assert any(r.startswith("low_grounding") for r in v.check("IMMUNITY!", "OWL BEAR!", "t").reasons)
    assert "repeats_title" in v.check("ROOM GATE!", "OWL BEAR!", "llm").reasons
    assert "character_name" in v.check("GIMBAPLOVER!", "OWL BEAR!", "llm").reasons


def test_apply_prefers_valid_llm_option_and_rewrites_prompt_text():
    concept = _concept("c1", "SKY IS FALLING!", "IMMUNITY AWAKENED!")
    options = {"c1": [("BAD TEXT THAT IS LONG", "X"), ("ASTEROID HITS!", "OWL BEAR!")]}
    [updated], checks = apply_overlays([concept], options, OverlayValidator(_sheet(), TITLE))
    assert updated["thumbnail_text"] == "ASTEROID HITS! / OWL BEAR!"
    assert "'ASTEROID HITS!'" in updated["gpt_prompt"] and "IMMUNITY" not in updated["gpt_prompt"]
    assert updated["overlay_valid"] is True
    # The valid option does not fit the generic "Scene" concept, so the template is checked too.
    assert [c.passed for c in checks] == [False, True, False]


def test_invalid_template_without_options_is_flagged_not_truncated():
    concept = _concept("c4", "YOU'RE CORNERED!", "NOT EVEN CLOSE!")
    [updated], _ = apply_overlays([concept], {}, OverlayValidator(_sheet(), TITLE))
    assert updated["overlay_valid"] is False
    assert updated["thumbnail_text"] == "YOU'RE CORNERED! / NOT EVEN CLOSE!"


def test_parse_and_llm_failure():
    raw = '```json\n{"c1": [{"main": "sky is falling!", "sub": "owl bear attack!"}]}\n```'
    assert parse_overlay_options(raw) == {"c1": [("SKY IS FALLING!", "OWL BEAR ATTACK!")]}

    async def failing(_prompt):
        raise RuntimeError("quota")

    assert asyncio.run(generate_llm_overlay_options(_sheet(), TITLE, [_concept("c1", "A", "B")], failing)) == {}


def _story_dir(tmp_path, extra_segment=""):
    ep = tmp_path / "episode_1"
    ep.mkdir()
    segs = CORPUS + ([extra_segment] if extra_segment else [])
    (ep / "recap.json").write_text(json.dumps([{"speech": s, "images": [{"page": 1, "priority": 1.0}]} for s in segs]), encoding="utf-8")
    return str(tmp_path)


def test_no_rival_concept_without_antagonists(tmp_path):
    meta = generate_youtube_metadata("Veteran of the Apocalypse", 1, 1, download_dir=_story_dir(tmp_path))
    ids = [c["id"] for c in meta["thumbnail_concepts"]]
    assert "concept_rival_standoff" not in ids
    assert all(len(part) <= 15 or c.get("overlay_valid") is False
               for c in meta["thumbnail_concepts"] for part in c["thumbnail_text"].split(" / "))


def test_seduction_concept_requires_a_named_female_character(tmp_path):
    from series_bible import CharacterEntry, new_bible, save_bible

    download_dir = _story_dir(tmp_path)
    ids = [c["id"] for c in generate_youtube_metadata("Veteran of the Apocalypse", 1, 1, download_dir=download_dir)["thumbnail_concepts"]]
    assert "concept_sexy_clickbait_allure" not in ids

    bible = new_bible("Veteran of the Apocalypse")
    bible.protagonist = CharacterEntry(name="Gimbaplover", gender="male")
    bible.characters.append(CharacterEntry(name="Sora", gender="female"))
    save_bible(bible, download_dir)
    concepts = generate_youtube_metadata("Veteran of the Apocalypse", 1, 1, download_dir=download_dir)["thumbnail_concepts"]
    c7 = next(c for c in concepts if c["id"] == "concept_sexy_clickbait_allure")
    assert "Sora" in c7["composition"]


def test_kit_flags_unfixable_overlays_in_gate(tmp_path):
    meta = generate_youtube_metadata("Veteran of the Apocalypse", 1, 1, download_dir=_story_dir(tmp_path))
    gate = {c["id"]: c for c in meta["prepublish_audit"]["gate"]["checks"]}
    top = meta["thumbnail_concepts"][:3]
    assert gate["thumbnail_overlays_valid"]["passed"] == all(c.get("overlay_valid") for c in top)


def _scene_concept(cid, name, composition, main, sub):
    concept = _concept(cid, main, sub)
    concept.update({"name": name, "composition": composition})
    return concept


def test_fits_scene_needs_a_word_from_the_scene():
    from thumbnail_text import fits_scene
    companion = {"name": "Mutated Beast Companion Stand (His Loyal Pup Dingo)",
                 "composition": "Seongho and His Loyal Pup Dingo side-by-side on rooftop vantage point"}
    assert not fits_scene("SCAVENGERS", "CIRCLE OUTSIDE", companion)  # Veteran 1-33 kit
    assert fits_scene("LOYAL BEAST", "NEVER LEAVES", companion)
    assert fits_scene("ANYTHING", "AT ALL", {"name": "", "composition": ""})


def test_apply_prefers_the_option_that_fits_the_scene():
    concept = _scene_concept("c1", "Apex Monster Clash (The Colossal Owl Bear)", "Hero dodging, Owl Bear looming",
                             "SKY IS FALLING!", "IMMUNITY AWAKENED!")
    options = {"c1": [("ASTEROID HITS!", "COUNTDOWN"), ("OWL BEAR!", "MUTANTS SCATTER")]}
    [updated], _ = apply_overlays([concept], options, OverlayValidator(_sheet(), TITLE))
    assert updated["thumbnail_text"] == "OWL BEAR! / MUTANTS SCATTER" and updated["overlay_scene_fit"] is True


def test_valid_but_off_scene_text_is_kept_and_flagged():
    concept = _scene_concept("c1", "Hero And His Dog", "Petting the dog on a rooftop", "YOU'RE CORNERED!", "NOT EVEN CLOSE!")
    [updated], _ = apply_overlays([concept], {"c1": [("ASTEROID HITS!", "COUNTDOWN")]}, OverlayValidator(_sheet(), TITLE))
    assert updated["thumbnail_text"] == "ASTEROID HITS! / COUNTDOWN"
    assert updated["overlay_valid"] is True and updated["overlay_scene_fit"] is False


def test_prompt_asks_for_the_scene_subject():
    from thumbnail_text import build_overlay_prompt
    assert "subject" in build_overlay_prompt(_sheet(), TITLE, [_concept("c1", "A", "B")])
