import json

from series_bible import CharacterEntry, new_bible, save_bible
from youtube_metadata import (
    detect_archetype, generate_youtube_metadata, plan_chapter_arcs, recommend_card_and_endscreen_anchors,
)

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


def test_kit_lists_each_ab_title_once_and_counts_thumbnails(tmp_path):
    download_dir = _veteran_dir(tmp_path)
    meta = generate_youtube_metadata(
        "Veteran of the Apocalypse", 1, 1, story_memory=EARLY_MEMORY, download_dir=download_dir,
        llm_title_candidates=["The Zombie Apocalypse HIT But His Room Holds a Gate!"],
    )
    lines = meta["formatted_kit"].splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("[1. NATIVE A/B TEST"))
    end = lines.index("--- Top Ranked Title Candidates ---")
    options = [lines[i + 1].strip() for i in range(start, end) if lines[i].startswith("★ Option ")]
    assert options and len(options) == len(set(options))
    if len(options) == 1:
        assert "upload without A/B test" in lines[start]
    else:
        assert f"Paste these {len(options)} options" in lines[start]

    concepts = sum(1 for l in lines if l.startswith("▶ CONCEPT "))
    assert f"[5. TOP {concepts} VIRAL THUMBNAILS" in meta["formatted_kit"]


CHAPTERS = [{"timestamp": t} for t in ("00:00", "06:56", "13:41")]


def test_cards_never_share_a_slot_and_skip_missing_series_links():
    anchors = recommend_card_and_endscreen_anchors(CHAPTERS)
    card_1, card_2 = anchors["card_1_playlist"], anchors["card_2_next_arc"]
    assert card_1["recommended_timestamp"] == "06:56" and card_2["recommended_timestamp"] == "13:41"
    assert "Playlist" not in card_1["card_type"] and card_1["link"] is None
    assert "Next Part" not in card_2["card_type"]
    assert not any("Playlist" in e for e in anchors["end_screen"]["recommended_elements"])

    nav = {"playlist_url": "https://www.youtube.com/playlist?list=PLabc123", "next_part_url": "https://youtu.be/xyz"}
    anchors = recommend_card_and_endscreen_anchors(CHAPTERS, nav)
    assert anchors["card_1_playlist"]["link"] == nav["playlist_url"]
    assert anchors["card_2_next_arc"]["link"] == nav["next_part_url"]


def test_end_screen_sits_on_the_outro():
    plain = recommend_card_and_endscreen_anchors(CHAPTERS)
    assert "outro_start" not in plain["end_screen"]

    outro = {"appended": True, "start_seconds": 7740.4, "type": "continues"}
    anchors = recommend_card_and_endscreen_anchors(CHAPTERS, {"next_part_url": "https://youtu.be/xyz"}, outro)
    assert anchors["end_screen"]["outro_start"] == "02:09:00"
    assert "02:09:00" in anchors["end_screen"]["timing"]
    assert anchors["end_screen"]["recommended_elements"][0] == "1x Video (Next Part)"

    # An outro that failed to render does not move the end screen.
    failed = recommend_card_and_endscreen_anchors(CHAPTERS, None, {"appended": False, "type": "continues"})
    assert "outro_start" not in failed["end_screen"]


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


TYRANT_SETTING = ("In an apocalyptic world overrun by demon-spawning Hellgates since 2047, sole survivor Goong Nam "
                  "achieves timeline regression through a legendary demon-slaying quest to return to the past.")
TYRANT_TERMS = "Hellgates Timeline Regression Legendary Quest High-Ranking Demons Ghouls"


def test_most_evidence_wins_not_first_keyword():
    """Tyrant 1-3 was tagged zombie_apocalypse from a single "Ghouls" term (first-match cascade)."""
    memory = {"episodes": {"1": {"summary": "Goong Nam slays a horned demon and a ghoul in the abyss."}}}
    assert detect_archetype("The Tyrant of the Apocalypse Returns", memory,
                            extra_context=TYRANT_SETTING, extra_terms=TYRANT_TERMS) == "regression_prep"


def test_keywords_match_whole_words():
    # "Hellgates" is not a hunter "gate"; shadows in the narration are not a "shadow army".
    assert detect_archetype("X", {"s": "Hellgates open. Shadows fall."}) == "general_apocalypse"
    assert detect_archetype("X", {"s": "The hunters enter the gate."}) == "hunter_gate"


def test_terms_count_less_than_the_genre_statement():
    # Veteran: an ability named "Personal Dimensional Gate" must not outweigh "zombie" in the setting.
    setting = "An asteroid turns the apocalyptic zombie scenario of the game Survival Life into reality."
    assert detect_archetype("Veteran of the Apocalypse", EARLY_MEMORY, extra_context=setting,
                            extra_terms="Survival Life Personal Dimensional Gate") == "zombie_apocalypse"
