import pytest
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from workflow_stages_2 import CameraPlanner, interpolate_camera_plan

# 800x1200 has only 24px of vertical travel -> Mode C (standard panel).
STANDARD_BOUNDS = (0, 0, 800, 1200)


@pytest.mark.parametrize("duration", [4.0, 8.5])
@pytest.mark.parametrize("shot_index", range(4))
def test_camera_planner_no_longer_emits_removed_modes(shot_index, duration):
    """action_punch_zoom, focal_zoom_in/out (1.10) and dual_shot_cinematic were removed in 38e349f:
    standard panels always get one continuous 2-keyframe subtle zoom, whatever the shot or duration."""
    plan = CameraPlanner.generate_camera_plan(page_num=1, duration=duration, bounds=STANDARD_BOUNDS, shot_index=shot_index)
    assert plan["animation_type"] in ("subtle_focal_zoom_in", "subtle_focal_zoom_out")
    assert plan["easing"] == "soft_linear_glide"
    assert len(plan["keyframes"]) == 2


def test_camera_planner_focal_zooms():
    plan0 = CameraPlanner.generate_camera_plan(page_num=1, duration=4.0, bounds=STANDARD_BOUNDS, shot_index=0)
    assert plan0["animation_type"] == "subtle_focal_zoom_in"
    assert plan0["keyframes"][-1]["scale"] == 1.06

    plan1 = CameraPlanner.generate_camera_plan(page_num=1, duration=4.0, bounds=STANDARD_BOUNDS, shot_index=1)
    assert plan1["animation_type"] == "subtle_focal_zoom_out"
    assert plan1["keyframes"][0]["scale"] == 1.06
    assert plan1["keyframes"][-1]["scale"] == 1.00


def test_interpolate_camera_plan_subtle_zoom():
    plan = CameraPlanner.generate_camera_plan(page_num=1, duration=4.0, bounds=STANDARD_BOUNDS, shot_index=2)
    _, _, s0 = interpolate_camera_plan(plan, 0.0)
    _, _, s2 = interpolate_camera_plan(plan, 2.0)
    _, _, s4 = interpolate_camera_plan(plan, 4.0)
    assert s0 == 1.00
    assert 1.00 < s2 < 1.06
    assert s4 == 1.06
