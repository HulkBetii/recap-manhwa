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

        # Check keyframe bounds
        W_c = tc["bounds"][2]
        H_c = tc["bounds"][3]
        for kf in plan["keyframes"]:
            assert 0 <= kf["x"] <= W_c
            assert 0 <= kf["y"] <= H_c
            assert 1.0 <= kf["scale"] <= 1.30


def test_camera_planner_mode_selection():
    # 1. Short duration -> subtle_breath
    plan_short = CameraPlanner.generate_camera_plan(1, 1.2, (0, 0, 600, 800))
    assert plan_short["animation_type"] == "subtle_breath"

    # 2. Long duration -> virtual_multicam continuous gentle focus
    plan_long = CameraPlanner.generate_camera_plan(1, 6.0, (0, 0, 600, 800))
    assert plan_long["animation_type"] == "virtual_multicam"
    assert len(plan_long["keyframes"]) >= 2

    # 3. Wide panel -> cinematic_pan_horizontal
    plan_wide = CameraPlanner.generate_camera_plan(1, 3.0, (0, 0, 1200, 600))
    assert plan_wide["animation_type"] == "cinematic_pan_horizontal"


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
