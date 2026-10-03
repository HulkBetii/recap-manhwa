import pytest
import config
from workflow_stages_2 import (
    align_subtitles_to_segments,
    CameraPlanner,
    interpolate_camera_plan,
)


def test_subtitle_normalization_hard_floor():
    """Verify that segments with very short duration (< 1.8s) are expanded to at least 1.8s."""
    segments = [
        {"speech": "Cậu ấy nhìn thấy lối thoát hiểm."},
        {"speech": "Nhưng lũ quái vật đã phong tỏa toàn bộ cửa ra vào."},
    ]
    # Simulate Whisper subtitle compression where segment 0 is compressed to 0.11s
    subtitles = [
        {"start": 86.231, "end": 86.340, "text": "Cậu ấy nhìn thấy lối thoát hiểm."},
        {"start": 90.000, "end": 94.000, "text": "Nhưng lũ quái vật đã phong tỏa toàn bộ cửa ra vào."},
    ]
    
    aligned = align_subtitles_to_segments(subtitles, segments, audio_duration=100.0)
    assert len(aligned) == 2
    
    seg0_dur = aligned[0]["end"] - aligned[0]["start"]
    assert seg0_dur >= 1.8, f"Expected segment 0 duration >= 1.8s, got {seg0_dur:.3f}s"
    assert aligned[0]["start"] == 86.231
    assert aligned[0]["end"] >= 86.231 + 1.8

    seg1_dur = aligned[1]["end"] - aligned[1]["start"]
    assert seg1_dur >= 1.8, f"Expected segment 1 duration >= 1.8s, got {seg1_dur:.3f}s"


def test_dual_sub_shot_camera_planner_for_long_duration():
    """Verify that images displayed > 7.0s use continuous camera motion without jarring jump cuts."""
    bounds = (0, 0, 800, 1200)
    duration = 11.46  # Example from Episode 1 Segment 33
    plan = CameraPlanner.generate_camera_plan(
        page_num=35,
        duration=duration,
        bounds=bounds,
        focal_point=(400, 300)
    )

    assert plan["animation_type"] in ("subtle_focal_zoom_in", "dual_shot_cinematic", "focal_zoom_in")
    keyframes = plan["keyframes"]
    assert len(keyframes) >= 2


def test_standard_and_medium_durations_unaffected():
    """Verify durations <= 7.0s still use their designated animation types."""
    bounds = (0, 0, 800, 1200)
    
    # 6.0s should use subtle or standard focal zoom
    plan_med = CameraPlanner.generate_camera_plan(1, 6.0, bounds)
    assert plan_med["animation_type"] in ("subtle_focal_zoom_in", "focal_zoom_in", "focal_zoom_out")

    # 1.2s should use subtle or standard focal zoom
    plan_short = CameraPlanner.generate_camera_plan(1, 1.2, bounds)
    assert plan_short["animation_type"] in ("subtle_focal_zoom_in", "focal_zoom_in", "focal_zoom_out")


def test_display_guardrail_merges_sub_1_8s():
    """Simulate Stage 10 display guardrail logic to ensure no display < 1.8s survives."""
    merged_page_displays = [
        {"image_file": "p1.jpg", "duration": 4.5, "start_time": 0.0, "end_time": 4.5},
        {"image_file": "p2.jpg", "duration": 0.11, "start_time": 4.5, "end_time": 4.61},
        {"image_file": "p3.jpg", "duration": 3.0, "start_time": 4.61, "end_time": 7.61},
    ]

    cleaned_page_displays = []
    for pd in merged_page_displays:
        if cleaned_page_displays and pd["duration"] < 1.8:
            cleaned_page_displays[-1]["duration"] += pd["duration"]
            cleaned_page_displays[-1]["end_time"] = (
                cleaned_page_displays[-1]["start_time"] + cleaned_page_displays[-1]["duration"]
            )
        else:
            cleaned_page_displays.append(pd)

    if len(cleaned_page_displays) > 1 and cleaned_page_displays[0]["duration"] < 1.8:
        first = cleaned_page_displays.pop(0)
        cleaned_page_displays[0]["duration"] += first["duration"]
        cleaned_page_displays[0]["start_time"] = first["start_time"]

    final_page_displays = []
    for pd in cleaned_page_displays:
        if final_page_displays and final_page_displays[-1]["image_file"] == pd["image_file"]:
            final_page_displays[-1]["duration"] += pd["duration"]
            final_page_displays[-1]["end_time"] = (
                final_page_displays[-1]["start_time"] + final_page_displays[-1]["duration"]
            )
        else:
            final_page_displays.append(pd)

    assert len(final_page_displays) == 2
    assert final_page_displays[0]["image_file"] == "p1.jpg"
    assert round(final_page_displays[0]["duration"], 2) == 4.61
    assert final_page_displays[1]["image_file"] == "p3.jpg"
    assert all(d["duration"] >= 1.8 for d in final_page_displays)


def test_flash_forward_intro_disabled_by_default():
    """Verify that flash-forward intro is disabled by default (Cold Open policy)."""
    assert config.ENABLE_FLASH_FORWARD_INTRO is False


def test_subtitle_floor_never_passes_audio_end():
    """The 1.8s floor used to push the last cue past the audio, overlapping the next episode once merged."""
    subtitles = [{"start": 0.0, "end": 4.0, "text": "First line here."}, {"start": 9.5, "end": 9.9, "text": "End."}]
    segments = [{"speech": "First line here."}, {"speech": "End."}]
    aligned = align_subtitles_to_segments(subtitles, segments, audio_duration=10.0)
    assert aligned[-1]["end"] == 10.0


def test_merged_cues_stay_inside_their_segment(tmp_path):
    from workflow_stages_2 import merge_srt_files
    first, second = tmp_path / "a.srt", tmp_path / "b.srt"
    first.write_text("1\n00:00:00,000 --> 00:00:04,000\nOne.\n\n2\n00:00:08,000 --> 00:00:10,700\nTwo.\n", encoding="utf-8")
    second.write_text("1\n00:00:00,000 --> 00:00:02,000\nThree.\n", encoding="utf-8")
    out = tmp_path / "merged.srt"
    merge_srt_files([str(first), str(second)], [10.0, 5.0], str(out))
    text = out.read_text(encoding="utf-8")
    assert "00:00:08,000 --> 00:00:10,000" in text
    assert "00:00:10,000 --> 00:00:12,000" in text


def test_split_subtitle_text_keeps_two_lines():
    from workflow_stages_2 import split_subtitle_text, wrap_srt_text
    short = "Seongho checks his gear."
    assert split_subtitle_text(short) == [short]
    long = ("That emergency hotline instantly kicks President Wontaek Jang into gear, mobilizing national "
            "defense forces without hesitation while the city burns around them.")
    pieces = split_subtitle_text(long)
    assert len(pieces) >= 2 and " ".join(pieces) == long
    assert all(wrap_srt_text(p).count("\n") <= 1 for p in pieces)


def test_split_long_cues_shares_time_by_length():
    from workflow_stages_2 import split_long_cues
    text = "A first long clause that clearly fills one subtitle line, and a second clause that fills another, then more words."
    parts = split_long_cues([{"start": 10.0, "end": 16.0, "text": text}])
    assert len(parts) >= 2
    assert parts[0]["start"] == 10.0 and parts[-1]["end"] == 16.0
    assert all(a["end"] == b["start"] for a, b in zip(parts, parts[1:]))


def test_merge_splits_three_line_cues(tmp_path):
    from workflow_stages_2 import merge_srt_files
    src = tmp_path / "a.srt"
    src.write_text("1\n00:00:00,000 --> 00:00:06,000\nThat emergency hotline instantly kicks\nPresident Wontaek Jang into gear,\n"
                   "mobilizing national defense forces without\nhesitation.\n", encoding="utf-8")
    out = tmp_path / "m.srt"
    merge_srt_files([str(src)], [6.0], str(out))
    blocks = [b for b in out.read_text(encoding="utf-8").strip().split("\n\n") if b]
    assert len(blocks) >= 2 and all(len(b.split("\n")) <= 4 for b in blocks)  # index + time + <=2 lines


def test_lines_do_not_end_on_a_leading_word():
    from workflow_stages_2 import split_subtitle_text
    text = ("Seongho firmly maintains his defensive guard to shield the injured woman coughing crimson on the "
            "pavement while the killer closes in")
    pieces = split_subtitle_text(text)
    assert len(pieces) >= 2 and " ".join(pieces) == text
    assert all(p.split()[-1].lower() not in {"to", "the", "his", "while"} for p in pieces[:-1])


def test_timeline_is_compressed_inside_the_audio():
    """Unmatched segments are estimated after the last cue; they must not run past the audio."""
    subtitles = [{"start": 0.0, "end": 8.0, "text": "One long sentence spoken here."}]
    segments = [{"speech": "One long sentence spoken here."}, {"speech": "Second."}, {"speech": "Third one."}]
    aligned = align_subtitles_to_segments(subtitles, segments, audio_duration=10.0)
    assert aligned[-1]["end"] <= 10.0 + 1e-9
    assert all(a["end"] <= b["start"] + 1e-9 for a, b in zip(aligned, aligned[1:]))
