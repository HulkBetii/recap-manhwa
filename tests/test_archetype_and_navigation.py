import json

from series_bible import CharacterEntry, new_bible, save_bible
from youtube_metadata import detect_archetype, generate_youtube_metadata, plan_chapter_arcs

# Story memory as produced for Veteran of the Apocalypse ep 1-3: no zombie vocabulary yet,
# but a "Personal Dimensional Gate" — which used to classify the comic as hunter_gate.
EARLY_MEMORY = {"episodes": {"1": {"summary": "A countdown ends; he awakens a Personal Dimensional Gate in his room."}}}


def _veteran_dir(tmp_path):
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir()
    segments = [
        "The digital watch hits eight fifty-nine as the countdown to disaster ticks.",
        "A massive asteroid named Eunjambi burns across deep space toward Earth.",
        "Gimbaplover finds a pulsing dimensional gate inside his room.",
        "The zombie apocalypse hits the city while his room holds the gate shut.",
    ]
    (ep_dir / "recap.json").write_text(
        json.dumps([{"speech": s, "images": [{"page": 1, "priority": 1.0}]} for s in segments]), encoding="utf-8"
    )
    bible = new_bible("Veteran of the Apocalypse")
    bible.protagonist = CharacterEntry(name="Gimbaplover", gender="male")
    bible.setting = "An asteroid turns the apocalyptic zombie scenario of the game Survival Life into reality."
    bible.terms = ["Survival Life", "Personal Dimensional Gate"]
    save_bible(bible, str(tmp_path))
    return str(tmp_path)


def test_bible_setting_corrects_early_episode_archetype():
    assert detect_archetype("Veteran of the Apocalypse", EARLY_MEMORY) == "hunter_gate"
    setting = "An asteroid turns the apocalyptic zombie scenario of the game Survival Life into reality."
    assert detect_archetype("Veteran of the Apocalypse", EARLY_MEMORY, extra_context=setting) == "zombie_apocalypse"


def test_kit_uses_bible_archetype(tmp_path):
    download_dir = _veteran_dir(tmp_path)
    meta = generate_youtube_metadata("Veteran of the Apocalypse", 1, 1, story_memory=EARLY_MEMORY, download_dir=download_dir)
    assert meta["prepublish_audit"]["archetype"] == "zombie_apocalypse"
    assert "#dungeonmanhwa" not in meta["description"]
    assert "hunter gate" not in meta["description"]


def test_stage11_arc_plan_and_kit_agree_on_archetype(tmp_path):
    download_dir = _veteran_dir(tmp_path)
    raw = [{"episode": 1, "timestamp": "00:00", "title": "Episode 1"}]
    arcs = plan_chapter_arcs(raw, "Veteran of the Apocalypse", EARLY_MEMORY, download_dir, 1, 1)
    assert arcs and arcs[0]["episode"] == 1


def test_description_has_no_synthesized_navigation(tmp_path):
    download_dir = _veteran_dir(tmp_path)
    meta = generate_youtube_metadata("Veteran of the Apocalypse", 1, 3, story_memory=EARLY_MEMORY, download_dir=download_dir)
    desc = meta["description"]
    assert "full-recap" not in desc and "Coming Soon" not in desc and "Next Arc" not in desc
    assert "SERIES NAVIGATION" not in desc
    assert meta["series_navigation"] == {"playlist_url": None, "previous_part_url": None, "next_part_url": None}
    gate = {c["id"]: c for c in meta["prepublish_audit"]["gate"]["checks"]}
    assert gate["description_placeholders"]["passed"]


PITCH_TITLE = "The Zombie Apocalypse HIT But His Room Holds a Gate! | Manhwa Recap"
PITCH = {
    "title": PITCH_TITLE,
    "prepended": True,
    "text": "The zombie apocalypse hits modern-day Earth, but Gimbaplover discovers that his room holds a pulsing "
            "dimensional gate. It all begins as the countdown starts.",
}


def test_description_opens_with_title_aligned_keyword_sentence(tmp_path):
    download_dir = _veteran_dir(tmp_path)
    meta = generate_youtube_metadata(
        "Veteran of the Apocalypse", 1, 1, story_memory=EARLY_MEMORY, download_dir=download_dir,
        llm_title_candidates=["The Zombie Apocalypse HIT But His Room Holds a Gate!"], premise_pitch=PITCH,
    )
    assert meta["title"] == PITCH_TITLE  # the pitch only counts for the shipped title
    first_line = meta["description"].splitlines()[0]
    assert first_line == ("The zombie apocalypse hits modern-day Earth, but he discovers that his room "
                          "holds a pulsing dimensional gate.")


def test_description_falls_back_to_short_bible_setting_without_pitch(tmp_path):
    download_dir = _veteran_dir(tmp_path)
    meta = generate_youtube_metadata("Veteran of the Apocalypse", 1, 1, story_memory=EARLY_MEMORY, download_dir=download_dir)
    assert meta["description"].splitlines()[0].startswith("An asteroid turns the apocalyptic zombie scenario")


def test_niche_hashtag_beats_brand_and_tags_are_capped(tmp_path):
    download_dir = _veteran_dir(tmp_path)
    meta = generate_youtube_metadata("Veteran of the Apocalypse", 1, 1, story_memory=EARLY_MEMORY, download_dir=download_dir)
    hashtags = meta["description"].splitlines()[-1].split()
    assert hashtags[:2] == ["#veteranoftheapocalypse", "#zombiemanhwa"]
    assert "#jaehwanmanhwa" not in hashtags  # brand is dropped before a discovery hashtag
    assert 5 <= len(meta["tags"]) <= 10
    assert "manhwa english" not in meta["tags"] and "manhwa summary" not in meta["tags"]


def test_real_links_are_kept(tmp_path):
    download_dir = _veteran_dir(tmp_path)
    playlist = "https://www.youtube.com/playlist?list=PLabc123"
    meta = generate_youtube_metadata(
        "Veteran of the Apocalypse", 1, 3, story_memory=EARLY_MEMORY, download_dir=download_dir,
        playlist_url=playlist, next_part_url="https://youtu.be/xyz",
    )
    desc = meta["description"]
    assert f"• Full Playlist: {playlist}" in desc
    assert "• ⏩ Next Part: https://youtu.be/xyz" in desc
    assert "Previous Part" not in desc
