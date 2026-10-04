import json

from series_bible import CharacterEntry, new_bible, save_bible
from youtube_metadata import (
    format_mini_status_block,
    generate_engagement_question,
    generate_youtube_metadata,
)

DASHBOARD = {"story_arc": "Episodes 1–3 (3 Chapters)", "outside_condition": "Infected Urban Sector — Active Swarms"}
GUESSED_BEATS = {"shelter": "Mountain Sanctuary", "companion_name": "His Mutated Companion", "boss_name": "The Apex Beast"}


def _bible():
    bible = new_bible("Veteran of the Apocalypse")
    bible.protagonist = CharacterEntry(name="Gimbaplover", gender="male")
    bible.setting = "An asteroid turns the zombie scenario of the game Survival Life into reality."
    return bible


def test_status_block_prints_only_verifiable_facts():
    block = format_mini_status_block("zombie_apocalypse", DASHBOARD, beats=GUESSED_BEATS, series_bible=_bible())
    assert "Episodes 1–3" in block
    assert "Premise: An asteroid turns the zombie scenario" in block
    for guessed in ("Mountain Sanctuary", "Mutated Companion", "Apex Beast", "Infected Urban Sector"):
        assert guessed not in block


def test_asteroid_question_never_says_in_days_without_a_number():
    q = generate_engagement_question("zombie_apocalypse", {"disaster": "The Asteroid Impact", "time_before": "Days"})
    assert " in Days" not in q and "about to hit Earth," in q
    q2 = generate_engagement_question("zombie_apocalypse", {"disaster": "The Asteroid Impact", "time_before": "27 Days"})
    assert "about to hit Earth in 27 Days," in q2


def test_engagement_question_is_deterministic():
    picks = {generate_engagement_question("zombie_apocalypse", None, seed="Veteran of the Apocalypse") for _ in range(20)}
    assert len(picks) == 1


def test_kit_pinned_comment_has_no_guessed_lines(tmp_path):
    ep = tmp_path / "episode_1"
    ep.mkdir()
    segments = [
        "The asteroid Eunjambi burns toward Earth as the countdown ticks.",
        "A loyal dog barks near the mountain road while survivors flee.",
    ]
    (ep / "recap.json").write_text(json.dumps([{"speech": s, "images": [{"page": 1, "priority": 1.0}]} for s in segments]), encoding="utf-8")
    save_bible(_bible(), str(tmp_path))
    first = generate_youtube_metadata("Veteran of the Apocalypse", 1, 1, download_dir=str(tmp_path))["pinned_comment"]
    second = generate_youtube_metadata("Veteran of the Apocalypse", 1, 1, download_dir=str(tmp_path))["pinned_comment"]
    assert first == second
    assert "Sanctuary" not in first and "Companion" not in first and " in Days" not in first
    assert "🌍 Premise:" in first


def test_where_we_left_off_uses_the_last_episode_not_the_last_saved():
    """Parallel Stage 5 chunks save StoryMemory episodes in completion order (here 3, 1, 2)."""
    def ep(n, cliff):
        return {"opening": f"Episode {n} opens on the ruined highway.", "summary": f"Summary of episode {n}.", "closing_cliffhanger": cliff}

    memory = {"episodes": {
        "3": ep(3, "The final gate cracks open and a colossal shadow steps through the breach."),
        "1": ep(1, "The countdown hits zero as the first sirens wail across the city."),
        "2": ep(2, "Behind the president, a demonic entity looms in the shadows of the hall."),
    }}
    pinned = generate_youtube_metadata("Veteran of the Apocalypse", 1, 3, story_memory=memory)["pinned_comment"]
    assert "The final gate cracks open" in pinned
    assert "demonic entity looms" not in pinned


def test_one_mention_is_not_a_story_beat():
    """Tyrant 1-3: a single "freeze" made it a Global Freeze story with a heated-bunker question."""
    from youtube_metadata import _beat_evidence
    assert not _beat_evidence("he could freeze in fear for a second", ["freeze", "frozen"])
    assert _beat_evidence("the freeze spreads; frozen streets everywhere", ["freeze", "frozen"])
    assert not _beat_evidence("he bowed his head", ["recurve bow", "bow and arrow", "arrow"])


def test_engagement_question_skips_invented_names():
    from youtube_metadata import _names_in_story
    corpus = "goong nam slays a demon in the abyss"
    beats = {"disaster": "The Hellgate Invasion", "boss_name": "The Skeleton Chieftain"}
    q = generate_engagement_question(
        "regression_prep", beats, seed="Tyrant", accept=lambda text: _names_in_story(text, corpus),
    )
    assert "Skeleton Chieftain" not in q


def test_rejected_premise_line_is_dropped():
    from youtube_metadata import format_mini_status_block
    bible = _bible()
    block = format_mini_status_block("zombie_apocalypse", {"story_arc": "Episodes 1–3"}, series_bible=bible,
                                     accept=lambda text: False)
    assert "Premise" not in block and "Episodes 1–3" in block


def test_weapon_beat_is_the_most_mentioned_weapon(tmp_path):
    """Tyrant 1-10: two arrows fired at him outranked 18 "blade" mentions (first-match order)."""
    from youtube_metadata import _extract_story_beats
    ep = tmp_path / "episode_1"
    ep.mkdir()
    lines = ["Arrows pin his arm.", "Goblins with arrows fall."] + ["He swings his blade at the demon."] * 5
    (ep / "recap.json").write_text(json.dumps([{"speech": s} for s in lines]), encoding="utf-8")
    beats = _extract_story_beats("Tyrant", "regression_prep", None, str(tmp_path), 1, 1)
    assert beats["primary_weapon"] == "A Survival Blade"


def test_abandoned_places_are_not_betrayal(tmp_path):
    from youtube_metadata import generate_youtube_metadata
    ep = tmp_path / "episode_1"
    ep.mkdir()
    lines = ["He searches an abandoned building.", "The abandoned car blocks the road.", "Demons roam the abandoned city."]
    (ep / "recap.json").write_text(json.dumps([{"speech": s, "images": [{"page": 1, "priority": 1.0}]} for s in lines]), encoding="utf-8")
    save_bible(_bible(), str(tmp_path))
    meta = generate_youtube_metadata("Veteran of the Apocalypse", 1, 1, download_dir=str(tmp_path))
    assert not any(c["id"] == "concept_betrayal_retribution" for c in meta["thumbnail_concepts"])
