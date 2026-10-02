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
