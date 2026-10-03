import asyncio
import json
import os

import pytest

from app import generate_gemini_prompt
from premise_pitch import build_pitch_prompt, generate_premise_pitch, validate_pitch
from series_bible import CharacterEntry, new_bible, save_bible
from title_engine import HookSheet, NumericFact
from workflow_stages_2 import Stage11_FinalVideoAssembly
from youtube_metadata import generate_youtube_metadata, preview_primary_title

TITLE = "Zombie Outbreak Hits, He Hoards 300 Cans Of Food! | Manhwa Recap"
CORPUS = [
    "Martial law hits Seoul as the zombie outbreak spreads from a drifting trawler.",
    "Tae, a former taekwondo athlete, refuses to panic while the city collapses.",
    "He drags 300 cans of food into the abandoned church basement before the horde arrives.",
    "By winter only 40 survivors remain inside the church in Jamsil, rationing every can of food.",
]
GOOD_PITCH = (
    "When the zombie outbreak hits Seoul, Tae does not run for the bridges like everyone else. "
    "He hoards 300 cans of food and drags them into an abandoned church basement while martial law collapses outside. "
    "Within weeks the city is a graveyard, and only 40 survivors are left in Jamsil to fight over every last can. "
    "Tae is no soldier, just a former taekwondo athlete who refuses to panic, and that cold head is exactly what keeps "
    "his people breathing when the horde finally comes knocking. It all begins on the night the first infected "
    "reaches the checkpoint."
)


def _sheet():
    return HookSheet(
        comic_title="Zombie Revelation 82-08", protagonist="Tae", corpus=CORPUS,
        numeric_facts=[NumericFact(phrase="300 cans", mentions=1), NumericFact(phrase="40 survivors", mentions=1)],
        story_beats=["Ep 1: Martial law hits Seoul."],
    )


def _bible():
    bible = new_bible("Zombie Revelation 82-08")
    bible.protagonist = CharacterEntry(name="Tae", gender="male")
    return bible


# --- Validation --------------------------------------------------------------

def test_grounded_title_aligned_pitch_passes():
    check = validate_pitch(GOOD_PITCH, TITLE, _sheet(), _bible())
    assert check.passed, check.reasons
    assert 60 <= check.word_count <= 115


@pytest.mark.parametrize("edit, reason", [
    (lambda t: t.replace("300 cans", "60,000 tons"), "numbers not in the story"),
    (lambda t: t.replace("Tae is no soldier", "Haneul is no soldier"), "names not in the story"),
    (lambda t: "Welcome back to the channel! " + t, "greeting"),
    (lambda t: t.replace("former taekwondo athlete", "SSS-rank trainee"), "genre claims not in the story"),
    (lambda t: t.split(". ")[0] + ".", "word_count"),
])
def test_pitch_defects_are_rejected(edit, reason):
    check = validate_pitch(edit(GOOD_PITCH), TITLE, _sheet(), _bible())
    assert not check.passed
    assert any(reason in r for r in check.reasons), check.reasons


def test_pitch_must_echo_the_title():
    unrelated = GOOD_PITCH.replace("zombie outbreak", "storm").replace("hoards 300 cans of food", "keeps quiet")
    unrelated = unrelated.replace("can.", "night.").replace("food", "rest")
    check = validate_pitch(unrelated, TITLE, _sheet(), _bible())
    assert any("does not echo the title" in r for r in check.reasons)


@pytest.mark.parametrize("opener", ["Fortunately", "Suddenly", "Facing the horde"])
def test_sentence_openers_are_not_invented_names(opener):
    # Real rejection: the Veteran 1-33 pitch failed twice on "Fortunately".
    text = GOOD_PITCH.replace("Tae is no soldier", f"{opener}, Tae is no soldier")
    check = validate_pitch(text, TITLE, _sheet(), _bible())
    assert not any("names not in the story" in r for r in check.reasons), check.reasons


def test_pitch_must_state_the_official_premise_when_known():
    sheet = _sheet()
    sheet.synopsis = "When the outbreak hits Seoul, Tae turns an abandoned church basement into a stockpiled fortress."
    assert validate_pitch(GOOD_PITCH, TITLE, sheet, _bible()).passed  # church basement = the premise
    off_premise = GOOD_PITCH.replace("abandoned church basement", "quiet back room").replace("church", "district")
    check = validate_pitch(off_premise, TITLE, sheet, _bible())
    assert any("official premise" in r for r in check.reasons), check.reasons
    assert "OFFICIAL PREMISE" in build_pitch_prompt(sheet, TITLE)


def test_places_from_the_narration_are_allowed():
    assert "Jamsil" in GOOD_PITCH
    assert validate_pitch(GOOD_PITCH, TITLE, _sheet(), _bible()).passed


# --- Generation loop ---------------------------------------------------------

def test_retry_feeds_rejection_reasons_and_normalizes_names():
    prompts = []

    async def fake_llm(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return "Welcome back! " + GOOD_PITCH
        return GOOD_PITCH.replace("Tae", "Paran")  # placeholder leak is normalized, not rejected

    result = asyncio.run(generate_premise_pitch(_sheet(), TITLE, fake_llm, _bible()))
    assert result.ok and "Paran" not in result.text
    assert len(result.attempts) == 2
    assert "PREVIOUS DRAFT WAS REJECTED" in prompts[1] and "greeting" in prompts[1]


def test_llm_failure_yields_no_pitch():
    async def failing(_prompt):
        raise RuntimeError("quota")

    result = asyncio.run(generate_premise_pitch(_sheet(), TITLE, failing, _bible()))
    assert not result.ok


def test_prompt_carries_title_numbers_and_protagonist():
    prompt = build_pitch_prompt(_sheet(), TITLE)
    assert '"Zombie Outbreak Hits, He Hoards 300 Cans Of Food!"' in prompt
    assert "- 300 cans" in prompt and 'The protagonist is "Tae"' in prompt


# --- Stage 5 prompt ----------------------------------------------------------

def test_setup_compression_only_for_first_two_episodes():
    assert "SETUP COMPRESSION" in generate_gemini_prompt("X", 1, 30, "en")
    assert "SETUP COMPRESSION" in generate_gemini_prompt("X", 2, 30, "en")
    assert "SETUP COMPRESSION" not in generate_gemini_prompt("X", 3, 30, "en")


# --- Title preview / kit agreement & gate --------------------------------------

def _write_story(tmp_path):
    d = tmp_path / "episode_1"
    d.mkdir()
    (d / "recap.json").write_text(
        json.dumps([{"speech": s, "images": [{"page": 1, "priority": 1.0}]} for s in CORPUS]), encoding="utf-8"
    )
    save_bible(_bible(), str(tmp_path))
    return str(tmp_path)


def test_preview_title_matches_kit_title(tmp_path):
    download_dir = _write_story(tmp_path)
    hooks = ["Zombie Outbreak Hits, He Hoards 300 Cans Of Food!", "Only 40 Survivors Remain As Zombie Horde Hits Seoul"]
    preview = preview_primary_title("Zombie Revelation 82-08", 1, 1, download_dir=download_dir, llm_title_candidates=hooks)
    meta = generate_youtube_metadata("Zombie Revelation 82-08", 1, 1, download_dir=download_dir, llm_title_candidates=hooks)
    assert preview["status"] == "validated"
    assert preview["primary_title"] == meta["title"]


def _promise_check(meta):
    return next(c for c in meta["prepublish_audit"]["gate"]["checks"] if c["id"] == "title_promise_in_opening")


def test_gate_counts_pitch_only_when_it_matches_the_shipped_title(tmp_path):
    download_dir = _write_story(tmp_path)
    hooks = ["Zombie Outbreak Hits, He Hoards 300 Cans Of Food!"]
    matching = {"title": TITLE, "text": GOOD_PITCH, "prepended": True}
    meta = generate_youtube_metadata("Zombie Revelation 82-08", 1, 1, download_dir=download_dir,
                                     llm_title_candidates=hooks, premise_pitch=matching)
    assert meta["prepublish_audit"]["premise_pitch_in_video"] is True
    assert _promise_check(meta)["passed"]

    stale = {**matching, "title": "Some Older Title | Manhwa Recap"}
    meta = generate_youtube_metadata("Zombie Revelation 82-08", 1, 1, download_dir=download_dir,
                                     llm_title_candidates=hooks, premise_pitch=stale)
    assert meta["prepublish_audit"]["premise_pitch_in_video"] is False


# --- Pitch images ------------------------------------------------------------

def _fake_select(calls):
    def select(download_dir, ep, num_images=3):
        calls.append((ep, num_images))
        return [{"path": f"ep{ep}_img{i}.jpg"} for i in range(num_images)]
    return select


def test_pitch_images_come_from_first_two_thirds_in_episode_order():
    calls = []
    paths = Stage11_FinalVideoAssembly._pitch_images("d", 1, 143, 8, select_fn=_fake_select(calls))
    episodes = [ep for ep, _ in calls]
    assert episodes == sorted(episodes) and episodes[0] == 1
    assert max(episodes) <= 96  # ceil(143 * 2/3) = 96: never climax-end panels
    assert len(episodes) == 4 and len(paths) == 8
    assert paths[0].startswith("ep1_")


def test_pitch_images_short_range_and_missing_episode():
    calls = []
    paths = Stage11_FinalVideoAssembly._pitch_images("d", 1, 3, 8, select_fn=_fake_select(calls))
    assert [ep for ep, _ in calls] == [1, 2]

    def flaky(download_dir, ep, num_images=3):
        if ep == 1:
            raise FileNotFoundError("no images")
        return [{"path": f"ep{ep}.jpg"}]

    assert Stage11_FinalVideoAssembly._pitch_images("d", 1, 3, 2, select_fn=flaky) == ["ep2.jpg"]


def test_pitch_images_keep_page_order_within_an_episode():
    def by_score(download_dir, ep, num_images=3):
        return [{"path": "p/109.jpg"}, {"path": "p/040.jpg"}, {"path": "p/098.jpg"}]

    assert Stage11_FinalVideoAssembly._pitch_images("d", 1, 1, 3, select_fn=by_score) == ["p/040.jpg", "p/098.jpg", "p/109.jpg"]


# --- Stage 11 intro bookkeeping ----------------------------------------------

@pytest.fixture
def fake_prepender(monkeypatch):
    import arc_intro_engine

    def fake(intro_video_path, intro_srt_path, intro_duration, target_video_path, target_srt_path,
             output_video_path, output_srt_path):
        body = open(target_video_path, "rb").read()
        with open(output_video_path, "wb") as f:
            f.write(b"INTRO|" + body)
        return True

    monkeypatch.setattr(arc_intro_engine.FastIntroPrepender, "prepend_intro", staticmethod(fake))


def _ep1(tmp_path, content):
    d = tmp_path / "episode_1"
    d.mkdir(exist_ok=True)
    (d / "video.mp4").write_bytes(content)
    return d / "video.mp4"


def test_rerendered_episode_refreshes_the_no_intro_backup(tmp_path, fake_prepender):
    video = _ep1(tmp_path, b"OLD-EPISODE")
    intro = {"video_path": "i.mp4", "srt_path": "i.srt", "duration": 40.0}
    assert Stage11_FinalVideoAssembly._prepend_intro_to_first_episode(intro, str(tmp_path), 1)
    assert video.read_bytes() == b"INTRO|OLD-EPISODE"

    video.write_bytes(b"NEW-EPISODE-RENDER")  # Stage 10 re-rendered episode 1
    os.utime(video, (1, 1))                   # make the signature differ even on coarse clocks
    assert Stage11_FinalVideoAssembly._prepend_intro_to_first_episode(intro, str(tmp_path), 1)
    assert video.read_bytes() == b"INTRO|NEW-EPISODE-RENDER"  # never the stale backup


def test_run_without_intro_removes_previous_intro(tmp_path, fake_prepender):
    video = _ep1(tmp_path, b"EPISODE")
    intro = {"video_path": "i.mp4", "srt_path": "i.srt", "duration": 40.0}
    Stage11_FinalVideoAssembly._prepend_intro_to_first_episode(intro, str(tmp_path), 1)
    assert Stage11_FinalVideoAssembly._restore_first_episode_without_intro(str(tmp_path), 1)
    assert video.read_bytes() == b"EPISODE"
    assert not (tmp_path / "episode_1" / "intro_state.json").exists()


# --- Outro assembly helpers (Stage 11) ---------------------------------------

def test_outro_images_keep_latest_pages_in_order():
    def by_score(_d, ep, num_images):
        assert ep == 33 and num_images == 6
        return [{"path": f"p/{n:03d}.jpg"} for n in (98, 12, 109, 40, 77, 5)]
    assert Stage11_FinalVideoAssembly._outro_images("d", 33, 2, select_fn=by_score) == ["p/098.jpg", "p/109.jpg"]


def test_outro_images_missing_episode_returns_empty():
    def missing(_d, _ep, num_images):
        raise FileNotFoundError("no images")
    assert Stage11_FinalVideoAssembly._outro_images("d", 33, 5, select_fn=missing) == []


def test_assembly_segments_append_outro_after_last_episode():
    import os
    plain = Stage11_FinalVideoAssembly._assembly_segments("d", [1, 2])
    assert [os.path.normpath(v) for v, _ in plain] == [os.path.normpath("d/episode_1/video.mp4"), os.path.normpath("d/episode_2/video.mp4")]
    outro = {"video_path": "d/outro/video.mp4", "srt_path": "d/outro/transcript.srt"}
    with_outro = Stage11_FinalVideoAssembly._assembly_segments("d", [1, 2], outro)
    assert with_outro[-1] == ("d/outro/video.mp4", "d/outro/transcript.srt") and len(with_outro) == 3
    # A single-episode video with an outro has two segments, so it goes through concat, not a plain copy.
    assert len(Stage11_FinalVideoAssembly._assembly_segments("d", [5], outro)) == 2


def test_clip_subtitles_use_script_wording(tmp_path):
    """Pitch/outro clips keep Whisper timings but the script's words (a Veteran outro read "Ciongho")."""
    from arc_intro_engine import align_clip_srt_to_script
    srt = tmp_path / "transcript.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,700\nHunting season begins elsewhere.\n\n"
        "2\n00:00:02,360 --> 00:00:06,900\nCiongho stands resolute before the injured woman.\n\n"
        "3\n00:00:07,460 --> 00:00:09,840\nongoing chapters, the story continues.\n",
        encoding="utf-8",
    )
    script = ("While hunting season begins elsewhere, Seongho stands resolute before the injured woman. "
              "With ongoing chapters, the story continues.")
    assert align_clip_srt_to_script(str(srt), script, 10.0)
    text = srt.read_text(encoding="utf-8")
    assert "Seongho" in text and "Ciongho" not in text and "With ongoing chapters" in text
    assert text.startswith("1\n00:00:00,000 --> ")


def test_clip_subtitles_missing_file_is_a_no_op(tmp_path):
    from arc_intro_engine import align_clip_srt_to_script
    assert not align_clip_srt_to_script(str(tmp_path / "none.srt"), "Text.", 5.0)


def test_clip_cues_are_at_most_two_lines():
    from arc_intro_engine import MAX_CLIP_CUE_CHARS, _clip_cue_texts
    script = ("Fortunately, Seongho awakened with the rare ability to open dimensional gates, allowing him to "
              "safely level up his skills and prepare to save mankind from impending doom. It all begins today.")
    cues = _clip_cue_texts(script)
    assert all(len(c) <= MAX_CLIP_CUE_CHARS for c in cues[:-1]) and cues[-1] == "It all begins today."
    assert " ".join(cues) == script
