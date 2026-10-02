import pytest

from app import generate_gemini_prompt
from seam_bridge import partition_contiguous
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
