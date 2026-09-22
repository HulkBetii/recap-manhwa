# -*- coding: utf-8 -*-
"""
Horizontal Projection Profile (HPP) Scanner for Comic & Manhwa Canvases.
Pure Computer Vision approach: Ultra-fast (2-5ms), zero GPU overhead.

Projects 2D image matrix onto 1D vertical axis to calculate row-wise variance,
mean luminance, and edge density. Detects solid-color gutters (white/black/gray
margins between panels) and connected content blocks.
"""

import time
import numpy as np
import cv2
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional


@dataclass
class HorizontalProjectionProfile:
    """Stores 1D vertical profile metrics along the canvas height."""
    canvas_height: int
    row_variance: np.ndarray
    row_mean: np.ndarray
    row_std: np.ndarray
    row_edge_density: np.ndarray
    scan_time_ms: float = 0.0


@dataclass
class GutterInterval:
    """Represents a detected solid gutter interval between panels."""
    y_start: int
    y_end: int
    height: int
    mean_luminance: float
    mean_variance: float
    cut_y: int
    is_clean: bool = True
    reason: str = "clean_gutter"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "y_start": self.y_start,
            "y_end": self.y_end,
            "height": self.height,
            "mean_luminance": round(float(self.mean_luminance), 2),
            "mean_variance": round(float(self.mean_variance), 2),
            "cut_y": self.cut_y,
            "is_clean": self.is_clean,
            "reason": self.reason
        }


@dataclass
class ContentBlock:
    """Represents a continuous vertical segment of comic artwork."""
    y_start: int
    y_end: int
    height: int
    mean_variance: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "y_start": self.y_start,
            "y_end": self.y_end,
            "height": self.height,
            "mean_variance": round(float(self.mean_variance), 2)
        }


class HorizontalProjectionScanner:
    """
    Pure CV 1D Horizontal Projection Profile engine.
    Downsamples canvas horizontally to 128-256px for vectorized NumPy operations,
    delivering sub-5ms gutter detection across 100,000+ pixel canvases.
    """

    def __init__(
        self,
        default_var_threshold: float = 6.0,
        min_gutter_height: int = 8,
        downsample_width: int = 128
    ):
        self.default_var_threshold = default_var_threshold
        self.min_gutter_height = min_gutter_height
        self.downsample_width = downsample_width

    def compute_profile(
        self,
        canvas_bgr: np.ndarray,
        downsample_width: Optional[int] = None
    ) -> HorizontalProjectionProfile:
        """
        Computes 1D vertical profile (variance, mean, std, edge density) for each row.
        """
        t0 = time.time()
        h, w = canvas_bgr.shape[:2]
        if h <= 0 or w <= 0:
            empty = np.zeros(0, dtype=np.float32)
            return HorizontalProjectionProfile(0, empty, empty, empty, empty, 0.0)

        target_w = downsample_width or self.downsample_width
        target_w = min(w, max(32, target_w))

        if target_w < w:
            small_bgr = cv2.resize(canvas_bgr, (target_w, h), interpolation=cv2.INTER_AREA)
        else:
            small_bgr = canvas_bgr

        gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)

        # 1. Row variance and mean across downsampled width
        row_var = np.var(gray, axis=1).astype(np.float32)
        row_mean = np.mean(gray, axis=1).astype(np.float32)
        row_std = np.sqrt(row_var)

        # 2. Row horizontal and vertical Sobel edge density
        sobel_x = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
        sobel_y = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
        row_edge = (np.mean(sobel_x, axis=1) + np.mean(sobel_y, axis=1)).astype(np.float32)

        elapsed_ms = round((time.time() - t0) * 1000, 2)

        return HorizontalProjectionProfile(
            canvas_height=h,
            row_variance=row_var,
            row_mean=row_mean,
            row_std=row_std,
            row_edge_density=row_edge,
            scan_time_ms=elapsed_ms
        )

    def find_gutters(
        self,
        canvas_bgr: np.ndarray,
        bg_val: Optional[int] = None,
        var_threshold: Optional[float] = None,
        min_gutter_height: Optional[int] = None,
        downsample_width: Optional[int] = None,
        profile: Optional[HorizontalProjectionProfile] = None
    ) -> List[GutterInterval]:
        """
        Identifies all horizontal gutter intervals where variance < var_threshold
        and pixel luminance matches the background (pure white/black or bg_val).
        Returns a list of GutterInterval objects with recommended cut coordinates.
        """
        h = canvas_bgr.shape[0]
        if h <= 0:
            return []

        if profile is None:
            profile = self.compute_profile(canvas_bgr, downsample_width=downsample_width)

        v_thresh = var_threshold if var_threshold is not None else self.default_var_threshold
        min_h = min_gutter_height if min_gutter_height is not None else self.min_gutter_height

        # A comic/manhwa gutter must match the canvas background
        if bg_val is not None:
            if bg_val >= 200:
                is_bg = profile.row_mean >= 225
            elif bg_val <= 50:
                is_bg = profile.row_mean <= 30
            else:
                is_bg = np.abs(profile.row_mean - bg_val) <= 12.0
        else:
            is_bg = (profile.row_mean >= 235) | (profile.row_mean <= 20)

        is_gutter = (profile.row_variance < v_thresh) & (profile.row_edge_density < 8.0) & is_bg

        gutters: List[GutterInterval] = []
        in_g = False
        g_start = 0

        for y, flag in enumerate(is_gutter):
            if flag and not in_g:
                in_g = True
                g_start = y
            elif not flag and in_g:
                in_g = False
                g_len = y - g_start
                if g_len >= min_h:
                    vert_std = float(np.std(profile.row_mean[g_start:y]))
                    if vert_std <= 3.5:
                        m_lum = float(np.mean(profile.row_mean[g_start:y]))
                        m_var = float(np.mean(profile.row_variance[g_start:y]))
                        cut_y = g_start + (g_len // 2)
                        gutters.append(GutterInterval(
                            y_start=g_start,
                            y_end=y,
                            height=g_len,
                            mean_luminance=m_lum,
                            mean_variance=m_var,
                            cut_y=cut_y
                        ))

        if in_g:
            g_len = h - g_start
            if g_len >= min_h:
                vert_std = float(np.std(profile.row_mean[g_start:h]))
                if vert_std <= 3.5:
                    m_lum = float(np.mean(profile.row_mean[g_start:h]))
                    m_var = float(np.mean(profile.row_variance[g_start:h]))
                    cut_y = g_start + (g_len // 2)
                    gutters.append(GutterInterval(
                        y_start=g_start,
                        y_end=h,
                        height=g_len,
                        mean_luminance=m_lum,
                        mean_variance=m_var,
                        cut_y=cut_y
                    ))

        return gutters

    def extract_content_blocks(
        self,
        canvas_bgr: np.ndarray,
        gutters: Optional[List[GutterInterval]] = None,
        var_threshold: Optional[float] = None,
        min_block_height: int = 20
    ) -> List[ContentBlock]:
        """
        Extracts continuous comic content blocks (panels/scenes) between gutters.
        """
        h = canvas_bgr.shape[0]
        if h <= 0:
            return []

        if gutters is None:
            gutters = self.find_gutters(canvas_bgr, var_threshold=var_threshold)

        if not gutters:
            return [ContentBlock(y_start=0, y_end=h, height=h)]

        blocks: List[ContentBlock] = []
        curr_y = 0

        for g in gutters:
            if g.y_start > curr_y:
                b_len = g.y_start - curr_y
                if b_len >= min_block_height:
                    blocks.append(ContentBlock(
                        y_start=curr_y,
                        y_end=g.y_start,
                        height=b_len
                    ))
            curr_y = g.y_end

        if curr_y < h:
            b_len = h - curr_y
            if b_len >= min_block_height:
                blocks.append(ContentBlock(
                    y_start=curr_y,
                    y_end=h,
                    height=b_len
                ))

        return blocks

    def snap_to_panel_edge(
        self,
        canvas_bgr: np.ndarray,
        cut_y: int,
        search_radius: int = 15
    ) -> int:
        """
        Snaps a cut coordinate to the nearest high-contrast horizontal edge (panel border)
        within +/- search_radius pixels, preventing 1-2px border slivers.
        """
        h, w = canvas_bgr.shape[:2]
        y_min = max(0, cut_y - search_radius)
        y_max = min(h, cut_y + search_radius + 1)
        if y_max - y_min <= 2:
            return cut_y

        sub_band = canvas_bgr[y_min:y_max, :]
        gray_band = cv2.cvtColor(sub_band, cv2.COLOR_BGR2GRAY)
        sobel_y = np.abs(cv2.Sobel(gray_band, cv2.CV_32F, 0, 1, ksize=3))
        row_edge_strength = np.mean(sobel_y, axis=1)

        best_offset = int(np.argmax(row_edge_strength))
        if row_edge_strength[best_offset] > 15.0:
            return y_min + best_offset
        return cut_y
