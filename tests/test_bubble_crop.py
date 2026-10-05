import cv2
import numpy as np

from bubble_crop import Bubbles, _plain_lettering, _spills_over, choose_crop, drawn_panel_bounds
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


def _mask(*boxes):
    mask = np.zeros((H, W), np.uint8)
    for x1, y1, x2, y2 in boxes:
        mask[y1:y2, x1:x2] = 1
    return mask


def test_bubble_at_the_top_is_cropped_away():
    crop = choose_crop((H, W), FULL, _mask((100, 20, 500, 180)), faces=[(200, 400, 400, 600)],
                       detail=_detail((50, 250, 550, 950)))
    assert crop is not None
    x, y, w, h = crop["bounds"]
    assert y >= 150 and crop["bubble_left"] < 0.2
    assert x <= 200 and x + w >= 400 and y <= 400 and y + h >= 600  # the face stays whole


def test_bubble_across_the_face_keeps_the_panel():
    """User decision: when the bubble cannot be cut away without losing the subject, the panel stays."""
    crop = choose_crop((H, W), FULL, _mask((150, 300, 450, 700)), faces=[(200, 350, 400, 650)],
                       detail=_detail((0, 0, W, H)))
    assert crop is None


def test_no_obstacles_no_crop():
    assert choose_crop((H, W), FULL, _mask(), faces=[], detail=_detail((0, 0, W, H))) is None


def test_crop_stays_inside_the_given_bounds():
    bounds = (50, 100, 500, 800)
    crop = choose_crop((H, W), bounds, _mask((100, 110, 500, 250)), faces=[], detail=_detail((60, 300, 540, 890)))
    x, y, w, h = crop["bounds"]
    assert x >= 50 and y >= 100 and x + w <= 550 and y + h <= 900


def test_drawn_panel_excludes_gutter_and_bubbles():
    """cat-anh.docx example 4: bubbles in the white gutter around a framed panel."""
    paper = np.ones((H, W), bool)
    paper[200:800, 50:550] = False                       # the drawn panel
    bubbles = Bubbles(open_mask=np.zeros((H, W), np.uint8), enclosed=[(100, 20, 300, 180), (300, 820, 500, 980)])
    assert drawn_panel_bounds(paper, bubbles, FULL) == (50, 200, 500, 600)


def test_only_bubbles_leaving_the_panel_spill_over():
    panel = (50, 200, 500, 600)
    assert _spills_over((100, 150, 300, 300), panel)      # crosses the top frame (example 2)
    assert not _spills_over((100, 250, 300, 400), panel)  # inside the panel (example 1): kept
    assert not _spills_over((100, 20, 300, 180), panel)   # entirely in the gutter: framing removes it


def test_coloured_lettering_is_not_a_speech_bubble():
    gray = np.full((100, 300), 250, np.uint8)
    sat = np.zeros((100, 300), np.uint8)
    cv2.putText(gray, "TEXT", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 2, 20, 6)
    ys, xs = np.nonzero(gray < 100)
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)  # OCR boxes hug the text
    assert _plain_lettering(gray, sat, box)
    sat[gray < 100] = 200                                  # red sound-effect lettering ("CLENCH")
    assert not _plain_lettering(gray, sat, box)


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


def _bgr(gray):
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def test_dark_void_around_a_panel_is_empty_space():
    """Tyrant "GLUG": black bubbles float in a black void above the drawn scene."""
    from bubble_crop import _void_mask
    gray = np.zeros((H, W), np.uint8)
    gray[600:, :] = 140                      # the drawn scene (mid-grey art)
    void = _void_mask(_bgr(gray))
    assert void[:600].all() and not void[600:].any()


def test_bubble_fragment_cut_by_the_page_split_is_marked():
    """Tyrant money panel: half a bubble at the top edge, outlined in ink, without readable text."""
    from bubble_crop import _components, _mark_edge_fragments
    gray = np.full((H, W), 120, np.uint8)
    cv2.ellipse(gray, (300, 0), (150, 60), 0, 0, 360, 255, -1)   # white bubble interior cut by the edge
    cv2.ellipse(gray, (300, 0), (150, 60), 0, 0, 360, 0, 4)      # its ink outline
    paper = gray >= 235
    mask = np.zeros((H, W), np.uint8)
    _mark_edge_fragments(gray, _components(paper), mask)
    assert mask[5, 300] == 1 and mask[500, 300] == 0


def test_bubble_box_covers_its_last_text_line():
    """Tyrant "GLUG": glowing letters split the dark interior, so the last line fell outside the box."""
    from bubble_crop import BUBBLE_PAD, _cover_text_lines
    bubble = (32, 432, 483, 681)
    bubbles = Bubbles(open_mask=np.zeros((H, W), np.uint8), enclosed=[bubble], dark=[bubble])
    _cover_text_lines(bubbles, [(175, 665, 335, 705), (130, 934, 246, 1031)], (H, W))
    assert bubbles.enclosed == bubbles.dark == [(32, 432, 483, 705 + BUBBLE_PAD)]  # SFX far below untouched


def test_line_near_the_edge_is_cut_and_its_bubble_is_looked_up_inward():
    """Tyrant: "...HERE YOU ARE" ended 7px above the bottom; "BE SERIOUS!" touched the top."""
    from bubble_crop import _cut_side, _inward
    assert _cut_side((113, 729, 363, 769), (776, 505)) == "bottom"
    assert _cut_side((348, 0, 570, 26), (343, 700)) == "top"
    assert _cut_side((100, 300, 300, 340), (776, 505)) is None
    assert _inward((348, 0, 570, 26), "top", (343, 700)) == (348, 26, 570, 52)
    assert _inward((113, 729, 363, 769), "bottom", (776, 505)) == (113, 689, 363, 729)


def test_caption_is_a_clean_sentence_in_small_letters():
    from bubble_crop import _is_caption
    assert _is_caption("ROXANNE'S HAND;", 0.87, (164, 265, 535, 316), 700)
    assert _is_caption("AS I HOLD", 0.9, (253, 227, 451, 263), 700)
    assert not _is_caption("WHOOSH", 0.95, (100, 100, 400, 160), 700)          # one sound-effect word
    assert not _is_caption("AS I HOLD", 0.45, (253, 227, 451, 263), 700)       # unsure read
    assert not _is_caption("BANG BANG", 0.9, (100, 100, 500, 220), 700)        # big lettering: SFX


def test_a_frame_never_slices_a_text_line():
    """Tyrant system-message panels were cut into a slice through their lines."""
    from bubble_crop import _cuts_through
    line = (100, 200, 400, 240)
    assert _cuts_through([0, 0, 250, 500], line)       # half the line kept
    assert _cuts_through([0, 220, 600, 300], line)     # top of the letters cut off
    assert not _cuts_through([0, 0, 600, 500], line)   # whole line inside
    assert not _cuts_through([0, 250, 600, 300], line)  # line left out entirely


def test_full_width_gutter_is_not_a_fragment():
    from bubble_crop import _components, _mark_edge_fragments
    gray = np.full((H, W), 120, np.uint8)
    gray[:80, :] = 255                       # white gutter strip across the whole top
    gray[80:84, :] = 0                       # panel frame line
    mask = np.zeros((H, W), np.uint8)
    _mark_edge_fragments(gray, _components(gray >= 235), mask)
    assert not mask.any()
