# -*- coding: utf-8 -*-
"""
Visual Boundary Scanner: 1D Vertical Signal Analysis for Comic/Manhwa Canvases.

Treats the Y axis of an extremely tall vertical comic image as a 1D signal.
Computes multi-dimensional visual features:
- Luminance & Local Contrast
- Color Distribution & Color Transition Distance
- Edge Density & Texture Complexity
- Horizontal Structures (Panel borders & Gutter dividers)
- Content Width & Left/Right Margin Shifts
- Local Image Similarity & Visual Continuity across Y

Produces candidate page boundaries with rich metadata and type classification.
"""

import math
import numpy as np
import cv2
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional


class BoundaryClassification:
    SAFE_CUT = "SAFE_CUT"
    CONTINUOUS_CHARACTER = "CONTINUOUS_CHARACTER"
    CONTINUOUS_ACTION = "CONTINUOUS_ACTION"
    CONTINUOUS_SCENE = "CONTINUOUS_SCENE"
    SCENE_TRANSITION = "SCENE_TRANSITION"
    COMPOSITION_TRANSITION = "COMPOSITION_TRANSITION"
    EDGE_BUBBLE = "EDGE_BUBBLE"
    INTERNAL_BUBBLE = "INTERNAL_BUBBLE"
    OBJECT_CONTINUATION = "OBJECT_CONTINUATION"
    UNSAFE_CUT = "UNSAFE_CUT"

    ALL = [
        SAFE_CUT,
        CONTINUOUS_CHARACTER,
        CONTINUOUS_ACTION,
        CONTINUOUS_SCENE,
        SCENE_TRANSITION,
        COMPOSITION_TRANSITION,
        EDGE_BUBBLE,
        INTERNAL_BUBBLE,
        OBJECT_CONTINUATION,
        UNSAFE_CUT,
    ]


class BoundaryRecommendation:
    RECOMMEND_CUT = "RECOMMEND_CUT"
    FORBID_CUT = "FORBID_CUT"
    OPTIONAL_CUT = "OPTIONAL_CUT"


@dataclass
class BoundaryEvaluation:
    classification: str
    recommendation: str
    confidence: float
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "classification": self.classification,
            "recommendation": self.recommendation,
            "confidence": round(float(self.confidence), 4),
            "reason": self.reason,
            "details": self.details
        }


@dataclass
class BoundaryCandidate:
    y: int
    candidate_type: str
    score: float = 0.5
    hard: bool = False
    is_safe: bool = True
    rejection_reason: str = ""
    visual_transition_score: float = 0.0
    composition_score: float = 0.0
    panel_boundary_score: float = 0.0
    content_width_score: float = 0.0
    natural_endpoint_score: float = 0.0
    visual_continuity: float = 0.5
    speech_edge_score: float = 0.0
    action_continuity: float = 0.0
    same_composition_score: float = 0.0
    penalties: Dict[str, float] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)
    classification: str = ""
    recommendation: str = ""
    confidence: float = 0.0
    reason: str = ""
    evaluation: Optional[BoundaryEvaluation] = None

    def to_dict(self) -> Dict[str, Any]:
        cls_val = self.classification or self.candidate_type
        rec_val = self.recommendation or (
            BoundaryRecommendation.RECOMMEND_CUT if (self.is_safe and self.score >= 0.35)
            else (BoundaryRecommendation.FORBID_CUT if not self.is_safe else BoundaryRecommendation.OPTIONAL_CUT)
        )
        conf_val = self.confidence if self.confidence > 0 else self.score
        rsn_val = self.reason or self.rejection_reason or ("safe_visual_cut" if self.is_safe else "unsafe")
        return {
            "y": int(self.y),
            "type": self.candidate_type,
            "candidate_type": self.candidate_type,
            "score": round(float(self.score), 4),
            "boundary_score": round(float(self.score), 4),
            "hard": bool(self.hard),
            "is_safe": bool(self.is_safe),
            "rejection_reason": self.rejection_reason,
            "visual_transition_score": round(float(self.visual_transition_score), 4),
            "composition_score": round(float(self.composition_score), 4),
            "panel_boundary_score": round(float(self.panel_boundary_score), 4),
            "content_width_score": round(float(self.content_width_score), 4),
            "natural_endpoint_score": round(float(self.natural_endpoint_score), 4),
            "visual_continuity": round(float(self.visual_continuity), 4),
            "continuity": round(float(self.visual_continuity), 4),
            "speech_edge_score": round(float(self.speech_edge_score), 4),
            "action_continuity": round(float(self.action_continuity), 4),
            "same_composition_score": round(float(self.same_composition_score), 4),
            "penalties": {k: round(float(v), 4) for k, v in self.penalties.items()},
            "details": self.details,
            "classification": cls_val,
            "recommendation": rec_val,
            "confidence": round(float(conf_val), 4),
            "reason": rsn_val,
            "evaluation": self.evaluation.to_dict() if self.evaluation else {
                "classification": cls_val,
                "recommendation": rec_val,
                "confidence": round(float(conf_val), 4),
                "reason": rsn_val,
                "details": self.details
            }
        }


class VisualBoundaryScanner:
    """
    Fast, robust 1D vertical visual signal scanner for long manhwa/comic canvases.
    Downscales width for high-throughput scanning while preserving exact 1:1 Y coordinates.
    """

    def __init__(
        self,
        scan_width: int = 200,
        window_size: int = 80,
        canny_low: int = 40,
        canny_high: int = 120,
        min_candidate_distance: int = 40,
        bg_diff_threshold: float = 12.0
    ):
        self.scan_width = scan_width
        self.window_size = window_size
        self.canny_low = canny_low
        self.canny_high = canny_high
        self.min_candidate_distance = min_candidate_distance
        self.bg_diff_threshold = bg_diff_threshold

    @staticmethod
    def _moving_average_1d(arr: np.ndarray, w: int) -> np.ndarray:
        if len(arr) == 0 or w <= 1:
            return arr.astype(np.float32)
        w = min(w, len(arr))
        kernel = np.ones(w, dtype=np.float32) / float(w)
        return np.convolve(arr.astype(np.float32), kernel, mode="same")

    @staticmethod
    def _box_window_means(signal: np.ndarray, window: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        Computes mean of signal in upper window [y - window, y] and lower window [y, y + window].
        Uses cumsum for O(H) computational complexity.
        """
        h = len(signal)
        if h == 0:
            return np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.float32)

        csum = np.zeros(h + 1, dtype=np.float64)
        csum[1:] = np.cumsum(signal.astype(np.float64))

        # Upper window: [max(0, y - window), y]
        upper_start = np.maximum(0, np.arange(h) - window)
        upper_end = np.arange(h)
        upper_len = np.maximum(1, upper_end - upper_start)
        upper_means = (csum[upper_end] - csum[upper_start]) / upper_len

        # Lower window: [y, min(h, y + window)]
        lower_start = np.arange(h)
        lower_end = np.minimum(h, np.arange(h) + window)
        lower_len = np.maximum(1, lower_end - lower_start)
        lower_means = (csum[lower_end] - csum[lower_start]) / lower_len

        return upper_means.astype(np.float32), lower_means.astype(np.float32)

    def scan_visual_signals(
        self,
        canvas_bgr: np.ndarray,
        bg_val: int = 255
    ) -> Dict[str, np.ndarray]:
        """
        Scans canvas vertically and calculates 1D visual signals along Y.
        Returns a dictionary of 1D arrays of length total_height.
        """
        total_h, total_w = canvas_bgr.shape[:2]
        if total_h <= 0 or total_w <= 0:
            return {}

        target_w = min(self.scan_width, total_w)
        if target_w < total_w:
            small_bgr = cv2.resize(canvas_bgr, (target_w, total_h), interpolation=cv2.INTER_AREA)
        else:
            small_bgr = canvas_bgr

        gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2HSV)

        # 1. Luminance & Background difference
        row_gray_means = np.mean(gray, axis=1).astype(np.float32)
        row_gray_stds = np.std(gray, axis=1).astype(np.float32)
        bg_diff = np.abs(row_gray_means - float(bg_val))

        # 2. Edge density & texture density
        canny = cv2.Canny(gray, self.canny_low, self.canny_high)
        edge_density = (np.mean(canny > 0, axis=1)).astype(np.float32)

        # Vertical gradient (|dI/dy|) for horizontal contrast steps
        sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        vert_grad = (np.mean(np.abs(sobel_y), axis=1) / 255.0).astype(np.float32)

        # Horizontal gradient (|dI/dx|) for vertical strokes & action / speed lines
        sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        horiz_grad = (np.mean(np.abs(sobel_x), axis=1) / 255.0).astype(np.float32)

        # Directional action line & kinetic effect density
        action_line_density = np.clip(
            0.6 * horiz_grad * 4.0 + 0.4 * edge_density * 3.0,
            0.0, 1.0
        ).astype(np.float32)
        smooth_action = self._moving_average_1d(action_line_density, 21)

        # 3. Horizontal structure detection (panel borders & frame boundaries)
        horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, target_w // 10), 1))
        horiz_lines = cv2.morphologyEx(canny, cv2.MORPH_OPEN, horiz_kernel)
        border_density = (np.mean(horiz_lines > 0, axis=1)).astype(np.float32)

        # 4. Color distribution along Y
        hue_vals = hsv[:, :, 0].astype(np.float32)
        sat_vals = hsv[:, :, 1].astype(np.float32)
        val_vals = hsv[:, :, 2].astype(np.float32)

        h_mean = np.mean(hue_vals, axis=1)
        s_mean = np.mean(sat_vals, axis=1)
        v_mean = np.mean(val_vals, axis=1)

        # Color transition distance: compare window above Y and window below Y
        w_size = self.window_size
        h_up, h_dn = self._box_window_means(h_mean, w_size)
        s_up, s_dn = self._box_window_means(s_mean, w_size)
        v_up, v_dn = self._box_window_means(v_mean, w_size)

        # Circular hue difference in [0, 90]
        hue_diff = np.abs(h_up - h_dn)
        hue_diff = np.minimum(hue_diff, 180.0 - hue_diff) / 90.0
        sat_diff = np.abs(s_up - s_dn) / 255.0
        val_diff = np.abs(v_up - v_dn) / 255.0

        color_transition = np.clip(0.4 * hue_diff + 0.3 * sat_diff + 0.3 * val_diff, 0.0, 1.0).astype(np.float32)

        # 5. Content width & margin analysis (Vectorized for high-speed scanning)
        non_bg_mask = (np.abs(gray.astype(np.int16) - bg_val) > self.bg_diff_threshold) | (canny > 0)
        content_row_mask = np.any(non_bg_mask, axis=1)

        first_idx = (non_bg_mask != 0).argmax(axis=1)
        last_idx = target_w - 1 - (non_bg_mask[:, ::-1] != 0).argmax(axis=1)
        left_margin = np.where(content_row_mask, first_idx.astype(np.float32) / float(target_w), 0.0).astype(np.float32)
        right_margin = np.where(content_row_mask, (target_w - 1 - last_idx).astype(np.float32) / float(target_w), 0.0).astype(np.float32)
        content_width = np.where(content_row_mask, (last_idx - first_idx + 1).astype(np.float32) / float(target_w), 0.0).astype(np.float32)

        # Width transition: difference in content width above and below Y
        w_up, w_dn = self._box_window_means(content_width, w_size // 2)
        width_transition = np.clip(np.abs(w_up - w_dn), 0.0, 1.0).astype(np.float32)

        # 6. Visual Continuity C(y) in [0.0..1.0]
        e_up, e_dn = self._box_window_means(edge_density, w_size)
        edge_diff = np.abs(e_up - e_dn)

        continuity_disruption = np.clip(
            0.70 * color_transition + 0.35 * width_transition + 0.20 * edge_diff,
            0.0, 1.0
        )
        base_continuity = (1.0 - continuity_disruption).astype(np.float32)

        # Action and connected layout continuity reinforcement
        action_boost = np.clip(0.35 * smooth_action, 0.0, 0.35)
        # Margin alignment bonus for connected panels of the same width
        aligned_margins = np.clip(1.0 - (width_transition * 2.0), 0.0, 1.0) * 0.10

        # Sub-band partial gutter analysis: covers 60-70% SFX / speech bubble occlusion
        w_band1 = max(5, int(target_w * 0.35))
        w_band2 = max(w_band1 + 5, int(target_w * 0.65))
        left_band = gray[:, :w_band1]
        mid_band = gray[:, w_band1:w_band2]
        right_band = gray[:, w_band2:]

        left_diff = np.abs(np.mean(left_band, axis=1) - float(bg_val))
        mid_diff = np.abs(np.mean(mid_band, axis=1) - float(bg_val))
        right_diff = np.abs(np.mean(right_band, axis=1) - float(bg_val))

        left_edges = np.mean(canny[:, :w_band1] > 0, axis=1)
        mid_edges = np.mean(canny[:, w_band1:w_band2] > 0, axis=1)
        right_edges = np.mean(canny[:, w_band2:] > 0, axis=1)

        is_left_gutter = (left_diff < self.bg_diff_threshold) & (left_edges < 0.02)
        is_mid_gutter = (mid_diff < self.bg_diff_threshold) & (mid_edges < 0.02)
        is_right_gutter = (right_diff < self.bg_diff_threshold) & (right_edges < 0.02)

        # Gutter signal: full clean gutter or partial gutter (gutter with horizontal border divider)
        is_full_gutter = (bg_diff < self.bg_diff_threshold) & (edge_density < 0.015) & (row_gray_stds < 10.0)
        is_partial_gutter = (border_density > 0.12) & (is_left_gutter | is_right_gutter | is_mid_gutter) & (edge_density < 0.05)

        gutter_strength = np.zeros(total_h, dtype=np.float32)
        gutter_strength[is_partial_gutter] = 0.60
        gutter_strength[is_full_gutter] = 1.0
        smooth_gutter = self._moving_average_1d(gutter_strength, 15)

        # Content presence: drops towards 0 across clean gutters/whitespace.
        content_presence = np.clip(1.0 - smooth_gutter, 0.0, 1.0).astype(np.float32)
        visual_continuity = np.clip(
            (base_continuity * content_presence) + action_boost + (aligned_margins * content_presence),
            0.0, 1.0
        ).astype(np.float32)

        # Scene transition signal: combines sharp color transition, contrast step, and continuity drop
        scene_transition = np.clip(
            0.5 * color_transition + 0.3 * vert_grad + 0.2 * (1.0 - visual_continuity),
            0.0, 1.0
        ).astype(np.float32)

        # Composition transition: margin changes + width changes
        comp_transition = np.clip(
            0.6 * width_transition + 0.4 * border_density,
            0.0, 1.0
        ).astype(np.float32)

        return {
            "row_gray_means": row_gray_means,
            "row_gray_stds": row_gray_stds,
            "bg_diff": bg_diff,
            "edge_density": edge_density,
            "vert_grad": vert_grad,
            "horiz_grad": horiz_grad,
            "action_line_density": smooth_action,
            "border_density": border_density,
            "color_transition": color_transition,
            "content_width": content_width,
            "width_transition": width_transition,
            "visual_continuity": visual_continuity,
            "gutter_strength": smooth_gutter,
            "scene_transition": scene_transition,
            "comp_transition": comp_transition
        }

    def generate_candidates(
        self,
        canvas_bgr: np.ndarray,
        bg_val: int = 255,
        min_page_height: int = 300,
        max_candidates: int = 350,
        precomputed_signals: Optional[Dict[str, np.ndarray]] = None
    ) -> List[BoundaryCandidate]:
        """
        Scans canvas and generates candidate page boundary cuts with 1D NMS filtering.
        Returns a sorted list of BoundaryCandidate objects.
        """
        total_h = canvas_bgr.shape[0]
        if total_h <= 0:
            return []

        signals = precomputed_signals if precomputed_signals is not None else self.scan_visual_signals(canvas_bgr, bg_val=bg_val)
        if not signals:
            return []

        scene_trans = signals["scene_transition"]
        comp_trans = signals["comp_transition"]
        gutter_str = signals["gutter_strength"]
        border_den = signals["border_density"]
        width_trans = signals["width_transition"]
        continuity = signals["visual_continuity"]
        bg_diff = signals["bg_diff"]
        action_den = signals.get("action_line_density", np.zeros(total_h, dtype=np.float32))

        # Composite candidate signal: places where transitions, borders, or gutters are strong.
        # Strengthened for zero-gutter scene transitions (no visible whitespace).
        raw_signal = (
            0.30 * gutter_str +
            0.25 * border_den +
            0.25 * scene_trans +
            0.15 * comp_trans +
            0.05 * width_trans
        )

        # Find local peaks of raw_signal and gutter center points
        candidates_dict: Dict[int, BoundaryCandidate] = {}

        # 1. Gutter runs: find center of contiguous gutter spans
        is_gutter = gutter_str > 0.45
        in_gutter = False
        g_start = 0
        for y in range(total_h):
            if is_gutter[y] and not in_gutter:
                in_gutter = True
                g_start = y
            elif not is_gutter[y] and in_gutter:
                in_gutter = False
                g_end = y
                g_len = g_end - g_start
                if g_len >= 8:
                    center_y = int((g_start + g_end) // 2)
                    sample_top = max(0, g_start - 30)
                    sample_bot = min(total_h, g_end + 30)
                    is_scene_shift = False
                    if sample_top < g_start and g_end < sample_bot:
                        top_slice = canvas_bgr[sample_top:g_start, :]
                        bot_slice = canvas_bgr[g_end:sample_bot, :]
                        if top_slice.size > 0 and bot_slice.size > 0:
                            top_med = np.median(top_slice.reshape(-1, 3), axis=0)
                            bot_med = np.median(bot_slice.reshape(-1, 3), axis=0)
                            if float(np.linalg.norm(top_med - bot_med)) > 55.0:
                                is_scene_shift = True

                    if is_scene_shift or scene_trans[center_y] >= 0.35:
                        c_type = "scene_transition"
                    elif border_den[center_y] > 0.1:
                        c_type = "panel_boundary"
                    else:
                        c_type = "natural_visual_endpoint"
                    is_internal_ws = g_len < 35 and continuity[center_y] > 0.55
                    base_score = float(min(1.0, 0.4 + 0.5 * (g_len / 50.0))) if not is_internal_ws else 0.35
                    candidates_dict[center_y] = BoundaryCandidate(
                        y=center_y,
                        candidate_type=c_type,
                        score=base_score,
                        hard=False,
                        visual_transition_score=1.0 if is_scene_shift else float(scene_trans[center_y]),
                        panel_boundary_score=float(border_den[center_y]),
                        natural_endpoint_score=float(min(1.0, g_len / 40.0)),
                        visual_continuity=float(continuity[center_y]),
                        action_continuity=float(action_den[center_y]),
                        details={
                            "gutter_span": (g_start, g_end),
                            "gutter_length": g_len,
                            "is_internal_whitespace": is_internal_ws
                        }
                    )
        if in_gutter:
            g_end = total_h
            if g_end - g_start >= 8:
                center_y = int((g_start + g_end) // 2)
                candidates_dict[center_y] = BoundaryCandidate(
                    y=center_y,
                    candidate_type="natural_visual_endpoint",
                    score=0.7,
                    hard=False,
                    visual_continuity=float(continuity[center_y]),
                    action_continuity=float(action_den[center_y]),
                    details={"gutter_span": (g_start, g_end), "gutter_length": g_end - g_start}
                )

        # Collect detected gutter spans so we don't spawn redundant transitions inside gutters
        gutter_spans = [
            c.details["gutter_span"] for c in candidates_dict.values()
            if c.details.get("gutter_span") and (c.details["gutter_span"][1] - c.details["gutter_span"][0]) >= 25
        ]

        # 2. Panel border peaks (horizontal lines)
        border_thresh = 0.15
        for y in range(5, total_h - 5):
            if any(gs - 8 <= y <= ge + 8 for gs, ge in gutter_spans):
                continue
            b_val = border_den[y]
            if b_val > border_thresh and b_val >= border_den[y - 1] and b_val >= border_den[y + 1]:
                cont_val = float(continuity[y])
                act_val = float(action_den[y])
                s_val = float(scene_trans[y])
                c_val = float(comp_trans[y])
                is_connected = (cont_val > 0.60 or act_val > 0.25) and (s_val < 0.40)
                border_score = float(min(1.0, 0.5 + b_val))
                c_type = "scene_transition" if s_val >= 0.50 else "panel_boundary"
                candidates_dict[y] = BoundaryCandidate(
                    y=y,
                    candidate_type=c_type,
                    score=border_score,
                    hard=False,
                    visual_transition_score=s_val,
                    composition_score=c_val,
                    panel_boundary_score=float(b_val),
                    visual_continuity=cont_val,
                    action_continuity=act_val,
                    details={"border_strength": float(b_val), "is_connected_panel": is_connected}
                )

        # 3. Scene and composition transition peaks (including zero-gutter boundaries)
        step_window = 10
        effective_signal = np.maximum(raw_signal, scene_trans * 0.70)
        for y in range(step_window, total_h - step_window, 4):
            if any(gs - 8 <= y <= ge + 8 for gs, ge in gutter_spans):
                continue
            s_val = float(scene_trans[y])
            c_val = float(comp_trans[y])
            sig_val = float(effective_signal[y])

            # Trigger on transition signal peak even when there is no gutter whitespace
            if sig_val >= 0.45 or s_val >= 0.45 or c_val >= 0.45:
                local_window = effective_signal[y - step_window:y + step_window + 1]
                if sig_val >= np.max(local_window):
                    c_type = "scene_transition" if s_val >= c_val else "composition_transition"
                    effective_score = float(max(sig_val, s_val, c_val))
                    is_zero_gutter = gutter_str[y] < 0.20
                    if y not in candidates_dict or effective_score > candidates_dict[y].score:
                        candidates_dict[y] = BoundaryCandidate(
                            y=y,
                            candidate_type=c_type,
                            score=effective_score,
                            hard=False,
                            visual_transition_score=s_val,
                            composition_score=c_val,
                            content_width_score=float(width_trans[y]),
                            visual_continuity=float(continuity[y]),
                            action_continuity=float(action_den[y]),
                            details={
                                "signal_peak": sig_val,
                                "zero_gutter_transition": is_zero_gutter
                            }
                        )

        # 4. Filter by 1D Non-Maximum Suppression (min_candidate_distance)
        all_cands = sorted(candidates_dict.values(), key=lambda c: c.y)
        if not all_cands:
            return []

        filtered_cands: List[BoundaryCandidate] = []
        min_dist = self.min_candidate_distance

        for cand in all_cands:
            if not filtered_cands:
                filtered_cands.append(cand)
            else:
                prev = filtered_cands[-1]
                if (cand.y - prev.y) < min_dist:
                    # Keep candidate with higher score or hard status
                    if cand.hard and not prev.hard:
                        filtered_cands[-1] = cand
                    elif not prev.hard and cand.score > prev.score:
                        filtered_cands[-1] = cand
                else:
                    filtered_cands.append(cand)

        # Cap candidates dynamically based on canvas height to prevent candidate starvation
        # on long multi-page vertical canvases (e.g. 100k - 200k+ pixels)
        effective_max = max(max_candidates, int(total_h / 120))
        if len(filtered_cands) > effective_max:
            # Spatial bucketing: divide canvas into 1000px chunks and ensure
            # each chunk retains its best candidates, preventing whole pages from being starved
            num_chunks = max(10, int(total_h / 1000))
            chunk_size = total_h / float(num_chunks)
            quota_per_chunk = max(2, int(np.ceil(effective_max / float(num_chunks))))

            chunk_buckets: List[List[BoundaryCandidate]] = [[] for _ in range(num_chunks)]
            for cand in filtered_cands:
                c_idx = min(num_chunks - 1, int(cand.y / chunk_size))
                chunk_buckets[c_idx].append(cand)

            spatially_selected: List[BoundaryCandidate] = []
            for bucket in chunk_buckets:
                if not bucket:
                    continue
                bucket.sort(key=lambda c: (c.hard, c.score), reverse=True)
                spatially_selected.extend(bucket[:quota_per_chunk])

            top_cands = sorted(spatially_selected, key=lambda c: c.y)
            return top_cands

        return filtered_cands
