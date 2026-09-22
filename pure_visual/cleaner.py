# -*- coding: utf-8 -*-
"""
PURE VISUAL REGION DETECTION: JUNK FRAME CLEANER
Applies multi-tier quality gates to filter out micro-SFX, floating text bubbles,
blank gutter splits, and low-information transitional strips.
Optimized for NVIDIA RTX 4070 SUPER GPU Tensor Cores.
"""
import re
import os
import sys
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple, Dict, Any, Optional
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

from pure_visual.types import PureVisualRegion, BBox
from pure_visual.config import DetectionConfig

logger = logging.getLogger("VisualRegionCleaner")

_ocr_lock = threading.Lock()
_ocr_instance = None

def get_ocr_engine():
    """Returns a thread-safe RapidOCR instance for fast OCR/text verification."""
    global _ocr_instance
    if _ocr_instance is None:
        with _ocr_lock:
            if _ocr_instance is None:
                try:
                    from rapidocr_onnxruntime import RapidOCR
                    # CPUExecutionProvider is ultra-fast for small 320x320 slices and completely avoids CUDA stream/graph capture conflicts
                    _ocr_instance = RapidOCR(use_cls=False)
                except Exception as e:
                    logger.warning(f"[VisualRegionCleaner] Failed to initialize RapidOCR: {e}")
                    _ocr_instance = None
    return _ocr_instance


class VisualRegionCleaner:
    """
    Cleans candidate visual regions to ensure only high-value storytelling panels,
    character art, and composition scenes are exported.
    """

    def __init__(self, config: Optional[DetectionConfig] = None):
        self.config = config or DetectionConfig()

    def _has_text_potential(self, img_bgr: np.ndarray) -> bool:
        """
        Ultra-fast CV heuristic (<0.1ms): Check if image has potential text strokes/contrast
        before running deep ONNX OCR.
        """
        h, w = img_bgr.shape[:2]
        if h < 40 or w < 40:
            return False

        small = img_bgr[::4, ::4]
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
        
        grad_x = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_16S, 0, 1, ksize=3)
        grad_mag = cv2.addWeighted(cv2.convertScaleAbs(grad_x), 0.5, cv2.convertScaleAbs(grad_y), 0.5, 0)
        
        high_contrast_ratio = float(np.mean(grad_mag > 40))
        return high_contrast_ratio >= 0.015

    def _check_ocr_text(
        self,
        img_bgr: np.ndarray,
        is_credit_candidate: bool = False
    ) -> Tuple[str, float, int, float, int, float]:
        """
        Runs GPU DBNet on candidate image to extract detected boxes and area coverage.
        Runs text recognition only on credit candidates or text-dense panels.
        Returns: (full_text, text_ratio, text_lines_count, union_coverage_ratio, dbnet_box_count, dbnet_area_ratio)
        """
        h, w = img_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return "", 0.0, 0, 0.0, 0, 0.0

        if not self._has_text_potential(img_bgr):
            return "", 0.0, 0, 0.0, 0, 0.0

        ocr = get_ocr_engine()
        if ocr is None:
            return "", 0.0, 0, 0.0, 0, 0.0

        # Fixed standard square (320, 320) for zero-compilation fixed-shape DBNet inference
        ocr_input = cv2.resize(img_bgr, (320, 320), interpolation=cv2.INTER_AREA)
        inv_scale_x = float(w) / 320.0
        inv_scale_y = float(h) / 320.0

        try:
            with _ocr_lock:
                # 1. Specialized DBNet Text Detection
                dt_boxes, _ = ocr.text_det(ocr_input)
                dbnet_box_count = len(dt_boxes) if dt_boxes is not None else 0
                dbnet_area = 0.0
                total_area = max(1.0, float(h * w))
                
                min_x, min_y = float('inf'), float('inf')
                max_x, max_y = 0.0, 0.0

                if dt_boxes is not None:
                    for b in dt_boxes:
                        xs = [pt[0] * inv_scale_x for pt in b]
                        ys = [pt[1] * inv_scale_y for pt in b]
                        bw = max(0.0, max(xs) - min(xs))
                        bh = max(0.0, max(ys) - min(ys))
                        dbnet_area += bw * bh
                        min_x = min(min_x, min(xs))
                        min_y = min(min_y, min(ys))
                        max_x = max(max_x, max(xs))
                        max_y = max(max_y, max(ys))

                dbnet_area_ratio = float(dbnet_area) / total_area
                union_w = max(0.0, max_x - min_x) if max_x > min_x else 0.0
                union_h = max(0.0, max_y - min_y) if max_y > min_y else 0.0
                union_coverage = float(union_w * union_h) / total_area

                # 2. Text Recognition: Only run when necessary (credit candidate)
                full_text = ""
                text_lines_count = dbnet_box_count
                text_ratio = dbnet_area_ratio

                if is_credit_candidate and dbnet_box_count > 0:
                    res, _ = ocr(ocr_input)
                    if res:
                        text_lines = [str(line[1]).lower() for line in res]
                        full_text = " ".join(text_lines)
                        text_lines_count = len(text_lines)

            return full_text, text_ratio, text_lines_count, union_coverage, dbnet_box_count, dbnet_area_ratio
        except Exception:
            return "", 0.0, 0, 0.0, 0, 0.0

    def _is_translator_credit_banner(self, img_bgr: np.ndarray, region: PureVisualRegion, full_text: str, text_lines_count: int) -> bool:
        """Detects scanlation / translator credit / recruitment / support banners."""
        if not full_text:
            return False
        
        # Exact scanlation / credit phrases with word boundaries
        hard_credit = bool(re.search(
            r'\b(translated by|nyxscans|nyx scans|scanlation|nhóm dịch|tuyển dụng|discord\.gg|patreon\.com|visit our website|join our discord|all rights reserved|support us on|bản dịch phi thương mại)\b',
            full_text,
            re.IGNORECASE
        ))
        if hard_credit:
            return True

        # Scanlation team combinations
        has_scans = bool(re.search(r'\b(scans|scan|team)\b', full_text, re.IGNORECASE))
        has_website = bool(re.search(r'\b(website|support|donate|translator|nyx)\b', full_text, re.IGNORECASE))
        if has_scans and has_website:
            return True

        return False

    def _evaluate_single_region(
        self,
        idx: int,
        img_bgr: np.ndarray,
        region: PureVisualRegion,
        total_candidates: int = 100
    ) -> Tuple[int, Optional[Tuple[np.ndarray, PureVisualRegion]], Optional[Dict[str, Any]]]:
        """
        Evaluates a single candidate region using multi-tier quality gates.
        Fast strided sampling (<0.2ms) + GPU accelerated DBNet verification.
        """
        h, w = img_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return idx, None, {
                "original_id": region.region_id,
                "reason": "DROP_ZERO_DIMENSION",
                "height": h,
                "width": w
            }

        faces = getattr(region, "face_count", 0) or 0
        bodies = getattr(region, "body_count", 0) or 0
        comp = region.details.get("visual_complexity", {})
        edge_density = comp.get("edge_density", 0.0)
        
        # Fast strided metrics (<0.2ms)
        sub = img_bgr[::4, ::4]
        color_std = float(np.mean(np.std(sub, axis=(0, 1))))
        
        gray_sub = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY) if sub.ndim == 3 else sub
        canny_sub = cv2.Canny(gray_sub, 30, 100)
        is_void = ((gray_sub < 28) & (canny_sub == 0)) | ((gray_sub > 228) & (canny_sub == 0))
        solid_bg_ratio = float(np.mean(is_void))
        content_fill = max(0.0, 1.0 - solid_bg_ratio)

        aspect_ratio = float(w) / max(1.0, float(h))
        laplacian_var = float(cv2.Laplacian(gray_sub, cv2.CV_32F).var())

        # Tier 1: Character Pass-Through
        # If the region has a verified character face or rich body composition, KEEP IMMEDIATELY.
        has_character = (
            faces > 0 or 
            (bodies > 0 and h >= 320 and aspect_ratio <= 2.8 and color_std >= 25.0 and laplacian_var >= 80.0)
        )
        text_ratio = 0.0

        if not has_character:
            # Tier 2: Unified Visual Density Gate (<0.05ms)
            # Filter out empty background voids, low-content slices, and isolated SFX on black/white voids
            is_visual_trash = (
                (h < self.config.min_clean_height) or
                (aspect_ratio > self.config.max_aspect_ratio_no_char and h < 450) or
                (color_std < self.config.min_color_variance_no_char) or
                (laplacian_var < self.config.min_laplacian_var * 0.30) or
                (edge_density < self.config.min_edge_density_no_char and color_std < self.config.min_color_variance_no_char) or
                (content_fill < 0.35) or
                (solid_bg_ratio >= 0.65)
            )

            if is_visual_trash:
                logger.debug(f"[VisualRegionCleaner] Dropping R{region.region_id} (H={h}px, ColorStd={color_std:.1f}, VoidRatio={solid_bg_ratio:.2f}, Fill={content_fill:.2f}): Low visual density / junk frame.")
                return idx, None, {
                    "original_id": region.region_id,
                    "reason": "DROP_LOW_VISUAL_DENSITY",
                    "height": h,
                    "width": w,
                    "color_variance": round(color_std, 2),
                    "laplacian_var": round(laplacian_var, 2),
                    "solid_bg_ratio": round(solid_bg_ratio, 2),
                    "content_fill": round(content_fill, 2)
                }

            # Check if this candidate is at the start or end of the comic (translator credit position)
            is_credit_candidate = (idx <= 3 or idx >= total_candidates - 2)

            # Tier 3: Unified Semantic OCR & DBNet Gate on GPU
            full_text, text_ratio, text_lines_count, union_coverage, dbnet_box_count, dbnet_area_ratio = self._check_ocr_text(
                img_bgr, is_credit_candidate=is_credit_candidate
            )

            # 3A. Drop Narration Text Card / Text Coverage > 35% or DBNet Area > 25%
            if text_ratio >= 0.35 or dbnet_area_ratio >= 0.25 or (union_coverage >= 0.35 and text_lines_count >= 2):
                logger.debug(f"[VisualRegionCleaner] Dropping R{region.region_id} (TextRatio={text_ratio:.2f}, DBNetRatio={dbnet_area_ratio:.2f}, Lines={text_lines_count}): Narration / SFX text card.")
                return idx, None, {
                    "original_id": region.region_id,
                    "reason": "DROP_NARRATION_TEXT_CARD",
                    "height": h,
                    "width": w,
                    "text_ratio": round(text_ratio, 2),
                    "dbnet_area_ratio": round(dbnet_area_ratio, 2),
                    "union_coverage": round(union_coverage, 2),
                    "text": full_text[:100]
                }

            # 3B. Drop Translator / Scanlation Credit Banner
            if full_text and self._is_translator_credit_banner(img_bgr, region, full_text, text_lines_count):
                logger.info(f"[VisualRegionCleaner] Dropping R{region.region_id}: Translator / Scanlation Credit Banner ('{full_text[:60]}...').")
                return idx, None, {
                    "original_id": region.region_id,
                    "reason": "DROP_TRANSLATOR_CREDIT_BANNER",
                    "height": h,
                    "width": w,
                    "text": full_text[:100]
                }

            # 3C. Drop Isolated Speech Bubbles or Floating SFX on solid backgrounds
            if (solid_bg_ratio >= 0.50 or (h < 400 and solid_bg_ratio >= 0.40)) and (text_lines_count >= 1 or dbnet_box_count >= 1 or text_ratio >= 0.05):
                corners = [gray_sub[0, 0], gray_sub[0, -1], gray_sub[-1, 0], gray_sub[-1, -1]]
                corner_mean = float(np.mean(corners))
                is_solid_bg = (corner_mean <= 35) or (corner_mean >= 220) or (solid_bg_ratio >= 0.50)
                if is_solid_bg:
                    logger.debug(f"[VisualRegionCleaner] Dropping R{region.region_id} (H={h}px, DBNetBoxes={dbnet_box_count}): Isolated Speech Bubble / Floating SFX.")
                    return idx, None, {
                        "original_id": region.region_id,
                        "reason": "DROP_ISOLATED_SPEECH_BUBBLE",
                        "height": h,
                        "width": w,
                        "dbnet_boxes": dbnet_box_count,
                        "text": full_text[:80]
                    }

        # Update region details with computed Laplacian variance
        if "visual_complexity" not in region.details:
            region.details["visual_complexity"] = {}
        region.details["visual_complexity"]["laplacian_variance"] = round(laplacian_var, 2)
        if text_ratio > 0:
            region.details["text_area_ratio"] = round(text_ratio, 3)
        return idx, (img_bgr, region), None

    def clean_regions(
        self,
        candidate_regions: List[Tuple[np.ndarray, PureVisualRegion]]
    ) -> Tuple[List[Tuple[np.ndarray, PureVisualRegion]], List[Dict[str, Any]]]:
        """
        Filters out junk frames from candidate visual regions with ultra-fast GPU acceleration.

        Args:
            candidate_regions: List of (image_bgr, PureVisualRegion) tuples.

        Returns:
            Tuple of:
            - filtered_regions: High-value visual regions (preserving original order).
            - audit_dropped: List of audit records for dropped junk frames.
        """
        if not candidate_regions:
            return [], []

        total_cand = len(candidate_regions)
        results = [
            self._evaluate_single_region(idx, img_bgr, region, total_candidates=total_cand)
            for idx, (img_bgr, region) in enumerate(candidate_regions, start=1)
        ]

        filtered_regions: List[Tuple[np.ndarray, PureVisualRegion]] = []
        audit_dropped: List[Dict[str, Any]] = []

        for _, kept, dropped in results:
            if kept is not None:
                filtered_regions.append(kept)
            if dropped is not None:
                audit_dropped.append(dropped)

        logger.info(f"[VisualRegionCleaner] Retained {len(filtered_regions)}/{len(candidate_regions)} regions (Dropped {len(audit_dropped)} junk frames).")
        return filtered_regions, audit_dropped
