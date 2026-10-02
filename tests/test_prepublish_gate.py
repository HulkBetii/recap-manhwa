import json

from prepublish_gate import (
    check_chapters,
    check_description_placeholders,
    check_names,
    check_title_promise_in_opening,
    render_gate_banner,
    run_prepublish_gate,
)
from series_bible import CharacterEntry, audit_names, new_bible, save_bible
from youtube_metadata import generate_youtube_metadata

GOOD_TITLE = "Zombie Outbreak Hits, He Hoards 300 Cans Of Food! | Manhwa Recap"
OPENING = [
    "The zombie outbreak hits Seoul overnight and martial law follows.",
    "He hoards 300 cans of food in the church basement before the horde arrives.",
]
GOOD_CHAPTERS = [
    {"timestamp": "00:00", "theme": "Martial Law Falls"},
    {"timestamp": "01:32:56", "theme": "The Church Basement Siege"},
    {"timestamp": "03:16:04", "theme": "Convoy Ambush"},
]
GOOD_DESCRIPTION = "Hook line.\n00:00 - Martial Law Falls\n01:32:56 - The Church Basement Siege\n03:16:04 - Convoy Ambush\n"
ALL_LIMITS_OK = {"title_max_100_chars": True, "originality_statement": True}


def _bible():
    bible = new_bible("Zombie Revelation 82-08")
    bible.protagonist = CharacterEntry(name="Tae", gender="male")
    return bible


def _gate(**overrides):
    args = dict(
        primary_title=GOOD_TITLE,
        title_engine_audit={"status": "validated"},
        primary_title_reasons=[],
        name_audit=audit_names(_bible(), {1: ["Tae locks the church door."]}),
        narrative_chapters=GOOD_CHAPTERS,
        description=GOOD_DESCRIPTION,
        chapters_explicitly_disabled=False,
        legacy_flags=ALL_LIMITS_OK,
        opening_segments=OPENING,
    )
    args.update(overrides)
    return run_prepublish_gate(**args)


def _check(report, check_id):
    return next(c for c in report.checks if c.id == check_id)


def test_clean_kit_passes():
    report = _gate()
    assert report.status == "PASS", [c for c in report.checks if not c.passed]
    assert "DO NOT UPLOAD" not in "\n".join(render_gate_banner(report))


def test_unvalidated_title_blocks_upload():
    report = _gate(
        title_engine_audit={"status": "no_valid_candidates"},
        primary_title_reasons=["hook_too_long:73>60"],
    )
    assert report.status == "FAIL"
    assert "hook_too_long:73>60" in _check(report, "title_validated").detail
    banner = "\n".join(render_gate_banner(report))
    assert "PRE-PUBLISH STATUS: FAIL" in banner and "DO NOT UPLOAD" in banner


def test_duplicate_of_published_title_blocks_upload():
    report = _gate(primary_title_reasons=["duplicate_of_published:He Refused To Regress"])
    assert not _check(report, "title_not_duplicate").passed
    assert report.status == "FAIL"


# --- Names -------------------------------------------------------------------

def test_placeholder_name_left_in_narration_fails():
    audit = audit_names(_bible(), {1: ["Paran scans the street.", "Tae runs."], 2: ["Tae waits."]})
    assert audit.placeholder_hits == {"Paran": 1}
    check = check_names(audit)
    assert not check.passed and check.severity == "fail"


def test_placeholder_fails_even_without_bible():
    audit = audit_names(None, {1: ["Paran scans the street."]})
    check = check_names(audit)
    assert not check.passed and check.severity == "fail"


def test_missing_bible_is_only_a_warning():
    check = check_names(audit_names(None, {1: ["He scans the street."]}))
    assert not check.passed and check.severity == "warn"


def test_protagonist_drift_episode_fails():
    drifting = ["Everyone stares at Haneul."] * 6
    audit = audit_names(_bible(), {1: ["Tae runs."], 2: drifting})
    assert audit.drift_episodes == [2]
    assert not check_names(audit).passed


# --- Chapters ----------------------------------------------------------------

def test_chapter_defects_found_on_the_channel_fail():
    chapters = [
        {"timestamp": "00:00", "theme": "Martial Law & First Encounters"},
        {"timestamp": "01:32:56", "theme": "Tae Plants His Feet Against The"},
        {"timestamp": "11:54:50", "theme": "Martial Law & First Encounters"},
    ]
    description = "00:00 — Martial Law & First Encounters\n01:32:56 — Tae Plants His Feet Against The\n"
    check = check_chapters(chapters, description, chapters_explicitly_disabled=False)
    assert not check.passed
    assert "truncated chapter" in check.detail
    assert "duplicate chapter" in check.detail
    assert "em dash" in check.detail


def test_too_few_chapters_fail_unless_disabled():
    assert not check_chapters(GOOD_CHAPTERS[:2], GOOD_DESCRIPTION, False).passed
    assert check_chapters([], "", chapters_explicitly_disabled=True).passed


# --- Title promise & description ---------------------------------------------

def test_title_promise_missing_from_opening_is_a_warning():
    weekend = ["Friends gather around the barbecue grill and argue about idols."] * 5
    check = check_title_promise_in_opening(GOOD_TITLE, weekend)
    assert not check.passed and check.severity == "warn"
    assert check_title_promise_in_opening(GOOD_TITLE, OPENING).passed


def test_description_placeholders_and_fake_playlist_are_flagged():
    desc = (
        "• Full Playlist: https://www.youtube.com/playlist?list=zombie-revelation-82-08-full-recap\n"
        "• Next Arc (Eps 144–286): [Coming Soon — Subscribe & Ring 🔔]\n"
    )
    check = check_description_placeholders(desc)
    assert not check.passed
    assert "Coming Soon" in check.detail and "full-recap" in check.detail


# --- End-to-end --------------------------------------------------------------

def test_kit_leads_with_gate_and_drops_prime_time(tmp_path):
    ep_dir = tmp_path / "episode_1"
    ep_dir.mkdir()
    segments = [
        "Paran scans the ruined street as the zombie outbreak spreads.",
        "Martial law hits Seoul and the infected overrun the barricade.",
        "He drags 300 cans of food into the church basement.",
    ]
    (ep_dir / "recap.json").write_text(
        json.dumps([{"speech": s, "images": [{"page": 1, "priority": 1.0}]} for s in segments]), encoding="utf-8"
    )
    save_bible(_bible(), str(tmp_path))

    meta = generate_youtube_metadata("Zombie Revelation 82-08", 1, 1, download_dir=str(tmp_path))
    audit = meta["prepublish_audit"]
    kit = meta["formatted_kit"]

    assert audit["gate_status"] == "FAIL"
    assert audit["passed"] is False  # never "passed" while the gate blocks
    failing = {c["id"] for c in audit["gate"]["checks"] if not c["passed"]}
    assert {"names_consistent", "chapters_valid"} <= failing
    assert kit.index("PRE-PUBLISH STATUS") < kit.index("[1. NATIVE A/B TEST")
    assert "Prime-Time" not in kit and "publishing_schedule" not in meta
