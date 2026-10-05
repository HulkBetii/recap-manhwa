"""
Speech-bubble-free framing for episode panels.

Why: text removal stays off on this channel (inpainting damages the artwork), so rendered videos showed
every speech bubble. This module only chooses a crop rectangle; pixels are never edited.

Rules (the user's hand crops: cat-anh.docx, 7 examples, plus 7 Tyrant panels judged on 2026-10-05):
- A small bubble inside the drawn scene stays: the panel is kept whole (example 1; Tyrant bubbles of
  2-7% of the panel were kept).
- A bubble that spills past the panel frame, opens into the white gutter or sits outside the panel is
  cut away: the frame is the drawn panel minus the strips those bubbles cover (examples 2, 4-7).
- The characters must stay whole; losing background is acceptable (the user kept as little as a third
  of a panel's area when bubbles covered two corners, example 6).
- Dark empty space is a gutter like white space (Tyrant "GLUG": black bubbles in a black void above the
  scene), and bubble fragments cut by the page split at the image edge are cut away (Tyrant money panel).
- A large dark bubble inside the scene (>= INSIDE_BUBBLE_MIN_SHARE of the panel, Tyrant's demon) is cut
  away only when every character detected by Grounding DINO stays whole; small or white inside bubbles
  always stay.
- Sound effects drawn on the art are part of the picture (example 3). Narration captions printed on the
  art without a bubble (Tyrant 50: "AS I HOLD ROXANNE'S HAND...") are cut away like large inside bubbles:
  only when every character stays whole.

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
# v5: dark void gutters, edge bubble fragments, large inside bubbles cut when characters stay whole.
# v6: closed bubbles cover every text line overlapping them.
# v7: dark bubble pieces at the image edge are cut, with a weaker OCR read for lines cut by the edge.
# v8: lines near the edge count as cut, their bubble is looked up inward; captions on the art are cut
#     when characters stay whole (leftovers found in the Tyrant 1-50 render).
BUBBLE_CROP_VERSION = 8

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
VOID_MIN_SHARE = 0.05          # an edge-touching ink-black area this large is empty space, not art
FRAGMENT_MIN_SHARE = 0.003      # white blob at the image edge: a bubble cut by the page split...
FRAGMENT_MAX_SHARE = 0.25
FRAGMENT_MAX_SPAN = 0.9         # ...unless it spans the whole image side (that is a gutter strip)
FRAGMENT_MIN_OUTLINE = 0.5      # share of its inner border drawn in dark outline
FRAGMENT_OCR_MIN_CONF = 0.2     # OCR confidence enough for a text line cut by the image edge
CUT_LINE_MARGIN = 20            # a text line this close to the image edge is cut by the page split
CAPTION_MIN_CONF = 0.6          # captions are cleanly lettered; sound effects rarely read this well
CAPTION_MIN_LETTERS = 8         # sentences, not a single sound-effect word...
CAPTION_MIN_WORDS = 2           # ...unless several words
CAPTION_MAX_LINE_HEIGHT = 0.08  # of the image width: caption lettering is small, sound effects are big
OUTLINE_MAX_GRAY = 90
INSIDE_BUBBLE_MIN_SHARE = 0.10  # inside bubbles below this share of the panel always stay (user: 2-7% kept)
PEOPLE_MODEL_ID = "IDEA-Research/grounding-dino-base"  # already cached locally (Safe Mode)
PEOPLE_PROMPT = "a person. a monster. an animal."
PEOPLE_MIN_SCORE = 0.3
PEOPLE_TEXT_MIN_SCORE = 0.25
AREA_LOSS_WEIGHT = 0.75         # area kept vs bubble left: the user accepts a bubble tail at the edge for a wider frame


@dataclass
class Bubbles:
    open_mask: np.ndarray                              # white bubble regions joined with the gutter
    enclosed: List[Box] = field(default_factory=list)  # closed bubbles, padded bounding boxes
    dark: List[Box] = field(default_factory=list)      # the closed bubbles that are dark (ink-black inside)
    captions: List[Box] = field(default_factory=list)  # narration lines printed on the art, no bubble
    lines: List[Box] = field(default_factory=list)     # every text line read

    def any(self) -> bool:
        return bool(self.enclosed) or bool(self.captions) or bool(self.open_mask.any())


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
    text_boxes: List[Box] = []
    for bbox, text, conf in results:
        xs, ys = [p[0] for p in bbox], [p[1] for p in bbox]
        box = (max(0, int(min(xs))), max(0, int(min(ys))), min(w, int(max(xs))), min(h, int(max(ys))))
        # Lines cut by the page split read poorly ("YOUR GOAL?!" at 0.27): weaker reads at the image
        # edge only count for bubble pieces there.
        cut_line = _cut_side(box, (h, w))
        if conf < (FRAGMENT_OCR_MIN_CONF if cut_line else OCR_MIN_CONF):
            continue
        weak = conf < OCR_MIN_CONF
        text_boxes.append(box)
        min_fill = BUBBLE_MIN_TEXT_RATIO * max(1, (box[2] - box[0]) * (box[3] - box[1]))
        in_bubble = False
        for index, (labels, edge_labels) in enumerate(layers):
            label = _region_around(labels, box)
            if cut_line and index == 1:
                # Glowing letters hide the dark interior around a cut line ("BE SERIOUS!"): look inward.
                label = _region_around(labels, _inward(box, cut_line, (h, w))) or label
            if label is None:
                continue
            region = labels == label
            area = int(np.count_nonzero(region))
            if area < min_fill:
                continue  # only the inside of letters: a sound effect drawn on the art
            in_bubble = True
            if label in edge_labels:
                if index == 0 and _plain_lettering(gray, saturation, box):  # white bubble open to the gutter
                    bubbles.open_mask[region] = 1
                    bubbles.open_mask[max(0, box[1] - BUBBLE_PAD):box[3] + BUBBLE_PAD,
                                      max(0, box[0] - BUBBLE_PAD):box[2] + BUBBLE_PAD] = 1
                elif index == 1 and _is_edge_fragment(region, area):
                    # Dark bubble cut by the page split (Tyrant "YOUR GOAL?!" over the skull).
                    bubbles.open_mask[region] = 1
                    bubbles.open_mask[max(0, box[1] - BUBBLE_PAD):box[3] + BUBBLE_PAD,
                                      max(0, box[0] - BUBBLE_PAD):box[2] + BUBBLE_PAD] = 1
                break
            if weak or area > BUBBLE_MAX_AREA * h * w:
                break  # a huge enclosed plain area is a background, not a bubble
            ry, rx = np.nonzero(region)
            closed = (
                max(0, int(rx.min()) - BUBBLE_PAD), max(0, int(ry.min()) - BUBBLE_PAD),
                min(w, int(rx.max()) + BUBBLE_PAD), min(h, int(ry.max()) + BUBBLE_PAD),
            )
            bubbles.enclosed.append(closed)
            if index == 1:
                bubbles.dark.append(closed)
            break
        if not in_bubble and _is_caption(text, conf, box, w):
            bubbles.captions.append(box)
    bubbles.lines = text_boxes
    _cover_text_lines(bubbles, text_boxes, (h, w))
    _mark_edge_fragments(gray, layers[0], bubbles.open_mask)
    return bubbles


def _cut_side(box: Box, shape: Tuple[int, int]) -> Optional[str]:
    """The image side a text line touches (within CUT_LINE_MARGIN), or None."""
    h, w = shape
    x1, y1, x2, y2 = box
    for side, gap in (("top", y1), ("bottom", h - y2), ("left", x1), ("right", w - x2)):
        if gap <= CUT_LINE_MARGIN:
            return side
    return None


def _inward(box: Box, side: str, shape: Tuple[int, int]) -> Box:
    """The strip just inside a cut text line, one line height deep, where its bubble's interior is."""
    h, w = shape
    x1, y1, x2, y2 = box
    lh, lw = y2 - y1, x2 - x1
    return {
        "top": (x1, y2, x2, min(h, y2 + lh)), "bottom": (x1, max(0, y1 - lh), x2, y1),
        "left": (x2, y1, min(w, x2 + lw), y2), "right": (max(0, x1 - lw), y1, x1, y2),
    }[side]


def _is_caption(text: str, conf: float, box: Box, width: int) -> bool:
    """A narration line printed on the art: a clean read of a sentence in small lettering."""
    words = [word for word in text.split() if any(ch.isalpha() for ch in word)]
    letters = sum(ch.isalpha() for ch in text)
    return (
        conf >= CAPTION_MIN_CONF
        and (len(words) >= CAPTION_MIN_WORDS or letters >= CAPTION_MIN_LETTERS)
        and box[3] - box[1] <= CAPTION_MAX_LINE_HEIGHT * width
    )


def _cover_text_lines(bubbles: Bubbles, text_boxes: List[Box], shape: Tuple[int, int]) -> None:
    """Grows each closed bubble over the text lines that overlap it. Glowing letters can split a dark
    bubble's interior, leaving its last line outside the box (Tyrant "GLUG": "DEMONS." stayed in the crop)."""
    h, w = shape

    def grown(bubble: Box) -> Box:
        x1, y1, x2, y2 = bubble
        for tx1, ty1, tx2, ty2 in text_boxes:
            if tx1 < x2 and tx2 > x1 and ty1 < y2 and ty2 > y1:
                x1, y1 = min(x1, max(0, tx1 - BUBBLE_PAD)), min(y1, max(0, ty1 - BUBBLE_PAD))
                x2, y2 = max(x2, min(w, tx2 + BUBBLE_PAD)), max(y2, min(h, ty2 + BUBBLE_PAD))
        return (x1, y1, x2, y2)

    bubbles.enclosed = [grown(b) for b in bubbles.enclosed]
    bubbles.dark = [grown(b) for b in bubbles.dark]


def _is_edge_fragment(region: np.ndarray, area: int) -> bool:
    """Size and span of a bubble piece at the image edge: not a speck, not a gutter strip along a whole side."""
    h, w = region.shape
    if not FRAGMENT_MIN_SHARE * h * w <= area <= FRAGMENT_MAX_SHARE * h * w:
        return False
    ys, xs = np.nonzero(region)
    return xs.max() - xs.min() < FRAGMENT_MAX_SPAN * w and ys.max() - ys.min() < FRAGMENT_MAX_SPAN * h


def _mark_edge_fragments(gray: np.ndarray, paper_layer: Tuple[np.ndarray, set], open_mask: np.ndarray) -> None:
    """Marks white bubble pieces cut by the page split: edge-touching paper blobs outlined in dark ink.
    They often carry no readable text, so OCR alone misses them."""
    labels, edge_labels = paper_layer
    kernel = np.ones((5, 5), np.uint8)
    for label in edge_labels:
        region = labels == label
        if not _is_edge_fragment(region, int(np.count_nonzero(region))):
            continue
        ring = cv2.dilate(region.astype(np.uint8), kernel).astype(bool) & ~region
        ring[0, :] = ring[-1, :] = ring[:, 0] = ring[:, -1] = False
        if ring.any() and float(np.mean(gray[ring] <= OUTLINE_MAX_GRAY)) >= FRAGMENT_MIN_OUTLINE:
            open_mask[region] = 1


def _void_mask(img_bgr: np.ndarray) -> np.ndarray:
    """Large ink-black areas touching the image edge: empty space around a panel, like a white gutter."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    saturation = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)[:, :, 1]
    labels, edge_labels = _components((gray <= INK_MAX_GRAY) & (saturation <= PAPER_MAX_SATURATION))
    void = np.zeros(gray.shape, bool)
    for label in edge_labels:
        region = labels == label
        if np.count_nonzero(region) >= VOID_MIN_SHARE * gray.size:
            void |= region
    return void


def drawn_panel_bounds(paper: np.ndarray, bubbles: Bubbles, bounds: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    """Bounding box (x, y, w, h) of the drawn panel inside `bounds`: everything that is neither empty space
    (`paper`: white gutter and dark void) nor a speech bubble. Falls back to `bounds` when no clear panel."""
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


_people_model = None
_people_lock = None


def detect_people(img_bgr: np.ndarray) -> List[Box]:
    """Characters (people, monsters, animals) via the locally cached Grounding DINO; [] when unavailable."""
    global _people_model, _people_lock
    import threading
    if _people_lock is None:
        _people_lock = threading.Lock()
    with _people_lock:
        try:
            import torch
            from PIL import Image
            from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
            if _people_model is None:
                device = "cuda" if torch.cuda.is_available() else "cpu"
                processor = AutoProcessor.from_pretrained(PEOPLE_MODEL_ID, local_files_only=True)
                model = AutoModelForZeroShotObjectDetection.from_pretrained(PEOPLE_MODEL_ID, local_files_only=True)
                _people_model = (processor, model.to(device).eval(), device)
            processor, model, device = _people_model
            pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
            inputs = processor(images=pil, text=PEOPLE_PROMPT, return_tensors="pt").to(device)
            with torch.no_grad():
                outputs = model(**inputs)
            result = processor.post_process_grounded_object_detection(
                outputs, inputs.input_ids, threshold=PEOPLE_MIN_SCORE, text_threshold=PEOPLE_TEXT_MIN_SCORE,
                target_sizes=[pil.size[::-1]],
            )[0]
            return [tuple(int(v) for v in box) for box in result["boxes"].tolist()]
        except Exception as err:
            logger.warning("Character detection unavailable (%s); large inside bubbles are kept", err)
            _people_model = False if _people_model is None else _people_model
            return []


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
    keep_whole: Optional[List[Box]] = None,
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
        for x1, y1, x2, y2 in list(faces) + list(keep_whole or [])
        if x2 > bx and y2 > by and x1 < bx + bw and y1 < by + bh
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


def _cuts_through(bounds: List[int], line: Box) -> bool:
    """True when the crop (x, y, w, h) keeps part of a text line but not all of it."""
    x, y, w, h = bounds
    ix = min(x + w, line[2]) - max(x, line[0])
    iy = min(y + h, line[3]) - max(y, line[1])
    if ix <= 0 or iy <= 0:
        return False
    return ix < line[2] - line[0] or iy < line[3] - line[1]


def _contains_center(outer: Box, inner: Box) -> bool:
    cx, cy = (inner[0] + inner[2]) / 2.0, (inner[1] + inner[3]) / 2.0
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def bubble_free_crop(img_bgr: np.ndarray, bounds: Tuple[int, int, int, int]) -> Optional[dict]:
    """Crop of the panel `bounds` without the bubbles the user cuts away, or None to keep the panel whole."""
    bubbles = detect_bubbles(img_bgr)
    if not bubbles.any():
        return None
    panel = drawn_panel_bounds(_paper_mask(img_bgr) | _void_mask(img_bgr), bubbles, bounds)
    px, py, pw, ph = panel
    spill = bubbles.open_mask.copy()
    inside_large = []
    for box in bubbles.enclosed:
        x1, y1, x2, y2 = box
        if _spills_over(box, panel):
            spill[y1:y2, x1:x2] = 1
        elif box in bubbles.dark and (x2 - x1) * (y2 - y1) >= INSIDE_BUBBLE_MIN_SHARE * pw * ph:
            # White inside bubbles always stay (the user kept even a 19% one, example 1), and text printed
            # on white objects (banknotes, signs) looks like one; only large dark bubbles are cut.
            inside_large.append(box)
    inside_large += [
        (max(0, x1 - BUBBLE_PAD), max(0, y1 - BUBBLE_PAD), x2 + BUBBLE_PAD, y2 + BUBBLE_PAD)
        for x1, y1, x2, y2 in bubbles.captions
    ]
    faces = detect_face_boxes(img_bgr)

    if inside_large:
        people = detect_people(img_bgr)
        obstacles = spill.copy()
        for x1, y1, x2, y2 in inside_large:
            obstacles[y1:y2, x1:x2] = 1
        # A face outside every detected character is a false hit (a cloud in Tyrant 50's sky blocked the crop).
        people_faces = [f for f in faces if any(_contains_center(p, f) for p in people)] if people else faces
        crop = choose_crop(img_bgr.shape[:2], panel, obstacles, people_faces, _detail_map(img_bgr, obstacles),
                           keep_whole=people)
        # A frame through a line of text is worse than the whole panel (system-message panels were sliced).
        if crop and not any(_cuts_through(crop["bounds"], line) for line in bubbles.lines):
            return crop

    if not spill[py:py + ph, px:px + pw].any():
        # Bubbles only outside the drawn panel (gutter or void): frame the panel itself (example 4).
        bx, by, bw, bh = [int(v) for v in bounds]
        spilled = spill.any() or any(_spills_over(b, (bx, by, bw, bh)) for b in bubbles.enclosed)
        if spilled and pw * ph <= (1.0 - MIN_TRIM_GAIN) * bw * bh:
            return {"bounds": [px, py, pw, ph], "bubble_left": 0.0, "kept_area": round(pw * ph / float(bw * bh), 3)}
        return None
    return choose_crop(img_bgr.shape[:2], panel, spill, faces, _detail_map(img_bgr, spill))
