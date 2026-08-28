import random
import cv2
import numpy as np
import pytest
from PIL import Image

from app import _parse_gemini_image_specs, parse_gemini_recap_text
from moderation_utils import is_junk_or_title_page, is_blank_or_solid_page
from recap_schema import parse_recap_data
from workflow_stages_2 import (
    detect_focal_point,
    detect_content_bounds,
    CameraPlanner,
    interpolate_camera_plan,
    draw_subtitles_on_frame,
    shift_srt_time,
)


def test_metric_zero_camera_drift_across_random_scenarios():
    """
    Quality Metric: 100% of camera keyframes and interpolated points across 50 random
    panel sizes, aspect ratios, and durations must stay strictly within bounds without drifting into black/white voids.
    """
    random.seed(42)
    for i in range(50):
        w = random.randint(400, 1600)
        h = random.randint(300, 1800)
        dur = random.uniform(1.0, 8.5)
        bounds = (0, 0, w, h)
        focal_pt = (random.uniform(0.1 * w, 0.9 * w), random.uniform(0.1 * h, 0.9 * h))

        plan = CameraPlanner.generate_camera_plan(
            page_num=i + 1,
            duration=dur,
            bounds=bounds,
            focal_point=focal_pt,
        )

        # 1. Assert animation_type is never scroll_down
        assert plan["animation_type"] != "scroll_down"

        # 2. Check all keyframes
        for kf in plan["keyframes"]:
            assert 0 <= kf["x"] <= w, f"Keyframe x={kf['x']} out of bounds [0, {w}]"
            assert 0 <= kf["y"] <= h, f"Keyframe y={kf['y']} out of bounds [0, {h}]"
            assert kf["scale"] >= 1.0, f"Scale {kf['scale']} cannot be less than 1.0"

        # 3. Check continuous interpolation at 10 random timestamps
        for _ in range(10):
            t_sample = random.uniform(0.0, dur)
            x_interp, y_interp, scale_interp = interpolate_camera_plan(plan, t_sample)
            assert 0 <= x_interp <= w
            assert 0 <= y_interp <= h
            assert scale_interp >= 1.0


def test_metric_focal_point_detection_precision():
    """
    Quality Metric: Focal point detector must correctly anchor onto character positions
    (top-left, top-right, center) within a tight tolerance.
    """
    target_locations = [
        (150, 200),  # Top-left
        (450, 200),  # Top-right
        (300, 350),  # Center
        (200, 450),  # Lower-mid
    ]

    for tx, ty in target_locations:
        canvas = np.zeros((800, 600), dtype=np.uint8)
        # Draw character face/feature at target
        cv2.circle(canvas, (tx, ty), 30, 255, -1)
        cv2.rectangle(canvas, (tx - 15, ty - 15), (tx + 15, ty + 15), 100, 2)
        pil_img = Image.fromarray(canvas)

        fx, fy = detect_focal_point(pil_img, (0, 0, 600, 800))
        # Verify detected focal point is close to target (within 40px)
        assert abs(fx - tx) <= 40, f"Target X={tx}, Got {fx}"
        assert abs(fy - ty) <= 40, f"Target Y={ty}, Got {fy}"


def test_metric_multi_panel_priority_normalization():
    """
    Quality Metric: Multi-panel script timing weights must always strictly sum to 1.0.
    """
    test_cases = [
        "[14, 15]",
        "[10, 11, 12]",
        "[5:30%, 6:70%]",
        "[1:25%, 2:25%, 3:50%]",
        "[8:0.33, 9:0.67]",
    ]

    for spec in test_cases:
        parsed = _parse_gemini_image_specs(spec)
        assert len(parsed) >= 2
        total_p = sum(img["priority"] for img in parsed)
        assert abs(total_p - 1.0) < 1e-3, f"Spec {spec} sum={total_p} != 1.0"


def test_metric_junk_title_detection_accuracy():
    """
    Quality Metric: Title banners, credit cards, and blank pages must be detected as junk 100% of the time.
    """
    # 1. Title banner "PREPARE APOCALYPSE"
    title_img = np.ones((350, 700, 3), dtype=np.uint8) * 15
    cv2.putText(title_img, "PREPARE APOCALYPSE", (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    is_junk, _ = is_junk_or_title_page(title_img)
    assert is_junk is True

    # 2. Credit banner
    credit_img = np.ones((400, 700, 3), dtype=np.uint8) * 230
    cv2.putText(credit_img, "Chapter 1 - Scanlated by Team", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    is_junk_cr, _ = is_junk_or_title_page(credit_img, ocr_texts=["Chapter 1", "Scanlated by Team", "Donate via paypal"])
    assert is_junk_cr is True

    # 3. Solid blank page
    blank_img = np.ones((500, 500, 3), dtype=np.uint8) * 255
    is_blank, _ = is_blank_or_solid_page(blank_img)
    assert is_blank is True
