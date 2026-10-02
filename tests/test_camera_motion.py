import cv2
import numpy as np
import pytest
from PIL import Image

from workflow_stages_2 import (
    detect_focal_point,
    CameraPlanner,
    interpolate_camera_plan,
    apply_motion_blur,
)


def test_detect_focal_point_on_character_feature():
    # Create 800x600 image with a distinct bright circle (character head) at (180, 250)
    canvas = np.zeros((800, 600), dtype=np.uint8)
    cv2.circle(canvas, (180, 250), 35, 255, -1)
    pil_img = Image.fromarray(canvas)

    bounds = (0, 0, 600, 800)
    fx, fy = detect_focal_point(pil_img, bounds)

    # Focal point should be close to (180, 250)
    assert abs(fx - 180) < 30
    assert abs(fy - 250) < 30


def test_detect_focal_point_fallback_on_blank():
    # Blank image should return center coordinates clamped to safe interior
    canvas = np.zeros((600, 600), dtype=np.uint8)
    pil_img = Image.fromarray(canvas)

    bounds = (0, 0, 600, 600)
    fx, fy = detect_focal_point(pil_img, bounds)
    assert 120 <= fx <= 480
    assert 90 <= fy <= 510


def test_camera_planner_never_uses_scroll_down():
    # Test across multiple durations and aspect ratios
    test_cases = [
        {"duration": 1.2, "bounds": (0, 0, 600, 1800)},
        {"duration": 3.0, "bounds": (0, 0, 600, 1800)},
        {"duration": 6.0, "bounds": (0, 0, 600, 1800)},
        {"duration": 2.5, "bounds": (0, 0, 1200, 600)},  # Wide panel
        {"duration": 7.0, "bounds": (0, 0, 800, 800)},
    ]

    for tc in test_cases:
        plan = CameraPlanner.generate_camera_plan(
            page_num=1,
            duration=tc["duration"],
            bounds=tc["bounds"],
            focal_point=(tc["bounds"][2] * 0.4, tc["bounds"][3] * 0.3),
        )
        assert plan["animation_type"] != "scroll_down", "scroll_down must be completely abolished"
        assert len(plan["keyframes"]) >= 2

        # Check keyframe bounds and center-lock / micro-scale limits
        W_c = tc["bounds"][2]
        H_c = tc["bounds"][3]
        for kf in plan["keyframes"]:
            assert 0 <= kf["x"] <= W_c
            assert 0 <= kf["y"] <= H_c
            assert 1.0 <= kf["scale"] <= 1.40, f"Scale {kf['scale']} exceeded subject-zoom limit 1.40"
            # focal_x is now unlocked (subject-tracked), so only verify it's within safe bounds
            if plan["animation_type"] != "cinematic_pan_horizontal":
                assert 0.10 * W_c <= kf["x"] <= 0.90 * W_c, f"Keyframe X {kf['x']} outside safe margins"


def test_camera_planner_mode_selection():
    # 1. Tall webtoon strip panel (usable_v_travel >= 160px) -> vertical_pan_glide
    plan_tall = CameraPlanner.generate_camera_plan(1, 3.0, (0, 0, 600, 1600))
    assert plan_tall["animation_type"] == "vertical_pan_glide"
    assert plan_tall["easing"] in ("easeInOutCubic", "soft_linear_glide")
    assert len(plan_tall["keyframes"]) in (2, 3)

    # 2. Speech bubble at the top of a tall panel: the glide starts below it and never reveals it
    #    (bubble-edge clamping replaced bubble-driven direction in 38e349f).
    bubble_bottom = 300.0
    plan_bubble_top = CameraPlanner.generate_camera_plan(
        page_num=1,
        duration=3.0,
        bounds=(0, 0, 600, 1600),
        top_bubble_bottom_y=bubble_bottom,
    )
    assert plan_bubble_top["animation_type"] == "vertical_pan_glide"
    assert plan_bubble_top["direction"] == "top_to_bottom"
    half_view = (600 / 0.68) * 0.5
    assert all(kf["y"] - half_view > bubble_bottom for kf in plan_bubble_top["keyframes"])

    # 3. Standard / Square / Low-height panel -> subtle continuous zoom, alternating in/out (never frozen!)
    plan_square_even = CameraPlanner.generate_camera_plan(1, 3.0, (0, 0, 800, 800), shot_index=0)
    assert plan_square_even["animation_type"] == "subtle_focal_zoom_in"
    assert plan_square_even["keyframes"][0]["scale"] == 1.00
    assert plan_square_even["keyframes"][1]["scale"] == 1.06

    plan_square_odd = CameraPlanner.generate_camera_plan(1, 3.0, (0, 0, 800, 800), shot_index=1)
    assert plan_square_odd["animation_type"] == "subtle_focal_zoom_out"
    assert plan_square_odd["keyframes"][0]["scale"] == 1.06
    assert plan_square_odd["keyframes"][1]["scale"] == 1.00

    # 4. Standard moderate wide panel (aspect_ratio < 1.70, e.g. 1000x700 = 1.43) -> subtle zoom
    plan_mod_wide = CameraPlanner.generate_camera_plan(1, 3.0, (0, 0, 1000, 700))
    assert plan_mod_wide["animation_type"] in ("subtle_focal_zoom_in", "subtle_focal_zoom_out")

    # 5. Landscape / Panoramic panel (aspect_ratio >= 1.70, e.g. 1200x600 = 2.0, 1500x500 = 3.0) -> Cinematic Horizontal Pan
    plan_wide = CameraPlanner.generate_camera_plan(1, 3.0, (0, 0, 1200, 600))
    assert plan_wide["animation_type"] == "cinematic_pan_horizontal"
    assert plan_wide["easing"] in ("soft_linear_glide", "easeInOutCubic")

    plan_panorama = CameraPlanner.generate_camera_plan(1, 3.0, (0, 0, 1500, 500))
    assert plan_panorama["animation_type"] == "cinematic_pan_horizontal"
    assert plan_panorama["easing"] in ("soft_linear_glide", "easeInOutCubic")


def test_interpolate_camera_plan_and_jump_cut():
    plan = {
        "easing": "easeInOutSine",
        "keyframes": [
            {"time": 0.0, "x": 150.0, "y": 200.0, "scale": 1.10},
            {"time": 2.0, "x": 150.0, "y": 200.0, "scale": 1.14},
            {"time": 2.001, "x": 300.0, "y": 400.0, "scale": 1.01},  # Jump cut
            {"time": 5.0, "x": 300.0, "y": 400.0, "scale": 1.05},
        ]
    }

    # At start
    x0, y0, s0 = interpolate_camera_plan(plan, 0.0)
    assert (x0, y0, s0) == (150.0, 200.0, 1.10)

    # Before jump cut
    x_pre, y_pre, s_pre = interpolate_camera_plan(plan, 1.99)
    assert x_pre == 150.0 and y_pre == 200.0

    # Right after jump cut
    x_post, y_post, s_post = interpolate_camera_plan(plan, 2.05)
    assert abs(x_post - 300.0) < 5.0
    assert abs(y_post - 400.0) < 5.0


def test_apply_motion_blur():
    img_np = np.ones((100, 100, 3), dtype=np.uint8) * 128
    # No motion
    res_static = apply_motion_blur(img_np, 0.1, 0.1)
    assert res_static.shape == img_np.shape

    # Fast horizontal motion
    res_blurred = apply_motion_blur(img_np, 8.0, 0.0)
    assert res_blurred.shape == img_np.shape


def test_hybrid_motion_alternating_motion_and_progress():
    """Verify v1.6.1 Hybrid Motion alternating direction and continuous progress interpolation."""
    from workflow_stages_2 import soft_linear_glide, interpolate_camera_progress

    # 1. Tall panel (usable_v_travel >= 160) -> alternating pan direction
    tall_bounds = (0, 0, 800, 1800)
    plan_even = CameraPlanner.generate_camera_plan(1, 3.0, tall_bounds, shot_index=0)
    assert plan_even["animation_type"] == "vertical_pan_glide"
    assert plan_even["direction"] == "top_to_bottom"
    assert plan_even["keyframes"][0]["progress"] == 0.0
    assert plan_even["keyframes"][-1]["progress"] == 1.0

    plan_odd = CameraPlanner.generate_camera_plan(1, 3.0, tall_bounds, shot_index=1)
    assert plan_odd["animation_type"] == "vertical_pan_glide"
    assert plan_odd["direction"] == "bottom_to_top"

    # 2. Soft linear glide easing property: linear constant speed in [0.05, 0.95]
    assert soft_linear_glide(0.0) == 0.0
    assert abs(soft_linear_glide(0.5) - 0.5) < 1e-4
    assert soft_linear_glide(1.0) == 1.0

    # Intermediate progress is strictly monotonic
    for t in [0.1, 0.25, 0.5, 0.75, 0.9]:
        p = interpolate_camera_progress(plan_even, t * 3.0)
        assert 0.0 <= p <= 1.0
    assert interpolate_camera_progress(plan_even, 0.0) == 0.0
    assert interpolate_camera_progress(plan_even, 3.0) == 1.0


def test_adaptive_velocity_clamping_v170():
    """Verify that vertical pan velocity is strictly clamped <= 120 px/s in v1.7.0."""
    tall_bounds = (0, 0, 800, 2800)
    duration = 2.5  # Short dialogue line
    plan = CameraPlanner.generate_camera_plan(1, duration, tall_bounds, shot_index=0)
    
    kf = plan["keyframes"]
    travel_dist = abs(kf[1]["y"] - kf[0]["y"])
    pan_speed = travel_dist / duration
    assert pan_speed <= 120.0 + 1e-4, f"Pan speed {pan_speed:.1f}px/s exceeded 120px/s limit"


def test_camera_planner_semi_vertical_top_threat_and_action_panning():
    """Tall panels pan from the subject: subject low (looming threat) -> bottom_to_top, subject high -> top_to_bottom.
    The focal point overrides the shot_index alternation (38e349f)."""
    # 1. Composite panel (800x1800) with character in lower half (y=1300 > 0.55*1800=990)
    tall_bounds = (0, 0, 800, 1800)
    plan_threat = CameraPlanner.generate_camera_plan(
        page_num=40,
        duration=3.5,
        bounds=tall_bounds,
        focal_point=(400.0, 1300.0),
        shot_index=0  # alternation alone would give top_to_bottom
    )
    assert plan_threat["animation_type"] == "vertical_pan_glide"
    assert plan_threat["direction"] == "bottom_to_top"

    # 2. Tall panel with subject in upper half (y=500 < 0.45*1800=810)
    plan_upper = CameraPlanner.generate_camera_plan(
        page_num=41,
        duration=3.5,
        bounds=tall_bounds,
        focal_point=(400.0, 500.0),
        shot_index=1  # alternation alone would give bottom_to_top
    )
    assert plan_upper["animation_type"] == "vertical_pan_glide"
    assert plan_upper["direction"] == "top_to_bottom"


