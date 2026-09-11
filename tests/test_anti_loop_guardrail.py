import pytest
from recap_schema import (
    detect_recap_loop,
    prune_recap_loops,
    parse_recap_data,
    RecapSegment,
)
from app import parse_gemini_recap_text


def create_mock_segment(page: int, speech: str = 'Narration') -> dict:
    return {
        'speech': f'{speech} on page {page}.',
        'images': [{'page': page, 'priority': 1.0}],
    }


def test_detect_recap_loop_on_real_repetition():
    # Simulate a 40-segment recap where pages 1..25 are narrated,
    # then at segment 26 it jumps back to page 1, 2, 3...
    segments = [create_mock_segment(p) for p in range(1, 26)]
    # Loop restart:
    loop_tail = [create_mock_segment(p, speech='Repeated') for p in range(1, 15)]
    full_segments = segments + loop_tail

    has_loop, loop_idx = detect_recap_loop(full_segments, max_page=40)
    assert has_loop is True
    assert loop_idx == 25


def test_prune_recap_loops_auto_heals_and_sanitizes():
    segments = [create_mock_segment(p) for p in range(1, 26)]
    # Boundary segment accidentally contains leaked header at the end of speech
    segments[-1]['speech'] = 'Chien binh mot minh tien vao toa thap [1, 2] - Khi toa thap bat ngo'
    loop_tail = [create_mock_segment(p, speech='Repeated') for p in range(1, 15)]
    full_segments = segments + loop_tail

    pruned, was_pruned = prune_recap_loops(full_segments, max_page=40)
    assert was_pruned is True
    assert len(pruned) == 25
    assert pruned[-1]['speech'] == 'Chien binh mot minh tien vao toa thap'
    # Pruned segments should now pass parse_recap_data cleanly
    validated = parse_recap_data(pruned, max_page=40, allow_loops=False)
    assert len(validated) == 25


def test_legitimate_brief_flashback_not_flagged_as_loop():
    # Story progresses: 1..20, then 1 flashback to page 2, then immediately continues to 21, 22, 23
    segments = [create_mock_segment(p) for p in range(1, 21)]
    flashback = [create_mock_segment(2, speech='Hoi tuong')]
    resumption = [create_mock_segment(p) for p in range(21, 30)]
    full_segments = segments + flashback + resumption

    has_loop, loop_idx = detect_recap_loop(full_segments, max_page=40)
    assert has_loop is False
    assert loop_idx is None


def test_parse_recap_data_rejects_unpruned_loop():
    segments = [create_mock_segment(p) for p in range(1, 26)]
    loop_tail = [create_mock_segment(p, speech='Repeated') for p in range(1, 15)]
    full_segments = segments + loop_tail

    with pytest.raises(ValueError, match='Recap contains a detected narrative loop'):
        parse_recap_data(full_segments, max_page=40, allow_loops=False)


def test_short_primary_portion_fails_safe_without_pruning():
    # If a loop starts very early (e.g. only 4 segments before restarting),
    # it cannot be auto-healed safely into a valid recap.
    segments = [create_mock_segment(p) for p in range(1, 5)]
    loop_tail = [create_mock_segment(p) for p in range(1, 15)]
    full_segments = segments + loop_tail

    pruned, was_pruned = prune_recap_loops(full_segments, max_page=40)
    assert was_pruned is False
    assert len(pruned) == len(full_segments)


def test_app_parse_gemini_recap_text_auto_prunes_raw_response():
    # Test end-to-end with raw text format from Gemini containing a loop
    raw_lines = []
    for p in range(1, 26):
        raw_lines.append(f'{p} - Dien bien quan trong tren trang {p}.#')
    # Loop restart
    for p in range(1, 10):
        raw_lines.append(f'{p} - Kể lặp lại trên trang {p}.#')
    raw_text = '\n'.join(raw_lines)

    parsed = parse_gemini_recap_text(raw_text)
    assert len(parsed) == 25
    assert parsed[0]['images'][0]['page'] == 1
    assert parsed[-1]['images'][0]['page'] == 25
