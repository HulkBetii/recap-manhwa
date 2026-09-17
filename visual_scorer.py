"""
Visual Semantic Scorer for comic/manhwa pages.

Computes a deterministic Visual Semantic Score (0-100) based on five
weighted criteria.  The score helps downstream stages (PDF watermarking,
Gemini prompt) decide which pages are visually rich enough for video
narration.

Ported from renderer/smart_pagination.py of the
feat-multi-episode-optimization branch.
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

import cv2
import numpy as np
from PIL import Image


class VisualSemanticScorer:
    """
    Computes deterministic Visual Semantic Score (0-100) for manhwa/comic pages:

      FINAL SCORE =
        Semantic Similarity × 0.30 +
        Visual Detail × 0.25 +
        Character Presence × 0.25 +
        Action/Context × 0.10 +
        Image Quality × 0.10

    Evaluates visual utility for downstream narration-to-image semantic
    matching. Character presence is weighted heavily to prefer panels
    showing genuine faces, character interactions, and action over
    text-heavy, empty, or limb-only panels.
    """

    _detector = None
    _detector_initialized = False
    _model_path = os.path.join(os.path.dirname(__file__), "models", "face_detection_yunet_2023mar.onnx")

    @classmethod
    def _get_detector(cls, w: int, h: int):
        if not cls._detector_initialized:
            cls._detector_initialized = True
            if os.path.exists(cls._model_path) and hasattr(cv2, "FaceDetectorYN"):
                try:
                    cls._detector = cv2.FaceDetectorYN.create(
                        model=cls._model_path,
                        config="",
                        input_size=(w, h),
                        score_threshold=0.55,
                        nms_threshold=0.3,
                        top_k=5000,
                    )
                except Exception:
                    cls._detector = None
            else:
                cls._detector = None

        if cls._detector is not None:
            try:
                cls._detector.setInputSize((w, h))
            except Exception:
                pass
        return cls._detector

    @classmethod
    def detect_faces(cls, img_bgr: np.ndarray) -> list:
        """Detect human/character faces using YuNet ONNX."""
        if img_bgr is None or img_bgr.size == 0:
            return []
        h, w = img_bgr.shape[:2]
        detector = cls._get_detector(w, h)
        if detector is None:
            return []
        try:
            _, faces = detector.detect(img_bgr)
            return list(faces) if faces is not None else []
        except Exception:
            return []

    @classmethod
    def calculate_score(
        cls,
        img_bgr: np.ndarray,
        bg_val: Optional[int] = None,
    ) -> Tuple[int, Dict[str, float]]:
        """Score a BGR numpy array.

        Parameters
        ----------
        img_bgr : np.ndarray
            Input image in BGR colour order (as read by ``cv2.imread``).
        bg_val : int, optional
            Background luminance value.  Automatically detected from the
            image border when *None*.

        Returns
        -------
        (score, breakdown) : Tuple[int, dict]
            ``score`` is an integer in [0, 100].
            ``breakdown`` maps each sub-criterion name to its raw 0-100 value.
        """

        _EMPTY = {
            "semantic_similarity": 0.0,
            "visual_detail": 0.0,
            "character_presence": 0.0,
            "action_context": 0.0,
            "image_quality": 0.0,
            "is_meaningless": False,
        }

        if img_bgr is None or img_bgr.size == 0:
            return 0, {**_EMPTY}

        h, w = img_bgr.shape[:2]
        if h < 5 or w < 5:
            return 0, {**_EMPTY}

        # ------------------------------------------------------------------
        # Fast downscale to max width 500 for high-speed computation (~3 ms)
        # ------------------------------------------------------------------
        calc_w = min(w, 500)
        calc_h = max(5, int(round(h * (calc_w / w))))
        if calc_w != w or calc_h != h:
            interp = cv2.INTER_AREA if calc_w < w else cv2.INTER_LINEAR
            small_bgr = cv2.resize(img_bgr, (calc_w, calc_h), interpolation=interp)
        else:
            small_bgr = img_bgr

        gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2HSV)
        ycrcb = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2YCrCb)

        if bg_val is None:
            border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
            bg_val = int(np.median(border)) if len(border) > 0 else 255

        # ==================================================================
        # 1. Semantic Similarity  (Weight: 0.35)
        #    – Occupancy ratio, information entropy, spatial distribution
        # ==================================================================
        diff_from_bg = np.abs(gray.astype(np.float32) - bg_val)
        non_bg_mask = diff_from_bg > 16.0
        occupancy_ratio = float(np.mean(non_bg_mask))
        occ_score = np.clip(occupancy_ratio / 0.55 * 100.0, 0.0, 100.0)

        # Grayscale information entropy (Shannon, 64 bins)
        hist, _ = np.histogram(gray, bins=64, range=(0, 256), density=True)
        hist = hist[hist > 0]
        entropy = -float(np.sum(hist * np.log2(hist))) if len(hist) > 0 else 0.0
        ent_score = np.clip((entropy - 2.8) / 2.7 * 100.0, 0.0, 100.0)

        # Spatial distribution (3×3 grid)
        cell_h = max(1, calc_h // 3)
        cell_w = max(1, calc_w // 3)
        active_cells = 0
        for r in range(3):
            for c in range(3):
                cell_mask = non_bg_mask[r * cell_h:(r + 1) * cell_h,
                                       c * cell_w:(c + 1) * cell_w]
                if cell_mask.size > 0 and np.mean(cell_mask) > 0.08:
                    active_cells += 1
        dist_score = (active_cells / 9.0) * 100.0

        semantic_similarity = float(
            np.clip(0.40 * occ_score + 0.35 * ent_score + 0.25 * dist_score,
                    0.0, 100.0)
        )

        # ==================================================================
        # 2. Visual Detail  (Weight: 0.30)
        #    – Canny edge density, Sobel gradient magnitude
        # ==================================================================
        edges = cv2.Canny(gray, 40, 120)
        edge_ratio = float(np.mean(edges > 0))
        edge_score = np.clip((edge_ratio - 0.012) / 0.088 * 100.0, 0.0, 100.0)

        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        grad_mag = np.sqrt(gx ** 2 + gy ** 2)
        mean_grad = float(np.mean(grad_mag))
        grad_score = np.clip((mean_grad - 6.0) / 32.0 * 100.0, 0.0, 100.0)

        visual_detail = float(
            np.clip(0.55 * edge_score + 0.45 * grad_score, 0.0, 100.0)
        )

        # ==================================================================
        # 3. Character Presence  (Weight: 0.15)
        #    – Skin-tone spectrum (YCrCb), focal contrast, contour structure
        # ==================================================================
        cr = ycrcb[:, :, 1]
        cb = ycrcb[:, :, 2]
        y_chan = ycrcb[:, :, 0]
        skin_mask = (
            (cr >= 133) & (cr <= 173) &
            (cb >= 77) & (cb <= 127) &
            (y_chan >= 40) & (y_chan <= 245)
        )
        skin_ratio = float(np.mean(skin_mask))
        skin_score = np.clip(skin_ratio / 0.12 * 100.0, 0.0, 100.0)

        # Upper/Central focal contrast (character head/face position)
        focal_top = int(calc_h * 0.10)
        focal_bot = int(calc_h * 0.70)
        focal_left = int(calc_w * 0.15)
        focal_right = int(calc_w * 0.85)
        if focal_bot > focal_top and focal_right > focal_left:
            focal_roi = gray[focal_top:focal_bot, focal_left:focal_right]
            focal_std = float(np.std(focal_roi))
            focal_score = np.clip((focal_std - 15.0) / 45.0 * 100.0, 0.0, 100.0)
        else:
            focal_score = 50.0

        # Non-background contour structure (character outlines)
        contours, _ = cv2.findContours(
            non_bg_mask.astype(np.uint8),
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        significant_contours = sum(
            1 for cnt in contours
            if cv2.contourArea(cnt) > (calc_w * calc_h * 0.015)
        )
        contour_score = np.clip(significant_contours / 5.0 * 100.0, 0.0, 100.0)

        # AI Face Detection (YuNet ONNX)
        detected_faces = cls.detect_faces(small_bgr)
        num_faces = len(detected_faces)
        if num_faces > 0:
            max_conf = float(max(f[-1] for f in detected_faces))
            # Human/character face strongly anchors character presence
            face_score = float(np.clip(num_faces * 40.0 + max_conf * 50.0, 0.0, 100.0))
            character_presence = float(
                np.clip(0.60 * face_score + 0.25 * skin_score + 0.15 * focal_score, 0.0, 100.0)
            )
        else:
            # When NO face is detected, prevent false-positive skin-tone artifacts
            # (e.g. orange wooden walls, sunlight, or bare walking legs) from inflating score.
            capped_skin = min(25.0, skin_score)
            character_presence = float(
                np.clip(0.35 * capped_skin + 0.35 * focal_score + 0.30 * contour_score, 0.0, 60.0)
            )

        # ==================================================================
        # 4. Action / Context  (Weight: 0.10)
        #    – Diagonal speedlines, dynamic contrast range, colour vibrancy
        # ==================================================================
        diag_energy = float(np.mean(np.abs(gx * gy)))
        diag_score = np.clip(diag_energy / 120.0 * 100.0, 0.0, 100.0)

        p5, p95 = np.percentile(gray, [5, 95])
        dyn_range = float(p95 - p5)
        dyn_score = np.clip((dyn_range - 60.0) / 140.0 * 100.0, 0.0, 100.0)

        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        vibrant_mask = (sat > 80) & (val > 80)
        vibrant_ratio = float(np.mean(vibrant_mask))
        vibrant_score = np.clip(vibrant_ratio / 0.08 * 100.0, 0.0, 100.0)

        action_context = float(
            np.clip(0.40 * diag_score + 0.35 * dyn_score + 0.25 * vibrant_score,
                    0.0, 100.0)
        )

        # ==================================================================
        # 5. Image Quality  (Weight: 0.10)
        #    – Sharpness, contrast clarity, colour saturation variance
        # ==================================================================
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        sharpness_score = np.clip(
            (laplacian_var - 30.0) / 320.0 * 100.0, 0.0, 100.0
        )

        contrast_std = float(np.std(gray))
        contrast_score = np.clip(
            (contrast_std - 20.0) / 45.0 * 100.0, 0.0, 100.0
        )

        sat_std = float(np.std(sat))
        sat_score = np.clip(sat_std / 45.0 * 100.0, 0.0, 100.0)

        image_quality = float(
            np.clip(0.50 * sharpness_score + 0.30 * contrast_score + 0.20 * sat_score,
                    0.0, 100.0)
        )

        # ==================================================================
        # Text Bubble & Meaningless Panel Penalty (Anti-AI Cliché Filter)
        # ==================================================================
        art_color_ratio = float(np.mean((sat > 25) & (val > 45)))
        white_ratio = float(np.mean(gray > 205))
        black_ratio = float(np.mean(gray < 40))
        void_ratio = white_ratio + black_ratio

        # Bubble coverage ratio: fraction of image covered by speech bubble
        # regions (bright white blobs with very low saturation)
        bubble_cov_mask = (gray > 205) & (sat < 30)
        bubble_coverage_ratio = float(np.mean(bubble_cov_mask))
        gray_std = float(np.std(gray))

        from moderation_utils import is_text_bubble_dominant
        is_bubble, _ = is_text_bubble_dominant(small_bgr, bg_val=bg_val)
        is_empty_box = (void_ratio >= 0.78 and (art_color_ratio < 0.18 or skin_ratio < 0.015))
        is_tiny_slice = (h < 400 and (void_ratio > 0.65 or art_color_ratio < 0.20) and skin_ratio < 0.02)
        is_mostly_bubble = (bubble_coverage_ratio > 0.40 and skin_ratio < 0.03) or (bubble_coverage_ratio > 0.35 and character_presence < 18.0)
        # Low variance / solid / gradient gutter detection (catches grey bars, solid color bars, empty panels)
        is_solid_or_gutter = (gray_std < 14.0 or visual_detail < 8.0) and skin_ratio < 0.02
        is_limbs_no_face = bool(num_faces == 0 and skin_ratio > 0.35 and visual_detail < 25.0 and action_context < 25.0)
        is_bubble_no_face = bool(num_faces == 0 and bubble_coverage_ratio > 0.35 and character_presence < 30.0)

        is_meaningless = bool(is_bubble or is_empty_box or is_tiny_slice or is_mostly_bubble or is_solid_or_gutter or is_limbs_no_face or is_bubble_no_face)

        # ==================================================================
        # Final Score Combination
        # Weights rebalanced in v1.6.0: character_presence raised from 0.15
        # to 0.25 so panels with faces/characters are strongly preferred over
        # text-heavy or detail-only panels.
        # ==================================================================
        final_score_raw = (
            semantic_similarity * 0.30
            + visual_detail * 0.25
            + character_presence * 0.25
            + action_context * 0.10
            + image_quality * 0.10
        )
        if final_score_raw < 32.0:
            is_meaningless = True

        if is_meaningless:
            # Heavily penalize text-bubble, empty text-box, gutter bars, and tiny slices below threshold (capped at 25)
            final_score = min(25, max(0, int(round(final_score_raw * 0.25))))
        else:
            final_score = max(0, min(100, int(round(final_score_raw))))

        breakdown = {
            "semantic_similarity": round(semantic_similarity, 2),
            "visual_detail": round(visual_detail, 2),
            "character_presence": round(character_presence, 2),
            "action_context": round(action_context, 2),
            "image_quality": round(image_quality, 2),
            "bubble_coverage_ratio": round(bubble_coverage_ratio, 3),
            "is_meaningless": is_meaningless,
            "final_score": final_score,
        }

        return final_score, breakdown

    @classmethod
    def calculate_score_from_pil(
        cls,
        pil_img: Image.Image,
        bg_val: Optional[int] = None,
    ) -> Tuple[int, Dict[str, float]]:
        """Convenience wrapper to score a PIL Image directly."""
        if pil_img.mode != "RGB":
            rgb = pil_img.convert("RGB")
        else:
            rgb = pil_img
        np_rgb = np.asarray(rgb)
        bgr = cv2.cvtColor(np_rgb, cv2.COLOR_RGB2BGR)
        return cls.calculate_score(bgr, bg_val=bg_val)
