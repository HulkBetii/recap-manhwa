"""
Speech-bubble-free framing for episode panels.

Why: text removal stays off on this channel (inpainting damages the artwork), so rendered videos showed
every speech bubble. This module only chooses a crop rectangle; pixels are never edited.

Rules (the user's hand crops, cat-anh.docx, 7 examples):
- A bubble entirely inside the drawn panel stays: the panel is kept whole (example 1; confirmed by
  the user 2026-10-05 after seeing what cropping those panels would give).
- A bubble that spills past the panel frame, opens into the white gutter or sits outside the panel is
  cut away: the frame is the drawn panel minus the strips those bubbles cover (examples 2, 4-7).
- The characters must stay whole; losing background is acceptable (the user kept as little as a third
  of a panel's area when bubbles covered two corners, example 6).
- Sound effects and other text drawn on the art are part of the picture (example 3).

Detection: EasyOCR finds text lines; the bubble is the plain region behind the text on a binary
"paper white" (or "ink black", for dark bubbles) mask. Binary masks replace a tolerance flood fill,
which crept along smooth shading and light bubble outlines (it covered 87-97% of art panels in tests).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

Box = Tuple[int, int, int, int]  # x1, y1, x2, y2

# Bump when detection or crop rules change: cached crops and rendered episodes are then recomputed.
# v2: dark bubbles. v3: paper/ink regions. v4: only bubbles that leave the drawn panel are cut away,
#     the frame is searched inside the drawn panel; open bubbles need uncoloured lettering (user's hand
#     crops, cat-anh.docx).
BUBBLE_CROP_VERSION = 4

OCR_MIN_CONF = 0.3
BUBBLE_MAX_AREA = 0.35          # an enclosed plain area larger than this share of the image is background
BUBBLE_MIN_TEXT_RATIO = 1.3     # a bubble is larger than its text; the inside of SFX letters is not
BUBBLE_PAD = 10
PAPER_MIN_GRAY = 235            # gutters and bubble interiors
PAPER_MAX_SATURATION = 30
INK_MAX_GRAY = 35               # dark bubble interiors
# Lettering inside a speech bubble is black/grey; coloured lettering on a bright wall is a sound effect
# (example 4's red "CLENCH" joined the gutter through the wall and was taken for an open bubble).
LETTERING_DARK_SHARE = 0.15      # darkest share of the text box taken as its letters
LETTERING_MAX_SATURATION = 70
OVERFLOW_MARGIN = 6             # a bubble reaching this far past the drawn panel spills over its frame
ART_CLOSE_KERNEL = 15           # merges the drawn panel's pieces before taking its bounding box
MIN_ART_SHARE = 0.2             # a drawn region smaller than this share of the panel bounds is not the panel
MIN_TRIM_GAIN = 0.03            # cropping to the drawn panel alone must remove at least this share of area
FACE_PAD = 0.35                 # keep head and shoulders around each detected face
MIN_KEEP_AREA = 0.3             # of the drawn panel
MIN_KEEP_DETAIL = 0.55          # the user's crops kept 60-96% of the panel's edge detail
MIN_BUBBLE_REMOVED = 0.6        # a crop must remove at least this share of the spilling bubbles' area
TRIM_STEP = 0.05                # trim granularity per side (share of the drawn panel)
MAX_TRIM = 0.6
MIN_CROP_HEIGHT = 0.25
ASPECT_RANGE = (0.45, 2.2)
AREA_LOSS_WEIGHT = 0.75         # area kept vs bubble left: the user accepts a bubble tail at the edge for a wider frame


@dataclass
class Bubbles:
    open_mask: np.ndarray                              # white bubble regions joined with the gutter
    enclosed: List[Box] = field(default_factory=list)  # closed bubbles, padded bounding boxes

    def any(self) -> bool:
        return bool(self.enclosed) or bool(self.open_mask.any())


def _components(binary: np.ndarray) -> Tuple[np.ndarray, set]:
    _, labels = cv2.connectedComponents(binary.astype(np.uint8), connectivity=4)
    edge = np.concatenate([labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]])
    return labels, set(np.unique(edge).tolist()) - {0}


def _region_around(labels: np.ndarray, box: Box) -> Optional[int]:
    """The component that fills most of the text box background (the bubble interior), if any."""
    x1, y1, x2, y2 = box
    around = labels[y1:y2, x1:x2]
    values, counts = np.unique(around[around > 0], return_counts=True)
    return int(values[np.argmax(counts)]) if values.size else None


def _plain_lettering(gray: np.ndarray, saturation: np.ndarray, box: Box) -> bool:
    """True when the text's letters (the darkest pixels of its box) are uncoloured, as in speech bubbles."""
    x1, y1, x2, y2 = box
    g, s = gray[y1:y2, x1:x2].ravel(), saturation[y1:y2, x1:x2].ravel()
    if g.size == 0:
        return False
    letters = g <= np.quantile(g, LETTERING_DARK_SHARE)
    return float(np.median(s[letters])) <= LETTERING_MAX_SATURATION


def _paper_mask(img_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    saturation = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)[:, :, 1]
    return (gray >= PAPER_MIN_GRAY) & (saturation <= PAPER_MAX_SATURATION)


def detect_bubbles(img_bgr: np.ndarray) -> Bubbles:
    """Speech bubbles behind detected text: closed ones as boxes, white ones open to the gutter as a mask."""
    from tools.text_remover.comic_text_remover import get_easyocr_reader, ocr_lock

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    saturation = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)[:, :, 1]
    h, w = gray.shape
    plain = saturation <= PAPER_MAX_SATURATION
    layers = [
        _components((gray >= PAPER_MIN_GRAY) & plain),   # white bubbles and gutters
        _components((gray <= INK_MAX_GRAY) & plain),     # dark bubbles (Tyrant's demon speech)
    ]
    reader = get_easyocr_reader(["en"])
    with ocr_lock:
        results = reader.readtext(img_bgr)
    bubbles = Bubbles(open_mask=np.zeros((h, w), np.uint8))
    for bbox, _text, conf in results:
        if conf < OCR_MIN_CONF:
            continue
        xs, ys = [p[0] for p in bbox], [p[1] for p in bbox]
        box = (max(0, int(min(xs))), max(0, int(min(ys))), min(w, int(max(xs))), min(h, int(max(ys))))
        min_fill = BUBBLE_MIN_TEXT_RATIO * max(1, (box[2] - box[0]) * (box[3] - box[1]))
        for index, (labels, edge_labels) in enumerate(layers):
            label = _region_around(labels, box)
            if label is None:
                continue
            region = labels == label
            area = int(np.count_nonzero(region))
            if area < min_fill:
                continue  # only the inside of letters: a sound effect drawn on the art
            if label in edge_labels:
                if index == 0 and _plain_lettering(gray, saturation, box):  # white bubble open to the gutter
                    bubbles.open_mask[region] = 1
                    bubbles.open_mask[max(0, box[1] - BUBBLE_PAD):box[3] + BUBBLE_PAD,
                                      max(0, box[0] - BUBBLE_PAD):box[2] + BUBBLE_PAD] = 1
                break
            if area > BUBBLE_MAX_AREA * h * w:
                break  # a huge enclosed plain area is a background, not a bubble
            ry, rx = np.nonzero(region)
            bubbles.enclosed.append((
                max(0, int(rx.min()) - BUBBLE_PAD), max(0, int(ry.min()) - BUBBLE_PAD),
                min(w, int(rx.max()) + BUBBLE_PAD), min(h, int(ry.max()) + BUBBLE_PAD),
            ))
            break
    return bubbles


def drawn_panel_bounds(paper: np.ndarray, bubbles: Bubbles, bounds: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    """Bounding box (x, y, w, h) of the drawn panel inside `bounds`: everything that is neither white space
    nor a speech bubble. Falls back to `bounds` when no clear panel is found."""
    bx, by, bw, bh = [int(v) for v in bounds]
    art = ~paper[by:by + bh, bx:bx + bw]
    art &= bubbles.open_mask[by:by + bh, bx:bx + bw] == 0
    for x1, y1, x2, y2 in bubbles.enclosed:
        art[max(0, y1 - by):max(0, y2 - by), max(0, x1 - bx):max(0, x2 - bx)] = False
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (ART_CLOSE_KERNEL, ART_CLOSE_KERNEL))
    art = cv2.morphologyEx(art.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(art, connectivity=8)
    if count <= 1:
        return bx, by, bw, bh
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = [int(v) for v in stats[largest, :4]]
    if w * h < MIN_ART_SHARE * bw * bh:
        return bx, by, bw, bh
    return bx + x, by + y, w, h


def _spills_over(box: Box, panel: Tuple[int, int, int, int]) -> bool:
    px, py, pw, ph = panel
    x1, y1, x2, y2 = box
    overlaps = x2 > px and y2 > py and x1 < px + pw and y1 < py + ph
    outside = (x1 < px - OVERFLOW_MARGIN or y1 < py - OVERFLOW_MARGIN
               or x2 > px + pw + OVERFLOW_MARGIN or y2 > py + ph + OVERFLOW_MARGIN)
    return overlaps and outside


def detect_face_boxes(img_bgr: np.ndarray) -> List[Box]:
    from visual_scorer import VisualSemanticScorer

    h, w = img_bgr.shape[:2]
    boxes: List[Box] = []
    for face in VisualSemanticScorer.detect_faces(img_bgr):
        x, y, fw, fh = [int(v) for v in face[:4]]
        px, py = int(fw * FACE_PAD), int(fh * FACE_PAD)
        boxes.append((max(0, x - px), max(0, y - py), min(w, x + fw + px), min(h, y + fh + py)))
    return boxes


def _detail_map(img_bgr: np.ndarray, bubble_mask: np.ndarray) -> np.ndarray:
    """Edge density as a proxy for drawn content (characters, objects, action lines); bubbles count as none."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mag = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    mag = cv2.GaussianBlur(mag, (0, 0), 6)
    mag[bubble_mask > 0] = 0
    return mag


def choose_crop(
    shape: Tuple[int, int],
    bounds: Tuple[int, int, int, int],
    obstacle_mask: np.ndarray,
    faces: List[Box],
    detail: np.ndarray,
) -> Optional[dict]:
    """Best crop inside `bounds` (x, y, w, h): least obstacle area left, faces whole, >= MIN_KEEP_AREA of the
    bounds and >= MIN_KEEP_DETAIL of their detail. None when no crop removes enough obstacle area."""
    img_h, img_w = shape
    bx, by, bw, bh = [int(v) for v in bounds]
    bx, by = max(0, bx), max(0, by)
    bw, bh = min(bw, img_w - bx), min(bh, img_h - by)
    if bw < 10 or bh < 10:
        return None
    bubble_ii = cv2.integral((obstacle_mask[by:by + bh, bx:bx + bw] > 0).astype(np.float64))
    detail_ii = cv2.integral(detail[by:by + bh, bx:bx + bw].astype(np.float64))

    def total(ii, x1, y1, x2, y2):
        return ii[y2, x2] - ii[y1, x2] - ii[y2, x1] + ii[y1, x1]

    bubble_total = total(bubble_ii, 0, 0, bw, bh)
    detail_total = total(detail_ii, 0, 0, bw, bh)
    if bubble_total <= 0 or detail_total <= 0:
        return None
    local_faces = [
        (max(0, x1 - bx), max(0, y1 - by), min(bw, x2 - bx), min(bh, y2 - by))
        for x1, y1, x2, y2 in faces if x2 > bx and y2 > by and x1 < bx + bw and y1 < by + bh
    ]

    trims = np.arange(0.0, MAX_TRIM + 1e-9, TRIM_STEP)
    best, best_score = None, None
    for top in trims:
        for bottom in trims:
            y1, y2 = int(top * bh), int(bh - bottom * bh)
            if y2 - y1 < MIN_CROP_HEIGHT * bh:
                continue
            for left in trims:
                for right in trims:
                    x1, x2 = int(left * bw), int(bw - right * bw)
                    if x2 - x1 < 10:
                        continue
                    kept_area = (x2 - x1) * (y2 - y1) / float(bw * bh)
                    if kept_area < MIN_KEEP_AREA or not ASPECT_RANGE[0] <= (x2 - x1) / float(y2 - y1) <= ASPECT_RANGE[1]:
                        continue
                    if any(fx1 < x1 or fy1 < y1 or fx2 > x2 or fy2 > y2 for fx1, fy1, fx2, fy2 in local_faces):
                        continue
                    if total(detail_ii, x1, y1, x2, y2) / detail_total < MIN_KEEP_DETAIL:
                        continue
                    bubble_left = total(bubble_ii, x1, y1, x2, y2) / bubble_total
                    score = bubble_left + AREA_LOSS_WEIGHT * (1.0 - kept_area)
                    if best_score is None or score < best_score:
                        best, best_score = (x1, y1, x2, y2, bubble_left, kept_area), score
    if best is None or 1.0 - best[4] < MIN_BUBBLE_REMOVED:
        return None
    x1, y1, x2, y2, bubble_left, kept_area = best
    return {
        "bounds": [bx + x1, by + y1, x2 - x1, y2 - y1],
        "bubble_left": round(float(bubble_left), 3),
        "kept_area": round(float(kept_area), 3),
    }


def bubble_free_crop(img_bgr: np.ndarray, bounds: Tuple[int, int, int, int]) -> Optional[dict]:
    """Crop of the panel `bounds` without the speech bubbles that leave the drawn panel, or None to keep
    the panel whole (no such bubble, or no crop keeps the characters)."""
    bubbles = detect_bubbles(img_bgr)
    if not bubbles.any():
        return None
    panel = drawn_panel_bounds(_paper_mask(img_bgr), bubbles, bounds)
    obstacles = bubbles.open_mask.copy()
    for box in bubbles.enclosed:
        if _spills_over(box, panel):
            x1, y1, x2, y2 = box
            obstacles[y1:y2, x1:x2] = 1
    px, py, pw, ph = panel
    inside = obstacles[py:py + ph, px:px + pw]
    if not inside.any():
        # Bubbles only outside the drawn panel (in the gutter): frame the panel itself (example 4).
        bx, by, bw, bh = [int(v) for v in bounds]
        spilled = obstacles.any() or any(_spills_over(b, (bx, by, bw, bh)) for b in bubbles.enclosed)
        if spilled and pw * ph <= (1.0 - MIN_TRIM_GAIN) * bw * bh:
            return {"bounds": [px, py, pw, ph], "bubble_left": 0.0, "kept_area": round(pw * ph / float(bw * bh), 3)}
        return None
    return choose_crop(img_bgr.shape[:2], panel, obstacles, detect_face_boxes(img_bgr), _detail_map(img_bgr, obstacles))
