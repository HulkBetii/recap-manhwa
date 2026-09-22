# -*- coding: utf-8 -*-
"""
Speech Bubble Analyzer: Spatial Relationship and Classification for Comic/Manhwa Canvases.

Implements strict Speech Bubble Rules:
- CASE A: Speech Bubble ABOVE the visual composition -> Separated with a HARD boundary cut.
- CASE B: Speech Bubble BELOW the visual composition -> Separated with a HARD boundary cut.
- CASE C: Speech Bubble INSIDE the visual composition -> IGNORED for page splitting.
          Treated as an integral part of the visual composition.

Uses spatial relationships, surrounding content activity, and character bounding boxes
rather than arbitrary absolute thresholds.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional
import numpy as np
import cv2

from renderer.visual_boundary_scanner import BoundaryCandidate


class BubbleRole:
    EDGE_TOP = "EDGE_TOP"         # Case A: Above visual artwork
    EDGE_BOTTOM = "EDGE_BOTTOM"   # Case B: Below visual artwork
    INTERNAL = "INTERNAL"         # Case C: Embedded inside visual composition
    STANDALONE = "STANDALONE"     # Floating text in blank gutter


@dataclass
class AnalyzedBubble:
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2
    role: str                        # BubbleRole
    confidence: float = 0.9
    visual_above_score: float = 0.0
    visual_below_score: float = 0.0
    character_overlap: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


class SpeechBubbleAnalyzer:
    """
    Analyzes speech bubbles and classifies them as EDGE (above/below visual) vs INTERNAL (inside visual).
    Generates hard boundary cuts for edge bubbles and suppresses cuts through internal bubbles.
    """

    def __init__(
        self,
        context_window_h: int = 120,
        activity_threshold: float = 0.025,
        clearance_padding: int = 8
    ):
        self.context_window_h = context_window_h
        self.activity_threshold = activity_threshold
        self.clearance_padding = clearance_padding

    @staticmethod
    def detect_text_first_bubbles_cv(
        canvas_bgr: np.ndarray,
        bg_val: int = 255
    ) -> List[Tuple[int, int, int, int]]:
        """
        Primary Text-First Speech Bubble & Box Detector:
        1. Identifies text character regions using local contrast + MSER.
        2. Groups characters into words and paragraph blocks.
        3. Dynamically expands bounding boxes to encapsulate enclosing speech bubbles/boxes.
        4. Snaps to outer rectangular container contours if present.
        """
        h, w = canvas_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return []

        gray = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2GRAY) if canvas_bgr.ndim == 3 else canvas_bgr
        scale = min(1.0, 800.0 / float(w))
        calc_w = max(10, int(round(w * scale)))
        calc_h = max(10, int(round(h * scale)))
        small_gray = cv2.resize(gray, (calc_w, calc_h), interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_NEAREST)
        inv_scale = 1.0 / scale

        letter_mask = np.zeros((calc_h, calc_w), dtype=np.uint8)

        # 1. Local contrast character extraction
        local_mean = cv2.blur(small_gray, (max(5, int(15 * scale)), max(5, int(15 * scale))))
        is_dark = (small_gray < 85) & (local_mean > 125)
        is_light = (small_gray > 175) & (local_mean < 115)
        contrast_mask = (is_dark | is_light).astype(np.uint8)

        n_cc, labels, stats, _ = cv2.connectedComponentsWithStats(contrast_mask)
        for i in range(1, n_cc):
            area = stats[i, cv2.CC_STAT_AREA]
            cw = stats[i, cv2.CC_STAT_WIDTH]
            ch = stats[i, cv2.CC_STAT_HEIGHT]
            if int(4 * scale * scale) <= area <= int(800 * scale * scale) and 2 <= cw <= int(60 * scale) and int(4 * scale) <= ch <= int(60 * scale):
                letter_mask[labels == i] = 255

        # 2. MSER text region detector for stylized fonts & non-standard backgrounds
        try:
            mser = cv2.MSER_create(
                delta=5,
                min_area=max(8, int(15 * scale * scale)),
                max_area=max(100, int(1200 * scale * scale)),
                max_variation=0.4
            )
            _, mser_bboxes = mser.detectRegions(small_gray)
            for mb in mser_bboxes:
                mx, my, mw, mh = mb
                if int(4 * scale) <= mh <= int(65 * scale) and 0.15 <= (mw / float(max(1, mh))) <= 4.5:
                    letter_mask[my:my+mh, mx:mx+mw] = 255
        except Exception:
            pass

        # 3. Horizontal line grouping + Vertical paragraph grouping
        k_word = cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, int(18 * scale)), max(2, int(4 * scale))))
        word_mask = cv2.morphologyEx(letter_mask, cv2.MORPH_DILATE, k_word)

        k_para = cv2.getStructuringElement(cv2.MORPH_RECT, (max(4, int(12 * scale)), max(4, int(10 * scale))))
        para_mask = cv2.morphologyEx(word_mask, cv2.MORPH_DILATE, k_para)

        cnts, _ = cv2.findContours(para_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        raw_boxes = []

        for cnt in cnts:
            x, y, bw, bh = cv2.boundingRect(cnt)
            if bw >= int(15 * scale) and bh >= int(8 * scale):
                sub_let = letter_mask[y:y+bh, x:x+bw]
                n_l, _, _, _ = cv2.connectedComponentsWithStats(sub_let)
                if (n_l - 1) >= 2 or (bw >= int(45 * scale) and bh >= int(15 * scale)):
                    pad_x = max(int(6 * scale), int(bw * 0.08))
                    pad_y = max(int(5 * scale), int(bh * 0.10))
                    bx1 = max(0, int((x - pad_x) * inv_scale))
                    by1 = max(0, int((y - pad_y) * inv_scale))
                    bx2 = min(w, int((x + bw + pad_x) * inv_scale))
                    by2 = min(h, int((y + bh + pad_y) * inv_scale))
                    raw_boxes.append((bx1, by1, bx2, by2))

        # 4. Rectangular container outline snapping
        edges = cv2.Canny(gray, 35, 110)
        cnts_e, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in cnts_e:
            x, y, bw, bh = cv2.boundingRect(cnt)
            if 35 < bw < w * 0.96 and 18 < bh < h * 0.50:
                peri = cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
                if len(approx) in [4, 5, 6, 8]:
                    sub_small_let = letter_mask[int(y*scale):int((y+bh)*scale), int(x*scale):int((x+bw)*scale)]
                    if sub_small_let.size > 0 and np.count_nonzero(sub_small_let) > 10:
                        raw_boxes.append((x, y, x + bw, y + bh))

        # 5. IoU-based merge
        def box_iou(b1, b2):
            ix1, iy1, ix2, iy2 = max(b1[0], b2[0]), max(b1[1], b2[1]), min(b1[2], b2[2]), min(b1[3], b2[3])
            iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
            inter = iw * ih
            a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
            a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
            union = a1 + a2 - inter
            return inter / max(1.0, float(union)), inter / max(1.0, float(a1)), inter / max(1.0, float(a2))

        changed = True
        boxes = raw_boxes[:]
        while changed:
            changed = False
            new_boxes = []
            skip = set()
            for i in range(len(boxes)):
                if i in skip:
                    continue
                b1 = boxes[i]
                for j in range(i + 1, len(boxes)):
                    if j in skip:
                        continue
                    b2 = boxes[j]
                    iou, io_a1, io_a2 = box_iou(b1, b2)
                    if iou > 0.25 or io_a1 > 0.60 or io_a2 > 0.60:
                        b1 = (min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3]))
                        skip.add(j)
                        changed = True
                new_boxes.append(b1)
            boxes = new_boxes

        return sorted(boxes, key=lambda b: (b[1], b[0]))

    @staticmethod
    def detect_text_boxes_cv(
        canvas_bgr: np.ndarray,
        bg_val: int = 255
    ) -> List[Tuple[int, int, int, int]]:
        """
        Detector for rectangular text boxes, narration blocks, and dialogue containers.
        """
        return SpeechBubbleAnalyzer.detect_text_first_bubbles_cv(canvas_bgr, bg_val=bg_val)

    @staticmethod
    def detect_speech_bubbles_cv(
        canvas_bgr: np.ndarray,
        bg_val: int = 255
    ) -> List[Tuple[int, int, int, int]]:
        """
        Fast morphological text clustering & contour detector for speech bubbles
        and dialogue boxes on white, dark, or colored comic backgrounds.
        Returns list of (x1, y1, x2, y2).
        """
        h, w = canvas_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return []

        scale = min(1.0, 500.0 / float(w))
        calc_w = max(10, int(round(w * scale)))
        calc_h = max(10, int(round(h * scale)))

        small_bgr = cv2.resize(canvas_bgr, (calc_w, calc_h), interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_NEAREST)
        gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2HSV)
        inv_scale = 1.0 / scale
        raw_bubbles: List[Tuple[int, int, int, int]] = []

        # 1. Morphological Text Clustering (detects text/dialogue regions)
        local_mean = cv2.blur(gray, (max(5, int(25 * scale)), max(5, int(25 * scale))))
        is_dark_text = (gray < 85) & (local_mean > 135)
        is_light_text = (gray > 170) & (local_mean < 110)
        is_text_cand = is_dark_text | is_light_text

        if calc_h > 30:
            border_y = max(2, int(4 * scale))
            is_text_cand[:border_y, :] = False
            is_text_cand[-border_y:, :] = False

        text_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(18 * scale)), max(2, int(5 * scale))))
        text_closed = cv2.morphologyEx(is_text_cand.astype(np.uint8), cv2.MORPH_CLOSE, text_kernel)
        text_dilated = cv2.dilate(text_closed, cv2.getStructuringElement(cv2.MORPH_RECT, (max(2, int(12 * scale)), max(2, int(10 * scale)))), iterations=1)
        contours_text, _ = cv2.findContours(text_dilated, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours_text:
            x, y, bw, bh = cv2.boundingRect(cnt)
            if bw > int(25 * scale) and int(10 * scale) < bh < int(650 * scale) and bw < calc_w * 0.90:
                pad_y = max(1, int(30 * scale))
                pad_x = max(1, int(15 * scale))
                y1 = max(0, y - pad_y)
                y2 = min(calc_h, y + bh + pad_y)
                sub_gray = gray[y1:y2, max(0, x - pad_x):min(calc_w, x + bw + pad_x)]
                sub_hsv = hsv[y1:y2, max(0, x - pad_x):min(calc_w, x + bw + pad_x)]
                white_ratio = np.mean(sub_gray > 175)
                sat_mean = np.mean(sub_hsv[:, :, 1])

                is_valid = False
                if white_ratio > 0.30 and sat_mean < 100.0:
                    sub_dark = (gray[y:y + bh, x:x + bw] < 85).astype(np.uint8)
                    num_cc, _, stats_cc, _ = cv2.connectedComponentsWithStats(sub_dark)
                    small_letters = sum(
                        1 for k in range(1, num_cc)
                        if int(4 * scale * scale) <= stats_cc[k, cv2.CC_STAT_AREA] <= int(250 * scale * scale)
                        and stats_cc[k, cv2.CC_STAT_HEIGHT] <= int(45 * scale)
                    )
                    if small_letters >= 2:
                        is_valid = True
                elif bg_val <= 128 and sat_mean < 100.0:
                    sub_light = (gray[y:y + bh, x:x + bw] > 170).astype(np.uint8)
                    num_cc, _, stats_cc, _ = cv2.connectedComponentsWithStats(sub_light)
                    small_letters = sum(
                        1 for k in range(1, num_cc)
                        if int(4 * scale * scale) <= stats_cc[k, cv2.CC_STAT_AREA] <= int(250 * scale * scale)
                        and stats_cc[k, cv2.CC_STAT_HEIGHT] <= int(45 * scale)
                    )
                    if small_letters >= 2:
                        is_valid = True
                elif white_ratio > 0.25 and sat_mean < 120.0:
                    sub_dark = (gray[y:y + bh, x:x + bw] < 100).astype(np.uint8)
                    num_cc, _, stats_cc, _ = cv2.connectedComponentsWithStats(sub_dark)
                    small_letters = sum(
                        1 for k in range(1, num_cc)
                        if int(3 * scale * scale) <= stats_cc[k, cv2.CC_STAT_AREA] <= int(300 * scale * scale)
                        and stats_cc[k, cv2.CC_STAT_HEIGHT] <= int(50 * scale)
                    )
                    if small_letters >= 2:
                        is_valid = True

                if is_valid:
                    orig_y_start = max(0, int(y1 * inv_scale))
                    orig_y_end = min(h, int(y2 * inv_scale))
                    orig_x1 = max(0, int((x - pad_x) * inv_scale))
                    orig_x2 = min(w, int((x + bw + pad_x) * inv_scale))
                    if (orig_y_end - orig_y_start) <= 750:
                        raw_bubbles.append((orig_x1, orig_y_start, orig_x2, orig_y_end))

        # 2. Bubble Contour Detection for enclosed bubbles
        is_light = gray > 215
        edges = cv2.Canny(gray, 50, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        closed_edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        comb = cv2.bitwise_and(is_light.astype(np.uint8) * 255, cv2.bitwise_not(closed_edges))
        contours_c, _ = cv2.findContours(comb, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours_c:
            area = cv2.contourArea(cnt)
            if int(600 * (scale ** 2)) <= area <= int(150000 * (scale ** 2)):
                bx, by, cbw, cbh = cv2.boundingRect(cnt)
                # Ignore background gutter contours that touch outer image boundaries
                if bx <= 2 or by <= 2 or bx + cbw >= calc_w - 2 or by + cbh >= calc_h - 2:
                    continue
                if cbw < calc_w * 0.70 and cbh < int(700 * scale):
                    aspect = float(cbw) / float(max(1, cbh))
                    if 0.30 <= aspect <= 3.5 and cbh >= int(25 * scale) and cbw >= int(30 * scale):
                        roi_edges = edges[by:by + cbh, bx:bx + cbw]
                        if 0.015 <= np.mean(roi_edges > 0) <= 0.35:
                            raw_bubbles.append((
                                int(round(bx * inv_scale)),
                                int(round(by * inv_scale)),
                                int(round((bx + cbw) * inv_scale)),
                                int(round((by + cbh) * inv_scale))
                            ))

        return SpeechBubbleAnalyzer._cluster_bubble_boxes(
            raw_bubbles,
            max_cluster_w=int(w * 0.85),
            max_cluster_h=800
        )

    @staticmethod
    def _cluster_bubble_boxes(
        boxes: List[Tuple[int, int, int, int]],
        max_y_gap: int = 35,
        max_cluster_w: int = 800,
        max_cluster_h: int = 850
    ) -> List[Tuple[int, int, int, int]]:
        """
        Merges adjacent speech bubbles that belong to the same dialogue cluster.
        Prevents unbounded chaining across the canvas.
        """
        if not boxes:
            return []

        sorted_boxes = sorted(boxes, key=lambda b: (b[1], b[0]))
        merged: List[Tuple[int, int, int, int]] = []

        for b in sorted_boxes:
            bx1, by1, bx2, by2 = b
            matched = False
            for i, (mx1, my1, mx2, my2) in enumerate(merged):
                # Check vertical proximity and horizontal overlap
                y_overlap = (by1 <= my2 + max_y_gap) and (by2 >= my1 - max_y_gap)
                x_overlap = (min(bx2, mx2) - max(bx1, mx1)) >= -10
                new_w = max(bx2, mx2) - min(bx1, mx1)
                new_h = max(by2, my2) - min(by1, my1)
                if y_overlap and x_overlap and new_w <= max_cluster_w and new_h <= max_cluster_h:
                    merged[i] = (min(bx1, mx1), min(by1, my1), max(bx2, mx2), max(by2, my2))
                    matched = True
                    break
            if not matched:
                merged.append(b)

        return merged

    def _measure_region_visual_activity(
        self,
        canvas_bgr: np.ndarray,
        y_start: int,
        y_end: int,
        bg_val: int = 255
    ) -> float:
        """
        Measures visual artwork complexity/activity in a vertical slice [y_start, y_end].
        Returns activity in [0.0..1.0].
        """
        total_h, total_w = canvas_bgr.shape[:2]
        y1 = max(0, min(total_h, y_start))
        y2 = max(0, min(total_h, y_end))
        if y2 - y1 < 5:
            return 0.0

        # Sample strip
        sample_w = min(200, total_w)
        strip = cv2.resize(canvas_bgr[y1:y2, :], (sample_w, y2 - y1), interpolation=cv2.INTER_NEAREST)
        gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)

        bg_diff = np.mean(np.abs(gray.astype(np.int16) - bg_val) > 18)
        edges = cv2.Canny(gray, 40, 120)
        edge_density = np.mean(edges > 0)
        std_val = np.mean(np.std(gray, axis=1)) / 128.0

        activity = float(0.4 * bg_diff + 0.35 * min(1.0, edge_density * 8.0) + 0.25 * min(1.0, std_val))
        return min(1.0, activity)

    @staticmethod
    def detect_visual_composition_spans(
        canvas_bgr: np.ndarray,
        bg_val: int = 255,
        panel_boxes: Optional[List[Tuple[int, int, int, int]]] = None,
        character_boxes: Optional[List[Tuple[int, int, int, int]]] = None,
        min_gutter_break: int = 50,
        bubble_boxes: Optional[List[Tuple[int, int, int, int]]] = None
    ) -> List[Tuple[int, int]]:
        """
        Dynamically detects vertical spans [y_start, y_end] of visual compositions.
        Merges connected panels and internal whitespace (< min_gutter_break).
        Separates distinct visual compositions divided by substantial narrative gutters.
        """
        total_h, total_w = canvas_bgr.shape[:2]
        if total_h <= 0 or total_w <= 0:
            return []

        # Mask out speech bubbles so text bubbles aren't counted as visual artwork spans
        if bubble_boxes:
            mask_canvas = canvas_bgr.copy()
            for bx1, by1, bx2, by2 in bubble_boxes:
                by1_c = max(0, by1 - 4)
                by2_c = min(total_h, by2 + 4)
                bx1_c = max(0, bx1 - 4)
                bx2_c = min(total_w, bx2 + 4)
                mask_canvas[by1_c:by2_c, bx1_c:bx2_c] = bg_val
        else:
            mask_canvas = canvas_bgr

        target_w = min(200, total_w)
        if target_w < total_w:
            small_bgr = cv2.resize(mask_canvas, (target_w, total_h), interpolation=cv2.INTER_AREA)
        else:
            small_bgr = mask_canvas

        gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
        canny = cv2.Canny(gray, 40, 120)

        # Content rows: background difference or edge presence
        bg_diff = np.abs(gray.astype(np.int16) - bg_val)
        row_has_content = (np.mean(bg_diff > 38, axis=1) > 0.02) | (np.mean(canny > 0, axis=1) > 0.008)

        # Contiguous content spans
        spans: List[Tuple[int, int]] = []
        in_content = False
        s_start = 0
        for y in range(total_h):
            if row_has_content[y] and not in_content:
                in_content = True
                s_start = y
            elif not row_has_content[y] and in_content:
                in_content = False
                if y - s_start >= 10:
                    spans.append((s_start, y))
        if in_content and total_h - s_start >= 10:
            spans.append((s_start, total_h))

        # Include panel and character spans
        if panel_boxes:
            for _, py1, _, py2 in panel_boxes:
                if py2 > py1:
                    spans.append((max(0, py1), min(total_h, py2)))
        if character_boxes:
            for _, cy1, _, cy2 in character_boxes:
                if cy2 > cy1:
                    spans.append((max(0, cy1), min(total_h, cy2)))

        if not spans:
            return []

        spans.sort(key=lambda s: s[0])
        # Merge spans if the gap between them is smaller than min_gutter_break (connected panels / internal whitespace)
        merged: List[Tuple[int, int]] = [spans[0]]
        for s, e in spans[1:]:
            last_s, last_e = merged[-1]
            if s <= last_e + min_gutter_break:
                merged[-1] = (last_s, max(last_e, e))
            else:
                merged.append((s, e))

        return merged

    def classify_speech_bubbles(
        self,
        canvas_bgr: np.ndarray,
        bubble_boxes: List[Tuple[int, int, int, int]],
        character_boxes: Optional[List[Tuple[int, int, int, int]]] = None,
        panel_boxes: Optional[List[Tuple[int, int, int, int]]] = None,
        bg_val: int = 255
    ) -> List[AnalyzedBubble]:
        """
        Dynamically classifies speech bubbles relative to the surrounding visual composition:
        - Case A: EDGE_TOP (Bubble situated ABOVE visual artwork -> separated with boundary cut)
        - Case B: EDGE_BOTTOM (Bubble situated BELOW visual artwork -> separated with boundary cut)
        - Case C: INTERNAL (Bubble embedded INSIDE visual composition -> ignored from splitting)
        """
        total_h, total_w = canvas_bgr.shape[:2]
        if not bubble_boxes or total_h <= 0:
            return []

        char_boxes = character_boxes or []
        analyzed: List[AnalyzedBubble] = []
        pad = self.clearance_padding

        # Detect visual compositions on canvas (passing bubble_boxes to mask them out)
        compositions = self.detect_visual_composition_spans(
            canvas_bgr, bg_val=bg_val, panel_boxes=panel_boxes, character_boxes=char_boxes,
            bubble_boxes=bubble_boxes
        )

        for bx1, by1, bx2, by2 in bubble_boxes:
            b_h = by2 - by1
            b_w = bx2 - bx1
            if b_h <= 0 or b_w <= 0:
                continue

            # 1. Check direct vertical/spatial overlap with character bboxes
            char_overlap = False
            for cx1, cy1, cx2, cy2 in char_boxes:
                v_overlap = max(0, min(by2, cy2) - max(by1, cy1))
                if v_overlap > 0:
                    h_overlap = max(0, min(bx2, cx2) - max(bx1, cx1))
                    if h_overlap > 0 or (abs(bx1 - cx2) < 40 or abs(cx1 - bx2) < 40):
                        char_overlap = True
                        break

            # 2. Check panel enclosure
            in_panel_interior = False
            if panel_boxes:
                for px1, py1, px2, py2 in panel_boxes:
                    if by1 >= py1 + 15 and by2 <= py2 - 15:
                        in_panel_interior = True
                        break

            # 3. Dynamic Topological Relationship to Visual Compositions
            # Check if bubble is inside any visual composition
            is_internal = False
            inside_comp = None

            if char_overlap or in_panel_interior:
                is_internal = True

            if not is_internal and compositions:
                for cs, ce in compositions:
                    # Bubble fully or mostly enclosed in this composition
                    if by1 >= cs - 10 and by2 <= ce + 10:
                        is_internal = True
                        inside_comp = (cs, ce)
                        break
                    # Significant vertical overlap with active composition
                    v_int = max(0, min(by2, ce) - max(by1, cs))
                    if v_int > 0.25 * b_h:
                        is_internal = True
                        inside_comp = (cs, ce)
                        break

            cut_pos = None
            cut_top = None
            cut_bottom = None
            if is_internal:
                role = BubbleRole.INTERNAL
            elif compositions:
                # Find closest composition above and below
                comps_above = [c for c in compositions if c[0] < by1 and c[1] <= by2]
                c_above = comps_above[-1] if comps_above else None
                dist_above = max(0, by1 - c_above[1]) if c_above else 999999

                comps_below = [c for c in compositions if c[1] > by2 and c[0] >= by1]
                c_below = comps_below[0] if comps_below else None
                dist_below = max(0, c_below[0] - by2) if c_below else 999999

                if c_above is None and c_below is not None and dist_below <= 600:
                    # Case A: Bubble sits above the visual composition
                    role = BubbleRole.EDGE_TOP
                    comp_top = c_below[0]
                    cut_pos = min(comp_top, max(by2 + 4, min(comp_top, by2 + pad)))
                elif c_below is None and c_above is not None and dist_above <= 600:
                    # Case B: Bubble sits below the visual composition
                    role = BubbleRole.EDGE_BOTTOM
                    cut_pos = max(0, by1 - pad)
                elif c_above is not None and c_below is not None:
                    # Bubble sits in gutter between two compositions
                    if dist_below <= 50 and dist_above > 100:
                        role = BubbleRole.EDGE_TOP
                        comp_top = c_below[0]
                        cut_pos = min(comp_top, max(by2 + 4, min(comp_top, by2 + pad)))
                    elif dist_above <= 50 and dist_below > 100:
                        role = BubbleRole.EDGE_BOTTOM
                        cut_pos = max(0, by1 - pad)
                    else:
                        # Inter-panel dialogue region: standalone text block in gutter between two compositions
                        role = BubbleRole.STANDALONE
                        cut_pos = None
                        cut_top = max(c_above[1], by1 - pad)
                        cut_bottom = min(c_below[0], by2 + pad)
                elif dist_above > 180 and dist_below > 180:
                    role = BubbleRole.STANDALONE
                    cut_pos = min(total_h - 1, by2 + pad)
                else:
                    role = BubbleRole.STANDALONE
                    cut_pos = min(total_h - 1, by2 + pad)
            else:
                # No composition detected
                role = BubbleRole.STANDALONE
                cut_pos = min(total_h - 1, by2 + pad)

            # Visual activity metrics for logging
            act_above = self._measure_region_visual_activity(canvas_bgr, max(0, by1 - 100), by1, bg_val=bg_val)
            act_below = self._measure_region_visual_activity(canvas_bgr, by2, min(total_h, by2 + 100), bg_val=bg_val)

            details_dict = {
                "act_above": round(act_above, 3),
                "act_below": round(act_below, 3),
                "char_overlap": char_overlap,
                "in_panel_interior": in_panel_interior,
                "inside_composition": inside_comp is not None
            }
            if cut_pos is not None:
                details_dict["cut_y"] = int(cut_pos)
            if cut_top is not None:
                details_dict["cut_top"] = int(cut_top)
            if cut_bottom is not None:
                details_dict["cut_bottom"] = int(cut_bottom)

            analyzed.append(AnalyzedBubble(
                bbox=(bx1, by1, bx2, by2),
                role=role,
                confidence=0.95 if is_internal else 0.85,
                visual_above_score=act_above,
                visual_below_score=act_below,
                character_overlap=char_overlap,
                details=details_dict
            ))

        return analyzed

    def generate_bubble_boundary_candidates(
        self,
        canvas_bgr: np.ndarray,
        analyzed_bubbles: List[AnalyzedBubble],
        bg_val: int = 255,
        keep_with_visual: bool = False
    ) -> List[BoundaryCandidate]:
        """
        Generates boundary candidates for EDGE bubbles.
        When keep_with_visual=True:
          - EDGE_TOP bubble: attached to visual panel below it; cut is placed ABOVE bubble.
          - EDGE_BOTTOM bubble: attached to visual panel above it; cut is placed BELOW bubble.
          - STANDALONE: snap bubble to closest visual panel, never isolating it.
        When keep_with_visual=False:
          - Preserves legacy hard cuts between bubble and visual.
        Suppresses/omits cuts for INTERNAL bubbles (Case C).
        """
        total_h = canvas_bgr.shape[0]
        candidates: List[BoundaryCandidate] = []
        pad = self.clearance_padding

        for ab in analyzed_bubbles:
            bx1, by1, bx2, by2 = ab.bbox

            if ab.role == BubbleRole.EDGE_TOP:
                if keep_with_visual:
                    # Snap bubble to visual panel below it; cut above bubble
                    cut_y = max(0, by1 - pad)
                    if cut_y > 10:
                        candidates.append(BoundaryCandidate(
                            y=int(cut_y),
                            candidate_type="speech_bubble_edge",
                            score=0.90,
                            hard=False,
                            is_safe=True,
                            speech_edge_score=0.90,
                            visual_continuity=0.1,
                            details={"bubble_role": BubbleRole.EDGE_TOP, "bubble_bbox": ab.bbox, "attached_to": "below"}
                        ))
                else:
                    # Legacy: Hard cut placed between the bubble bottom and visual artwork
                    cut_y = ab.details.get("cut_y", min(total_h - 1, by2 + pad))
                    candidates.append(BoundaryCandidate(
                        y=int(cut_y),
                        candidate_type="speech_bubble_edge",
                        score=1.0,
                        hard=True,
                        is_safe=True,
                        speech_edge_score=1.0,
                        visual_continuity=0.1,  # Edge bubble indicates composition break
                        details={"bubble_role": BubbleRole.EDGE_TOP, "bubble_bbox": ab.bbox}
                    ))

            elif ab.role == BubbleRole.EDGE_BOTTOM:
                if keep_with_visual:
                    # Snap bubble to visual panel above it; cut below bubble
                    cut_y = min(total_h - 1, by2 + pad)
                    if cut_y < total_h - 10:
                        candidates.append(BoundaryCandidate(
                            y=int(cut_y),
                            candidate_type="speech_bubble_edge",
                            score=0.90,
                            hard=False,
                            is_safe=True,
                            speech_edge_score=0.90,
                            visual_continuity=0.1,
                            details={"bubble_role": BubbleRole.EDGE_BOTTOM, "bubble_bbox": ab.bbox, "attached_to": "above"}
                        ))
                else:
                    # Legacy: Hard cut placed between the visual artwork and bubble top
                    cut_y = ab.details.get("cut_y", max(0, by1 - pad))
                    candidates.append(BoundaryCandidate(
                        y=int(cut_y),
                        candidate_type="speech_bubble_edge",
                        score=1.0,
                        hard=True,
                        is_safe=True,
                        speech_edge_score=1.0,
                        visual_continuity=0.1,  # Edge bubble indicates composition break
                        details={"bubble_role": BubbleRole.EDGE_BOTTOM, "bubble_bbox": ab.bbox}
                    ))

            elif ab.role == BubbleRole.STANDALONE:
                if keep_with_visual:
                    cut_y = ab.details.get("cut_y", min(total_h - 1, by2 + pad))
                    if 10 < cut_y < total_h - 10:
                        candidates.append(BoundaryCandidate(
                            y=int(cut_y),
                            candidate_type="speech_bubble_edge",
                            score=0.75,
                            hard=False,
                            is_safe=True,
                            speech_edge_score=0.75,
                            visual_continuity=0.2,
                            details={"bubble_role": BubbleRole.STANDALONE, "bubble_bbox": ab.bbox}
                        ))
                else:
                    if "cut_top" in ab.details and "cut_bottom" in ab.details:
                        candidates.append(BoundaryCandidate(
                            y=int(ab.details["cut_top"]),
                            candidate_type="speech_bubble_edge",
                            score=1.0,
                            hard=True,
                            is_safe=True,
                            speech_edge_score=1.0,
                            visual_continuity=0.1,
                            details={"bubble_role": BubbleRole.STANDALONE, "cut_edge": "top", "bubble_bbox": ab.bbox}
                        ))
                        candidates.append(BoundaryCandidate(
                            y=int(ab.details["cut_bottom"]),
                            candidate_type="speech_bubble_edge",
                            score=1.0,
                            hard=True,
                            is_safe=True,
                            speech_edge_score=1.0,
                            visual_continuity=0.1,
                            details={"bubble_role": BubbleRole.STANDALONE, "cut_edge": "bottom", "bubble_bbox": ab.bbox}
                        ))
                    else:
                        cut_y = ab.details.get("cut_y", min(total_h - 1, by2 + pad))
                        candidates.append(BoundaryCandidate(
                            y=int(cut_y),
                            candidate_type="speech_bubble_edge",
                            score=0.75,
                            hard=False,
                            is_safe=True,
                            speech_edge_score=0.75,
                            visual_continuity=0.3,
                            details={"bubble_role": BubbleRole.STANDALONE, "bubble_bbox": ab.bbox}
                        ))

            # Case C: INTERNAL bubbles generate NO candidates!
            # They will also be used by boundary_scorer to suppress cuts crossing them.

        return candidates

    @staticmethod
    def get_internal_bubble_forbidden_spans(
        analyzed_bubbles: List[AnalyzedBubble]
    ) -> List[Tuple[int, int]]:
        """
        Returns list of (y1, y2) spans for INTERNAL bubbles where cuts are strictly prohibited.
        """
        spans: List[Tuple[int, int]] = []
        for ab in analyzed_bubbles:
            if ab.role == BubbleRole.INTERNAL:
                bx1, by1, bx2, by2 = ab.bbox
                spans.append((max(0, by1 - 4), by2 + 4))

        # Merge overlapping spans
        if not spans:
            return []
        spans.sort(key=lambda s: s[0])
        merged = [spans[0]]
        for s, e in spans[1:]:
            last_s, last_e = merged[-1]
            if s <= last_e:
                merged[-1] = (last_s, max(last_e, e))
            else:
                merged.append((s, e))

        return merged
