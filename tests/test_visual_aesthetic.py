import cv2
import numpy as np
import pytest
from PIL import Image

from workflow_stages_2 import (
    detect_focal_point,
    detect_content_bounds,
    CameraPlanner,
    interpolate_camera_plan,
)


def test_speech_bubble_suppression():
    """
    Test that a white speech bubble with black text is NOT chosen as the focal point
    when a character face/feature is present elsewhere in the frame.
    """
    # Create 800x1200 image with dark background
    canvas = np.ones((1200, 800, 3), dtype=np.uint8) * 40

    # Top area: Giant White Speech Bubble with high-contrast black text
    cv2.ellipse(canvas, (400, 250), (250, 120), 0, 0, 360, (250, 250, 250), -1)
    for row in range(5):
        cv2.putText(canvas, "I OUGHTA PUT THIS GUY SIX FEET UNDER", (180, 200 + row * 25), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 2)

    # Lower-middle area: Character face with warm skin tones
    # Skin tone BGR: (130, 170, 220) -> HSV: H~15, S~100, V~220
    cv2.circle(canvas, (400, 750), 70, (130, 170, 220), -1)  # Face
    cv2.circle(canvas, (380, 735), 10, (20, 20, 20), -1)    # Eye left
    cv2.circle(canvas, (420, 735), 10, (20, 20, 20), -1)    # Eye right

    pil_img = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    fx, fy = detect_focal_point(pil_img, (0, 0, 800, 1200))

    # The focal point must be in the character face area (y > 500), NOT inside the speech bubble (y < 400)
    assert fy >= 500, f"Focal point y={fy:.1f} was trapped inside speech bubble (should be >= 500 near character)"


def test_detect_content_bounds_trims_gutters():
    """
    Test that solid gutters (top/bottom black or white gaps) are cleanly cropped out.
    """
    # 1000x800 image: 150px top black gutter, 700px content, 150px bottom white gutter
    canvas = np.ones((1000, 800, 3), dtype=np.uint8) * 0
    canvas[150:850, :] = 100
    cv2.putText(canvas, "Comic Story Art", (100, 450), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
    canvas[850:, :] = 255

    pil_img = Image.fromarray(canvas)
    x, y, w, h = detect_content_bounds(pil_img)

    assert y >= 140, f"Top gutter was not trimmed (y={y})"
    assert (y + h) <= 860, f"Bottom gutter was not trimmed (y+h={y+h})"
    assert h < 1000


def test_camera_plan_safe_vertical_framing():
    """
    Test that camera plans generated from character focal points maintain headroom.
    """
    bounds = (0, 0, 800, 1400)
    focal_pt = (400.0, 450.0)

    plan = CameraPlanner.generate_camera_plan(1, 4.0, bounds, focal_point=focal_pt)
    assert plan["animation_type"] != "scroll_down"

    for kf in plan["keyframes"]:
        # Keyframe y should be in a safe framing zone
        assert 0.15 * 1400 <= kf["y"] <= 0.85 * 1400
        assert kf["scale"] >= 1.0
