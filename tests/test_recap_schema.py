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


def test_ensure_minimum_multipanel_density_enhances_sparse_recap():
    from recap_schema import ensure_minimum_multipanel_density

    # 10 single-panel segments (0% multi-panel)
    sparse_data = [
        {"speech": f"This is segment number {i} with enough descriptive words to qualify for pairing.", "images": [{"page": i + 1, "priority": 1.0}]}
        for i in range(10)
    ]

    enhanced = ensure_minimum_multipanel_density(sparse_data, min_ratio=0.15, target_ratio=0.20)
    multis = [s for s in enhanced if len(s["images"]) > 1]
    
    # Should now have at least 2 multi-panel segments (20%)
    assert len(multis) >= 2
    # Verify image priority sum is 1.0 on all multi-panel items
    for s in multis:
        assert len(s["images"]) == 2
        assert round(sum(img["priority"] for img in s["images"]), 2) == 1.0


def test_ensure_minimum_multipanel_density_preserves_already_dense_recap():
    from recap_schema import ensure_minimum_multipanel_density

    # Already has 30% multi-panel (3 out of 10)
    dense_data = [
        {"speech": f"Segment {i} long text description sentence.", "images": [{"page": i + 1, "priority": 1.0}]}
        for i in range(7)
    ] + [
        {"speech": f"Multi segment {i} long text description.", "images": [{"page": 8 + i, "priority": 0.7}, {"page": 9 + i, "priority": 0.3}]}
        for i in range(3)
    ]

    enhanced = ensure_minimum_multipanel_density(dense_data, min_ratio=0.15, target_ratio=0.20)
    multis = [s for s in enhanced if len(s["images"]) > 1]
    assert len(multis) == 3  # Unchanged
