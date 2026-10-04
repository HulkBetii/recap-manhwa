import asyncio
import json

from app import generate_gemini_prompt
from series_bible import (
    OBSERVED_MIN_MENTIONS,
    CharacterEntry,
    apply_user_identity,
    bootstrap_bible,
    clean_synopsis,
    extract_name_candidates,
    memory_name_is_trusted,
    protagonist_from_synopsis,
    load_bible,
    merge_bootstrap,
    new_bible,
    normalize_segments,
    normalize_text,
    observe_episode,
    parse_bootstrap_response,
    render_prompt_block,
    save_bible,
)
from youtube_metadata import _merge_series_bible, get_character_names


def _zombie_bible():
    bible = new_bible("Zombie Revelation 82-08")
    bible.protagonist = CharacterEntry(name="Tae", role="protagonist", gender="male", source="llm_bootstrap")
    bible.characters.append(CharacterEntry(name="Jinwoo", role="best friend", gender="male"))
    return bible


def _seg(text):
    return {"speech": text, "images": [{"page": 1, "priority": 1.0}]}


# --- Normalization -----------------------------------------------------------

def test_placeholder_name_is_replaced_with_canonical_protagonist():
    segments = [_seg("Paran scans the ruined street."), _seg("Blood splatters as Paran's blade swings.")]
    normalized, replaced = normalize_segments(segments, _zombie_bible())
    assert replaced == 2
    assert all("Paran" not in s["speech"] for s in normalized)
    assert normalized[1]["speech"] == "Blood splatters as Tae's blade swings."


def test_bracket_placeholder_is_replaced():
    text, n = normalize_text("Meanwhile, [MC name] switches off the TV.", _zombie_bible())
    assert n == 1
    assert text == "Meanwhile, Tae switches off the TV."


def test_words_containing_placeholder_are_untouched():
    text, n = normalize_text("Paranoid raiders approach the gate.", _zombie_bible())
    assert n == 0
    assert text == "Paranoid raiders approach the gate."


def test_aliases_are_kept_and_common_words_never_rewritten():
    """Nicknames are real in-story names; rewriting them also corrupted words like 'Duck!'."""
    bible = _zombie_bible()
    bible.characters.append(CharacterEntry(name="Duckbuttquackquack", aliases=["Duck"]))
    text = "Duck rushes forward with twin daggers. Duck! The beast swings again."
    assert normalize_text(text, bible) == (text, 0)


def test_alias_still_counts_as_known_name():
    bible = _zombie_bible()
    bible.characters.append(CharacterEntry(name="Duckbuttquackquack", aliases=["Duck"]))
    report = observe_episode(bible, 1, [_seg(" ".join(["Tae watches as Duck charges."] * 6))])
    assert report.top_unknown_name is None


def test_compound_terms_are_one_candidate_and_bible_terms_are_known():
    texts = ["The game called Survival Life becomes real as an Owl Bear attacks and President Park hides."]
    counts = extract_name_candidates(texts)
    assert counts["Survival Life"] == 1 and counts["Owl Bear"] == 1 and counts["Park"] == 1
    assert "Survival" not in counts and "Life" not in counts and "President Park" not in counts

    bible = _zombie_bible()
    bible.terms = ["Survival Life", "Personal Dimensional Gate"]
    texts = ["Everyone in Survival Life hides while he opens the Personal Dimensional Gate."] * 6
    report = observe_episode(bible, 1, [_seg(" ".join(texts))])
    assert report.top_unknown_name is None  # "Gate" is stripped from candidates, terms still match


def test_romanization_variants_map_to_canonical_spelling():
    bible = _zombie_bible()
    bible.characters.append(CharacterEntry(name="Mingu", role="mob boss"))
    text, n = normalize_text("Min-gu sets his glass down while Min Gu's thugs stand.", bible)
    assert n == 2
    assert text == "Mingu sets his glass down while Mingu's thugs stand."


def test_variant_matching_does_not_touch_longer_names_or_common_words():
    bible = new_bible("X")
    bible.protagonist = CharacterEntry(name="Will")
    bible.characters.append(CharacterEntry(name="Tae"))
    text, n = normalize_text("Taeyang will not wait; Tae-yang never does.", bible)
    assert n == 0
    assert text == "Taeyang will not wait; Tae-yang never does."


def test_spelling_variant_is_not_treated_as_unknown_name():
    bible = _zombie_bible()
    bible.characters.append(CharacterEntry(name="Mingu"))
    report = observe_episode(bible, 2, [_seg(" ".join(["Everyone fears Min-gu."] * 6))])
    assert report.top_unknown_name is None


# --- Prompt injection (parallel episodes) ------------------------------------

def test_observed_names_are_rendered_separately_from_confirmed_cast():
    bible = _zombie_bible()
    bible.characters.append(CharacterEntry(name="Jamsil", source="observed"))
    block = render_prompt_block(bible)
    assert '- "Jinwoo" (best friend)' in block
    assert '- "Jamsil"' not in block
    assert "RECURRING PROPER NOUNS (keep this exact spelling): Jamsil" in block



def test_cast_block_reaches_every_episode_prompt_without_rolling_context():
    block = render_prompt_block(_zombie_bible())
    ep1 = generate_gemini_prompt("Zombie Revelation 82-08", 1, 30, "en", cast_bible=block)
    # Episode 7 dispatched in parallel before episode 6 finished: no previous_context at all.
    ep7 = generate_gemini_prompt("Zombie Revelation 82-08", 7, 30, "en", previous_context=None, cast_bible=block)
    for prompt in (ep1, ep7):
        assert "CAST BIBLE" in prompt
        assert '"Tae"' in prompt
        assert '"Paran"' in prompt  # listed as forbidden placeholder


def test_prompt_without_bible_is_unchanged():
    assert "CAST BIBLE" not in generate_gemini_prompt("Solo Leveling", 2, 30, "en")


# --- Bootstrap ---------------------------------------------------------------

def test_parse_bootstrap_response_accepts_fenced_json():
    text = '```json\n{"protagonist": {"name": "Tae", "gender": "male"}, "characters": []}\n```'
    assert parse_bootstrap_response(text)["protagonist"]["name"] == "Tae"
    assert parse_bootstrap_response("Sorry, I can't help with that.") is None


def test_merge_never_overrides_locked_user_protagonist():
    bible = new_bible("Zombie Revelation 82-08")
    apply_user_identity(bible, {"protagonist_name": "Tae", "protagonist_gender": "male"})
    merge_bootstrap(bible, {"protagonist": {"name": "Taesu"}, "characters": [{"name": "Mingu", "role": "mob boss"}]})
    assert bible.protagonist_name == "Tae"
    assert bible.protagonist.locked
    assert [c.name for c in bible.characters] == ["Mingu"]


def test_merge_rejects_placeholder_and_invented_protagonist_names():
    bible = new_bible("X")
    merge_bootstrap(bible, {"protagonist": {"name": "Paran"}})
    assert bible.protagonist is None
    merge_bootstrap(bible, {"protagonist": {"name": "[MC name]"}})
    assert bible.protagonist is None


def test_bootstrap_stops_at_first_episode_with_full_cast(tmp_path):
    calls = []

    async def fake_llm(pdf_path, prompt, ep):
        calls.append(ep)
        if ep == 1:
            return '{"protagonist": {"name": ""}, "characters": []}'  # name not shown yet
        return json.dumps({"protagonist": {"name": "Tae", "gender": "male"},
                           "characters": [{"name": "Jinwoo", "role": "best friend"}]})

    bible, reused = asyncio.run(bootstrap_bible(
        "Zombie Revelation 82-08", str(tmp_path), [1, 2, 3, 4],
        resolve_pdf=lambda ep: f"ep{ep}.pdf", llm_call=fake_llm,
    ))
    assert not reused
    assert calls == [1, 2]
    assert bible.protagonist_name == "Tae"


def test_bootstrap_survives_llm_failure(tmp_path):
    warnings = []

    async def failing_llm(pdf_path, prompt, ep):
        raise RuntimeError("quota exceeded")

    async def on_warning(msg, ep):
        warnings.append(msg)

    bible, _ = asyncio.run(bootstrap_bible(
        "X", str(tmp_path), [1, 2], resolve_pdf=lambda ep: "p.pdf",
        llm_call=failing_llm, on_warning=on_warning,
    ))
    assert bible.protagonist is None
    assert len(warnings) == 2


def test_bootstrap_reuses_existing_bible_without_llm_calls(tmp_path):
    save_bible(_zombie_bible(), str(tmp_path))

    async def must_not_be_called(*_):
        raise AssertionError("LLM must not be called when a bible already exists")

    bible, reused = asyncio.run(bootstrap_bible(
        "Zombie Revelation 82-08", str(tmp_path), [1], resolve_pdf=lambda ep: "p.pdf",
        llm_call=must_not_be_called,
    ))
    assert reused and bible.protagonist_name == "Tae"


# --- Official synopsis (Veteran 1-33 render named the hero after a game handle) -----

VETERAN_SYNOPSIS = (
    "When Seongho logs off Survival Life for the final time, the last thing he expects is for the video game "
    "to become reality. Having awakened as a hunter with the ability to open dimensional gates, Seongho rushes "
    "to build a hideout in another realm in order to survive."
)


def _bootstrap(tmp_path, llm_reply, synopsis=VETERAN_SYNOPSIS, **kw):
    prompts = []

    async def fake_llm(pdf_path, prompt, ep):
        prompts.append(prompt)
        return json.dumps(llm_reply)

    bible, reused = asyncio.run(bootstrap_bible(
        "Veteran of the Apocalypse", str(tmp_path), [1, 2, 3],
        resolve_pdf=lambda ep: f"ep{ep}.pdf", llm_call=fake_llm, synopsis=synopsis, **kw,
    ))
    return bible, reused, prompts


def test_synopsis_names_the_protagonist_when_pages_do_not(tmp_path):
    bible, _, prompts = _bootstrap(tmp_path, {"protagonist": {"name": ""}, "characters": [{"name": "Wontaek Jang"}]})
    assert bible.protagonist_name == "Seongho"
    assert bible.protagonist.source == "synopsis"
    assert "OFFICIAL SERIES SYNOPSIS" in prompts[0] and "Seongho" in prompts[0]
    assert load_bible(str(tmp_path)) is None  # bootstrap never saves; the caller does


def test_synopsis_overrides_a_game_handle_and_keeps_it_as_alias(tmp_path):
    reply = {"protagonist": {"name": "Survivor1", "gender": "male"},
             "characters": [{"name": "Survivor1"}, {"name": "Bunny", "role": "party member"}]}
    bible, _, _ = _bootstrap(tmp_path, reply)
    assert bible.protagonist_name == "Seongho"
    assert bible.protagonist.gender == "male"
    assert "Survivor1" in bible.protagonist.aliases
    assert [c.name for c in bible.characters] == ["Bunny"]


def test_user_supplied_protagonist_is_never_overridden_by_the_synopsis(tmp_path):
    bible, _, _ = _bootstrap(tmp_path, {"protagonist": {"name": ""}, "characters": []}, protagonist_name="Lee Seongho")
    assert bible.protagonist_name == "Lee Seongho" and bible.protagonist.locked


def test_saved_bible_with_unconfirmed_protagonist_is_rebuilt(tmp_path):
    stale = new_bible("Veteran of the Apocalypse")
    stale.protagonist = CharacterEntry(name="Survivor1", source="inferred")
    save_bible(stale, str(tmp_path))
    bible, reused, prompts = _bootstrap(tmp_path, {"protagonist": {"name": ""}, "characters": []})
    assert not reused and prompts
    assert bible.protagonist_name == "Seongho"


def test_memory_guess_is_trusted_only_if_the_synopsis_agrees():
    bible = new_bible("Veteran of the Apocalypse")
    assert memory_name_is_trusted("Survivor1", bible)  # no synopsis: nothing to check against
    bible.synopsis = VETERAN_SYNOPSIS
    assert not memory_name_is_trusted("Survivor1", bible)
    assert memory_name_is_trusted("Seongho", bible)
    assert not memory_name_is_trusted("", bible)


def test_synopsis_helpers():
    assert clean_synopsis("  Too short.  ") == ""
    assert clean_synopsis("x " * 900).startswith("x x") and len(clean_synopsis("x " * 900)) == 1200
    assert protagonist_from_synopsis(VETERAN_SYNOPSIS, "Veteran of the Apocalypse") == "Seongho"
    assert protagonist_from_synopsis("", "X") == ""
    # Real webtoons synopsis: a one-off capitalized term ("Hellgates") must not beat the possessive name.
    tyrant = ("As Hellgates open across the globe, humanity falls, bringing with it the death of Goong Nam’s "
              "family. On the edge of a cliff, he loses hold of his beloved daughter’s hand.")
    assert protagonist_from_synopsis(tyrant, "The Tyrant of the Apocalypse Returns") == "Goong Nam"
    # No clear person: leave it empty rather than guess.
    assert protagonist_from_synopsis("When the Hellgates open, humanity falls and the world burns.", "X") == ""


# --- Persistence -------------------------------------------------------------

def test_load_bible_rejects_other_comic(tmp_path):
    save_bible(_zombie_bible(), str(tmp_path))
    assert load_bible(str(tmp_path), "Zombie Revelation 82-08").protagonist_name == "Tae"
    assert load_bible(str(tmp_path), "Another Comic") is None


# --- Observation & drift -----------------------------------------------------

def test_name_candidates_ignore_sentence_starts_and_titles():
    counts = extract_name_candidates([
        "Meanwhile the squad follows Mingu inside. Professor Han watches as President Park speaks to Mingu.",
    ])
    assert counts["Mingu"] == 2
    assert "Meanwhile" not in counts
    assert "Professor" not in counts and "President" not in counts


def test_recurring_name_is_promoted_after_two_episodes():
    bible = _zombie_bible()
    per_ep = OBSERVED_MIN_MENTIONS // 2 + 1
    seg = [_seg(" ".join(["The crowd watches Mingu."] * per_ep))]
    first = observe_episode(bible, 3, seg)
    assert first.promoted_names == []
    second = observe_episode(bible, 4, seg)
    assert second.promoted_names == ["Mingu"]
    assert "Mingu" in [c.name for c in bible.characters]


def test_plural_mentions_count_toward_the_singular_name():
    bible = _zombie_bible()
    per_ep = OBSERVED_MIN_MENTIONS // 2 + 1
    first = observe_episode(bible, 3, [_seg("The horde follows Cobolt. " + " ".join(["Tae kills the Cobolts."] * per_ep))])
    assert "Cobolts" not in bible.observed_names and bible.observed_names["Cobolt"].mentions == per_ep + 1
    assert first.top_unknown_name == "Cobolt"
    # Later episodes that only use the plural still feed the same entry.
    second = observe_episode(bible, 4, [_seg(" ".join(["Tae burns the Cobolts."] * per_ep))])
    assert second.promoted_names == ["Cobolt"]


def test_plural_of_known_name_is_not_unknown_and_lone_plurals_stay():
    bible = _zombie_bible()
    report = observe_episode(bible, 1, [_seg(" ".join(["Tae calls the Jinwoos and James."] * 6))])
    assert report.top_unknown_name == "James"  # no "Jame" seen: real names ending in s are untouched


def test_protagonist_drift_is_flagged():
    bible = _zombie_bible()
    seg = [_seg(" ".join(["Everyone stares at Haneul."] * 6))]
    report = observe_episode(bible, 5, seg)
    assert report.protagonist_mentions == 0
    assert report.top_unknown_name == "Haneul"
    assert report.mc_drift


def test_no_drift_when_protagonist_is_named():
    report = observe_episode(_zombie_bible(), 5, [_seg("Tae ducks the punch while the crowd stares at Haneul.")])
    assert not report.mc_drift


# --- Metadata ----------------------------------------------------------------

def test_metadata_never_guesses_protagonist_from_title():
    names = get_character_names("Zombie Outbreak High School", story_memory=None)
    assert names["mc"] == "The Lone Survivor"


def test_metadata_uses_bible_over_story_memory(tmp_path):
    bible = _zombie_bible()
    bible.characters.append(CharacterEntry(name="Sora", gender="female"))
    save_bible(bible, str(tmp_path))
    merged = _merge_series_bible({"protagonist_name": "Paran"}, str(tmp_path))
    names = get_character_names("Zombie Revelation 82-08", merged)
    assert names["mc"] == "Tae"
    assert names["female_lead"] == "Sora"


def test_female_lead_is_never_an_antagonist():
    """Tyrant 1-3: the demon lord "The Master of the Seven Serpents" became a seduction-concept partner."""
    from series_bible import CharacterEntry, new_bible
    bible = new_bible("The Tyrant of the Apocalypse Returns")
    bible.characters = [
        CharacterEntry(name="The Master of the Seven Serpents", role="demon lord", gender="female"),
        CharacterEntry(name="Yuri", role="rival hunter", gender="female"),
        CharacterEntry(name="Haneul", role="ally healer", gender="female"),
    ]
    assert bible.first_female_character().name == "Haneul"
    bible.characters = bible.characters[:2]
    assert bible.first_female_character() is None
