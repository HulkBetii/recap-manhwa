# -*- coding: utf-8 -*-
"""
PURE VISUAL FRAME REFINER (PRE-RENDER VIDEO & VISUAL REGION CLEANER)
Cleans comic frames by:
1. Trimming solid color / 0% variance empty black/white margins from outside in (vectorized).
2. Detecting real panel border divider lines on 4 directions (top, bot, left, right)
   even if partially broken by SFX, speech bubbles, or text boxes using prefix sums.
3. Cropping peripheral speech bubbles and narration blocks in bottom/top margins.
Optimized with NumPy vectorization and GPU acceleration for sub-millisecond execution.
"""

import os
import sys
import logging
from dataclasses import dataclass
from typing import Tuple, List, Dict, Any, Optional
import cv2
import numpy as np

# Ensure PyTorch CUDA DLLs are linked for ONNX Runtime CUDAExecutionProvider
try:
    import torch
    torch_lib = os.path.join(os.path.dirname(torch.__file__), 'lib')
    if os.path.exists(torch_lib):
        os.add_dll_directory(torch_lib)
        os.environ['PATH'] = torch_lib + os.pathsep + os.environ['PATH']
except Exception:
    pass

logger = logging.getLogger("PureVisualFrameRefiner")


@dataclass
class FrameRefinerConfig:
    # 1. Zero-variance Gutter Trimming
    enable_zero_variance_trim: bool = True
    color_std_threshold: float = 4.0          # Max std dev to be considered solid color
    dark_bg_max: int = 28                     # Max intensity for black background
    light_bg_min: int = 225                   # Min intensity for white background
    
    # 2. Panel Border & Margin Divider Detection
    enable_panel_border_crop: bool = True
    border_search_depth_ratio: float = 0.20   # Strictly bounded to 20% margin
    border_inset_px: int = 1                  # Inset px inside border line to eliminate stroke
    
    # 3. Peripheral Text / Box Text Cropping & Margin Safety Guards
    enable_border_text_crop: bool = True
    enable_bubble_crop: bool = True
    max_text_crop_ratio: float = 0.35         # Max depth (up to 35%) to crop top/bottom text overhang
    margin_top_ratio: float = 0.20            # 20% Top margin panel line scan envelope
    margin_bot_ratio: float = 0.20            # 20% Bottom margin panel line scan envelope
    margin_side_ratio: float = 0.10           # 10% Left/Right margin safety zone (Crop MUST NOT exceed 10%)
    
    # 4. Safety Constraints
    min_area_retain_ratio: float = 0.25       # Retain at least 25% of candidate area
    min_width_px: int = 120
    min_height_px: int = 120


class PureVisualFrameRefiner:
    """
    Refines frames to achieve maximum pure visual immersion.
    Accurately cuts out outer gutters and peripheral text overhangs,
    snapping directly to true comic panel artwork borders while strictly respecting
    the safety envelope and retaining pure visual artwork.
    """
    _layout_model = None
    _onnx_session = None

    def __init__(self, config: Optional[FrameRefinerConfig] = None):
        self.config = config or FrameRefinerConfig()

    @classmethod
    def get_layout_model(cls):
        if cls._layout_model is None:
            try:
                from renderer.yolo_compat import YOLO, is_yolo_available
                if is_yolo_available():
                    candidates = ["weights/manga109_yolo11m.pt", "weights/comic_layout_yolo26s.pt"]
                    for p in candidates:
                        if os.path.exists(p):
                            cls._layout_model = YOLO(p)
                            break
            except Exception:
                pass
        return cls._layout_model

    @classmethod
    def detect_dbnet_text_boxes(cls, image_np: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detects true text/SFX bounding boxes accurately using GPU DBNet model (<5ms).
        Returns list of (x1, y1, x2, y2) text bounding boxes.
        """
        if image_np is None or image_np.size == 0:
            return []
        h, w = image_np.shape[:2]
        if h < 20 or w < 20:
            return []

        from pure_visual.cleaner import get_ocr_engine
        ocr = get_ocr_engine()
        if ocr is None:
            return []

        # Downscale for ultra-fast DBNet detection
        max_dim = max(h, w)
        if max_dim > 480:
            scale = 480.0 / max_dim
            inp = cv2.resize(image_np, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        else:
            scale = 1.0
            inp = image_np

        try:
            dt_boxes, _ = ocr.text_det(inp)
            if dt_boxes is None or len(dt_boxes) == 0:
                return []
            inv_scale = 1.0 / scale if scale != 1.0 else 1.0
            boxes = []
            for b in dt_boxes:
                xs = [pt[0] * inv_scale for pt in b]
                ys = [pt[1] * inv_scale for pt in b]
                bx1 = max(0, int(min(xs)))
                by1 = max(0, int(min(ys)))
                bx2 = min(w, int(max(xs)))
                by2 = min(h, int(max(ys)))
                if (bx2 - bx1) >= 8 and (by2 - by1) >= 6:
                    boxes.append((bx1, by1, bx2, by2))
            return boxes
        except Exception:
            return []

    def refine_frame(self, image_np: np.ndarray) -> Tuple[int, int, int, int]:
        """Calculates refined (x, y, w, h) bounding box."""
        bbox, _ = self.refine_frame_ex(image_np)
        return bbox

    def refine_frame_ex(
        self,
        image_np: np.ndarray,
        known_text_boxes: Optional[List[Tuple[int, int, int, int]]] = None
    ) -> Tuple[Tuple[int, int, int, int], List[Tuple[int, int, int, int]]]:
        """
        Calculates refined bounding box AND returns detected text_boxes with vectorized speed.

        Returns:
            ((x, y, w, h), text_boxes)
        """
        if image_np is None or image_np.size == 0:
            return (0, 0, 0, 0), []

        h, w = image_np.shape[:2]
        if h < 30 or w < 30:
            return (0, 0, w, h), []

        orig_area = float(w * h)
        gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY) if image_np.ndim == 3 else image_np
        canny = cv2.Canny(gray, 35, 120)
        cfg = self.config
        inset = cfg.border_inset_px

        top_limit = int(h * cfg.margin_top_ratio)
        bot_limit = int(h * (1.0 - cfg.margin_bot_ratio))
        left_limit = int(w * cfg.margin_side_ratio)
        right_limit = int(w * (1.0 - cfg.margin_side_ratio))
        max_top_crop = top_limit
        max_bot_crop = bot_limit

        # ─────────────────────────────────────────────────────────────
        # STEP 1: VECTORIZED SOLID-COLOR GUTTER TRIM
        # ─────────────────────────────────────────────────────────────
        y1 = 0
        y2 = h
        x1 = 0
        x2 = w

        if cfg.enable_zero_variance_trim:
            # Top scan
            if top_limit > 0:
                top_slice = gray[:top_limit + 1, :]
                row_stds = np.std(top_slice, axis=1)
                row_means = np.mean(top_slice, axis=1)
                is_solid_top = (row_stds <= cfg.color_std_threshold) & ((row_means >= cfg.light_bg_min) | (row_means <= cfg.dark_bg_max))
                non_solid_top = np.where(~is_solid_top)[0]
                y1 = int(non_solid_top[0]) if len(non_solid_top) > 0 else top_limit

            # Bottom scan
            if bot_limit < h:
                bot_slice = gray[bot_limit:, :]
                row_stds = np.std(bot_slice, axis=1)
                row_means = np.mean(bot_slice, axis=1)
                is_solid_bot = (row_stds <= cfg.color_std_threshold) & ((row_means >= cfg.light_bg_min) | (row_means <= cfg.dark_bg_max))
                non_solid_bot = np.where(~is_solid_bot)[0]
                y2 = int(bot_limit + non_solid_bot[-1] + 1) if len(non_solid_bot) > 0 else bot_limit

            # Left scan
            if left_limit > 0 and (y2 - y1) > 0:
                left_slice = gray[y1:y2, :left_limit + 1]
                col_stds = np.std(left_slice, axis=0)
                col_means = np.mean(left_slice, axis=0)
                is_solid_left = (col_stds <= cfg.color_std_threshold) & ((col_means >= cfg.light_bg_min) | (col_means <= cfg.dark_bg_max))
                non_solid_left = np.where(~is_solid_left)[0]
                x1 = int(non_solid_left[0]) if len(non_solid_left) > 0 else left_limit

            # Right scan
            if right_limit < w and (y2 - y1) > 0:
                right_slice = gray[y1:y2, right_limit:]
                col_stds = np.std(right_slice, axis=0)
                col_means = np.mean(right_slice, axis=0)
                is_solid_right = (col_stds <= cfg.color_std_threshold) & ((col_means >= cfg.light_bg_min) | (col_means <= cfg.dark_bg_max))
                non_solid_right = np.where(~is_solid_right)[0]
                x2 = int(right_limit + non_solid_right[-1] + 1) if len(non_solid_right) > 0 else right_limit

        # ─────────────────────────────────────────────────────────────
        # STEP 2: VECTORIZED TOP PANEL BORDER DIVIDER SCAN (Prefix Sums)
        # ─────────────────────────────────────────────────────────────
        if (x2 - x1) > 20 and cfg.enable_panel_border_crop and top_limit > 0:
            cur_w = x2 - x1
            horiz_k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, int(cur_w * 0.15)), 1))
            canny_crop = canny[0:top_limit + 1, x1:x2]
            h_lines_top = cv2.morphologyEx(canny_crop, cv2.MORPH_OPEN, horiz_k) if canny_crop.size > 0 else np.zeros((0, cur_w), dtype=np.uint8)

            gray_sub = gray[0:top_limit + 1, x1:x2].astype(np.float32)
            canny_sub = (canny[0:top_limit + 1, x1:x2] > 0).astype(np.float32)
            white_sub = (gray_sub > 215).astype(np.float32)
            black_sub = (gray_sub < 40).astype(np.float32)

            cum_mean_gray = np.cumsum(np.mean(gray_sub, axis=1))
            cum_mean_sq = np.cumsum(np.mean(gray_sub ** 2, axis=1))
            cum_edge = np.cumsum(np.mean(canny_sub, axis=1))
            cum_white = np.cumsum(np.mean(white_sub, axis=1))
            cum_black = np.cumsum(np.mean(black_sub, axis=1))

            counts = np.arange(1, top_limit + 1, dtype=np.float32)
            above_means_gray = cum_mean_gray[:top_limit] / counts
            above_means_sq = cum_mean_sq[:top_limit] / counts
            above_var = np.maximum(0.0, above_means_sq - above_means_gray ** 2)
            above_std_vec = np.sqrt(above_var)
            above_edge_vec = cum_edge[:top_limit] / counts
            above_white_vec = cum_white[:top_limit] / counts
            above_black_vec = cum_black[:top_limit] / counts

            above_is_gutter_vec = (
                ((above_std_vec < 12.0) & (above_edge_vec < 0.015) & ((above_white_vec > 0.75) | (above_black_vec > 0.75))) |
                ((above_white_vec > 0.55) & (above_edge_vec < 0.080) & (above_black_vec < 0.25))
            )

            for r in range(1, min(h, top_limit + 1)):
                h_line_val = float(np.mean(h_lines_top[r, :] > 0)) if (0 <= r < h_lines_top.shape[0]) else 0.0
                row_black = float(np.mean(gray[r, x1:x2] < 45))
                row_dark = float(np.mean(gray[r, x1:x2] < 80))

                above_is_gutter = bool(above_is_gutter_vec[r - 1])
                is_panel_line = (
                    h_line_val >= 0.20 or
                    row_black >= 0.25 or
                    row_dark >= 0.30 or
                    (h_line_val >= 0.12 and row_black >= 0.20)
                )

                if is_panel_line and above_is_gutter:
                    crop_candidate = min(r + inset, top_limit)
                    if (y2 - crop_candidate) >= cfg.min_height_px:
                        y1 = max(y1, crop_candidate)

        # ─────────────────────────────────────────────────────────────
        # STEP 3: VECTORIZED BOTTOM PANEL BORDER DIVIDER SCAN
        # ─────────────────────────────────────────────────────────────
        if (x2 - x1) > 20 and cfg.enable_panel_border_crop and bot_limit < h:
            cur_w = x2 - x1
            horiz_k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, int(cur_w * 0.15)), 1))
            canny_crop_bot = canny[bot_limit:h, x1:x2]
            h_lines_bot = cv2.morphologyEx(canny_crop_bot, cv2.MORPH_OPEN, horiz_k) if canny_crop_bot.size > 0 else np.zeros((0, cur_w), dtype=np.uint8)

            gray_bot = gray[bot_limit:h, x1:x2].astype(np.float32)
            canny_bot = (canny[bot_limit:h, x1:x2] > 0).astype(np.float32)
            white_bot = (gray_bot > 215).astype(np.float32)
            black_bot = (gray_bot < 40).astype(np.float32)

            # Suffix/reverse cumulative sums
            rev_gray = gray_bot[::-1]
            rev_sq = (gray_bot ** 2)[::-1]
            rev_edge = canny_bot[::-1]
            rev_white = white_bot[::-1]
            rev_black = black_bot[::-1]

            cum_rev_gray = np.cumsum(np.mean(rev_gray, axis=1))
            cum_rev_sq = np.cumsum(np.mean(rev_sq, axis=1))
            cum_rev_edge = np.cumsum(np.mean(rev_edge, axis=1))
            cum_rev_white = np.cumsum(np.mean(rev_white, axis=1))
            cum_rev_black = np.cumsum(np.mean(rev_black, axis=1))

            bot_len = h - bot_limit
            counts_bot = np.arange(1, bot_len + 1, dtype=np.float32)
            below_means_gray = (cum_rev_gray / counts_bot)[::-1]
            below_means_sq = (cum_rev_sq / counts_bot)[::-1]
            below_var = np.maximum(0.0, below_means_sq - below_means_gray ** 2)
            below_std_vec = np.sqrt(below_var)
            below_edge_vec = (cum_rev_edge / counts_bot)[::-1]
            below_white_vec = (cum_rev_white / counts_bot)[::-1]
            below_black_vec = (cum_rev_black / counts_bot)[::-1]

            below_is_gutter_vec = (
                ((below_std_vec < 12.0) & (below_edge_vec < 0.015) & ((below_white_vec > 0.75) | (below_black_vec > 0.75))) |
                ((below_white_vec > 0.55) & (below_edge_vec < 0.080) & (below_black_vec < 0.25))
            )

            for r in range(h - 1, max(-1, bot_limit - 1), -1):
                r_rel = r - bot_limit
                h_line_val = float(np.mean(h_lines_bot[r_rel, :] > 0)) if (0 <= r_rel < h_lines_bot.shape[0]) else 0.0
                row_black = float(np.mean(gray[r, x1:x2] < 45))
                row_dark = float(np.mean(gray[r, x1:x2] < 80))

                below_is_gutter = bool(below_is_gutter_vec[r_rel]) if (r_rel < len(below_is_gutter_vec)) else True
                is_panel_line = (
                    h_line_val >= 0.20 or
                    row_black >= 0.25 or
                    row_dark >= 0.30 or
                    (h_line_val >= 0.12 and row_black >= 0.20)
                )

                if is_panel_line and below_is_gutter:
                    crop_candidate = max(r - inset, bot_limit)
                    if (crop_candidate - y1) >= cfg.min_height_px:
                        y2 = min(y2, crop_candidate)

        # ─────────────────────────────────────────────────────────────
        # STEP 4: LEFT VERTICAL PANEL DIVIDER SCAN
        # ─────────────────────────────────────────────────────────────
        if cfg.enable_panel_border_crop and (y2 - y1) > 20 and left_limit > 0:
            for c in range(x1, min(w, left_limit + 1)):
                col = gray[y1:y2, c]
                if len(col) == 0:
                    break
                black_ratio = float(np.count_nonzero(col < 45)) / len(col)
                dark_ratio = float(np.count_nonzero(col < 80)) / len(col)
                if black_ratio >= 0.22 or dark_ratio >= 0.28:
                    left_side = gray[y1:y2, max(0, c - 40):c]
                    right_side = gray[y1:y2, c + 1:min(w, c + 41)]
                    if left_side.size > 0 and right_side.size > 0:
                        left_white = float(np.count_nonzero(left_side > 210)) / left_side.size
                        left_std = float(np.std(left_side))
                        right_black = float(np.count_nonzero(right_side < 45)) / right_side.size
                        if (left_white > 0.45 or left_std < 12.0) and right_black < 0.80:
                            crop_candidate = min(c + inset, left_limit)
                            if (x2 - crop_candidate) >= cfg.min_width_px:
                                x1 = max(x1, crop_candidate)
                            break

        # ─────────────────────────────────────────────────────────────
        # STEP 5: RIGHT VERTICAL PANEL DIVIDER SCAN
        # ─────────────────────────────────────────────────────────────
        if cfg.enable_panel_border_crop and (y2 - y1) > 20 and right_limit < w:
            for c in range(x2 - 1, max(-1, right_limit - 1), -1):
                col = gray[y1:y2, c]
                if len(col) == 0:
                    break
                black_ratio = float(np.count_nonzero(col < 45)) / len(col)
                dark_ratio = float(np.count_nonzero(col < 80)) / len(col)
                if black_ratio >= 0.22 or dark_ratio >= 0.28:
                    right_side = gray[y1:y2, c + 1:min(w, c + 41)]
                    left_side = gray[y1:y2, max(0, c - 40):c]
                    if right_side.size > 0 and left_side.size > 0:
                        right_white = float(np.count_nonzero(right_side > 210)) / right_side.size
                        right_std = float(np.std(right_side))
                        left_black = float(np.count_nonzero(left_side < 45)) / left_side.size
                        if (right_white > 0.45 or right_std < 12.0) and left_black < 0.80:
                            crop_candidate = max(c - inset, right_limit)
                            if (crop_candidate - x1) >= cfg.min_width_px:
                                x2 = min(x2, crop_candidate)
                            break

        # ─────────────────────────────────────────────────────────────
        # STEP 6: DBNET / BUBBLE MARGIN CROPPER (Bounded to 20% Margins)
        # ─────────────────────────────────────────────────────────────
        text_boxes = known_text_boxes if known_text_boxes is not None else []
        if cfg.enable_bubble_crop and known_text_boxes is None and cfg.enable_border_text_crop:
            text_boxes = self.detect_dbnet_text_boxes(image_np)

        if cfg.enable_bubble_crop and text_boxes:
            # Top margin text crop: boxes lying mostly within top 20%
            top_text_blocks = [b for b in text_boxes if b[1] < top_limit and b[3] <= top_limit + 15]
            if top_text_blocks:
                max_bot_top_text = max(b[3] for b in top_text_blocks)
                crop_cand = min(max_bot_top_text + inset, max_top_crop)
                if (y2 - crop_cand) >= cfg.min_height_px and (y2 - crop_cand) * (x2 - x1) >= orig_area * cfg.min_area_retain_ratio:
                    y1 = max(y1, crop_cand)

            # Bottom margin text crop: boxes lying mostly within bottom 20%
            bot_text_blocks = [b for b in text_boxes if b[3] > bot_limit and b[1] >= bot_limit - 15]
            if bot_text_blocks:
                min_top_bot_text = min(b[1] for b in bot_text_blocks)
                crop_cand = max(min_top_bot_text - inset, max_bot_crop)
                if (crop_cand - y1) >= cfg.min_height_px and (crop_cand - y1) * (x2 - x1) >= orig_area * cfg.min_area_retain_ratio:
                    y2 = min(y2, crop_cand)

        # ─────────────────────────────────────────────────────────────
        # STEP 7: SAFETY CLAMP — prevent over-cropping
        # ─────────────────────────────────────────────────────────────
        x1 = max(0, int(x1))
        y1 = max(0, min(int(y1), max_top_crop))
        x2 = min(w, int(x2))
        y2 = min(h, max(int(y2), max_bot_crop))

        final_w = max(0, x2 - x1)
        final_h = max(0, y2 - y1)
        final_area = float(final_w * final_h)

        if (final_area < orig_area * cfg.min_area_retain_ratio or
                final_w < cfg.min_width_px or
                final_h < cfg.min_height_px):
            logger.debug("[FrameRefiner] Safety guard triggered: crop too aggressive, resetting to full frame.")
            return (0, 0, w, h), text_boxes

        return (int(x1), int(y1), int(final_w), int(final_h)), text_boxes
