import re

from youtube_metadata import generate_youtube_metadata

TIMESTAMP_LINE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?\s")


def test_description_chapter_lines_use_plain_hyphen():
    """YouTube drops description chapters when timestamp lines use an em dash separator."""
    chapters = [
        {"episode": 1, "timestamp": "00:00", "title": "Martial Law Falls"},
        {"episode": 2, "timestamp": "01:32:56", "title": "Execution Signal"},
        {"episode": 3, "timestamp": "03:16:04", "title": "Springing the Trap"},
    ]

    meta = generate_youtube_metadata("Test Apocalypse", 1, 3, chapters=chapters)

    ts_lines = [ln for ln in meta["description"].splitlines() if TIMESTAMP_LINE.match(ln)]
    assert len(ts_lines) >= 3, f"Expected at least 3 chapter lines, got: {ts_lines}"
    assert ts_lines[0].startswith("00:00 - ")
    for line in ts_lines:
        assert "—" not in line, f"Em dash in chapter line breaks YouTube chapters: {line!r}"
        assert re.match(r"^\d{1,2}:\d{2}(?::\d{2})? - \S", line), f"Bad chapter line format: {line!r}"
