# -*- coding: utf-8 -*-
"""
PURE VISUAL REGION DETECTION: AI & SIGNAL ENGINE
Identifies high-value visual artwork, characters, action scenes, and composition frames
in ultra-tall manhwa canvases (up to 400,000px) with Zero-Cut Face/Body Guardrail and
Horizontal Margin Auto-Cropping on NVIDIA RTX 4070 SUPER.
"""
import os
import logging
import threading
from typing import List, Tuple, Dict, Any, Optional
import cv2
import numpy as np

from pure_visual.types import BBox, PureVisualRegion, VisualRegionCandidate, TextDetection
from pure_visual.config import DetectionConfig

logger = logging.getLogger("VisualRegionDetector")


class VisualRegionDetector:
    """
    Detects semantic pure visual regions across tall manhwa canvases with GPU acceleration
    and zero character cut protection.
    """
    _yolo_model = None
    _face_model = None
    _gpu_lock = threading.Lock()

    def __init__(self, config: Optional[DetectionConfig] = None):
        self.config = config or DetectionConfig()
        self._init_models()

    def _init_models(self):
        """Initializes layout & face models on GPU if available."""
        try:
            import torch
            from renderer.yolo_compat import YOLO, is_yolo_available
            if not is_yolo_available():
                logger.warning("[VisualRegionDetector] YOLO not available, using pure CV detector.")
                return

            dev = "cuda" if (self.config.device == "cuda" and torch.cuda.is_available()) else "cpu"
            if dev == "cuda":
                try:
                    torch.backends.cudnn.benchmark = True
                    torch.set_float32_matmul_precision("high")
                except Exception:
                    pass

            # 1. Main Manga Layout Model (YOLO11m / Manga109)
            if VisualRegionDetector._yolo_model is None:
                candidates = [
                    self.config.yolo_weights,
                    "weights/manga109_yolo11m.pt",
                    "yolo26x.pt",
                    "weights/comic_layout_yolo26s.pt"
                ]
                for c in candidates:
                    if c and os.path.exists(c):
                        try:
                            m = YOLO(c)
                            if dev == "cuda":
                                m.to("cuda")
                                try:
                                    m.model.half()
                                except Exception:
                                    pass
                            VisualRegionDetector._yolo_model = m
                            logger.info(f"[VisualRegionDetector] Loaded layout model ({c}) on {dev} (FP16={dev=='cuda'})")
                            break
                        except Exception as e:
                            logger.warning(f"[VisualRegionDetector] Could not load {c}: {e}")

            # 2. Anime Face Detection Model
            if VisualRegionDetector._face_model is None:
                face_p = self.config.anime_face_weights
                if face_p and os.path.exists(face_p):
                    try:
                        fm = YOLO(face_p)
                        if dev == "cuda":
                            fm.to("cuda")
                            try:
                                fm.model.half()
                            except Exception:
                                pass
                        VisualRegionDetector._face_model = fm
                        logger.info(f"[VisualRegionDetector] Loaded Anime Face Detector ({face_p}) on {dev} (FP16={dev=='cuda'})")
                    except Exception as e:
                        logger.warning(f"[VisualRegionDetector] Could not load face model: {e}")

        except Exception as e:
            logger.warning(f"[VisualRegionDetector] Model initialization warning: {e}")

    # -------------------------------------------------------------------------
    # Horizontal Margin Auto-Cropper (Removes Black/White side padding)
    # -------------------------------------------------------------------------
    def find_tight_horizontal_bounds(self, img_bgr: np.ndarray, tol: int = 15) -> Tuple[int, int]:
        """
        Scans left and right columns to identify real artwork content bounds,
        stripping solid black/white side padding bars with vectorized numpy.
        """
        h, w = img_bgr.shape[:2]
        if w <= 10 or h <= 10:
            return 0, w

        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        
        # Check median of extreme left/right column
        left_col_val = int(np.median(gray[:, 0]))
        right_col_val = int(np.median(gray[:, -1]))

        scan_w = min(w // 3, 300)
        if scan_w <= 0:
            return 0, w

        # Vectorized left scan
        left_cols = gray[:, :scan_w]
        left_pad = np.mean(np.abs(left_cols.astype(np.int32) - left_col_val) <= tol, axis=0) > 0.98
        non_pad_left = np.where(~left_pad)[0]
        x_min = int(non_pad_left[0]) if len(non_pad_left) > 0 else 0

        # Vectorized right scan
        right_cols = gray[:, w - scan_w:]
        right_pad = np.mean(np.abs(right_cols.astype(np.int32) - right_col_val) <= tol, axis=0) > 0.98
        non_pad_right = np.where(~right_pad)[0]
        x_max = int(w - scan_w + non_pad_right[-1] + 1) if len(non_pad_right) > 0 else w

        # If detected bounds are valid and span at least 40% of width, use them
        if (x_max - x_min) >= int(w * 0.40):
            return x_min, x_max
        return 0, w

    # -------------------------------------------------------------------------
    # Gutter & Background Analysis
    # -------------------------------------------------------------------------
    def detect_background(self, img_gray: np.ndarray) -> int:
        """Determines dominant background value using border and central pixels."""
        h, w = img_gray.shape[:2]
        if h == 0 or w == 0:
            return 255
        # Sample border pixels inset slightly from edges
        margin_x = max(1, int(w * 0.05))
        margin_y = max(1, int(h * 0.05))
        border_pixels = np.concatenate([
            img_gray[margin_y, margin_x:-margin_x] if w > 2*margin_x else img_gray[margin_y, :],
            img_gray[-margin_y, margin_x:-margin_x] if w > 2*margin_x else img_gray[-margin_y, :],
            img_gray[:, margin_x],
            img_gray[:, -margin_x]
        ])
        return int(np.median(border_pixels))

    def get_clean_rows(
        self,
        img_gray: np.ndarray,
        bg_val: int,
        tol: Optional[int] = None,
        bg_threshold: Optional[float] = None
    ) -> np.ndarray:
        """
        Returns boolean array of rows that consist purely of background
        supporting dual backgrounds (pure white, pure black, or solid row).
        """
        tol = tol or self.config.bg_tolerance
        bg_threshold = bg_threshold or self.config.bg_threshold
        h, w = img_gray.shape[:2]
        if h == 0 or w == 0:
            return np.zeros(0, dtype=bool)

        col_margin = max(1, int(w * 0.06))
        col_start = col_margin
        col_end = max(col_start + 1, w - col_margin)
        img_mid = img_gray[:, col_start:col_end]

        diff = np.abs(img_mid.astype(np.int32) - bg_val)
        is_clean = (np.mean(diff <= tol, axis=1) >= bg_threshold)

        if getattr(self.config, "enable_dual_bg_gutter", True):
            dark_thresh = getattr(self.config, "dark_bg_threshold", 25)
            light_thresh = getattr(self.config, "light_bg_threshold", 230)

            # Check if row is pure dark background (black gutter)
            is_dark_row = (np.mean(img_mid <= dark_thresh, axis=1) >= bg_threshold)
            # Check if row is pure light background (white gutter)
            is_light_row = (np.mean(img_mid >= light_thresh, axis=1) >= bg_threshold)

            is_clean = (is_clean | is_dark_row | is_light_row)

        return is_clean

    def find_gutters(self, clean_rows: np.ndarray, min_gap: Optional[int] = None) -> List[Tuple[int, int]]:
        """Finds contiguous gutter bands (start_y, end_y) that exceed min_gap."""
        min_gap = min_gap or self.config.min_gutter_gap
        h = len(clean_rows)
        gutters = []
        in_gutter = False
        start_y = 0

        for y in range(h):
            if clean_rows[y]:
                if not in_gutter:
                    start_y = y
                    in_gutter = True
            else:
                if in_gutter:
                    end_y = y - 1
                    if (end_y - start_y + 1) >= min_gap:
                        gutters.append((start_y, end_y))
                    in_gutter = False

        if in_gutter:
            end_y = h - 1
            if (end_y - start_y + 1) >= min_gap:
                gutters.append((start_y, end_y))

        return gutters

    def find_tight_horizontal_bounds(
        self,
        img_bgr: np.ndarray,
        tol: int = 14,
        content_threshold: float = 0.02
    ) -> Tuple[int, int]:
        """Vectorized horizontal margin auto-cropping."""
        h, w = img_bgr.shape[:2]
        if w < 50 or h < 50:
            return 0, w

        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
        left_bg = int(np.median(gray[:, :min(15, w)]))
        right_bg = int(np.median(gray[:, max(0, w - 15):]))

        left_diff = np.abs(gray[:, :w // 2].astype(np.int16) - left_bg) > tol
        left_content_cols = np.where(np.mean(left_diff, axis=0) > content_threshold)[0]
        hx1 = int(left_content_cols[0]) if len(left_content_cols) > 0 else 0

        right_half = gray[:, w // 2:]
        right_diff = np.abs(right_half.astype(np.int16) - right_bg) > tol
        right_content_cols = np.where(np.mean(right_diff, axis=0) > content_threshold)[0]
        hx2 = int(w // 2 + right_content_cols[-1] + 1) if len(right_content_cols) > 0 else w

        hx1 = max(0, hx1 - 2)
        hx2 = min(w, hx2 + 2)
        if (hx2 - hx1) < (w * 0.4):
            return 0, w
        return hx1, hx2

    def calculate_visual_complexity(self, img_bgr: np.ndarray, bg_val: int) -> Dict[str, float]:
        """Calculates visual richness metrics with strided arrays."""
        h, w = img_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return {"edge_density": 0.0, "color_variance": 0.0, "bg_diff": 0.0, "visual_score": 0.0}

        sample = img_bgr[::2, ::2]
        gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY) if sample.ndim == 3 else sample

        edges = cv2.Canny(gray, 40, 130)
        edge_density = float(np.mean(edges > 0))

        color_std = float(np.mean(np.std(sample.astype(np.float32), axis=(0, 1))))
        bg_diff = float(np.mean(np.abs(gray.astype(np.int16) - bg_val) > 18))

        visual_score = (
            min(1.0, edge_density * 8.0) * 0.4 +
            min(1.0, color_std / 45.0) * 0.3 +
            min(1.0, bg_diff * 1.5) * 0.3
        )
        return {
            "edge_density": round(edge_density, 4),
            "color_variance": round(color_std, 2),
            "bg_diff": round(bg_diff, 4),
            "visual_score": round(visual_score, 4)
        }

    # -------------------------------------------------------------------------
    # Entity Detection (GPU Layout + Face Model Ensemble with Batch Parallelism)
    # -------------------------------------------------------------------------
    def detect_entities_in_region(self, img_bgr: np.ndarray) -> Dict[str, Any]:
        """Single region wrapper over detect_entities_batch."""
        results = self.detect_entities_batch([img_bgr])
        return results[0] if results else {"faces": [], "bodies": [], "bubbles": [], "frames": []}

    def detect_entities_batch(self, img_bgr_list: List[np.ndarray], batch_size: int = 32) -> List[Dict[str, Any]]:
        """
        Runs batch-parallel inference on GPU across multiple regions.
        Thread-safe across multiple concurrent episode pipelines.
        """
        if not img_bgr_list:
            return []

        import torch
        from ultralytics.utils import nms, ops
        from ultralytics.data.augment import LetterBox

        yolo_model = VisualRegionDetector._yolo_model
        face_model = VisualRegionDetector._face_model
        dev = "cuda" if (torch.cuda.is_available() and self.config.device == "cuda") else "cpu"

        all_results: List[Dict[str, Any]] = [
            {"faces": [], "bodies": [], "bubbles": [], "frames": []}
            for _ in range(len(img_bgr_list))
        ]

        letterbox = LetterBox(640, auto=False, stride=32)

        with VisualRegionDetector._gpu_lock:
            if dev == "cuda":
                try:
                    torch.cuda.synchronize()
                except Exception:
                    pass

            # 1. Batch Inference for Main Layout Model (Manga109)
            if yolo_model is not None and img_bgr_list:
                try:
                    yolo_dtype = next(yolo_model.model.parameters()).dtype
                    for i in range(0, len(img_bgr_list), batch_size):
                        batch = img_bgr_list[i:i + batch_size]
                        lb_imgs = [letterbox(image=cv2.cvtColor(im, cv2.COLOR_BGR2RGB)) for im in batch]
                        batch_t = torch.from_numpy(np.stack(lb_imgs)).permute(0, 3, 1, 2).to(dev).to(yolo_dtype) / 255.0
                        with torch.inference_mode():
                            preds = yolo_model.model(batch_t)
                            nms_res = nms.non_max_suppression(preds, conf_thres=0.30, iou_thres=0.45)
                            for idx_in_b, p in enumerate(nms_res):
                                global_idx = i + idx_in_b
                                orig_shape = batch[idx_in_b].shape[:2]
                                if len(p) > 0:
                                    p_scaled = ops.scale_boxes((640, 640), p[:, :4], orig_shape)
                                    for box, conf, cls_id_t in zip(p_scaled, p[:, 4], p[:, 5]):
                                        cls_id = int(cls_id_t.item())
                                        cls_name = yolo_model.names.get(cls_id, "").lower()
                                        bbox = BBox(
                                            int(round(box[0].item())),
                                            int(round(box[1].item())),
                                            int(round(box[2].item())),
                                            int(round(box[3].item())),
                                        )
                                        if cls_name == "face" or "face" in cls_name or cls_id == 1:
                                            all_results[global_idx]["faces"].append(bbox)
                                        elif cls_name == "body" or "body" in cls_name or "character" in cls_name or cls_id == 0:
                                            all_results[global_idx]["bodies"].append(bbox)
                                        elif cls_name == "frame" or "panel" in cls_name or cls_id == 2:
                                            all_results[global_idx]["frames"].append(bbox)
                                        elif cls_name == "text" or "bubble" in cls_name or cls_id == 3:
                                            all_results[global_idx]["bubbles"].append(bbox)
                except Exception as e:
                    logger.warning(f"[VisualRegionDetector] Fast Batch Layout infer warning: {e}")
                    if dev == "cuda":
                        try:
                            torch.cuda.empty_cache()
                        except Exception:
                            pass

            # 2. Batch Inference for Auxiliary Anime Face Model
            if face_model is not None and img_bgr_list:
                try:
                    face_dtype = next(face_model.model.parameters()).dtype
                    for i in range(0, len(img_bgr_list), batch_size):
                        batch = img_bgr_list[i:i + batch_size]
                        lb_imgs = [letterbox(image=cv2.cvtColor(im, cv2.COLOR_BGR2RGB)) for im in batch]
                        batch_t = torch.from_numpy(np.stack(lb_imgs)).permute(0, 3, 1, 2).to(dev).to(face_dtype) / 255.0
                        with torch.inference_mode():
                            preds = face_model.model(batch_t)
                            nms_res = nms.non_max_suppression(preds, conf_thres=self.config.face_conf_threshold, iou_thres=0.45)
                            for idx_in_b, p in enumerate(nms_res):
                                global_idx = i + idx_in_b
                                orig_shape = batch[idx_in_b].shape[:2]
                                if len(p) > 0:
                                    p_scaled = ops.scale_boxes((640, 640), p[:, :4], orig_shape)
                                    for box in p_scaled:
                                        all_results[global_idx]["faces"].append(BBox(
                                            int(round(box[0].item())),
                                            int(round(box[1].item())),
                                            int(round(box[2].item())),
                                            int(round(box[3].item())),
                                        ))
                except Exception as e:
                    logger.warning(f"[VisualRegionDetector] Fast Batch Face infer warning: {e}")
                    if dev == "cuda":
                        try:
                            torch.cuda.empty_cache()
                        except Exception:
                            pass

            if dev == "cuda":
                try:
                    torch.cuda.synchronize()
                except Exception:
                    pass

        return all_results

    # -------------------------------------------------------------------------
    # Zero-Cut Face/Body Guardrail in Oversized Split
    # -------------------------------------------------------------------------
    def _split_oversized_block(
        self,
        img_bgr: np.ndarray,
        global_y_offset: int,
        bg_val: int,
        entities: Dict[str, Any]
    ) -> List[Tuple[int, int]]:
        """
        Splits an oversized panel while STRICTLY PRESERVING character faces and bodies.
        If no safe cut point exists, keeps the entire continuous panel unbroken.
        """
        h, w = img_bgr.shape[:2]
        target_h = self.config.target_region_height
        
        # 1. Build Forbidden Cut Ranges for Faces and Bodies
        is_forbidden = np.zeros(h, dtype=bool)
        face_pad = self.config.face_protection_padding
        body_pad = self.config.body_protection_padding

        for face in entities.get("faces", []):
            fy1 = max(0, face.y1 - face_pad)
            fy2 = min(h, face.y2 + face_pad)
            is_forbidden[fy1:fy2] = True

        for body in entities.get("bodies", []):
            # Protect upper & middle torso strictly
            by1 = max(0, body.y1 - body_pad)
            by2 = min(h, body.y2 + body_pad)
            is_forbidden[by1:by2] = True

        # 2. Compute 1D Edge Energy Profile across Y with fast downscale
        if h > 1000:
            scale_y = 0.5
            small_bgr = cv2.resize(img_bgr, (0, 0), fx=scale_y, fy=scale_y, interpolation=cv2.INTER_AREA)
            gray_small = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
            canny_small = cv2.Canny(gray_small, 40, 140)
            row_energy_small = np.mean(canny_small > 0, axis=1)
            row_energy = np.repeat(row_energy_small, 2)[:h]
            if len(row_energy) < h:
                row_energy = np.pad(row_energy, (0, h - len(row_energy)), mode='edge')
            clean_rows_small = self.get_clean_rows(gray_small, bg_val, tol=20, bg_threshold=0.90)
            clean_rows = np.repeat(clean_rows_small, 2)[:h]
            if len(clean_rows) < h:
                clean_rows = np.pad(clean_rows, (0, h - len(clean_rows)), mode='edge')
        else:
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            canny = cv2.Canny(gray, 40, 140)
            row_energy = np.mean(canny > 0, axis=1)
            clean_rows = self.get_clean_rows(gray, bg_val, tol=20, bg_threshold=0.90)
        
        # Smooth energy
        kernel_size = 31
        kernel = np.ones(kernel_size) / kernel_size
        smooth_energy = np.convolve(row_energy, kernel, mode='same')

        # 3. Dynamic Safe Cut Searching
        splits = [0]
        curr_y = 0

        while curr_y < h:
            remaining_h = h - curr_y
            if remaining_h <= self.config.max_region_height:
                splits.append(h)
                break

            ideal_y = curr_y + target_h
            min_y = curr_y + self.config.min_region_height
            max_y = min(h - 1, curr_y + self.config.max_region_height)

            best_split = None
            best_score = float('inf')

            # Search outward from ideal_y for safe non-forbidden cut with lowest edge energy
            for test_y in range(min_y, max_y + 1):
                if not is_forbidden[test_y]:
                    dist_penalty = abs(test_y - ideal_y) / float(target_h)
                    energy_penalty = float(smooth_energy[test_y]) * 5.0
                    clean_bonus = -2.0 if clean_rows[test_y] else 0.0
                    
                    score = dist_penalty + energy_penalty + clean_bonus
                    if score < best_score:
                        best_score = score
                        best_split = test_y

            if best_split is not None and best_split > curr_y:
                splits.append(best_split)
                curr_y = best_split
            else:
                # If no safe non-forbidden split found in range, try expanding search outwards
                found_expansion = False
                for delta in range(1, int(self.config.max_region_height * 0.4)):
                    y_above = ideal_y - delta
                    y_below = ideal_y + delta
                    
                    if y_below < h and not is_forbidden[y_below] and (y_below - curr_y) >= self.config.min_region_height:
                        splits.append(y_below)
                        curr_y = y_below
                        found_expansion = True
                        break
                    elif y_above >= curr_y + self.config.min_region_height and not is_forbidden[y_above]:
                        splits.append(y_above)
                        curr_y = y_above
                        found_expansion = True
                        break

                if not found_expansion:
                    # Entire block is one continuous character: DO NOT CUT, KEEP INTACT!
                    logger.info(f"[VisualRegionDetector] Continuous unbroken character panel (h={h}px): Preserved as single region without cutting.")
                    splits.append(h)
                    break

        ranges = []
        for i in range(len(splits) - 1):
            s_y = global_y_offset + splits[i]
            e_y = global_y_offset + splits[i + 1]
            if e_y > s_y:
                ranges.append((s_y, e_y))
        return ranges

    # -------------------------------------------------------------------------
    # Main Pure Visual Detection Pipeline
    # -------------------------------------------------------------------------
    def detect_pure_visual_regions(
        self,
        canvas: np.ndarray,
        bg_val: Optional[int] = None,
        source_offsets: Optional[List[Dict[str, Any]]] = None
    ) -> List[Tuple[np.ndarray, PureVisualRegion]]:
        """
        Detects pure visual regions from an ultra-tall canvas, accurately isolating
        individual panels, removing black/white side margins, and filtering out junk/empty/text-only regions.
        """
        if canvas is None or canvas.size == 0:
            return []

        h_canvas, w_canvas = canvas.shape[:2]
        if h_canvas <= 0 or w_canvas <= 0:
            return []

        logger.info(f"[VisualRegionDetector] Processing canvas ({w_canvas}x{h_canvas} px)...")

        # 1. Downscale canvas to exact 0.5x (even integer dimensions) for ultra-fast gutter & background scanning
        target_w = (w_canvas // 2) & ~1
        target_h = (h_canvas // 2) & ~1
        if target_w >= 2 and target_h >= 2 and (target_w < w_canvas or target_h < h_canvas):
            scale_s = float(target_w) / float(w_canvas)
            down_canvas = cv2.resize(canvas, (target_w, target_h), interpolation=cv2.INTER_AREA)
            down_gray = cv2.cvtColor(down_canvas, cv2.COLOR_BGR2GRAY)
            logger.info(f"[VisualRegionDetector] Downscaled canvas for fast gutter scan: {w_canvas}x{h_canvas} -> {target_w}x{target_h} (scale={scale_s:.3f})")
        else:
            scale_s = 1.0
            down_canvas = canvas
            down_gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)

        if bg_val is None:
            bg_val = self.detect_background(down_gray)

        min_gap_down = max(2, int(round(self.config.min_gutter_gap * scale_s)))
        clean_rows = self.get_clean_rows(down_gray, bg_val)
        gutters_down = self.find_gutters(clean_rows, min_gap=min_gap_down)

        raw_blocks_down: List[Tuple[int, int]] = []
        curr_y_down = 0

        for g_start, g_end in gutters_down:
            if g_start > curr_y_down:
                raw_blocks_down.append((curr_y_down, g_start))
            curr_y_down = g_end + 1

        if curr_y_down < down_gray.shape[0]:
            raw_blocks_down.append((curr_y_down, down_gray.shape[0]))

        # Map downscaled blocks to original canvas coordinates
        raw_blocks: List[Tuple[int, int]] = []
        for s_down, e_down in raw_blocks_down:
            s_orig = max(0, int(round(s_down / scale_s)))
            e_orig = min(h_canvas, int(round(e_down / scale_s)))
            if (e_orig - s_orig) >= self.config.min_region_height:
                raw_blocks.append((s_orig, e_orig))

        # 2. Extract and pre-filter all raw cropped blocks
        prepared_blocks = []
        for b_idx, (y_start, y_end) in enumerate(raw_blocks):
            block_h = y_end - y_start
            if block_h < self.config.min_region_height:
                continue

            # 3A. Vertical Tight Auto-Crop (remove vertical empty margins using downscaled map)
            s_down = max(0, int(round(y_start * scale_s)))
            e_down = min(down_gray.shape[0], int(round(y_end * scale_s)))
            block_down_gray = down_gray[s_down:e_down, :]

            block_clean_rows = self.get_clean_rows(block_down_gray, bg_val, tol=12, bg_threshold=0.98)
            non_clean_indices = np.where(~block_clean_rows)[0]

            if len(non_clean_indices) == 0:
                continue

            crop_y1 = max(0, int(round(non_clean_indices[0] / scale_s)))
            crop_y2 = min(block_h, int(round((non_clean_indices[-1] + 1) / scale_s)))
            cropped_h = crop_y2 - crop_y1

            if cropped_h < self.config.min_region_height:
                continue

            final_global_y1 = y_start + crop_y1
            final_global_y2 = y_start + crop_y2
            raw_cropped_bgr = canvas[final_global_y1:final_global_y2, 0:w_canvas]

            # 3B. Horizontal Auto-Crop (Strip black/white side padding bars)
            if self.config.horizontal_auto_crop:
                hx1, hx2 = self.find_tight_horizontal_bounds(raw_cropped_bgr, tol=self.config.horizontal_tolerance)
                cropped_bgr = raw_cropped_bgr[:, hx1:hx2].copy()
            else:
                hx1, hx2 = 0, w_canvas
                cropped_bgr = raw_cropped_bgr.copy()

            # 3C. Fast Visual Complexity Evaluation
            comp = self.calculate_visual_complexity(cropped_bgr, bg_val)
            if comp["edge_density"] < 0.008 and comp["color_variance"] < 6.0:
                continue

            prepared_blocks.append({
                "cropped_bgr": cropped_bgr,
                "final_global_y1": final_global_y1,
                "final_global_y2": final_global_y2,
                "cropped_h": cropped_h,
                "cur_w": cropped_bgr.shape[1],
                "hx1": hx1,
                "hx2": hx2,
                "comp": comp
            })

        logger.info(f"[VisualRegionDetector] Running Batch Parallel AI inference on GPU across {len(prepared_blocks)} candidate blocks...")

        # 3D. Batch GPU Inference for All Candidate Blocks simultaneously
        batch_images = [b["cropped_bgr"] for b in prepared_blocks]
        batch_entities = self.detect_entities_batch(batch_images, batch_size=32)

        candidate_regions: List[Tuple[np.ndarray, PureVisualRegion]] = []
        region_counter = 1

        for b_idx, (block_data, entities) in enumerate(zip(prepared_blocks, batch_entities), start=1):
            cropped_bgr = block_data["cropped_bgr"]
            final_global_y1 = block_data["final_global_y1"]
            final_global_y2 = block_data["final_global_y2"]
            cropped_h = block_data["cropped_h"]
            cur_w = block_data["cur_w"]
            hx1 = block_data["hx1"]
            hx2 = block_data["hx2"]
            comp = block_data["comp"]

            face_count = len(entities["faces"])
            body_count = len(entities["bodies"])
            bubble_count = len(entities["bubbles"])

            # Filter text-heavy / text-only regions (>50% text area)
            total_bubble_area = sum(b.area for b in entities["bubbles"])
            region_area = max(1, cur_w * cropped_h)
            bubble_ratio = float(total_bubble_area) / float(region_area)

            if bubble_ratio >= self.config.max_text_only_ratio:
                logger.info(f"[VisualRegionDetector] Dropping region {b_idx} (Text/Bubble Area Ratio={bubble_ratio:.2f} >= 50%): Text-heavy clutter.")
                continue

            # 3E. Split Oversized Panels with Zero-Cut Guardrail
            if cropped_h > self.config.max_region_height:
                sub_splits = self._split_oversized_block(cropped_bgr, final_global_y1, bg_val, entities)
                for sub_y1, sub_y2 in sub_splits:
                    sub_h = sub_y2 - sub_y1
                    if sub_h < self.config.min_region_height:
                        continue
                    
                    sub_raw = canvas[sub_y1:sub_y2, 0:w_canvas]
                    if self.config.horizontal_auto_crop:
                        shx1, shx2 = self.find_tight_horizontal_bounds(sub_raw, tol=self.config.horizontal_tolerance)
                        sub_bgr = sub_raw[:, shx1:shx2]
                    else:
                        shx1, shx2 = 0, w_canvas
                        sub_bgr = sub_raw

                    sub_w = sub_bgr.shape[1]
                    # Inherit entities from parent panel with vertical offset
                    offset_in_parent = sub_y1 - final_global_y1
                    sub_faces = [
                        BBox(f.x1, max(0, f.y1 - offset_in_parent), f.x2, min(sub_h, f.y2 - offset_in_parent))
                        for f in entities["faces"]
                        if (f.y2 > offset_in_parent and f.y1 < offset_in_parent + sub_h)
                    ]
                    sub_bodies = [
                        BBox(b.x1, max(0, b.y1 - offset_in_parent), b.x2, min(sub_h, b.y2 - offset_in_parent))
                        for b in entities["bodies"]
                        if (b.y2 > offset_in_parent and b.y1 < offset_in_parent + sub_h)
                    ]
                    sub_bubbles = [
                        BBox(bb.x1, max(0, bb.y1 - offset_in_parent), bb.x2, min(sub_h, bb.y2 - offset_in_parent))
                        for bb in entities["bubbles"]
                        if (bb.y2 > offset_in_parent and bb.y1 < offset_in_parent + sub_h)
                    ]
                    
                    sub_bubble_area = sum(b.area for b in sub_bubbles)
                    sub_area = max(1, sub_w * sub_h)
                    sub_bubble_ratio = float(sub_bubble_area) / float(sub_area)
                    if sub_bubble_ratio >= self.config.max_text_only_ratio:
                        logger.info(f"[VisualRegionDetector] Dropping sub-region (Text/Bubble Area Ratio={sub_bubble_ratio:.2f} >= 50%): Text-heavy clutter.")
                        continue

                    sub_comp = self.calculate_visual_complexity(sub_bgr, bg_val)

                    pvr = PureVisualRegion(
                        region_id=region_counter,
                        original_bbox=BBox(shx1, sub_y1, shx2, sub_y2),
                        pure_visual_bbox=BBox(0, 0, sub_w, sub_h),
                        confidence=min(1.0, 0.85 + sub_comp["visual_score"] * 0.15),
                        status="PURE_VISUAL",
                        visual_ratio=sub_comp["visual_score"],
                        file_name=f"{region_counter:03d}.webp",
                        body_count=len(sub_bodies),
                        face_count=len(sub_faces),
                        details={
                            "yStart": sub_y1,
                            "yEnd": sub_y2,
                            "height": sub_h,
                            "width": sub_w,
                            "x1": shx1,
                            "x2": shx2,
                            "bubble_ratio": round(sub_bubble_ratio, 3),
                            "text_area_ratio": round(sub_bubble_ratio, 3),
                            "visual_complexity": sub_comp,
                            "bubbles": [b.to_list() for b in sub_bubbles],
                            "faces": [f.to_list() for f in sub_faces],
                            "bodies": [b.to_list() for b in sub_bodies]
                        }
                    )
                    candidate_regions.append((sub_bgr, pvr))
                    region_counter += 1
            else:
                pvr = PureVisualRegion(
                    region_id=region_counter,
                    original_bbox=BBox(hx1, final_global_y1, hx2, final_global_y2),
                    pure_visual_bbox=BBox(0, 0, cur_w, cropped_h),
                    confidence=min(1.0, 0.85 + comp["visual_score"] * 0.15),
                    status="PURE_VISUAL",
                    visual_ratio=comp["visual_score"],
                    file_name=f"{region_counter:03d}.webp",
                    body_count=body_count,
                    face_count=face_count,
                    details={
                        "yStart": final_global_y1,
                        "yEnd": final_global_y2,
                        "height": cropped_h,
                        "width": cur_w,
                        "x1": hx1,
                        "x2": hx2,
                        "bubble_ratio": round(bubble_ratio, 3),
                        "text_area_ratio": round(bubble_ratio, 3),
                        "visual_complexity": comp,
                        "bubbles": [b.to_list() for b in entities["bubbles"]],
                        "faces": [f.to_list() for f in entities["faces"]],
                        "bodies": [b.to_list() for b in entities["bodies"]]
                    }
                )
                candidate_regions.append((cropped_bgr, pvr))
                region_counter += 1

        logger.info(f"[VisualRegionDetector] Successfully extracted {len(candidate_regions)} pure visual regions.")
        return candidate_regions
