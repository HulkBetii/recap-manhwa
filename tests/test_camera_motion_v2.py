"""CameraPlanner.generate_camera_plan: the simplified 2-keyframe camera (commit 38e349f).

Previously a script that replaced PIL, workflow_base, cv2, app... in sys.modules with empty stubs at
import time, which broke every test collected after it. It now imports the real module.
"""
import pytest

from workflow_stages_2 import CameraPlanner, interpolate_camera_plan

BOUNDS_WIDE = (0, 0, 2400, 900)    # aspect 2.67 -> Mode A, wide scale 1.12
BOUNDS_TALL = (0, 0, 800, 2400)   # aspect 0.33 -> Mode B
BOUNDS_MED = (0, 0, 800, 1400)    # aspect 0.57, 224px of vertical travel -> Mode B
BOUNDS_STD = (0, 0, 800, 900)     # aspect 0.89 -> Mode C
DUR = 4.0


def plan(bounds, duration=DUR, **kw):
    return CameraPlanner.generate_camera_plan(1, duration, bounds, transition="cross_fade", **kw)


@pytest.mark.parametrize("bounds", [BOUNDS_TALL, BOUNDS_MED])
def test_tall_panels_glide_vertically_with_two_keyframes(bounds):
    p = plan(bounds, shot_index=0)
    assert p["animation_type"] == "vertical_pan_glide"
    assert p["easing"] == "soft_linear_glide"
    start, end = p["keyframes"]
    assert (start["time"], end["time"]) == (0.0, DUR)
    assert (start["scale"], end["scale"]) == (1.00, 1.03)
    assert start["y"] != end["y"]


def test_vertical_glide_alternates_depth_scaling():
    start, end = plan(BOUNDS_TALL, shot_index=1)["keyframes"]
    assert (start["scale"], end["scale"]) == (1.03, 1.00)


def test_vertical_glide_speed_is_capped():
    start, end = plan(BOUNDS_TALL, duration=2.0)["keyframes"]
    assert abs(end["y"] - start["y"]) <= 2.0 * 120.0 + 1e-6


@pytest.mark.parametrize("shot_index, animation, scales", [
    (0, "subtle_focal_zoom_in", (1.00, 1.06)),
    (1, "subtle_focal_zoom_out", (1.06, 1.00)),
])
def test_standard_panels_use_a_subtle_continuous_zoom(shot_index, animation, scales):
    p = plan(BOUNDS_STD, shot_index=shot_index)
    assert p["animation_type"] == animation
    assert tuple(kf["scale"] for kf in p["keyframes"]) == scales


def test_wide_panels_pan_horizontally_at_constant_scale():
    p = plan(BOUNDS_WIDE, shot_index=0)
    assert p["animation_type"] == "cinematic_pan_horizontal"
    assert p["direction"] == "left_to_right"
    assert {kf["scale"] for kf in p["keyframes"]} == {1.12}
    assert plan(BOUNDS_WIDE, shot_index=1)["direction"] == "right_to_left"


def test_motion_is_linear_without_mid_shot_pauses():
    p = plan(BOUNDS_STD, shot_index=0)
    _, _, s_mid = interpolate_camera_plan(p, DUR / 2)
    assert s_mid == pytest.approx(1.03)
