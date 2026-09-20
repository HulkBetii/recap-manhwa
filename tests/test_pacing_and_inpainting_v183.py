import pytest
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from workflow_stages_2 import CameraPlanner, interpolate_camera_plan

def test_camera_planner_action_punch_zoom():
    bounds = (0, 0, 800, 1200)
    plan = CameraPlanner.generate_camera_plan(
        page_num=1,
        duration=4.0,
        bounds=bounds,
        shot_index=2
    )
    assert plan["animation_type"] == "action_punch_zoom"
    assert plan["direction"] == "punch_in"
    assert plan["easing"] == "soft_linear_glide"
    keyframes = plan["keyframes"]
    assert keyframes[0]["scale"] == 1.00
    assert keyframes[-1]["scale"] == 1.12

def test_camera_planner_focal_zooms():
    bounds = (0, 0, 800, 1200)
    plan0 = CameraPlanner.generate_camera_plan(page_num=1, duration=4.0, bounds=bounds, shot_index=0)
    assert plan0["animation_type"] == "focal_zoom_in"
    assert plan0["keyframes"][-1]["scale"] == 1.10

    plan1 = CameraPlanner.generate_camera_plan(page_num=1, duration=4.0, bounds=bounds, shot_index=1)
    assert plan1["animation_type"] == "focal_zoom_out"
    assert plan1["keyframes"][0]["scale"] == 1.10
    assert plan1["keyframes"][-1]["scale"] == 1.00

def test_camera_planner_dual_shot_for_long_duration():
    bounds = (0, 0, 800, 1200)
    plan = CameraPlanner.generate_camera_plan(page_num=1, duration=8.5, bounds=bounds, shot_index=0)
    assert plan["animation_type"] == "dual_shot_cinematic"
    assert len(plan["keyframes"]) == 3

def test_interpolate_camera_plan_punch_zoom():
    bounds = (0, 0, 800, 1200)
    plan = CameraPlanner.generate_camera_plan(page_num=1, duration=4.0, bounds=bounds, shot_index=2)
    x0, y0, s0 = interpolate_camera_plan(plan, 0.0)
    x2, y2, s2 = interpolate_camera_plan(plan, 2.0)
    x4, y4, s4 = interpolate_camera_plan(plan, 4.0)
    assert s0 == 1.00
    assert 1.00 < s2 < 1.12
    assert s4 == 1.12
