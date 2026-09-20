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
