import json

import pytest

from recap_schema import load_recap, parse_recap_data


def valid_recap():
    return [{
        "speech": "A valid narration.",
        "images": [
            {"page": 1, "priority": 0.6},
            {"page": 2, "priority": 0.4},
        ],
    }]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data[0].update(speech="   "),
        lambda data: data[0]["images"][0].update(page=0),
        lambda data: data[0]["images"][1].update(page=1),
        lambda data: data[0]["images"][0].update(priority=0),
        lambda data: data[0]["images"][0].update(priority=-0.1),
        lambda data: data[0]["images"][0].update(priority=float("nan")),
        lambda data: data[0]["images"][0].update(priority=0.9),
    ],
)
def test_invalid_recap_values_are_rejected(mutate):
    data = valid_recap()
    mutate(data)
    with pytest.raises(ValueError):
        parse_recap_data(data, max_page=2)


def test_out_of_range_page_is_rejected():
    with pytest.raises(ValueError):
        parse_recap_data(valid_recap(), max_page=1)


def test_non_finite_json_is_rejected(tmp_path):
    recap_path = tmp_path / "recap.json"
    recap_path.write_text(
        '[{"speech":"test","images":[{"page":1,"priority":NaN}]}]',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_recap(recap_path, max_page=1)


def test_priority_tolerance_boundary_is_accepted():
    data = valid_recap()
    data[0]["images"][0]["priority"] = 0.62
    parse_recap_data(data, max_page=2)


def test_sanitize_recap_speech_ocr_artifacts():
    from recap_schema import sanitize_recap_speech

    # Test stripping OCR vocatives
    assert sanitize_recap_speech("Sir, news broadcast scrambled to report the outbreak,") == "News broadcast scrambled to report the outbreak."
    assert sanitize_recap_speech("Ah, the monsters are approaching:") == "The monsters are approaching."
    assert sanitize_recap_speech("Ugh- the pain was unbearable,") == "The pain was unbearable."
    assert sanitize_recap_speech("Wait, he held the sword tightly") == "He held the sword tightly."
    assert sanitize_recap_speech("Sir Panic flooded the streets") == "Panic flooded the streets."

    # Test lowercase start and missing period
    assert sanitize_recap_speech("sudden monster cataclysm engulfed humanity in flames,") == "Sudden monster cataclysm engulfed humanity in flames."
    assert sanitize_recap_speech("he opened the bunker door") == "He opened the bunker door."


def test_sanitize_recap_speech_placeholders_and_slips():
    from recap_schema import sanitize_recap_speech

    assert sanitize_recap_speech("Meanwhile, A turns his attention to the perimeter,") == "Meanwhile, he turns his attention to the perimeter."
    assert sanitize_recap_speech("A steps forward to confront the beast") == "He steps forward to confront the beast."
    assert sanitize_recap_speech("I can't afford to hesitate in this dungeon") == "He cannot afford to hesitate in this dungeon."
    assert sanitize_recap_speech("I had to find shelter before nightfall") == "He had to find shelter before nightfall."


def test_stitch_fragmented_recap_segments():
    from recap_schema import stitch_fragmented_recap_segments

    # Case 1: Hanging possessive / preposition
    raw_segments = [
        {
            "speech": "When the system first crashed, everyone tried to awaken their",
            "images": [{"page": 1, "priority": 1.0}],
        },
        {
            "speech": "abilities in a frantic bid to survive the initial wave.",
            "images": [{"page": 2, "priority": 1.0}],
        },
        {
            "speech": "Paran quietly observes the chaos from his reinforced fortress.",
            "images": [{"page": 3, "priority": 1.0}],
        },
    ]

    stitched = stitch_fragmented_recap_segments(raw_segments)
    assert len(stitched) == 2
    assert stitched[0]["speech"] == "When the system first crashed, everyone tried to awaken their abilities in a frantic bid to survive the initial wave."
    assert len(stitched[0]["images"]) == 2
    assert stitched[0]["images"][0]["page"] == 1
    assert stitched[0]["images"][1]["page"] == 2
    assert round(sum(img["priority"] for img in stitched[0]["images"]), 2) == 1.0

    # Case 2: Hanging verb + lowercase start
    raw_verbs = [
        {
            "speech": "He drops",
            "images": [{"page": 5, "priority": 1.0}],
        },
        {
            "speech": "lays it out in cold hard numbers: nine out of ten perish.",
            "images": [{"page": 6, "priority": 1.0}],
        },
    ]
    stitched_verbs = stitch_fragmented_recap_segments(raw_verbs)
    assert len(stitched_verbs) == 1
    assert "drops and lays it out in cold hard numbers" in stitched_verbs[0]["speech"]
    assert len(stitched_verbs[0]["images"]) == 2

    # Case 3: Complete sentences are preserved separately
    raw_complete = [
        {
            "speech": "Paran enters his reinforced shelter and seals the hatch.",
            "images": [{"page": 1, "priority": 1.0}],
        },
        {
            "speech": "Outside, ferocious beasts tear through the desolate streets.",
            "images": [{"page": 2, "priority": 1.0}],
        },
    ]
    stitched_complete = stitch_fragmented_recap_segments(raw_complete)
    assert len(stitched_complete) == 2
    assert stitched_complete[0]["speech"] == "Paran enters his reinforced shelter and seals the hatch."
    assert stitched_complete[1]["speech"] == "Outside, ferocious beasts tear through the desolate streets."


