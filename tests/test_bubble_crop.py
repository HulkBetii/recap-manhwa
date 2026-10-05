import cv2
import numpy as np

from bubble_crop import choose_crop
from tools.text_remover.comic_text_remover import segment_bubble_floodfill
from workflow_stages_2 import apply_bubble_crop

H, W = 1000, 600
FULL = (0, 0, W, H)


def _detail(art_box):
    """Synthetic detail map: drawn content only inside `art_box`."""
    detail = np.zeros((H, W), np.float32)
    x1, y1, x2, y2 = art_box
    detail[y1:y2, x1:x2] = 1.0
    return detail


def test_bubble_at_the_top_is_cropped_away():
    crop = choose_crop((H, W), FULL, bubbles=[(100, 20, 500, 180)], faces=[(200, 400, 400, 600)],
                       detail=_detail((50, 250, 550, 950)))
    assert crop is not None
    x, y, w, h = crop["bounds"]
    assert y >= 180 and crop["bubble_left"] == 0.0
    assert x <= 200 and x + w >= 400 and y <= 400 and y + h >= 600  # the face stays whole


def test_bubble_in_the_middle_keeps_the_panel():
    """User decision: a bubble that cannot be cut away without losing the subject stays."""
    crop = choose_crop((H, W), FULL, bubbles=[(150, 420, 450, 580)], faces=[(200, 200, 400, 380)],
                       detail=_detail((0, 0, W, H)))
    assert crop is None


def test_crop_never_drops_below_half_the_panel():
    crop = choose_crop((H, W), FULL, bubbles=[(0, 0, W, 600)], faces=[], detail=_detail((0, 600, W, H)))
    assert crop is None or crop["kept_area"] >= 0.5


def test_no_bubbles_no_crop():
    assert choose_crop((H, W), FULL, bubbles=[], faces=[], detail=_detail((0, 0, W, H))) is None


def test_crop_stays_inside_the_clean_panel_bounds():
    bounds = (50, 100, 500, 800)
    crop = choose_crop((H, W), bounds, bubbles=[(100, 110, 500, 250)], faces=[], detail=_detail((60, 300, 540, 890)))
    x, y, w, h = crop["bounds"]
    assert x >= 50 and y >= 250 and x + w <= 550 and y + h <= 900


def test_focal_point_is_re_expressed_in_the_crop():
    bounds, focal = apply_bubble_crop({"bounds": [0, 200, 600, 800]}, (0, 0, 600, 1000), (300, 600))
    assert bounds == (0.0, 200.0, 600.0, 800.0) and focal == (300.0, 400.0)


def test_flood_fill_segments_a_bubble():
    """segment_bubble_floodfill used to reject every bubble (mask filled with 1s, counted as 255)."""
    gray = np.full((400, 400), 90, np.uint8)
    cv2.ellipse(gray, (200, 200), (120, 70), 0, 0, 360, 255, -1)
    cv2.ellipse(gray, (200, 200), (120, 70), 0, 0, 360, 0, 3)
    cv2.putText(gray, "HI", (175, 215), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 3)
    mask = segment_bubble_floodfill(gray, (150, 200))
    assert mask is not None and 15000 < np.count_nonzero(mask) < 30000
