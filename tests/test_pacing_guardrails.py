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
    """Verify that images displayed > 7.0s use continuous 2-phase Ken Burns motion without jarring jump cuts."""
    bounds = (0, 0, 800, 1200)
    duration = 11.46  # Example from Episode 1 Segment 33
    plan = CameraPlanner.generate_camera_plan(
        page_num=35,
        duration=duration,
        bounds=bounds,
        focal_point=(400, 300)
    )

    assert plan["animation_type"] == "dual_shot_cinematic"
    keyframes = plan["keyframes"]
    assert len(keyframes) == 3

    t_split = round(duration * 0.5, 3)
    # Peak zoom at t_split
    assert keyframes[1]["time"] == t_split
    assert keyframes[1]["scale"] > 1.05

    # Test interpolation continuity around t_split (no sudden jump or discontinuous snap)
    x_pre, y_pre, s_pre = interpolate_camera_plan(plan, t_split - 0.05)
    x_peak, y_peak, s_peak = interpolate_camera_plan(plan, t_split)
    x_post, y_post, s_post = interpolate_camera_plan(plan, t_split + 0.05)

    assert s_pre < s_peak
    assert s_post < s_peak
    assert abs(s_post - s_pre) < 0.02, "Scale must be smooth and continuous at t_split"
    assert abs(x_post - x_pre) < 1.0, "X position must be smooth and continuous at t_split"

    # End of Phase 2: Zoomed out completely to wide 1.00
    x_end, y_end, s_end = interpolate_camera_plan(plan, duration)
    assert abs(s_end - 1.00) < 0.001
    assert keyframes[2]["scale"] < keyframes[1]["scale"]


def test_standard_and_medium_durations_unaffected():
    """Verify durations <= 7.0s still use their designated animation types (focal zoom in/out)."""
    bounds = (0, 0, 800, 1200)
    
    # 6.0s should use standard focal zoom
    plan_med = CameraPlanner.generate_camera_plan(1, 6.0, bounds)
    assert plan_med["animation_type"] in ("focal_zoom_in", "focal_zoom_out")

    # 1.2s should use standard focal zoom
    plan_short = CameraPlanner.generate_camera_plan(1, 1.2, bounds)
    assert plan_short["animation_type"] in ("focal_zoom_in", "focal_zoom_out")


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
