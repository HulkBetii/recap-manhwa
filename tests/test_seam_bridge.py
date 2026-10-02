import asyncio
import json

import pytest

from app import generate_gemini_prompt
from seam_bridge import bridge_episode, partition_contiguous, seam_report, validate_bridge
from series_bible import CharacterEntry, new_bible
from story_memory import StoryMemory

EP1 = [
    {"speech": "The digital watch hits eight fifty-nine."},
    {"speech": "Grabbing his smartphone, headlines confirm the asteroid impact."},
    {"speech": "The roaring rift tears open inside his bedroom."},
    {"speech": "Turning toward the roaring rift, Gimbaplover prepares for the fight of his life."},
]


# --- Chunking ----------------------------------------------------------------

@pytest.mark.parametrize("episodes, workers, expected", [
    ([1, 2, 3], 2, [[1, 2], [3]]),
    (list(range(1, 11)), 3, [[1, 2, 3, 4], [5, 6, 7], [8, 9, 10]]),
    ([1, 2], 5, [[1], [2]]),
    ([], 3, []),
])
def test_partition_is_contiguous_and_covers_every_episode(episodes, workers, expected):
    chunks = partition_contiguous(episodes, workers)
    assert chunks == expected
    assert [ep for c in chunks for ep in c] == episodes


def test_partition_rejects_zero_workers():
    with pytest.raises(ValueError):
        partition_contiguous([1, 2], 0)


# --- Previous-episode tail in the prompt ---------------------------------------

def _memory():
    memory = StoryMemory(comic_title="Veteran of the Apocalypse", language="en")
    memory.set_protagonist_name("Gimbaplover")
    memory.add_episode_recap(1, EP1, language="en")
    return memory


def test_previous_context_carries_the_last_three_lines():
    ctx = _memory().get_previous_context(2)
    assert ctx["previous_tail"] == [s["speech"] for s in EP1[-3:]]


def test_prompt_forbids_repeating_the_previous_tail():
    prompt = generate_gemini_prompt("Veteran of the Apocalypse", 2, 30, "en", previous_context=_memory().get_previous_context(2))
    assert "LAST LINES THE VIEWER JUST HEARD" in prompt
    assert '"The roaring rift tears open inside his bedroom."' in prompt
    assert "Do NOT repeat, paraphrase or re-describe these events" in prompt


def test_prompt_never_quotes_an_empty_cliffhanger():
    # Only the protagonist is known (Series Bible), as for the first episode of a chunk.
    prompt = generate_gemini_prompt("Veteran of the Apocalypse", 3, 30, "en", previous_context={"protagonist_name": "Gimbaplover"})
    assert 'cliffhanger ("")' not in prompt
    assert "LAST LINES THE VIEWER JUST HEARD" not in prompt


# --- Bridge validation ---------------------------------------------------------

EP2 = [
    {"speech": "Gimbaplover reaches out, staring at the pulsing dimensional gate inside his room.", "images": [{"page": 1}]},
    {"speech": "Blindly rushing into an alien portal is suicide, so he hesitates to form a plan.", "images": [{"page": 2}]},
    {"speech": "He grabs his old recurve bow from the closet.", "images": [{"page": 3}]},
]
TAIL = [s["speech"] for s in EP1[-3:]]
ORIGINAL = [s["speech"] for s in EP2[:2]]
CORPUS = " ".join(s["speech"] for s in EP1 + EP2)
GOOD = [
    "But at the edge of the pulsing dimensional gate, Gimbaplover stops and stares inside.",
    "Blindly rushing into an alien portal is suicide, so he hesitates to form a plan.",
]


def _bible():
    bible = new_bible("Veteran of the Apocalypse")
    bible.protagonist = CharacterEntry(name="Gimbaplover", gender="male")
    return bible


def test_grounded_bridge_passes():
    check = validate_bridge(GOOD, ORIGINAL, TAIL, CORPUS, _bible())
    assert check.passed, check.reasons


@pytest.mark.parametrize("opener", ["Facing", "Far from", "Away from"])
def test_sentence_openers_are_not_names(opener):
    # Real rejections: "Facing …" (Veteran 1-3 trial), "Far from …" / "Away from …" (Veteran 1-33 render).
    lines = [f"{opener} the pulsing dimensional gate, Gimbaplover stops and stares inside.", GOOD[1]]
    check = validate_bridge(lines, ORIGINAL, TAIL, CORPUS, _bible())
    assert check.passed, check.reasons


@pytest.mark.parametrize("lines, reason", [
    ([GOOD[0]], "expected 2 lines"),
    (["Previously, " + GOOD[0], GOOD[1]], "previously"),
    ([GOOD[0].replace("Gimbaplover", "Haneul"), GOOD[1]], "names not in the story: Haneul"),
    ([GOOD[0] + " He keeps staring at the gate for a very long and tense moment.", GOOD[1]], "line 1 has"),
    (["Meanwhile the stock market in Tokyo crashes after a banking scandal erupts.", GOOD[1]], "come from the two episodes"),
])
def test_bridge_defects_are_rejected(lines, reason):
    check = validate_bridge(lines, ORIGINAL, TAIL, CORPUS, _bible())
    assert not check.passed
    assert any(reason in r for r in check.reasons), check.reasons


# --- Bridging an episode on disk -------------------------------------------------

def _story(tmp_path):
    for ep, segs in ((1, EP1), (2, EP2)):
        d = tmp_path / f"episode_{ep}"
        d.mkdir()
        (d / "recap.json").write_text(json.dumps(segs), encoding="utf-8")
    return str(tmp_path)


def _recap(tmp_path, ep):
    return json.loads((tmp_path / f"episode_{ep}" / "recap.json").read_text(encoding="utf-8"))


def test_bridge_rewrites_only_the_opening_and_is_idempotent(tmp_path):
    download_dir = _story(tmp_path)
    prompts = []

    async def llm(prompt):
        prompts.append(prompt)
        return json.dumps(GOOD)

    result = asyncio.run(bridge_episode(download_dir, 2, llm, _bible()))
    assert result.status == "bridged"
    recap = _recap(tmp_path, 2)
    assert [s["speech"] for s in recap[:2]] == GOOD
    assert recap[2] == EP2[2] and [s["images"] for s in recap] == [s["images"] for s in EP2]
    assert TAIL[-1] in prompts[0]
    seam = json.loads((tmp_path / "episode_2" / "seam.json").read_text(encoding="utf-8"))
    assert seam["original"] == ORIGINAL and seam["status"] == "bridged"

    again = asyncio.run(bridge_episode(download_dir, 2, llm, _bible()))
    assert again.status == "skipped" and len(prompts) == 1


def test_rejected_bridge_keeps_the_original_after_one_retry(tmp_path):
    download_dir = _story(tmp_path)
    prompts = []

    async def llm(prompt):
        prompts.append(prompt)
        return json.dumps(["Previously on the show, " + GOOD[0], GOOD[1]])

    result = asyncio.run(bridge_episode(download_dir, 2, llm, _bible()))
    assert result.status == "kept" and len(prompts) == 2
    assert "REJECTED FOR" in prompts[1]
    assert [s["speech"] for s in _recap(tmp_path, 2)] == [s["speech"] for s in EP2]
    assert "kept" in seam_report(download_dir)


def test_missing_previous_episode_is_skipped(tmp_path):
    download_dir = _story(tmp_path)
    (tmp_path / "episode_1" / "recap.json").unlink()

    async def llm(prompt):
        raise AssertionError("no LLM call without the previous episode")

    assert asyncio.run(bridge_episode(download_dir, 2, llm, _bible())).status == "skipped"
