import cv2
import numpy as np
import pytest

from moderation_utils import is_text_bubble_dominant


def test_empty_and_small_images():
    is_bub, reason = is_text_bubble_dominant(None)
    assert not is_bub
    assert reason == "empty_image"

    tiny = np.zeros((10, 10, 3), dtype=np.uint8)
    is_bub, reason = is_text_bubble_dominant(tiny)
    assert not is_bub
    assert reason == "too_small"

    tall = np.ones((1500, 800, 3), dtype=np.uint8) * 255
    is_bub, reason = is_text_bubble_dominant(tall)
    assert not is_bub
    assert reason == "too_tall_for_isolated_bubble"


def test_isolated_speech_bubble_white_on_black():
    img = np.zeros((500, 800, 3), dtype=np.uint8)
    cv2.ellipse(img, (400, 250), (250, 150), 0, 0, 360, (255, 255, 255), -1)
    cv2.putText(img, "EMERGENCY BROADCAST", (220, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    cv2.putText(img, "STATE OF EMERGENCY", (230, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

    is_bub, reason = is_text_bubble_dominant(img)
    assert is_bub is True
    assert reason == "text_bubble_dominant"


def test_isolated_speech_bubble_white_on_white():
    img = np.ones((400, 800, 3), dtype=np.uint8) * 255
    cv2.ellipse(img, (400, 200), (280, 140), 0, 0, 360, (0, 0, 0), 3)
    cv2.putText(img, "MY DEAR CITIZENS...", (230, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    cv2.putText(img, "THE OUTBREAK IS HERE", (210, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)

    is_bub, reason = is_text_bubble_dominant(img)
    assert is_bub is True
    assert reason == "text_bubble_dominant"


def test_character_action_panel_not_bubble():
    img = np.zeros((900, 800, 3), dtype=np.uint8)
    img[:, :] = (180, 120, 50)
    cv2.circle(img, (400, 400), 200, (140, 180, 230), -1)
    cv2.ellipse(img, (400, 300), (220, 150), 0, 180, 360, (30, 30, 80), -1)
    cv2.circle(img, (600, 500), 120, (30, 50, 240), -1)
    cv2.ellipse(img, (200, 150), (100, 60), 0, 0, 360, (255, 255, 255), -1)
    cv2.putText(img, "ATTACK!", (150, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    is_bub, reason = is_text_bubble_dominant(img)
    assert is_bub is False
    assert reason == "art_dominant"


def test_manga_screentone_panel_not_bubble():
    rng = np.random.default_rng(42)
    gray_art = rng.integers(60, 180, size=(800, 800), dtype=np.uint8)
    cv2.circle(gray_art, (400, 400), 250, 40, -1)
    img_bgr = cv2.cvtColor(gray_art, cv2.COLOR_GRAY2BGR)

    is_bub, reason = is_text_bubble_dominant(img_bgr)
    assert is_bub is False
    assert reason == "art_dominant"


def test_smart_merge_logic_vertical_stack():
    bubble_slice = np.ones((300, 800, 3), dtype=np.uint8) * 255
    cv2.ellipse(bubble_slice, (400, 150), (200, 80), 0, 0, 360, (0, 0, 0), 2)
    cv2.putText(bubble_slice, "HELLO WORLD", (300, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

    art_slice = np.zeros((700, 800, 3), dtype=np.uint8)
    art_slice[:, :] = (120, 80, 200)

    is_b1, _ = is_text_bubble_dominant(bubble_slice)
    is_b2, _ = is_text_bubble_dominant(art_slice)
    assert is_b1 is True
    assert is_b2 is False

    merged = np.vstack([bubble_slice, art_slice])
    assert merged.shape == (1000, 800, 3)

    is_b_merged, _ = is_text_bubble_dominant(merged)
    assert is_b_merged is False
