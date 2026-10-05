"""
Speech-bubble-free framing for episode panels.

Why: text removal stays off on this channel (inpainting damages the artwork), so rendered videos showed
every speech bubble. Bubbles usually sit at a panel's edges, so many panels can be framed without them
while keeping the faces and most of the drawn detail. This module only chooses a crop rectangle; the
pixels are never edited. A panel whose bubble cannot be cut away safely is kept whole (user decision
2026-10-05: content first).

Detection: EasyOCR finds text, then a flood fill from the text grows the bubble interior. Text whose
fill fails or stays inside the letters (sound effects, signs, dark system windows) is part of the art
and is never cropped.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

Box = Tuple[int, int, int, int]  # x1, y1, x2, y2

# Bump when detection or crop rules change: cached crops and rendered episodes are then recomputed.
# v2: dark bubbles (black fill, white text).
BUBBLE_CROP_VERSION = 2

OCR_MIN_CONF = 0.3
BUBBLE_MAX_AREA = 0.35          # a fill larger than this share of the image spilled into the background
BUBBLE_MIN_TEXT_RATIO = 1.3     # a bubble encloses its text; a fill inside white SFX letters is smaller
BUBBLE_PAD = 10
FACE_PAD = 0.35                 # keep head and shoulders around each detected face
MIN_KEEP_AREA = 0.5             # never show less than half of the panel
MIN_KEEP_DETAIL = 0.85          # keep at least this share of the drawn detail outside the bubbles
MIN_BUBBLE_REMOVED = 0.6        # crop only when it removes at least this share of the bubble area
TRIM_STEP = 0.05                # trim granularity per side (share of the panel)
MAX_TRIM = 0.45
MIN_CROP_HEIGHT = 0.3
ASPECT_RANGE = (0.45, 2.2)
AREA_LOSS_WEIGHT = 0.25         # tie-breaker: among equally bubble-free crops keep more of the panel


def detect_speech_bubbles(img_bgr: np.ndarray) -> List[Box]:
    """Bounding boxes of speech bubbles (enclosed bright regions around detected text)."""
    from tools.text_remover.comic_text_remover import get_easyocr_reader, ocr_lock, segment_bubble_floodfill

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    inverted = 255 - gray  # dark bubbles (black fill, white text: Tyrant's demon speech) fill like white ones
    h, w = gray.shape
    reader = get_easyocr_reader(["en"])
    with ocr_lock:
        results = reader.readtext(img_bgr)
    boxes: List[Box] = []
    for bbox, _text, conf in results:
        if conf < OCR_MIN_CONF:
            continue
        xs, ys = [p[0] for p in bbox], [p[1] for p in bbox]
        x1, y1, x2, y2 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
        seed = ((x1 + x2) // 2, (y1 + y2) // 2)
        min_fill = BUBBLE_MIN_TEXT_RATIO * max(1, (x2 - x1) * (y2 - y1))
        fill = None
        for channel in (gray, inverted):
            candidate = segment_bubble_floodfill(channel, seed, max_area_ratio=BUBBLE_MAX_AREA)
            if candidate is not None and np.count_nonzero(candidate) >= min_fill:
                fill = candidate
                break
        if fill is None:
            continue  # text on the art itself: sound effect, sign or narration over the picture
        fy, fx = np.nonzero(fill)
        boxes.append((
            max(0, min(int(fx.min()), x1) - BUBBLE_PAD), max(0, min(int(fy.min()), y1) - BUBBLE_PAD),
            min(w, max(int(fx.max()), x2) + BUBBLE_PAD), min(h, max(int(fy.max()), y2) + BUBBLE_PAD),
        ))
    return boxes


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
    bubbles: List[Box],
    faces: List[Box],
    detail: np.ndarray,
) -> Optional[dict]:
    """Best crop inside `bounds` (x, y, w, h): least bubble area left, faces whole, >= MIN_KEEP_AREA of the
    panel and >= MIN_KEEP_DETAIL of its detail. None when no crop removes enough bubble area."""
    img_h, img_w = shape
    bx, by, bw, bh = [int(v) for v in bounds]
    bx, by = max(0, bx), max(0, by)
    bw, bh = min(bw, img_w - bx), min(bh, img_h - by)
    if bw < 10 or bh < 10:
        return None
    bubble_mask = np.zeros((bh, bw), np.float64)
    for x1, y1, x2, y2 in bubbles:
        bubble_mask[max(0, y1 - by):max(0, y2 - by), max(0, x1 - bx):max(0, x2 - bx)] = 1.0
    bubble_ii = cv2.integral(bubble_mask)
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
    """Crop of the panel `bounds` without its speech bubbles, or None to keep the panel whole."""
    bubbles = detect_speech_bubbles(img_bgr)
    if not bubbles:
        return None
    mask = np.zeros(img_bgr.shape[:2], np.uint8)
    for x1, y1, x2, y2 in bubbles:
        mask[y1:y2, x1:x2] = 1
    return choose_crop(img_bgr.shape[:2], bounds, bubbles, detect_face_boxes(img_bgr), _detail_map(img_bgr, mask))
