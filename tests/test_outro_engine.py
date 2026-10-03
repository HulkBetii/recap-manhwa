import asyncio
import json

import pytest

from outro_engine import (
    OutroFacts,
    OutroType,
    build_outro_facts,
    build_outro_prompt,
    classify_outro,
    generate_outro,
    template_outro,
    validate_outro,
)
from series_status import ReleaseStatus

LAST_LINES = [
    "Seongho stares at the gate as the ground starts shaking beneath the base.",
    "Something enormous is pushing through from the other side of the portal tonight.",
    "And for the first time since the outbreak began, even he feels a chill of fear.",
]
FACTS = OutroFacts(
    protagonist="Seongho",
    known_names=["seongho"],
    episodes_covered=33,
    last_summary="Seongho defends his hidden realm base while a huge monster breaks through the gate.",
    last_lines=LAST_LINES,
    corpus_text=" ".join(LAST_LINES) + " Seongho built the base in 3 days and saved 12 survivors from Seoul.",
)
GOOD_CONTINUES = (
    "Seongho has survived the worst night since the outbreak, but the gate is still open and the base is "
    "shaking. The comic is still being released, so his story continues, and every new chapter tests what "
    "he built. Thanks for staying with this recap through every episode. If you enjoyed it, subscribe so you "
    "do not miss the next survival recap."
)


def _reasons(text, outro_type=OutroType.CONTINUES, facts=FACTS):
    return validate_outro(text, outro_type, facts).reasons


# --- classification ---------------------------------------------------------------------------

@pytest.mark.parametrize("status, to_ep, expected", [
    (ReleaseStatus(state="ongoing", latest_episode=64), 33, OutroType.CONTINUES),
    (ReleaseStatus(state="ongoing", latest_episode=33), 33, OutroType.CONTINUES),
    (ReleaseStatus(state="completed", latest_episode=120), 120, OutroType.FINALE),
    (ReleaseStatus(state="completed", latest_episode=120), 60, OutroType.NEUTRAL),
    (ReleaseStatus(state="completed"), 60, OutroType.NEUTRAL),        # unknown last episode: no ending claim
    (ReleaseStatus(state="hiatus", latest_episode=50), 50, OutroType.HIATUS),
    (ReleaseStatus(state="hiatus"), 50, OutroType.HIATUS),
    (ReleaseStatus(state="hiatus", latest_episode=80), 50, OutroType.NEUTRAL),
    (ReleaseStatus(state="unknown"), 10, OutroType.NEUTRAL),
    (None, 10, OutroType.NEUTRAL),
])
def test_classify_outro(status, to_ep, expected):
    assert classify_outro(status, to_ep) == expected


# --- validator --------------------------------------------------------------------------------

def test_good_draft_passes():
    assert _reasons(GOOD_CONTINUES) == []


def test_length_bounds():
    assert any("word_count" in r for r in _reasons("The story continues. Subscribe."))


def test_cta_verb_opening_a_sentence_is_not_a_name():
    text = GOOD_CONTINUES.replace("If you enjoyed it, subscribe so", "Subscribe so")
    assert not any("names not in the story" in r for r in _reasons(text))


def test_invented_name_rejected():
    text = GOOD_CONTINUES.replace("every new chapter tests what he built", "Haneul will test what he built")
    assert any("names not in the story: Haneul" in r for r in _reasons(text))


def test_invented_number_rejected():
    text = GOOD_CONTINUES.replace("the worst night", "the worst of 40 nights")
    assert any("numbers not in the story: 40" in r for r in _reasons(text))


@pytest.mark.parametrize("prediction", ["he will face", "he'll face", "Seongho is about to face", "he is going to face"])
def test_prediction_rejected(prediction):
    text = GOOD_CONTINUES.replace("every new chapter tests what he built", f"{prediction} his toughest enemy yet")
    assert any("predicts" in r for r in _reasons(text))


def test_cliffhanger_copy_rejected():
    text = GOOD_CONTINUES.replace(
        "Seongho has survived the worst night since the outbreak, but the gate is still open and the base is shaking.",
        "Something enormous is pushing through from the other side of the portal tonight.",
    )
    assert any("repeats the last narrated lines" in r for r in _reasons(text))


def test_two_ctas_rejected():
    text = GOOD_CONTINUES + " Leave a comment below too."
    reasons = _reasons(text.replace("Thanks for staying with this recap through every episode. ", ""))
    assert any("calls to action" in r for r in reasons)


def test_playlist_without_url_rejected():
    text = GOOD_CONTINUES.replace("subscribe so you do not miss the next survival recap", "watch the full playlist below")
    assert any("mentions a playlist" in r for r in _reasons(text))
    with_playlist = FACTS.model_copy(update={"has_playlist": True})
    assert not any("mentions a playlist" in r for r in _reasons(text, facts=with_playlist))


def test_continues_must_not_claim_ending():
    text = GOOD_CONTINUES.replace("so his story continues", "so this is the end of the story and his story continues")
    assert any("claims the story ended" in r for r in _reasons(text))


def test_status_signal_required():
    text = GOOD_CONTINUES.replace("The comic is still being released, so his story continues, and", "Through it all,")
    text = text.replace("every new chapter tests", "every hour tests")
    assert any("does not say the story status" in r for r in _reasons(text))


def test_finale_allows_ending_but_neutral_does_not():
    finale = template_outro(OutroType.FINALE, FACTS)
    assert validate_outro(finale, OutroType.FINALE, FACTS).passed
    assert any("claims the story ended" in r for r in _reasons(finale, OutroType.NEUTRAL))


# --- templates --------------------------------------------------------------------------------

@pytest.mark.parametrize("language", ["en", "vi"])
@pytest.mark.parametrize("outro_type", list(OutroType))
@pytest.mark.parametrize("nav", [{}, {"has_playlist": True}, {"has_next_part": True}])
def test_templates_pass_their_own_validator(language, outro_type, nav):
    facts = OutroFacts(**nav)  # no story facts at all
    text = template_outro(outro_type, facts, language)
    check = validate_outro(text, outro_type, facts, language)
    assert check.passed, (check.reasons, check.word_count)


def test_template_cta_follows_navigation():
    assert "playlist" not in template_outro(OutroType.CONTINUES, FACTS)
    assert "playlist" in template_outro(OutroType.CONTINUES, FACTS.model_copy(update={"has_playlist": True}))
    assert "next part" in template_outro(OutroType.CONTINUES, FACTS.model_copy(update={"has_next_part": True}))


def test_no_template_for_other_languages():
    assert template_outro(OutroType.CONTINUES, FACTS, "ko") is None


# --- generation -------------------------------------------------------------------------------

def _llm(*responses):
    prompts = []

    async def call(prompt):
        prompts.append(prompt)
        response = responses[min(len(prompts), len(responses)) - 1]
        if isinstance(response, Exception):
            raise response
        return response
    return call, prompts


def test_generate_accepts_valid_draft():
    call, prompts = _llm(GOOD_CONTINUES)
    result = asyncio.run(generate_outro(OutroType.CONTINUES, FACTS, call))
    assert result.source == "llm" and result.text == GOOD_CONTINUES and len(prompts) == 1


def test_generate_retries_with_feedback_then_accepts():
    call, prompts = _llm("Too short.", GOOD_CONTINUES)
    result = asyncio.run(generate_outro(OutroType.CONTINUES, FACTS, call))
    assert result.source == "llm" and len(result.attempts) == 2
    assert "REJECTED FOR" in prompts[1] and "word_count" in prompts[1]


def test_generate_falls_back_to_template():
    call, _ = _llm("Too short.", "Still too short.")
    result = asyncio.run(generate_outro(OutroType.CONTINUES, FACTS, call))
    assert result.source == "template" and result.text == template_outro(OutroType.CONTINUES, FACTS)


def test_generate_llm_error_uses_template():
    call, _ = _llm(RuntimeError("gateway down"))
    result = asyncio.run(generate_outro(OutroType.FINALE, FACTS, call))
    assert result.source == "template" and "llm_error" in result.attempts[0].reasons[0]


def test_generate_without_llm_or_template_returns_nothing():
    result = asyncio.run(generate_outro(OutroType.NEUTRAL, FACTS, None, language="ko"))
    assert not result.ok


# --- prompt / facts ---------------------------------------------------------------------------

def test_prompt_states_type_and_cta():
    prompt = build_outro_prompt(OutroType.CONTINUES, FACTS)
    assert "STILL BEING RELEASED" in prompt and "subscribe" in prompt and "Never mention a playlist" in prompt
    finale = build_outro_prompt(OutroType.FINALE, FACTS.model_copy(update={"has_playlist": True}))
    assert "COMPLETED" in finale and "playlist linked below" in finale


def test_build_outro_facts(tmp_path):
    for ep, lines in ((1, ["Ep one line."]), (2, ["First.", "Second.", "Third.", "Fourth."])):
        ep_dir = tmp_path / f"episode_{ep}"
        ep_dir.mkdir()
        (ep_dir / "recap.json").write_text(json.dumps([{"speech": s} for s in lines]), encoding="utf-8")
    memory = {"episodes": {"2": {"summary": "He fortifies the base."}}}
    facts = build_outro_facts(str(tmp_path), 1, 2, memory, None, {"playlist_url": "https://youtube.com/playlist?list=x"})
    assert facts.episodes_covered == 2
    assert facts.last_lines == ["Second.", "Third.", "Fourth."]
    assert facts.last_summary == "He fortifies the base."
    assert facts.has_playlist and not facts.has_next_part
    assert "Ep one line." in facts.corpus_text
