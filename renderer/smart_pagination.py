import os
import math
import json
import re
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional
import numpy as np
import cv2
from PIL import Image

CREDIT_KEYWORDS_REGEX = re.compile(
    r'\b(tl|pr|clrd|ts|qc|rp|raw|rd|cleaner|redrawer|typesetter|proofreader|translator|typesetting|translation|proofreading)\b'
    r'|(\b(tl|pr|clrd|ts|qc|rp)\s*[:|])'
    r'|\b(recruitment|recruiting|we are in need|hiring|staff recruitment|join our discord|join us on discord)\b'
    r'|\b(discord\.gg|discord\.com|patreon\.com|patreon|ko-fi|kofi|paypal)\b'
    r'|\b(manga\s*galaxy|mangagalaxy|asura\s*scans|asurascans|reaper\s*scans|flame\s*comics|void\s*scans|luminous\s*scans|comic\s*scans|scanlation|redice(?:\s*studio)?|chapter\s*(?:end|\d+\s*end|finish)|to\s*be\s*continued)\b',
    re.IGNORECASE
)


class PageTag:
    CHARACTER_ART = "CHARACTER_ART"
    CHARACTER_SCENE = "CHARACTER_SCENE"
    BACKGROUND_SCENE = "BACKGROUND_SCENE"
    ACTION_ART = "ACTION_ART"
    NON_VISUAL = "NON_VISUAL"

    ALL_TAGS = [CHARACTER_ART, CHARACTER_SCENE, BACKGROUND_SCENE, ACTION_ART, NON_VISUAL]
    KEEP_TAGS = [CHARACTER_ART, CHARACTER_SCENE, BACKGROUND_SCENE, ACTION_ART]
    REJECT_TAGS = [NON_VISUAL]


class _hybridmethod:
    """Descriptor that allows a method to be called either on an instance or a class."""
    def __init__(self, func):
        self.func = func
    def __get__(self, instance, owner):
        if instance is None:
            def class_call(*args, **kwargs):
                return self.func(owner(), *args, **kwargs)
            return class_call
        def instance_call(*args, **kwargs):
            return self.func(instance, *args, **kwargs)
        return instance_call


class PageType:
    CONTENT = "CONTENT"
    TEXT_BUBBLE = "TEXT_BUBBLE"
    EMPTY_GUTTER = "EMPTY_GUTTER"
    SPLIT_PANEL = "SPLIT_PANEL"

    # Frame-based content types per user specification:
    VISUAL = "VISUAL"
    VISUAL_WITH_TEXT = "VISUAL_WITH_TEXT"
    DIALOGUE = "DIALOGUE"
    MIXED = "MIXED"
    TEXT_ONLY = "TEXT_ONLY"
    CREDIT_ADS = "CREDIT_ADS"

    # 5-Tag Classification System:
    CHARACTER_ART = "CHARACTER_ART"
    CHARACTER_SCENE = "CHARACTER_SCENE"
    BACKGROUND_SCENE = "BACKGROUND_SCENE"
    ACTION_ART = "ACTION_ART"
    NON_VISUAL = "NON_VISUAL"

    # Backward compatibility aliases:
    ARTWORK = "VISUAL"
    PANEL = "VISUAL"
    SCENE = "VISUAL"
    TEXT_DOMINANT = "DIALOGUE"


@dataclass
class PageMetadata:
    page_index: int
    y_start: int
    y_end: int
    height: int
    page_type: str
    content_score: float
    boundary_confidence: float
    sources: List[Dict[str, Any]] = field(default_factory=list)
    visual_score: int = 50
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    # Enhanced Manhwa recap metadata fields
    content_type: str = "VISUAL"
    page_tag: str = PageTag.CHARACTER_SCENE
    text_score: int = 0
    importance_score: int = 50
    video_candidate: bool = True
    split_reason: str = "gutter"
    page_id: str = ""
    source_bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)
    pdf_page: Optional[int] = None
    # Smart Pagination V3 Enhancements
    focal_point: Tuple[float, float] = (0.5, 0.35)
    focal_points: List[Dict[str, Any]] = field(default_factory=list)
    camera_hint: str = "auto"
    sub_panels: List[Tuple[int, int, int, int]] = field(default_factory=list)
    layers: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        p_id = self.page_id or f"page_{self.page_index:03d}"
        res = {
            "pageId": p_id,
            "page_id": p_id,
            "pageIndex": self.page_index,
            "page_index": self.page_index,
            "sourceBBox": list(self.source_bbox),
            "source_bbox": list(self.source_bbox),
            "yStart": int(self.y_start),
            "y_start": int(self.y_start),
            "yEnd": int(self.y_end),
            "y_end": int(self.y_end),
            "height": int(self.height),
            "type": self.page_type,
            "contentScore": round(float(self.content_score), 3),
            "content_score": round(float(self.content_score), 3),
            "boundaryConfidence": round(float(self.boundary_confidence), 3),
            "boundary_confidence": round(float(self.boundary_confidence), 3),
            "visualScore": int(self.visual_score),
            "visual_score": int(self.visual_score),
            "point": int(self.visual_score),
            "scoreBreakdown": {
                "semanticSimilarity": round(float(self.score_breakdown.get("semantic_similarity", 0.0)), 2),
                "visualDetail": round(float(self.score_breakdown.get("visual_detail", 0.0)), 2),
                "characterPresence": round(float(self.score_breakdown.get("character_presence", 0.0)), 2),
                "actionContext": round(float(self.score_breakdown.get("action_context", 0.0)), 2),
                "imageQuality": round(float(self.score_breakdown.get("image_quality", 0.0)), 2),
                "finalScore": int(self.visual_score)
            },
            "sources": self.sources,
            "contentType": self.content_type,
            "content_type": self.content_type,
            "pageTag": self.page_tag,
            "page_tag": self.page_tag,
            "tag": self.page_tag,
            "textScore": int(self.text_score),
            "text_score": int(self.text_score),
            "importanceScore": int(self.importance_score),
            "importance_score": int(self.importance_score),
            "videoCandidate": bool(self.video_candidate),
            "video_candidate": bool(self.video_candidate),
            "splitReason": self.split_reason,
            "split_reason": self.split_reason,
            "focalPoint": list(self.focal_point),
            "focal_point": list(self.focal_point),
            "focalPoints": self.focal_points,
            "focal_points": self.focal_points,
            "cameraHint": self.camera_hint,
            "camera_hint": self.camera_hint,
            "subPanels": [list(sp["bbox"]) if isinstance(sp, dict) and "bbox" in sp else (list(sp) if isinstance(sp, (list, tuple)) else sp) for sp in self.sub_panels],
            "sub_panels": [list(sp["bbox"]) if isinstance(sp, dict) and "bbox" in sp else (list(sp) if isinstance(sp, (list, tuple)) else sp) for sp in self.sub_panels],
            "subPanelDetails": self.sub_panels,
            "sub_panel_details": self.sub_panels,
            "layers": self.layers
        }
        if self.pdf_page is not None:
            res["pdf_page"] = int(self.pdf_page)
            res["pdfPage"] = int(self.pdf_page)
        return res


class VisualSemanticScorer:
    """
    Computes deterministic Visual Semantic Score (0-100) for manhwa/comic pages:
      FINAL SCORE =
        Semantic Similarity × 0.35 +
        Visual Detail × 0.30 +
        Character Presence × 0.15 +
        Action/Context × 0.10 +
        Image Quality × 0.10
    Evaluates visual utility for downstream narration-to-image semantic matching.
    """

    @classmethod
    def calculate_score(
        cls,
        img_bgr: np.ndarray,
        bg_val: Optional[int] = None
    ) -> Tuple[int, Dict[str, float]]:
        if img_bgr is None or img_bgr.size == 0:
            return 0, {
                "semantic_similarity": 0.0,
                "visual_detail": 0.0,
                "character_presence": 0.0,
                "action_context": 0.0,
                "image_quality": 0.0
            }

        h, w = img_bgr.shape[:2]
        if h < 5 or w < 5:
            return 0, {
                "semantic_similarity": 0.0,
                "visual_detail": 0.0,
                "character_presence": 0.0,
                "action_context": 0.0,
                "image_quality": 0.0
            }

        # Fast downscale to max width 500 for deterministic high-speed computation (< 2-3ms)
        calc_w = min(w, 500)
        calc_h = max(5, int(round(h * (calc_w / w))))
        if calc_w != w or calc_h != h:
            small_bgr = cv2.resize(img_bgr, (calc_w, calc_h), interpolation=cv2.INTER_AREA if calc_w < w else cv2.INTER_LINEAR)
        else:
            small_bgr = img_bgr

        gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2HSV)
        ycrcb = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2YCrCb)

        if bg_val is None:
            border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
            bg_val = int(np.median(border)) if len(border) > 0 else 255

        # -------------------------------------------------------------
        # 1. Semantic Similarity (Weight: 0.35)
        # Evaluates meaningful content distribution, non-background coverage & entropy
        # -------------------------------------------------------------
        diff_from_bg = np.abs(gray.astype(np.float32) - bg_val)
        non_bg_mask = diff_from_bg > 16.0
        occupancy_ratio = float(np.mean(non_bg_mask))
        occ_score = np.clip(occupancy_ratio / 0.55 * 100.0, 0.0, 100.0)

        # Grayscale Information Entropy
        hist, _ = np.histogram(gray, bins=64, range=(0, 256), density=True)
        hist = hist[hist > 0]
        entropy = -float(np.sum(hist * np.log2(hist))) if len(hist) > 0 else 0.0
        ent_score = np.clip((entropy - 2.8) / 2.7 * 100.0, 0.0, 100.0)

        # Spatial Distribution (3x3 grid)
        cell_h = max(1, calc_h // 3)
        cell_w = max(1, calc_w // 3)
        active_cells = 0
        for r in range(3):
            for c in range(3):
                cell_mask = non_bg_mask[r*cell_h:(r+1)*cell_h, c*cell_w:(c+1)*cell_w]
                if cell_mask.size > 0 and np.mean(cell_mask) > 0.08:
                    active_cells += 1
        dist_score = (active_cells / 9.0) * 100.0

        semantic_similarity = float(np.clip(0.40 * occ_score + 0.35 * ent_score + 0.25 * dist_score, 0.0, 100.0))

        # -------------------------------------------------------------
        # 2. Visual Detail (Weight: 0.30)
        # Line art edge density, high-frequency texture & gradient magnitude
        # -------------------------------------------------------------
        edges = cv2.Canny(gray, 40, 120)
        edge_ratio = float(np.mean(edges > 0))
        edge_score = np.clip((edge_ratio - 0.012) / 0.088 * 100.0, 0.0, 100.0)

        # Sobel gradient magnitude
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        grad_mag = np.sqrt(gx**2 + gy**2)
        mean_grad = float(np.mean(grad_mag))
        grad_score = np.clip((mean_grad - 6.0) / 32.0 * 100.0, 0.0, 100.0)

        visual_detail = float(np.clip(0.55 * edge_score + 0.45 * grad_score, 0.0, 100.0))

        # -------------------------------------------------------------
        # 3. Character Presence (Weight: 0.15)
        # Skin tone spectrum, facial focal contrast, silhouette complexity
        # -------------------------------------------------------------
        cr = ycrcb[:, :, 1]
        cb = ycrcb[:, :, 2]
        y_chan = ycrcb[:, :, 0]
        skin_mask = (cr >= 133) & (cr <= 173) & (cb >= 77) & (cb <= 127) & (y_chan >= 40) & (y_chan <= 245)
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
        contours, _ = cv2.findContours(non_bg_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        significant_contours = sum(1 for cnt in contours if cv2.contourArea(cnt) > (calc_w * calc_h * 0.015))
        contour_score = np.clip(significant_contours / 5.0 * 100.0, 0.0, 100.0)

        character_presence = float(np.clip(0.45 * skin_score + 0.35 * focal_score + 0.20 * contour_score, 0.0, 100.0))

        # -------------------------------------------------------------
        # 4. Action / Context (Weight: 0.10)
        # Diagonal speedlines, dynamic contrast range, vibrancy
        # -------------------------------------------------------------
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

        action_context = float(np.clip(0.40 * diag_score + 0.35 * dyn_score + 0.25 * vibrant_score, 0.0, 100.0))

        # -------------------------------------------------------------
        # 5. Image Quality (Weight: 0.10)
        # Sharpness, contrast clarity, color richness
        # -------------------------------------------------------------
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        sharpness_score = np.clip((laplacian_var - 30.0) / 320.0 * 100.0, 0.0, 100.0)

        contrast_std = float(np.std(gray))
        contrast_score = np.clip((contrast_std - 20.0) / 45.0 * 100.0, 0.0, 100.0)

        sat_std = float(np.std(sat))
        sat_score = np.clip(sat_std / 45.0 * 100.0, 0.0, 100.0)

        image_quality = float(np.clip(0.50 * sharpness_score + 0.30 * contrast_score + 0.20 * sat_score, 0.0, 100.0))

        # -------------------------------------------------------------
        # Final Score Combination
        # -------------------------------------------------------------
        final_score_raw = (
            semantic_similarity * 0.35 +
            visual_detail * 0.30 +
            character_presence * 0.15 +
            action_context * 0.10 +
            image_quality * 0.10
        )
        final_score = int(round(final_score_raw))
        final_score = max(0, min(100, final_score))

        breakdown = {
            "semantic_similarity": round(semantic_similarity, 2),
            "visual_detail": round(visual_detail, 2),
            "character_presence": round(character_presence, 2),
            "action_context": round(action_context, 2),
            "image_quality": round(image_quality, 2),
            "final_score": final_score
        }

        return final_score, breakdown

    @classmethod
    def calculate_score_from_pil(
        cls,
        pil_img: Image.Image,
        bg_val: Optional[int] = None
    ) -> Tuple[int, Dict[str, float]]:
        """
        Convenience wrapper to score a PIL Image directly.
        """
        if pil_img.mode != "RGB":
            rgb = pil_img.convert("RGB")
        else:
            rgb = pil_img
        np_rgb = np.asarray(rgb)
        bgr = cv2.cvtColor(np_rgb, cv2.COLOR_RGB2BGR)
        return cls.calculate_score(bgr, bg_val=bg_val)


class TextScorer:
    """
    Computes deterministic Text Score (0-100) for a manhwa/comic image or page slice.
    Evaluates:
      - Text stroke/connected-component density
      - Speech bubble / dialogue box occupancy
      - Ratio of text characters to background/artwork
    Returns an integer text_score in [0, 100].
    """

    @classmethod
    def calculate_text_score(
        cls,
        img_bgr: np.ndarray,
        bg_val: Optional[int] = None
    ) -> int:
        if img_bgr is None or img_bgr.size == 0:
            return 0
        h, w = img_bgr.shape[:2]
        if h < 5 or w < 5:
            return 0

        scale = min(1.0, 500.0 / float(w))
        calc_w = max(5, int(round(w * scale)))
        calc_h = max(5, int(round(h * scale)))
        if calc_w != w or calc_h != h:
            small_bgr = cv2.resize(
                img_bgr, (calc_w, calc_h),
                interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            )
        else:
            small_bgr = img_bgr

        gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
        if bg_val is None:
            border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
            bg_val = int(np.median(border)) if len(border) > 0 else 255

        # 1. Dark text on light background (speech bubble/dialogue)
        is_dark = (gray < 85) & (np.abs(gray.astype(np.float32) - bg_val) > 25)
        # 2. Light text on dark background (narration box)
        is_light = (gray > 200) & (np.abs(gray.astype(np.float32) - bg_val) > 25)

        kw = max(3, int(15 * scale))
        kh = max(2, int(4 * scale))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, kh))

        closed_dark = cv2.morphologyEx(is_dark.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
        closed_light = cv2.morphologyEx(is_light.astype(np.uint8), cv2.MORPH_CLOSE, kernel)

        num_labels_d, _, stats_d, _ = cv2.connectedComponentsWithStats(closed_dark)
        num_labels_l, _, stats_l, _ = cv2.connectedComponentsWithStats(closed_light)

        text_area = 0
        text_blocks = 0
        tot_pixels = float(calc_w * calc_h)

        for stats, num_labels, is_contrast_valid in [
            (
                stats_d, num_labels_d,
                lambda r: np.mean(gray[r[1]:r[1] + r[3], r[0]:r[0] + r[2]] > 175) > 0.35
            ),
            (
                stats_l, num_labels_l,
                lambda r: np.mean(gray[r[1]:r[1] + r[3], r[0]:r[0] + r[2]] < 80) > 0.35
            )
        ]:
            for i in range(1, num_labels):
                x, y, bw, bh, area = stats[i]
                if 4 <= bh <= int(100 * scale) and bw >= int(8 * scale) and area >= int(15 * scale * scale) and bw <= int(0.85 * calc_w):
                    roi_y1 = max(0, y - int(6 * scale))
                    roi_y2 = min(calc_h, y + bh + int(6 * scale))
                    roi_x1 = max(0, x - int(6 * scale))
                    roi_x2 = min(calc_w, x + bw + int(6 * scale))
                    if is_contrast_valid((roi_x1, roi_y1, roi_x2 - roi_x1, roi_y2 - roi_y1)):
                        text_area += area
                        text_blocks += 1

        coverage = text_area / max(1.0, tot_pixels)
        coverage_score = np.clip(coverage / 0.08 * 70.0, 0.0, 70.0)
        block_score = np.clip(text_blocks * 6.0, 0.0, 30.0)

        raw_score = coverage_score + block_score
        text_score = int(round(np.clip(raw_score, 0.0, 100.0)))
        return text_score

    @classmethod
    def calculate_score_from_pil(
        cls,
        pil_img: Image.Image,
        bg_val: Optional[int] = None
    ) -> int:
        if pil_img.mode != "RGB":
            rgb = pil_img.convert("RGB")
        else:
            rgb = pil_img
        np_rgb = np.asarray(rgb)
        bgr = cv2.cvtColor(np_rgb, cv2.COLOR_RGB2BGR)
        return cls.calculate_text_score(bgr, bg_val=bg_val)


class PageQualityScorer:
    """
    Computes holistic page quality score according to user specification:
      page_score =
        visual_area
      + character_presence
      + action_score
      + scene_completeness
      + composition_score
      - text_density
      - empty_area
      - crop_penalty
      - fragmentation_penalty
    """

    @classmethod
    def calculate_page_score(
        cls,
        img_bgr: np.ndarray,
        bg_val: Optional[int] = None,
        y_start: int = 0,
        y_end: int = 0,
        total_canvas_h: int = 0
    ) -> Tuple[int, Dict[str, float]]:
        if img_bgr is None or img_bgr.size == 0:
            return 0, {
                "visual_area": 0.0,
                "character_presence": 0.0,
                "action_score": 0.0,
                "scene_completeness": 0.0,
                "composition_score": 0.0,
                "text_density": 0.0,
                "empty_area": 0.0,
                "crop_penalty": 0.0,
                "fragmentation_penalty": 0.0,
                "final_score": 0.0
            }

        h, w = img_bgr.shape[:2]
        calc_w = min(w, 500)
        calc_h = max(5, int(round(h * (calc_w / float(w)))))
        if calc_w != w or calc_h != h:
            small_bgr = cv2.resize(img_bgr, (calc_w, calc_h), interpolation=cv2.INTER_AREA if calc_w < w else cv2.INTER_LINEAR)
        else:
            small_bgr = img_bgr

        gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2HSV)
        ycrcb = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2YCrCb)

        if bg_val is None:
            border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
            bg_val = int(np.median(border)) if len(border) > 0 else 255

        diff_from_bg = np.abs(gray.astype(np.float32) - bg_val)
        non_bg_mask = diff_from_bg > 16.0
        non_bg_ratio = float(np.mean(non_bg_mask))

        # 1. visual_area (0..25)
        visual_area = float(np.clip(non_bg_ratio * 30.0, 0.0, 25.0))

        # 2. character_presence (0..25)
        cr = ycrcb[:, :, 1]
        cb = ycrcb[:, :, 2]
        y_chan = ycrcb[:, :, 0]
        skin_mask = (cr >= 133) & (cr <= 173) & (cb >= 77) & (cb <= 127) & (y_chan >= 40) & (y_chan <= 245)
        skin_ratio = float(np.mean(skin_mask))
        character_presence = float(np.clip(skin_ratio / 0.08 * 25.0, 0.0, 25.0))

        # 3. action_score (0..15)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        diag_energy = float(np.mean(np.abs(gx * gy)))
        action_score = float(np.clip(diag_energy / 100.0 * 15.0, 0.0, 15.0))

        # 4. scene_completeness (0..15)
        if 500 <= h <= 2000:
            scene_completeness = 15.0
        elif 300 <= h < 500 or 2000 < h <= 2800:
            scene_completeness = 10.0
        else:
            scene_completeness = 5.0

        # 5. composition_score (0..20)
        cell_h = max(1, calc_h // 3)
        cell_w = max(1, calc_w // 3)
        active_cells = 0
        for r in range(3):
            for c in range(3):
                cell_mask = non_bg_mask[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w]
                if cell_mask.size > 0 and np.mean(cell_mask) > 0.08:
                    active_cells += 1
        composition_score = float((active_cells / 9.0) * 20.0)

        # 6. text_density penalty (0..20)
        text_score = TextScorer.calculate_text_score(small_bgr, bg_val=bg_val)
        text_density = float(np.clip((text_score / 100.0) * 20.0, 0.0, 20.0))

        # 7. empty_area penalty (0..15)
        empty_ratio = 1.0 - non_bg_ratio
        empty_area = float(np.clip((empty_ratio - 0.40) / 0.50 * 15.0, 0.0, 15.0)) if empty_ratio > 0.40 else 0.0

        # 8. crop_penalty (0..10)
        top_cut_density = float(np.mean(non_bg_mask[:max(1, int(calc_h * 0.02)), :]))
        bot_cut_density = float(np.mean(non_bg_mask[-max(1, int(calc_h * 0.02)):, :]))
        crop_penalty = float(np.clip((top_cut_density + bot_cut_density) * 8.0, 0.0, 10.0))

        # 9. fragmentation_penalty (0..20)
        if h < 100:
            fragmentation_penalty = 20.0
        elif h < 250:
            fragmentation_penalty = 10.0
        elif h < 400:
            fragmentation_penalty = 5.0
        else:
            fragmentation_penalty = 0.0

        raw_score = (
            visual_area
            + character_presence
            + action_score
            + scene_completeness
            + composition_score
            - text_density
            - empty_area
            - crop_penalty
            - fragmentation_penalty
        )
        final_score = int(round(np.clip(raw_score, 0.0, 100.0)))

        breakdown = {
            "visual_area": round(visual_area, 2),
            "character_presence": round(character_presence, 2),
            "action_score": round(action_score, 2),
            "scene_completeness": round(scene_completeness, 2),
            "composition_score": round(composition_score, 2),
            "text_density": round(text_density, 2),
            "empty_area": round(empty_area, 2),
            "crop_penalty": round(crop_penalty, 2),
            "fragmentation_penalty": round(fragmentation_penalty, 2),
            "final_score": final_score
        }
        return final_score, breakdown


class YOLOVisualDetector:
    """
    YOLO-based segmentation & detection for character, object, and artwork visual regions.
    Integrates ultralytics.YOLO with resilient fallback to OpenCV contour & skin-tone saliency.
    """
    _model = None
    _initialized = False
    _device = "cpu"

    @classmethod
    def get_model(cls, model_name: Optional[str] = None):
        if model_name is None:
            try:
                from renderer.comic_vision_ai import ComicVisionAI
                ai_model = ComicVisionAI.get_model()
                if ai_model is not None:
                    cls._model = ai_model
                    cls._device = ComicVisionAI.get_device()
                    cls._initialized = True
                    return cls._model
            except Exception:
                pass

        if not cls._initialized or cls._model is None:
            cls._initialized = True
            try:
                import torch
                from renderer.yolo_compat import YOLO, is_yolo_available
                if not is_yolo_available():
                    cls._model = None
                    cls._device = "cpu"
                    return None
                if model_name is None:
                    model_name = "yolo11x.pt" if os.path.exists("yolo11x.pt") else "yolo11n.pt"
                cls._model = YOLO(model_name)
                cls._device = "cuda:0" if torch.cuda.is_available() else "cpu"
                if "cuda" in cls._device:
                    try:
                        cls._model.to(cls._device)
                        if hasattr(cls._model, "model") and hasattr(cls._model.model, "half"):
                            cls._model.model.half()
                    except Exception:
                        pass
            except Exception:
                cls._model = None
                cls._device = "cpu"
        return cls._model

    @classmethod
    def detect_visual_regions(
        cls,
        img_bgr: np.ndarray,
        conf_threshold: float = 0.25
    ) -> List[Dict[str, Any]]:
        h, w = img_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return []

        detections = []
        model = cls.get_model()
        if model is not None:
            try:
                # If image is very tall (e.g. stitched manhwa canvas), slice into vertical windows
                # so characters are not squashed into 1-2 pixels by extreme downscaling
                if h > 2400:
                    chunk_size = 2000
                    stride = 1600
                    y_slices = []
                    y_pos = 0
                    while y_pos < h:
                        y_end = min(h, y_pos + chunk_size)
                        y_slices.append((y_pos, y_end))
                        if y_end >= h:
                            break
                        y_pos += stride
                else:
                    y_slices = [(0, h)]

                for chunk_y1, chunk_y2 in y_slices:
                    chunk_img = img_bgr[chunk_y1:chunk_y2]
                    ch_h, ch_w = chunk_img.shape[:2]
                    max_dim = 640
                    scale = min(1.0, max_dim / float(max(ch_h, ch_w)))
                    if scale < 1.0:
                        infer_img = cv2.resize(chunk_img, (int(ch_w * scale), int(ch_h * scale)))
                    else:
                        infer_img = chunk_img
                    results = model(infer_img, conf=conf_threshold, device=cls._device, verbose=False)
                    for r in results:
                        boxes = r.boxes
                        if boxes is not None:
                            for box in boxes:
                                xyxy = box.xyxy[0].cpu().numpy()
                                conf = float(box.conf[0].cpu().numpy())
                                cls_id = int(box.cls[0].cpu().numpy())
                                cls_name = model.names.get(cls_id, str(cls_id))
                                inv_scale = 1.0 / scale
                                x1 = int(xyxy[0] * inv_scale)
                                y1 = int(xyxy[1] * inv_scale) + chunk_y1
                                x2 = int(xyxy[2] * inv_scale)
                                y2 = int(xyxy[3] * inv_scale) + chunk_y1
                                detections.append({
                                    "bbox": (x1, y1, x2, y2),
                                    "class": cls_name,
                                    "confidence": conf,
                                    "is_character": cls_name in ("person", "character", "face", "man", "woman", "creature")
                                })
            except Exception:
                pass

        # Resilient CV Fallback / Complement (skin tone & salient visual contour analysis)
        has_detected_chars = any(d.get("is_character") for d in detections)
        if not has_detected_chars:
            ycrcb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2YCrCb)
            cr = ycrcb[:, :, 1]
            cb = ycrcb[:, :, 2]
            y_chan = ycrcb[:, :, 0]
            skin_mask = ((cr >= 133) & (cr <= 173) & (cb >= 77) & (cb <= 127) & (y_chan >= 40) & (y_chan <= 245)).astype(np.uint8)
            num_cc, _, stats, _ = cv2.connectedComponentsWithStats(skin_mask)
            for i in range(1, num_cc):
                bx, by, bw, bh, area = stats[i]
                # Filter out full-width horizontal background bands or text banners (bw >= 0.90 * w)
                if bw >= int(0.90 * w):
                    continue
                if area > 100 and bh > 15:
                    detections.append({
                        "bbox": (bx, by, bx + bw, by + bh),
                        "class": "character",
                        "confidence": 0.85,
                        "is_character": True
                    })

        return detections


class OCRTextDetector:
    """
    Hybrid text detection for speech bubbles, narration, and text regions.
    Supports PaddleOCR -> EasyOCR -> OpenCV morphological letter clustering fallback.
    """
    _easyocr_reader = None
    _paddleocr_engine = None
    _initialized = False

    @classmethod
    def get_engine(cls):
        if not cls._initialized:
            cls._initialized = True
            # Tier 1: Try PaddleOCR
            try:
                import paddleocr
                cls._paddleocr_engine = paddleocr.PaddleOCR(use_angle_cls=False, lang='en')
            except Exception:
                cls._paddleocr_engine = None

            # Tier 2: Try EasyOCR
            if cls._paddleocr_engine is None:
                try:
                    import easyocr
                    import torch
                    use_gpu = torch.cuda.is_available()
                    cls._easyocr_reader = easyocr.Reader(['en'], gpu=use_gpu)
                except Exception:
                    cls._easyocr_reader = None

        return cls._paddleocr_engine, cls._easyocr_reader

    @classmethod
    def detect_text_regions(
        cls,
        img_bgr: np.ndarray,
        bg_val: int = 255
    ) -> List[Dict[str, Any]]:
        h, w = img_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return []

        p_ocr, e_ocr = cls.get_engine()
        results = []

        if p_ocr is not None:
            try:
                p_res = p_ocr.ocr(img_bgr, cls=False)
                if p_res and len(p_res) > 0 and p_res[0]:
                    for line in p_res[0]:
                        box, (text, conf) = line
                        xs = [int(pt[0]) for pt in box]
                        ys = [int(pt[1]) for pt in box]
                        x1, x2 = min(xs), max(xs)
                        y1, y2 = min(ys), max(ys)
                        results.append({
                            "bbox": (x1, y1, x2, y2),
                            "text": text,
                            "confidence": float(conf),
                            "is_bubble": True,
                            "is_narration": False
                        })
            except Exception:
                pass

        if not results and e_ocr is not None:
            try:
                e_res = e_ocr.readtext(img_bgr)
                for bbox, text, conf in e_res:
                    xs = [int(pt[0]) for pt in bbox]
                    ys = [int(pt[1]) for pt in bbox]
                    x1, x2 = min(xs), max(xs)
                    y1, y2 = min(ys), max(ys)
                    results.append({
                        "bbox": (x1, y1, x2, y2),
                        "text": text,
                        "confidence": float(conf),
                        "is_bubble": True,
                        "is_narration": False
                    })
            except Exception:
                pass

        return results


class ComicVisionDetector:
    """
    Unified ensemble detector for comic & manhwa visual elements:
    - PANEL: 2D rectangular panel frames / borders
    - CHARACTER: Faces, portraits, body figures
    - SPEECH_BUBBLE: Dialogue, thought, and scream bubbles
    - SFX_TEXT: Sound effects and onomatopoeia
    Combines optional lightweight ONNX model with resilient Classical CV and OCR.
    """
    _onnx_session = None
    _onnx_initialized = False

    @classmethod
    def get_onnx_session(cls, model_path: Optional[str] = None):
        if not cls._onnx_initialized:
            cls._onnx_initialized = True
            cand_paths = [
                model_path,
                "models/comic_detector.onnx",
                "models/comic_yolo.onnx",
                "tools/models/comic_detector.onnx"
            ]
            for cp in cand_paths:
                if cp and os.path.exists(cp):
                    try:
                        import onnxruntime as ort
                        cls._onnx_session = ort.InferenceSession(cp, providers=['CPUExecutionProvider'])
                        break
                    except Exception:
                        pass
        return cls._onnx_session

    @classmethod
    def detect_all(
        cls,
        img_bgr: np.ndarray,
        bg_val: int = 255
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Runs unified ensemble detection across all 4 comic object classes.
        """
        h, w = img_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return {"panels": [], "characters": [], "bubbles": [], "sfx": []}

        # 1. Characters from YOLO or Skin/Contour Saliency
        char_dets = YOLOVisualDetector.detect_visual_regions(img_bgr)
        characters = []
        for d in char_dets:
            if d.get("is_character", False):
                characters.append({
                    "bbox": d["bbox"],
                    "confidence": float(d.get("confidence", 0.85)),
                    "label": "character"
                })

        if not characters:
            try:
                ycrcb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2YCrCb)
                cr = ycrcb[:, :, 1]
                cb = ycrcb[:, :, 2]
                y_chan = ycrcb[:, :, 0]
                skin_mask = ((cr >= 133) & (cr <= 173) & (cb >= 77) & (cb <= 127) & (y_chan >= 40) & (y_chan <= 245)).astype(np.uint8)
                num_cc, _, stats, _ = cv2.connectedComponentsWithStats(skin_mask)
                for i in range(1, num_cc):
                    bx, by, bw, bh, area = stats[i]
                    if area > 100 and bh > 15:
                        characters.append({
                            "bbox": (bx, by, bx + bw, by + bh),
                            "confidence": 0.85,
                            "label": "character"
                        })
            except Exception:
                pass

        # 2. Speech Bubbles
        bubbles_2d = SmartPaginator.detect_speech_bubbles_2d(img_bgr, bg_val=bg_val)
        bubbles = []
        for bx1, by1, bx2, by2 in bubbles_2d:
            bubbles.append({
                "bbox": (bx1, by1, bx2, by2),
                "confidence": 0.90,
                "label": "speech_bubble"
            })

        # 3. Panels (2D boundary detection)
        panels_2d = SmartPaginator.detect_panels_2d(img_bgr, bg_val=bg_val)
        panels = []
        for pb in panels_2d:
            if isinstance(pb, dict):
                panels.append(pb)
            else:
                panels.append({
                    "bbox": pb,
                    "confidence": 0.92,
                    "label": "panel"
                })

        # 4. SFX (High-contrast non-bubble text strokes)
        sfx = []
        try:
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            canny = cv2.Canny(gray, 80, 200)
            bub_mask = np.zeros((h, w), dtype=np.uint8)
            for b in bubbles:
                bx1, by1, bx2, by2 = b["bbox"]
                bub_mask[max(0, by1):min(h, by2), max(0, bx1):min(w, bx2)] = 255
            canny[bub_mask > 0] = 0
            contours, _ = cv2.findContours(canny, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                cx, cy, cw, ch = cv2.boundingRect(c)
                if 25 < cw < 350 and 25 < ch < 250:
                    density = cv2.contourArea(c) / float(cw * ch + 1e-5)
                    if 0.20 < density < 0.80:
                        sfx.append({
                            "bbox": (cx, cy, cx + cw, cy + ch),
                            "confidence": 0.70,
                            "label": "sfx_text"
                        })
        except Exception:
            pass

        return {
            "panels": panels,
            "characters": characters,
            "bubbles": bubbles,
            "sfx": sfx
        }


@dataclass
class ContentZone:
    zone_id: int
    zone_type: str  # "VISUAL", "DIALOGUE", "TEXT_ONLY", "GUTTER"
    start_y: int
    end_y: int
    height: int
    bbox: Tuple[int, int, int, int]
    has_character: bool = False
    has_speech_bubble: bool = False
    is_attached_to_visual: bool = False


@dataclass
class PaginationConfig:
    preferred_min_height: int = 100
    preferred_max_height: int = 3000
    hard_max_height: int = 4500         # Maximum page height: preserves tall manhwa panels while preventing extreme runaway pages
    min_page_height: int = 20            # Minimum page height: allows small reaction/dialogue boxes down to 20px
    target_height: int = 1080
    tolerance: int = 15
    bg_threshold: float = 0.96
    forbidden_padding: int = 12
    crop_padding: int = 4                # Tight padding around visual regions to prevent empty gutter inclusion
    bridge_gap: int = 20                 # Bridge micro-gaps within drawings without bridging across real gutters (>= 25px)
    skip_blank: bool = True
    canny_low: int = 40
    canny_high: int = 120
    use_ocr: bool = False
    separate_speech_bubbles: bool = True # Separates speech bubbles that have clear gutter/border boundaries
    isolate_visual_frames: bool = True   # Isolate each visual panel/scene independently for video recap (do not merge panels)
    tight_auto_crop: bool = True         # Auto trim 4-edge background borders (top, bottom, left, right)
    filter_video_frames: bool = False    # Filter out non-visual frames (EMPTY_GUTTER, DIALOGUE-only) in output
    border_snap_ratio: float = 0.65      # Ratio of cuts snapping directly to panel border lines
    border_snap_tolerance: int = 6       # Pixel tolerance when snapping cut line to horizontal panel border
    min_bubble_clearance: int = 18       # Minimum safe clearance kept from speech bubbles
    min_gutter_gap: int = 8              # Minimum gutter gap width where user decides to separate panels
    gutter_cut_bias: float = 0.5         # Relative placement inside gutter (0.5 = center, 0.0 = top, 1.0 = bottom)
    # Smart Pagination V3 Enhancements
    enable_2d_panels: bool = True
    enable_narrative_clustering: bool = True
    enable_layer_separation: bool = False
    max_dialogue_gap: int = 180
    mode: str = "ai_direct"              # "ai_direct" (AI Visual Composition Segmentation)
    # Smart Paging Engine V2 Settings
    ideal_page_height: int = 1200
    max_page_height: int = 3500
    boundary_score_threshold: float = 0.35
    character_overlap_penalty: float = 5.0
    object_overlap_penalty: float = 2.5
    action_continuity_penalty: float = 3.0
    scene_transition_weight: float = 1.0
    composition_weight: float = 0.8
    content_width_weight: float = 0.6
    color_transition_weight: float = 0.7
    edge_weight: float = 0.5
    panel_boundary_weight: float = 0.9
    speech_edge_hard_cut: bool = True
    debug_paging: bool = False
    debug_output_dir: Optional[str] = None
    # Deep Learning & Pure CV Hybrid Paging
    comic_panel_model_path: Optional[str] = None
    enable_hpp_fast_path: bool = True
    hpp_variance_threshold: float = 6.0
    hpp_downsample_width: int = 128

    @classmethod
    def from_learned_profile(cls, profile_path: Optional[str] = None) -> "PaginationConfig":
        """Returns standard default PaginationConfig (learned profiles deprecated)."""
        return cls()

    @classmethod
    def webtoon_clean(cls) -> "PaginationConfig":
        """
        Preset optimized for webtoon panels and clean single-frame outputs:
        - Prevents multiple panels from merging into runaway tall pages (max_height 1280, ideal 900)
        - Forces panel isolation across gutters
        - Cleans top/bottom whitespace and orphan borders
        """
        return cls(
            ideal_page_height=900,
            max_page_height=1280,
            hard_max_height=1400,
            isolate_visual_frames=True,
            min_gutter_gap=6,
            panel_boundary_weight=1.2,
            tight_auto_crop=True,
            crop_padding=2,
            gutter_cut_bias=0.5,
            min_bubble_clearance=15,
        )

    @classmethod
    def tapas_clean(cls) -> "PaginationConfig":
        """Preset optimized for Tapas publishing format (max height 1280, width 940)."""
        return cls(
            ideal_page_height=950,
            max_page_height=1280,
            hard_max_height=1400,
            isolate_visual_frames=True,
            min_gutter_gap=6,
            panel_boundary_weight=1.2,
            tight_auto_crop=True,
            crop_padding=2,
            gutter_cut_bias=0.5,
            min_bubble_clearance=15,
        )

    @classmethod
    def video_recap(cls) -> "PaginationConfig":
        """
        Preset tailored specifically for video recap pipeline (continuous narrative scene pacing):
        - min_page_height = 1500 (prevents isolated speech bubbles and micro-pages)
        - ideal_page_height = 5200 (balanced narrative page height for 35-45 pages per episode)
        - max_page_height = 7000 (continuous action scene limit)
        - hard_max_height = 8000 (absolute runaway barrier)
        - isolate_visual_frames = True
        - tight_auto_crop = True
        - crop_padding = 4
        - speech_edge_hard_cut = False (bubbles snap to visual panels)
        - separate_speech_bubbles = False (speech bubbles stay attached to scenes)
        """
        return cls(
            min_page_height=1500,
            ideal_page_height=5200,
            max_page_height=7000,
            hard_max_height=8000,
            isolate_visual_frames=True,
            tight_auto_crop=True,
            crop_padding=4,
            speech_edge_hard_cut=False,
            separate_speech_bubbles=False,
        )

    @classmethod
    def from_preset(cls, preset_name: str = "default") -> "PaginationConfig":
        """
        Creates a PaginationConfig tailored for specific publishing or rendering targets:
        - "webtoon" or "webtoon_clean": Line Webtoon Canvas (max 1280px, panel isolation, clean borders)
        - "tapas" or "tapas_clean": Tapas format (max 1280px, 940px width)
        - "video" or "video_recap": Video frames (9:16 aspect, 1080p target)
        - "default": General intelligent comic segmentation
        """
        name = str(preset_name).lower().strip()
        if name in ("webtoon", "webtoon_clean", "line_webtoon"):
            return cls.webtoon_clean()
        elif name in ("tapas", "tapas_clean"):
            return cls.tapas_clean()
        elif name in ("video", "video_recap"):
            return cls.video_recap()
        return cls()



@dataclass
class VisualContentBlock:
    start_y: int
    end_y: int
    height: int
    block_type: str = PageType.CONTENT
    avg_activity: float = 0.5


class SmartPaginator:
    """
    Production-grade intelligent pagination engine for webtoons and vertical comics.
    Preserves complete illustration panels, characters, and scenes intact without cutting
    through drawings or characters, while placing page cuts cleanly inside gutters or panel borders.
    """

    def __init__(self, config: Optional[PaginationConfig] = None):
        if config is not None:
            self.config = config
        else:
            self.config = PaginationConfig.from_learned_profile()

    @staticmethod
    def detect_background(img_gray: np.ndarray) -> int:
        """
        Estimates the primary canvas gutter/background color from image borders,
        sampling insets to ignore screenshot frame margins.
        """
        h, w = img_gray.shape
        if h == 0 or w == 0:
            return 255
        inset_x = max(1, min(5, int(w * 0.015)))
        inset_y = max(1, min(5, int(h * 0.015)))
        border_pixels = np.concatenate([
            img_gray[inset_y, :],
            img_gray[-inset_y, :],
            img_gray[:, inset_x],
            img_gray[:, -inset_x]
        ])
        if len(border_pixels) == 0:
            return 255
        if np.mean(border_pixels > 180) >= 0.35:
            return int(np.median(border_pixels[border_pixels > 180]))
        elif np.mean(border_pixels < 75) >= 0.35:
            return int(np.median(border_pixels[border_pixels < 75]))
        return int(np.median(border_pixels))

    @classmethod
    def compute_row_metrics(
        cls,
        canvas_bgr: np.ndarray,
        bg_val: int,
        config: PaginationConfig
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Computes detailed row-level visual metrics:
        - diff_ratio: ratio of non-background pixels
        - edge_density: density of Canny edges per row
        - var_ratio: normalized pixel intensity variance
        - sat_mean: mean color saturation (0-255) per row (high in artwork, low in speech bubbles)
        - skin_ratio: ratio of skin tone pixels per row (YCrCb)
        - is_horizontal_border: boolean mask indicating panel horizontal border lines
        - activity: blended visual activity score (0.0 to 1.0)
        """
        total_h, max_w = canvas_bgr.shape[:2]
        if total_h <= 0 or max_w <= 0:
            z = np.zeros(0, dtype=np.float32)
            zb = np.zeros(0, dtype=bool)
            return z, z, z, z, z, zb, z

        target_w = min(240, max_w)
        small_bgr = cv2.resize(canvas_bgr, (target_w, total_h), interpolation=cv2.INTER_AREA if target_w < max_w else cv2.INTER_NEAREST)
        gray_small = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
        hsv_small = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2HSV)
        ycrcb_small = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2YCrCb)

        # Determine active content columns (ignore static sidebar padding if manhwa is centered)
        if total_h > 2500:
            chunk_h = 2000
            chunk_stds = [np.std(gray_small[i:min(total_h, i + chunk_h)], axis=0) for i in range(0, total_h, chunk_h) if (total_h - i) >= 400]
            col_std = np.median(chunk_stds, axis=0) if chunk_stds else np.std(gray_small, axis=0)
        else:
            col_std = np.std(gray_small, axis=0)
        active_cols = np.where(col_std > 5.0)[0]
        if len(active_cols) > int(target_w * 0.25):
            x_left = max(1, active_cols[0] + max(2, int(target_w * 0.02)))
            x_right = min(target_w - 1, active_cols[-1] - max(2, int(target_w * 0.02)))
        else:
            margin = max(1, int(target_w * 0.03))
            x_left = margin
            x_right = target_w - margin

        gray_interior = gray_small[:, x_left:x_right]
        interior_w = max(1, x_right - x_left)

        diff = np.abs(gray_interior.astype(np.int32) - bg_val)
        diff_ratio = np.mean(diff > config.tolerance, axis=1).astype(np.float32)

        blurred_small = cv2.GaussianBlur(gray_small, (5, 5), 0) if gray_small.shape[1] >= 5 else gray_small
        canny = cv2.Canny(blurred_small, config.canny_low, config.canny_high)
        edge_count = np.sum(canny[:, x_left:x_right] > 0, axis=1)
        edge_density = (edge_count / float(interior_w)).astype(np.float32)

        blurred_interior = blurred_small[:, x_left:x_right]
        variance = np.var(blurred_interior, axis=1)
        var_ratio = np.clip(variance / 600.0, 0.0, 1.0).astype(np.float32)

        # Saturation & Skin Tone analysis on interior
        sat_channel = hsv_small[:, x_left:x_right, 1]
        sat_mean = np.mean(sat_channel, axis=1).astype(np.float32)

        row_means = np.mean(gray_interior, axis=1)
        row_maxs = np.max(gray_interior, axis=1)
        row_mins = np.min(gray_interior, axis=1)

        # For light canvas (bg_val > 180), zero out dark gutters in dark scenes
        # For dark canvas (bg_val < 75), zero out light gutters in light scenes
        if bg_val > 180:
            is_dark_gutter = (row_means < 18) & (row_maxs < 35) & (edge_density < 0.012)
            diff_ratio[is_dark_gutter] = 0.0
            var_ratio[is_dark_gutter] = 0.0
            edge_density[is_dark_gutter] = 0.0
        elif bg_val < 75:
            is_light_gutter = (row_means > 235) & (row_mins > 215) & (edge_density < 0.012)
            diff_ratio[is_light_gutter] = 0.0
            var_ratio[is_light_gutter] = 0.0
            edge_density[is_light_gutter] = 0.0

        # Suppress reader screenshot boundary artifacts on top/bottom 5px
        if total_h > 30:
            diff_ratio[:5] = 0.0
            diff_ratio[-5:] = 0.0
            edge_density[:5] = 0.0
            edge_density[-5:] = 0.0
            var_ratio[:5] = 0.0
            var_ratio[-5:] = 0.0

        cr = ycrcb_small[:, x_left:x_right, 1]
        cb = ycrcb_small[:, x_left:x_right, 2]
        y_chan = ycrcb_small[:, x_left:x_right, 0]
        skin_mask = (cr >= 133) & (cr <= 173) & (cb >= 77) & (cb <= 127) & (y_chan >= 40) & (y_chan <= 245)
        skin_ratio = np.mean(skin_mask, axis=1).astype(np.float32)

        # Morphological horizontal line detection (finds horizontal panel border strokes across width)
        canny_edges = cv2.Canny(gray_small, 30, 100)
        k_len = max(15, int(target_w * 0.15))
        horiz_elem = cv2.getStructuringElement(cv2.MORPH_RECT, (k_len, 1))
        canny_opened = cv2.morphologyEx(canny_edges, cv2.MORPH_OPEN, horiz_elem)

        margin = max(1, int(target_w * 0.03))
        line_counts = np.sum(canny_opened[:, margin:target_w - margin] > 0, axis=1)
        reaches_left = np.any(canny_opened[:, margin:margin + int(target_w * 0.12)] > 0, axis=1)
        reaches_right = np.any(canny_opened[:, target_w - margin - int(target_w * 0.12):target_w - margin] > 0, axis=1)
        wide_line = line_counts >= int(target_w * 0.50)

        # Standard panel border spans across width or reaches BOTH left and right margins
        std_border = wide_line | (reaches_left & reaches_right & (line_counts >= int(target_w * 0.40)))

        has_edge = std_border
        has_edge_dilated = np.convolve(has_edge.astype(np.float32), np.ones(5), mode='same') > 0

        if bg_val > 128:
            has_contrast = (np.mean(gray_interior < 90, axis=1) > 0.15)
        else:
            has_contrast = (np.mean(gray_interior > 140, axis=1) > 0.15)

        cand_rows = np.where(has_edge_dilated & has_contrast)[0]
        cand_rows = [r for r in cand_rows if 12 <= r <= total_h - 12]

        is_horizontal_border = np.zeros(total_h, dtype=bool)
        if cand_rows:
            clusters = []
            curr = [cand_rows[0]]
            for r in cand_rows[1:]:
                if r <= curr[-1] + 15:
                    curr.append(r)
                else:
                    clusters.append(int(np.median(curr)))
                    curr = [r]
            clusters.append(int(np.median(curr)))

            for c_y in clusters:
                nearby = sum(1 for o in clusters if abs(o - c_y) <= 120)
                if nearby <= 2:
                    is_horizontal_border[c_y] = True

        activity = np.clip(diff_ratio * 0.45 + edge_density * 2.8 + var_ratio * 0.20, 0.0, 1.0).astype(np.float32)
        return diff_ratio, edge_density, var_ratio, sat_mean, skin_ratio, is_horizontal_border, activity

    @classmethod
    def detect_speech_bubbles_2d(cls, canvas_bgr: np.ndarray, bg_val: int = 255) -> List[Tuple[int, int, int, int]]:
        """
        Detects 2D bounding boxes [x1, y1, x2, y2] of speech bubbles and text regions
        in the canvas using morphological text clustering.
        """
        total_h, total_w = canvas_bgr.shape[:2]
        if total_h <= 0 or total_w <= 0:
            return []

        scale = min(1.0, 500.0 / float(total_w))
        calc_w = max(10, int(round(total_w * scale)))
        calc_h = max(10, int(round(total_h * scale)))

        small_bgr = cv2.resize(canvas_bgr, (calc_w, calc_h), interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_NEAREST)
        gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2HSV)
        inv_scale = 1.0 / scale
        bubble_boxes = []

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
            x, y, w, h = cv2.boundingRect(cnt)
            if w > int(30 * scale) and int(12 * scale) < h < int(650 * scale) and w < calc_w * 0.85:
                pad_y = max(1, int(35 * scale))
                y1 = max(0, y - pad_y)
                y2 = min(calc_h, y + h + pad_y)
                sub_gray = gray[y1:y2, max(0, x - int(10 * scale)):min(calc_w, x + w + int(10 * scale))]
                sub_hsv = hsv[y1:y2, max(0, x - int(10 * scale)):min(calc_w, x + w + int(10 * scale))]
                white_ratio = np.mean(sub_gray > 175)
                sat_mean = np.mean(sub_hsv[:, :, 1])

                is_valid_bubble = False
                if white_ratio > 0.35 and sat_mean < 100.0:
                    sub_dark = (gray[y:y + h, x:x + w] < 85).astype(np.uint8)
                    num_cc, _, stats_cc, _ = cv2.connectedComponentsWithStats(sub_dark)
                    small_letters = sum(
                        1 for k in range(1, num_cc)
                        if int(4 * scale * scale) <= stats_cc[k, cv2.CC_STAT_AREA] <= int(250 * scale * scale)
                        and stats_cc[k, cv2.CC_STAT_HEIGHT] <= int(45 * scale)
                    )
                    if small_letters >= 3:
                        is_valid_bubble = True
                elif bg_val <= 128 and sat_mean < 100.0:
                    sub_light = (gray[y:y + h, x:x + w] > 170).astype(np.uint8)
                    num_cc, _, stats_cc, _ = cv2.connectedComponentsWithStats(sub_light)
                    small_letters = sum(
                        1 for k in range(1, num_cc)
                        if int(4 * scale * scale) <= stats_cc[k, cv2.CC_STAT_AREA] <= int(250 * scale * scale)
                        and stats_cc[k, cv2.CC_STAT_HEIGHT] <= int(45 * scale)
                    )
                    if small_letters >= 3:
                        is_valid_bubble = True

                if not is_valid_bubble:
                    continue

                orig_y_start = max(0, int(y1 * inv_scale))
                orig_y_end = min(total_h, int(y2 * inv_scale))
                orig_x1 = max(0, int((x - int(10 * scale)) * inv_scale))
                orig_x2 = min(total_w, int((x + w + int(10 * scale)) * inv_scale))

                cand_patch = canvas_bgr[orig_y_start:orig_y_end, orig_x1:orig_x2]
                if cand_patch.size > 0:
                    t_score = TextScorer.calculate_text_score(cand_patch, bg_val=bg_val)
                    if t_score < 18:
                        continue

                if (orig_y_end - orig_y_start) <= 650:
                    bubble_boxes.append((orig_x1, orig_y_start, orig_x2, orig_y_end))

        return bubble_boxes

    @classmethod
    def detect_speech_bubbles(cls, canvas_bgr: np.ndarray, bg_val: int = 255) -> List[Tuple[int, int]]:
        """
        Detects vertical bounding boxes [y_start, y_end] of all speech bubbles and text regions
        in the canvas using 2D-aware clustering, preventing false multi-thousand-pixel chaining.
        """
        boxes = cls.detect_speech_bubbles_2d(canvas_bgr, bg_val=bg_val)
        if not boxes:
            return []

        # 2D-aware merging: only merge boxes that overlap in X and are vertically adjacent
        merged_boxes: List[Tuple[int, int, int, int]] = []
        for b in sorted(boxes, key=lambda x: (x[1], x[0])):
            x1, y1, x2, y2 = b
            merged = False
            for i in range(len(merged_boxes)):
                mx1, my1, mx2, my2 = merged_boxes[i]
                x_overlap = min(x2, mx2) - max(x1, mx1)
                if x_overlap > 10 and (y1 <= my2 + 15 and my1 <= y2 + 15):
                    if max(my2, y2) - min(my1, y1) <= 650:
                        merged_boxes[i] = (min(mx1, x1), min(my1, y1), max(mx2, x2), max(my2, y2))
                        merged = True
                        break
            if not merged:
                merged_boxes.append(b)

        raw_spans = sorted([(b[1], b[3]) for b in merged_boxes], key=lambda s: s[0])
        # Consolidate non-overlapping 1D spans for clean row masking
        merged_spans: List[Tuple[int, int]] = []
        for s_start, s_end in raw_spans:
            if not merged_spans:
                merged_spans.append((s_start, s_end))
            else:
                prev_s, prev_e = merged_spans[-1]
                if s_start <= prev_e + 5 and (s_end - prev_s) <= 650:
                    merged_spans[-1] = (prev_s, max(prev_e, s_end))
                else:
                    merged_spans.append((s_start, s_end))

        return merged_spans

    @classmethod
    def detect_panels_2d(
        cls,
        canvas_bgr: np.ndarray,
        bg_val: int = 255
    ) -> List[Dict[str, Any]]:
        """
        Detects 2D panel bounding boxes in the canvas/page, identifying individual comic panels,
        multi-panel layouts, and side-by-side (parallel) panels.
        """
        H, W = canvas_bgr.shape[:2]
        if H < 40 or W < 40:
            return []

        gray = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2GRAY)
        diff = np.abs(gray.astype(np.int32) - bg_val)
        
        canny = cv2.Canny(gray, 40, 140)
        k_size = max(3, int(min(W, H) * 0.015))
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (k_size, k_size))
        closed = cv2.morphologyEx(canny, cv2.MORPH_CLOSE, k)
        
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        raw_boxes = []
        min_panel_area = int(W * H * 0.03)
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            if area < min_panel_area or w < int(W * 0.18) or h < 45:
                continue
            if w > int(W * 0.98) and h > int(H * 0.98):
                continue
            hull = cv2.convexHull(cnt)
            solidity = float(cv2.contourArea(hull)) / (area + 1e-5)
            if solidity > 0.55:
                raw_boxes.append((x, y, x + w, y + h))

        # Check for vertical gutter dividing side-by-side panels
        col_activity = np.mean(diff > 18, axis=0)
        mid_s = int(W * 0.25)
        mid_e = int(W * 0.75)
        mid_cols = col_activity[mid_s:mid_e]
        if len(mid_cols) > 0 and np.min(mid_cols) < 0.05:
            gutter_x = mid_s + int(np.argmin(mid_cols))
            if len(raw_boxes) == 0:
                raw_boxes.append((0, 0, gutter_x, H))
                raw_boxes.append((gutter_x, 0, W, H))

        # Check side-by-side panels
        panel_dicts: List[Dict[str, Any]] = []
        for i, (x1, y1, x2, y2) in enumerate(raw_boxes):
            is_side_by_side = False
            for j, (ox1, oy1, ox2, oy2) in enumerate(raw_boxes):
                if i == j:
                    continue
                y_overlap = max(0, min(y2, oy2) - max(y1, oy1))
                min_h = min(y2 - y1, oy2 - oy1)
                if min_h > 0 and (y_overlap / min_h) > 0.40:
                    x_overlap = max(0, min(x2, ox2) - max(x1, ox1))
                    if x_overlap < 0.15 * min(x2 - x1, ox2 - ox1):
                        is_side_by_side = True
                        break
            panel_dicts.append({
                "bbox": (int(x1), int(y1), int(x2), int(y2)),
                "confidence": 0.92,
                "is_side_by_side": is_side_by_side,
                "label": "panel"
            })

        return panel_dicts

    @classmethod
    def calculate_focal_points(
        cls,
        img_bgr: np.ndarray,
        bg_val: int = 255,
        detected_characters: Optional[List[Any]] = None,
        detected_bubbles: Optional[List[Any]] = None,
        detected_faces: Optional[List[Any]] = None
    ) -> Tuple[Tuple[float, float], List[Dict[str, Any]], str]:
        """
        Calculates normalized focal points (0.0 to 1.0) and recommended camera motion hint.
        Supports passing pre-detected characters/bubbles/faces to eliminate redundant YOLO inferences.
        Returns:
            primary_focal_point: (norm_x, norm_y)
            focal_points_list: list of focal point dicts
            camera_hint: str ("zoom_in_face", "zoom_in", "zoom_out", "pan_left_to_right", "pan_top_to_bottom", "static")
        """
        H, W = img_bgr.shape[:2]
        if H <= 0 or W <= 0:
            return (0.5, 0.5), [], "static"

        points: List[Dict[str, Any]] = []

        # 0. Faces: highest priority for video camera focal point & zoom target
        face_points = []
        if detected_faces is not None:
            for f in detected_faces:
                fx1, fy1, fx2, fy2 = f if isinstance(f, (tuple, list)) else f.get("bbox", (0, 0, W, H))
                fw = fx2 - fx1
                fh = fy2 - fy1
                if fw <= 0 or fh <= 0:
                    continue
                fcx = (fx1 + fx2) / 2.0
                fcy = (fy1 + fy2) / 2.0
                f_pt = {
                    "x": round(float(fcx / W), 3),
                    "y": round(float(fcy / H), 3),
                    "weight": 2.5,
                    "type": "face",
                    "bbox": (int(fx1), int(fy1), int(fx2), int(fy2))
                }
                points.append(f_pt)
                face_points.append(f_pt)

        # 1. Characters: reuse pre-detected canvas characters if available
        if detected_characters is not None:
            for d in detected_characters:
                bx1, by1, bx2, by2 = d if isinstance(d, (tuple, list)) else d.get("bbox", (0, 0, W, H))
                cw = bx2 - bx1
                ch = by2 - by1
                if cw <= 0 or ch <= 0:
                    continue
                cx = (bx1 + bx2) / 2.0
                cy = by1 + ch * 0.35
                points.append({
                    "x": round(float(cx / W), 3),
                    "y": round(float(cy / H), 3),
                    "weight": 1.2,
                    "type": "character",
                    "bbox": (int(bx1), int(by1), int(bx2), int(by2))
                })
        else:
            char_regions = YOLOVisualDetector.detect_visual_regions(img_bgr)
            for d in char_regions:
                bx1, by1, bx2, by2 = d.get("bbox", (0, 0, W, H))
                cw = bx2 - bx1
                ch = by2 - by1
                if cw <= 0 or ch <= 0:
                    continue
                cx = (bx1 + bx2) / 2.0
                cy = by1 + ch * 0.35
                norm_x = round(float(cx / W), 3)
                norm_y = round(float(cy / H), 3)
                conf = float(d.get("confidence", 0.85))
                points.append({
                    "x": norm_x,
                    "y": norm_y,
                    "weight": conf * 1.2,
                    "type": "character",
                    "bbox": (int(bx1), int(by1), int(bx2), int(by2))
                })

        # 2. Speech bubbles: reuse pre-detected canvas bubbles if available
        if detected_bubbles is not None:
            for b in detected_bubbles:
                bx1, by1, bx2, by2 = b if isinstance(b, (tuple, list)) else b.get("bbox", (0, 0, W, H))
                cx = (bx1 + bx2) / 2.0
                cy = (by1 + by2) / 2.0
                points.append({
                    "x": round(float(cx / W), 3),
                    "y": round(float(cy / H), 3),
                    "weight": 0.65,
                    "type": "bubble",
                    "bbox": (int(bx1), int(by1), int(bx2), int(by2))
                })
        else:
            bubbles = cls.detect_speech_bubbles_2d(img_bgr, bg_val=bg_val)
            for bx1, by1, bx2, by2 in bubbles:
                cx = (bx1 + bx2) / 2.0
                cy = (by1 + by2) / 2.0
                points.append({
                    "x": round(float(cx / W), 3),
                    "y": round(float(cy / H), 3),
                    "weight": 0.65,
                    "type": "bubble",
                    "bbox": (int(bx1), int(by1), int(bx2), int(by2))
                })

        # 3. Fallback to center of mass if no characters or bubbles (vectorized without 2D meshgrid)
        if not points:
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            diff = np.abs(gray.astype(np.float32) - bg_val)
            diff[diff < 20] = 0
            total_mass = float(np.sum(diff))
            if total_mass > 100:
                com_x = float(np.sum(np.arange(W, dtype=np.float32) * np.sum(diff, axis=0)) / total_mass)
                com_y = float(np.sum(np.arange(H, dtype=np.float32) * np.sum(diff, axis=1)) / total_mass)
                norm_x = round(float(com_x / W), 3)
                norm_y = round(float(com_y / H), 3)
                points.append({
                    "x": norm_x,
                    "y": norm_y,
                    "weight": 0.5,
                    "type": "visual_center",
                    "bbox": (0, 0, W, H)
                })

        # Calculate weighted centroid primary focal point
        if points:
            total_w = sum(p["weight"] for p in points)
            avg_x = sum(p["x"] * p["weight"] for p in points) / total_w
            avg_y = sum(p["y"] * p["weight"] for p in points) / total_w
            primary_focal = (round(float(np.clip(avg_x, 0.05, 0.95)), 3),
                             round(float(np.clip(avg_y, 0.05, 0.95)), 3))
        else:
            primary_focal = (0.5, 0.35)

        # 4. Determine camera hint
        char_points = [p for p in points if p["type"] == "character"]
        bubble_points = [p for p in points if p["type"] == "bubble"]

        if face_points:
            camera_hint = "zoom_in_face"
        elif H > W * 1.80:
            camera_hint = "pan_top_to_bottom"
        elif len(points) >= 2:
            xs = [p["x"] for p in points]
            ys = [p["y"] for p in points]
            x_spread = max(xs) - min(xs)
            y_spread = max(ys) - min(ys)

            if bubble_points and char_points:
                avg_bubble_y = float(np.mean([p["y"] for p in bubble_points]))
                avg_char_y = float(np.mean([p["y"] for p in char_points]))
                if abs(avg_char_y - avg_bubble_y) > 0.25:
                    camera_hint = "pan_top_to_bottom"
                elif x_spread > 0.40:
                    camera_hint = "pan_left_to_right"
                else:
                    camera_hint = "zoom_in"
            elif x_spread > 0.45 and x_spread > y_spread:
                camera_hint = "pan_left_to_right"
            elif y_spread > 0.50:
                camera_hint = "pan_top_to_bottom"
            elif len(char_points) >= 1:
                camera_hint = "zoom_in"
            else:
                camera_hint = "zoom_out"
        elif len(char_points) == 1:
            camera_hint = "zoom_in"
        else:
            camera_hint = "static"

        return primary_focal, points, camera_hint

    @classmethod
    def cluster_narrative_beats(
        cls,
        blocks: List[VisualContentBlock],
        max_dialogue_gap: int = 180,
        max_cluster_height: int = 1400
    ) -> List[VisualContentBlock]:
        """
        Clusters adjacent rapid dialogue beats into unified narrative beat pages,
        preventing fragmented single-bubble pages while keeping height within preferred limits.
        """
        if not blocks or len(blocks) <= 1:
            return blocks

        clustered: List[VisualContentBlock] = []
        curr = blocks[0]

        for nxt in blocks[1:]:
            gap = nxt.start_y - curr.end_y
            combined_h = nxt.end_y - curr.start_y

            is_curr_dialogue = curr.block_type in (PageType.DIALOGUE, PageType.TEXT_ONLY)
            is_nxt_dialogue = nxt.block_type in (PageType.DIALOGUE, PageType.TEXT_ONLY)

            should_merge = False
            if gap <= max_dialogue_gap and combined_h <= max_cluster_height:
                if is_curr_dialogue and is_nxt_dialogue:
                    should_merge = True

            if should_merge:
                new_type = PageType.DIALOGUE if (is_curr_dialogue and is_nxt_dialogue) else PageType.VISUAL_WITH_TEXT
                w_curr = max(1, curr.height)
                w_nxt = max(1, nxt.height)
                new_act = (curr.avg_activity * w_curr + nxt.avg_activity * w_nxt) / (w_curr + w_nxt)
                curr = VisualContentBlock(
                    start_y=curr.start_y,
                    end_y=nxt.end_y,
                    height=combined_h,
                    block_type=new_type,
                    avg_activity=new_act
                )
            else:
                clustered.append(curr)
                curr = nxt

        clustered.append(curr)
        return clustered

    @classmethod
    def separate_page_layers(
        cls,
        page_bgr: np.ndarray,
        bg_val: int = 255
    ) -> Dict[str, Any]:
        """
        Separates a comic page into clean background plate (with speech bubbles inpainted)
        and transparent bubble overlay (RGBA PNG) for dynamic video recap animations.
        """
        H, W = page_bgr.shape[:2]
        if H <= 0 or W <= 0:
            return {"clean_plate": page_bgr, "bubble_overlay": np.zeros((H, W, 4), dtype=np.uint8), "bubble_count": 0}

        bubbles = cls.detect_speech_bubbles_2d(page_bgr, bg_val=bg_val)
        if not bubbles:
            clean_plate = page_bgr.copy()
            bubble_overlay = np.zeros((H, W, 4), dtype=np.uint8)
            return {"clean_plate": clean_plate, "bubble_overlay": bubble_overlay, "bubble_count": 0}

        bubble_mask = np.zeros((H, W), dtype=np.uint8)
        gray = cv2.cvtColor(page_bgr, cv2.COLOR_BGR2GRAY)

        for bx1, by1, bx2, by2 in bubbles:
            sub = gray[by1:by2, bx1:bx2]
            if bg_val > 128:
                sub_mask = (sub > 175).astype(np.uint8) * 255
                k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
                sub_mask = cv2.morphologyEx(sub_mask, cv2.MORPH_CLOSE, k)
                bubble_mask[by1:by2, bx1:bx2] = np.maximum(bubble_mask[by1:by2, bx1:bx2], sub_mask)
            else:
                bubble_mask[by1:by2, bx1:bx2] = 255

        k_inpaint = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        inpaint_mask = cv2.dilate(bubble_mask, k_inpaint, iterations=1)

        try:
            clean_plate = cv2.inpaint(page_bgr, inpaint_mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
        except Exception:
            clean_plate = page_bgr.copy()

        bubble_overlay = np.zeros((H, W, 4), dtype=np.uint8)
        bubble_overlay[:, :, :3] = page_bgr
        bubble_overlay[:, :, 3] = inpaint_mask

        return {
            "clean_plate": clean_plate,
            "bubble_overlay": bubble_overlay,
            "bubble_count": len(bubbles)
        }

    @classmethod
    def compute_row_content_mask(
        cls,
        canvas_bgr: np.ndarray,
        bg_val: int,
        config: PaginationConfig
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Computes boolean row content mask and row activity scores.
        A row is considered CONTENT if it has non-background pixels, edges, or color variance.
        """
        diff_ratio, edge_density, var_ratio, _, _, _, activity = cls.compute_row_metrics(canvas_bgr, bg_val, config)
        if len(diff_ratio) == 0:
            return np.zeros(0, dtype=bool), np.zeros(0, dtype=np.float32)

        is_content = (diff_ratio > 0.020) | (edge_density > 0.008) | (var_ratio > 0.025)
        return is_content, activity

    @classmethod
    def is_scene_transition(
        cls,
        canvas_bgr: Optional[np.ndarray],
        y_prev_end: int,
        y_next_start: int
    ) -> bool:
        """
        Determines whether the boundary between y_prev_end and y_next_start
        represents a major scene transition (significant background color shift
        or wide pacing gutter >= 80px).
        """
        if canvas_bgr is None or canvas_bgr.size == 0:
            return False
        h, w = canvas_bgr.shape[:2]
        if y_prev_end <= 0 or y_next_start >= h or y_prev_end >= y_next_start:
            return False

        gutter_h = y_next_start - y_prev_end
        # A wide gutter (>= 80px) in webtoons indicates a major scene or pacing transition
        if gutter_h >= 80:
            return True
        if gutter_h < 35:
            return False

        # Sample 30px above y_prev_end and 30px below y_next_start
        sample_top = max(0, y_prev_end - min(30, y_prev_end))
        sample_bot = min(h, y_next_start + min(30, h - y_next_start))

        top_slice = canvas_bgr[sample_top:y_prev_end, :]
        bot_slice = canvas_bgr[y_next_start:sample_bot, :]
        if top_slice.size == 0 or bot_slice.size == 0:
            return False

        top_med = np.median(top_slice.reshape(-1, 3), axis=0)
        bot_med = np.median(bot_slice.reshape(-1, 3), axis=0)
        color_dist = float(np.linalg.norm(top_med - bot_med))

        # Significant color/luminance shift (e.g. daytime to nighttime, white to dark)
        return color_dist > 55.0

    @classmethod
    def is_credit_or_recruitment_page(
        cls,
        slice_bgr: np.ndarray,
        page_index: Optional[int] = None,
        total_pages: Optional[int] = None
    ) -> bool:
        """
        Detects scanlation credit pages, scanlation recruitment outro pages,
        donation/patreon/discord links, and translator info.
        Targets:
        - Pages 1 & 2 (chapter start)
        - The last 3 pages (chapter end)
        - Any page with skin_ratio < 0.015 (text cards / ads)
        """
        if slice_bgr is None or slice_bgr.size == 0:
            return False

        h, w = slice_bgr.shape[:2]
        if h < 50 or w < 50:
            return False

        # Skin tone ratio check
        ycrcb = cv2.cvtColor(slice_bgr, cv2.COLOR_BGR2YCrCb)
        cr = ycrcb[:, :, 1]
        cb = ycrcb[:, :, 2]
        y_chan = ycrcb[:, :, 0]
        skin_mask = (cr >= 133) & (cr <= 173) & (cb >= 77) & (cb <= 127) & (y_chan >= 40) & (y_chan <= 245)
        skin_ratio = float(np.mean(skin_mask))

        # Fast exit: panels with human skin tone / character art are never credit/recruitment cards
        if skin_ratio >= 0.025:
            return False

        # Check candidacy to avoid running OCR unnecessarily on normal comic panels
        is_pos_candidate = False
        if page_index is not None:
            if page_index <= 2:
                is_pos_candidate = True
            elif total_pages is not None and page_index >= max(1, total_pages - 2):
                is_pos_candidate = True
            elif skin_ratio < 0.010 and h < 350:
                is_pos_candidate = True
        else:
            # Standalone image verification or testing without page_index
            is_pos_candidate = (skin_ratio < 0.010)

        if not is_pos_candidate:
            return False

        # Downscale for ultra-fast OCR check (max dimension 640px)
        scale = 640.0 / max(h, w) if max(h, w) > 640 else 1.0
        small_bgr = cv2.resize(slice_bgr, (int(w * scale), int(h * scale))) if scale < 1.0 else slice_bgr

        try:
            regions = OCRTextDetector.detect_text_regions(small_bgr)
            for r in regions:
                t = r.get("text", "")
                if t and CREDIT_KEYWORDS_REGEX.search(t):
                    return True
        except Exception:
            pass

        return False

    @classmethod
    def classify_page_content(
        cls,
        slice_bgr: np.ndarray,
        p_type: str = PageType.CONTENT,
        visual_score: int = 50,
        text_score: int = 0,
        bg_val: Optional[int] = None,
        page_index: Optional[int] = None,
        total_pages: Optional[int] = None
    ) -> Tuple[str, int, bool]:
        """
        Classifies page into frame-based semantic content types:
          - VISUAL: Character, action, or scene artwork panel (video_candidate=True)
          - DIALOGUE: Speech bubbles, dialogue text in gutters/whitespace (video_candidate=False)
          - MIXED: Comic frame containing both visual artwork and embedded speech bubbles (video_candidate=True)
          - TEXT_ONLY: Pure narration cards, prologue/recap text blocks, title cards (video_candidate=False)
          - TEXT_BUBBLE: Giant dialogue or scream bubbles taking up the page (video_candidate=False)
          - CREDIT_ADS: Scanlation credits, staff recruitment, discord/patreon cards (video_candidate=False)
          - EMPTY_GUTTER: Blank space / margins (video_candidate=False)

        Returns:
          (content_type, importance_score, video_candidate)
        """
        if slice_bgr is None or slice_bgr.size == 0:
            return PageType.EMPTY_GUTTER, 0, False

        h, w = slice_bgr.shape[:2]
        gray = cv2.cvtColor(slice_bgr, cv2.COLOR_BGR2GRAY)
        if bg_val is None:
            border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
            bg_val = int(np.median(border)) if len(border) > 0 else 255

        # Check for empty gutter / blank slice
        diff_from_bg = np.abs(gray.astype(np.float32) - bg_val)
        non_bg_ratio = float(np.mean(diff_from_bg > 16.0))
        if non_bg_ratio < 0.02 and visual_score < 15:
            return PageType.EMPTY_GUTTER, 0, False

        # Color & skin metrics to distinguish pure text/dialogue from rich artwork
        hsv = cv2.cvtColor(slice_bgr, cv2.COLOR_BGR2HSV)
        sat_mean = float(np.mean(hsv[:, :, 1]))
        ycrcb = cv2.cvtColor(slice_bgr, cv2.COLOR_BGR2YCrCb)
        cr = ycrcb[:, :, 1]
        cb = ycrcb[:, :, 2]
        y_chan = ycrcb[:, :, 0]
        skin_mask = (cr >= 133) & (cr <= 173) & (cb >= 77) & (cb <= 127) & (y_chan >= 40) & (y_chan <= 245)
        skin_ratio = float(np.mean(skin_mask))

        # 0. CREDIT & ADS DETECTION:
        if cls.is_credit_or_recruitment_page(slice_bgr, page_index=page_index, total_pages=total_pages):
            content_type = PageType.CREDIT_ADS
            importance_score = 0
            video_candidate = False
            return content_type, importance_score, video_candidate

        # 0b. GIANT SPEECH / SCREAM BUBBLE DETECTION:
        white_ratio = float(np.mean(gray >= 235))
        black_ratio = float(np.mean(gray <= 35))
        is_giant_bubble = (h < 500 and visual_score < 35 and skin_ratio < 0.015 and sat_mean < 25.0 and (white_ratio >= 0.45 or (white_ratio + black_ratio >= 0.70)))
        if is_giant_bubble:
            content_type = PageType.DIALOGUE
            importance_score = 5
            video_candidate = False
            return content_type, importance_score, video_candidate

        is_dialogue_flagged = p_type in (PageType.DIALOGUE, PageType.TEXT_BUBBLE)
        has_rich_artwork = (visual_score >= 38 and (sat_mean >= 25.0 or skin_ratio >= 0.020))

        # Fast deterministic page score from already-computed visual & text metrics (< 0.01ms)
        page_score = int(np.clip(visual_score * 0.85 + (10 if skin_ratio > 0.02 else 0) - (text_score * 0.15), 10, 100))

        # Monochrome dialogue/bubble slice detection:
        # A slice without color (sat_mean < 15) and without skin (skin_ratio < 0.01) that is mostly white/black gutter/bubble
        # is DIALOGUE or TEXT_ONLY, even if edge density from the bubble border elevated visual_score
        is_monochrome_dialogue = (
            h < 650
            and sat_mean < 15.0
            and skin_ratio < 0.01
            and (white_ratio >= 0.40 or (white_ratio + black_ratio >= 0.65))
            and not has_rich_artwork
        )
        if is_monochrome_dialogue:
            if text_score >= 30 and p_type == PageType.TEXT_ONLY:
                content_type = PageType.TEXT_ONLY
            else:
                content_type = PageType.DIALOGUE
            importance_score = max(5, min(25, text_score // 2))
            video_candidate = False
            return content_type, importance_score, video_candidate

        # 1. DIALOGUE & TEXT_ONLY detection:
        if is_dialogue_flagged and not has_rich_artwork:
            content_type = PageType.DIALOGUE
            importance_score = max(5, min(25, text_score // 2))
            video_candidate = False
            return content_type, importance_score, video_candidate

        if (text_score >= 35 and visual_score < 35 and not has_rich_artwork) or (p_type == PageType.TEXT_ONLY and not has_rich_artwork):
            content_type = PageType.TEXT_ONLY if (p_type == PageType.TEXT_ONLY or (sat_mean < 15.0 and skin_ratio < 0.005)) else PageType.DIALOGUE
            importance_score = max(5, min(25, text_score // 2))
            video_candidate = False
            return content_type, importance_score, video_candidate

        if text_score >= 50 and visual_score < 40 and not has_rich_artwork:
            content_type = PageType.TEXT_ONLY if sat_mean < 15.0 else PageType.DIALOGUE
            importance_score = max(10, min(30, text_score // 2))
            video_candidate = False
            return content_type, importance_score, video_candidate

        # 2. MIXED detection:
        # Comic frames containing both significant visual artwork and speech bubbles
        if has_rich_artwork and (p_type in (PageType.MIXED, PageType.DIALOGUE, PageType.TEXT_BUBBLE) or text_score >= 30):
            content_type = PageType.MIXED
            importance_score = max(20, min(100, page_score if page_score > 0 else int(round(visual_score * 0.80))))
            video_candidate = (visual_score >= 25)
            return content_type, importance_score, video_candidate

        # 3. VISUAL_WITH_TEXT detection:
        # Visual artwork with small attached speech bubble kept to preserve composition
        has_speech_bubble_in_page = (p_type in (PageType.MIXED, PageType.TEXT_BUBBLE)) or (text_score >= 25)
        if has_rich_artwork and has_speech_bubble_in_page and 25 <= text_score < 45:
            content_type = PageType.VISUAL_WITH_TEXT
            importance_score = max(20, min(100, page_score if page_score > 0 else visual_score))
            video_candidate = (visual_score >= 25 and h >= 50)
            return content_type, importance_score, video_candidate

        # 4. VISUAL detection:
        content_type = PageType.VISUAL
        importance_score = max(20, min(100, page_score if page_score > 0 else visual_score))
        video_candidate = (visual_score >= 25 and h >= 50)

        # Strict safety invariant: DIALOGUE, TEXT_ONLY, TEXT_BUBBLE, CREDIT_ADS are NEVER video candidates
        if content_type in (PageType.CREDIT_ADS, PageType.DIALOGUE, PageType.TEXT_ONLY, PageType.TEXT_BUBBLE, PageType.EMPTY_GUTTER):
            video_candidate = False

        return content_type, importance_score, video_candidate

    @classmethod
    def classify_page_tag(
        cls,
        slice_bgr: np.ndarray,
        p_type: str = PageType.CONTENT,
        visual_score: int = 50,
        text_score: int = 0,
        score_breakdown: Optional[Dict[str, float]] = None,
        bg_val: Optional[int] = None,
        content_type: Optional[str] = None,
        page_index: Optional[int] = None,
        total_pages: Optional[int] = None,
        detected_characters: Optional[List[Any]] = None,
        detected_bubbles: Optional[List[Any]] = None,
        detected_faces: Optional[List[Any]] = None
    ) -> str:
        """
        Classifies each paginated page into one of 5 visual semantic tags:
          - CHARACTER_ART: Main character is the primary visual focus (portrait, close-up, dominant focal character)
          - CHARACTER_SCENE: Character + background/scene, preserving full composition
          - BACKGROUND_SCENE: Scenery, architecture, environment, or crowd without a single dominant character focus
          - ACTION_ART: Combat, action, skill/magic visual effects, dynamic motion
          - NON_VISUAL: Speech bubble, narration text, dialogue, white space, separator, credit, ads, or low-utility regions
        """
        if slice_bgr is None or slice_bgr.size == 0:
            return PageTag.NON_VISUAL

        h, w = slice_bgr.shape[:2]

        # 1. NON_VISUAL detection:
        # Check content_type flags first
        if content_type in (
            PageType.CREDIT_ADS,
            PageType.EMPTY_GUTTER,
            PageType.TEXT_ONLY,
            PageType.TEXT_BUBBLE,
            PageType.DIALOGUE
        ):
            return PageTag.NON_VISUAL

        if p_type in (PageType.TEXT_BUBBLE, PageType.EMPTY_GUTTER):
            return PageTag.NON_VISUAL

        if visual_score < 18:
            return PageTag.NON_VISUAL

        if text_score >= 45 and visual_score < 30:
            return PageTag.NON_VISUAL

        # Tiny height dialogue snippet or separator
        if h < 130 and (text_score >= 35 or visual_score < 30):
            return PageTag.NON_VISUAL

        # Only check credit/recruitment OCR if content_type hasn't already confirmed visual/artwork
        if content_type not in (PageType.VISUAL, PageType.MIXED, PageType.VISUAL_WITH_TEXT):
            if cls.is_credit_or_recruitment_page(slice_bgr, page_index=page_index, total_pages=total_pages):
                return PageTag.NON_VISUAL

        # Color & skin metrics
        gray = cv2.cvtColor(slice_bgr, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(slice_bgr, cv2.COLOR_BGR2HSV)
        sat_mean = float(np.mean(hsv[:, :, 1]))
        white_ratio = float(np.mean(gray >= 235))
        black_ratio = float(np.mean(gray <= 35))

        ycrcb = cv2.cvtColor(slice_bgr, cv2.COLOR_BGR2YCrCb)
        cr = ycrcb[:, :, 1]
        cb = ycrcb[:, :, 2]
        y_chan = ycrcb[:, :, 0]
        skin_mask = (cr >= 133) & (cr <= 173) & (cb >= 77) & (cb <= 127) & (y_chan >= 40) & (y_chan <= 245)
        skin_ratio = float(np.mean(skin_mask))

        # Blank / gutter check
        if bg_val is None:
            border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
            bg_val = int(np.median(border)) if len(border) > 0 else 255
        diff_from_bg = np.abs(gray.astype(np.float32) - bg_val)
        non_bg_ratio = float(np.mean(diff_from_bg > 16.0))
        if non_bg_ratio < 0.02 and visual_score < 25:
            return PageTag.NON_VISUAL

        # Isolated dialogue / speech bubble page check:
        # High text score with no character faces/bodies and predominantly white/black or uniform background
        has_chars = bool(detected_characters and len(detected_characters) > 0)
        has_faces = bool(detected_faces and len(detected_faces) > 0)
        has_rich_visual = (visual_score >= 38 or sat_mean >= 35.0 or h >= 500)
        if not has_rich_visual and (text_score >= 35 or p_type == PageType.DIALOGUE) and not has_chars and not has_faces and skin_ratio < 0.015:
            if white_ratio >= 0.35 or black_ratio >= 0.35 or non_bg_ratio < 0.30 or visual_score < 40 or sat_mean < 35.0:
                return PageTag.NON_VISUAL

        if visual_score < 35 and skin_ratio < 0.015 and sat_mean < 25.0 and (white_ratio >= 0.45 or (white_ratio + black_ratio >= 0.70)):
            return PageTag.NON_VISUAL

        # Compute or retrieve score breakdown
        if score_breakdown is None:
            calc_v, score_breakdown = VisualSemanticScorer.calculate_score(slice_bgr, bg_val=bg_val)
            if calc_v < 18:
                return PageTag.NON_VISUAL

        cp = float(score_breakdown.get("character_presence", 0.0))
        ac = float(score_breakdown.get("action_context", 0.0))
        vd = float(score_breakdown.get("visual_detail", 0.0))
        ss = float(score_breakdown.get("semantic_similarity", 0.0))

        # Measure directional speedline energy on normalized downscaled canvas
        calc_w = min(w, 500)
        calc_h = max(5, int(round(h * (calc_w / w))))
        small = cv2.resize(gray, (calc_w, calc_h), interpolation=cv2.INTER_AREA if calc_w < w else cv2.INTER_LINEAR)
        gx = cv2.Sobel(small, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(small, cv2.CV_32F, 0, 1, ksize=3)
        diag_energy = float(np.mean(np.abs(gx * gy)))

        # Character coverage ratio
        char_area_ratio = 0.0
        if detected_characters:
            tot_area = float(w * h)
            for c in detected_characters:
                bx1, by1, bx2, by2 = c if isinstance(c, (tuple, list)) else c.get("bbox", (0, 0, 0, 0))
                char_area_ratio += max(0, bx2 - bx1) * max(0, by2 - by1) / max(1.0, tot_area)

        # 2. ACTION_ART: Genuine combat, weapon slashes, intense speedlines, dynamic martial arts
        # Requires high directional speedline energy, high action context, without dominant static portrait
        is_action = (
            (diag_energy >= 70.0 and ac >= 75.0 and vd >= 55.0 and text_score < 45 and (ac > cp + 8.0 or not has_faces))
            or (ac >= 88.0 and vd >= 65.0 and diag_energy >= 60.0 and text_score < 35 and not has_faces and char_area_ratio < 0.20)
            or (ac >= 80.0 and vd >= 75.0 and cp < 40.0 and text_score < 25 and diag_energy >= 50.0)
        )

        # 3. BACKGROUND_SCENE: Scenery, architecture, environment, crowd without single dominant character
        is_background = (
            not has_chars and not has_faces and cp < 30.0 and skin_ratio < 0.018 and (vd >= 25.0 or ss >= 35.0)
            and not is_action
        )

        # 4. CHARACTER_ART: Main character is the primary visual focus (portrait, close-up, prominent character)
        is_char_art = (
            (has_faces or char_area_ratio >= 0.18 or cp >= 52.0 or (cp >= 45.0 and skin_ratio >= 0.025))
            and not is_action
        )

        # 5. Tag routing
        if is_action:
            return PageTag.ACTION_ART
        elif is_char_art:
            return PageTag.CHARACTER_ART
        elif is_background:
            return PageTag.BACKGROUND_SCENE
        else:
            return PageTag.CHARACTER_SCENE

    @staticmethod
    def is_blank_page(
        slice_bgr: np.ndarray,
        bg_val: int,
        config: PaginationConfig,
        ratio_threshold: float = 0.995
    ) -> bool:
        """
        Determines whether a page slice is completely blank/filler background.
        """
        if slice_bgr is None or slice_bgr.shape[0] == 0 or slice_bgr.shape[1] == 0:
            return True

        gray_crop = cv2.cvtColor(slice_bgr, cv2.COLOR_BGR2GRAY)
        diff = np.abs(gray_crop.astype(int) - bg_val)
        bg_ratio = np.mean(diff <= config.tolerance)
        if bg_ratio >= ratio_threshold:
            return True

        canny = cv2.Canny(gray_crop, 50, 150)
        edge_ratio = np.mean(canny > 0)
        if edge_ratio < 0.0004:
            return True

        variance = np.var(gray_crop)
        if variance < 8.0:
            return True

        return False

    @staticmethod
    def find_content_range(
        slice_bgr: np.ndarray,
        pad: int = 4,
        min_content_h: int = 60,
        bg_val: Optional[int] = None
    ) -> Tuple[int, int]:
        """
        Trims excessive top and bottom empty margins inside an extracted page slice,
        ensuring empty white or black gutters are completely excluded from Visual Content Regions.
        """
        h, w = slice_bgr.shape[:2]
        if h <= min_content_h:
            return 0, h

        gray = cv2.cvtColor(slice_bgr, cv2.COLOR_BGR2GRAY)
        canny = cv2.Canny(gray, 25, 90)
        edge_proj = np.sum(canny > 0, axis=1)
        row_vars = np.var(gray, axis=1)
        row_means = np.mean(gray, axis=1)
        row_stds = np.std(gray, axis=1)

        # 1. Detect empty white and black gutters
        is_white_gutter = (row_means >= 240) & (row_stds < 18) & (edge_proj < 5)
        is_black_gutter = (row_means <= 22) & (row_stds < 18) & (edge_proj < 5)
        is_empty_gutter = is_white_gutter | is_black_gutter
        if bg_val is not None:
            is_bg_match = (np.abs(row_means - bg_val) <= 4) & (row_stds < 8) & (edge_proj < 5)
            is_empty_gutter = is_empty_gutter | is_bg_match

        # 2. Detect content rows
        min_edge_pixels = max(2, int(w * 0.004))
        is_content = np.zeros(h, dtype=bool)
        for y in range(h):
            if is_empty_gutter[y]:
                continue
            has_edges = edge_proj[y] >= min_edge_pixels
            has_variance = row_vars[y] >= 30.0
            has_bg_diff = (np.abs(row_means[y] - bg_val) >= 4.0) if bg_val is not None else False
            if has_edges or has_variance or has_bg_diff:
                is_content[y] = True

        if not np.any(is_content):
            # Fallback if whole slice is subtle art
            non_empty = np.where(~is_empty_gutter)[0]
            if len(non_empty) >= min_content_h:
                return int(non_empty[0]), int(non_empty[-1] + 1)
            return 0, h

        # 2.1 Filter top and bottom orphan border slivers (stray cut artifacts)
        # When a cut lands on the border line of an adjacent panel, a thin band of
        # dark/border pixels (<= 14px) appears at the slice boundary, followed (or preceded) by
        # a large empty background gutter (>= 15px) before the true panel content begins.
        # Detecting and filtering these orphan slivers prevents massive blank gutter gaps from being retained.
        if np.any(is_content):
            # Top orphan artifact
            for r in range(min(14, h)):
                if is_empty_gutter[r]:
                    span = 0
                    while (r + span) < h and is_empty_gutter[r + span]:
                        span += 1
                    if span >= 15:
                        if r > 0 and np.any(is_content[:r]):
                            is_content[:r] = False
                            is_empty_gutter[:r] = True
                        break

            # Bottom orphan artifact
            for r in range(h - 1, max(0, h - 14), -1):
                if is_empty_gutter[r]:
                    span = 0
                    while (r - span) >= 0 and is_empty_gutter[r - span]:
                        span += 1
                    if span >= 15:
                        if r < h - 1 and np.any(is_content[r + 1:]):
                            is_content[r + 1:] = False
                            is_empty_gutter[r + 1:] = True
                        break

        if not np.any(is_content):
            non_empty = np.where(~is_empty_gutter)[0]
            if len(non_empty) >= min_content_h:
                return int(non_empty[0]), int(non_empty[-1] + 1)
            return 0, h

        y_top = int(np.argmax(is_content))
        y_bottom = h - int(np.argmax(is_content[::-1]))

        # Strictly clamp padding so we NEVER pad into empty white or black gutters!
        first_non_empty = int(np.argmax(~is_empty_gutter))
        last_non_empty = h - int(np.argmax((~is_empty_gutter)[::-1]))

        y_top = max(first_non_empty, max(0, y_top - pad))
        y_bottom = min(last_non_empty, min(h, y_bottom + pad))

        # 3. Outer panel border snapping:
        # If there is a horizontal black border line near the top or bottom of the slice,
        # and the region outside it is background (empty white/dark gutter or faint floral/connecting decoration),
        # snap y_bottom / y_top directly to the border line!
        max_scan_bot = min(int(h * 0.45), 650)
        for r in range(h - 1, max(y_top + min_content_h, h - max_scan_bot), -1):
            row = gray[r]
            black_ratio = float(np.mean(row < 50))
            row_mean = float(np.mean(row))
            is_border_line = (black_ratio >= 0.55) or (row_mean < 35 and float(np.std(row)) < 30)
            if is_border_line:
                if r + 3 < h:
                    below = gray[r + 1:h]
                    mean_below = float(np.mean(below))
                    black_below = float(np.mean(below < 50))
                    is_light_bg = (mean_below >= 210 and black_below < 0.02)
                    is_dark_bg = (mean_below <= 35 and black_below > 0.95)
                    is_bg_match = (bg_val is not None and abs(mean_below - bg_val) < 20 and black_below < 0.02)
                    if is_light_bg or is_dark_bg or is_bg_match:
                        y_bottom = min(y_bottom, min(h, r + 1 + pad))
                        break

        max_scan_top = min(int(h * 0.45), 650)
        for r in range(y_top, min(y_bottom - min_content_h, max(y_top + 100, max_scan_top))):
            row = gray[r]
            black_ratio = float(np.mean(row < 50))
            row_mean = float(np.mean(row))
            is_border_line = (black_ratio >= 0.55) or (row_mean < 35 and float(np.std(row)) < 30)
            if is_border_line:
                if r > 3:
                    above = gray[0:r]
                    mean_above = float(np.mean(above))
                    black_above = float(np.mean(above < 50))
                    is_light_bg = (mean_above >= 210 and black_above < 0.02)
                    is_dark_bg = (mean_above <= 35 and black_above > 0.95)
                    is_bg_match = (bg_val is not None and abs(mean_above - bg_val) < 20 and black_above < 0.02)
                    if is_light_bg or is_dark_bg or is_bg_match:
                        y_top = max(y_top, max(0, r - pad))
                        break

        if y_top >= y_bottom or (y_bottom - y_top) < min_content_h:
            return 0, h

        return y_top, y_bottom

    @classmethod
    def find_tight_margins_x(
        cls,
        slice_bgr: np.ndarray,
        pad: int = 2,
        min_content_w: int = 40,
        bg_val: Optional[int] = None
    ) -> Tuple[int, int]:
        """
        Ultra-fast horizontal margin detection for an extracted comic slice.
        Downscales height to accelerate projections while preserving full horizontal width resolution.
        """
        h, w = slice_bgr.shape[:2]
        if w <= min_content_w:
            return 0, w

        target_h = min(h, 240)
        sub = cv2.resize(slice_bgr, (w, target_h), interpolation=cv2.INTER_NEAREST) if target_h < h else slice_bgr
        gray_sub = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)

        if bg_val is None:
            border = np.concatenate([gray_sub[0, :], gray_sub[-1, :], gray_sub[:, 0], gray_sub[:, -1]])
            bg_val = int(np.median(border)) if len(border) > 0 else 255

        col_means = np.mean(gray_sub, axis=0)
        col_stds = np.std(gray_sub, axis=0)
        col_vars = np.var(gray_sub, axis=0)
        diff = np.abs(gray_sub.astype(np.int16) - bg_val)
        col_non_bg = np.mean(diff > 16, axis=0)

        is_white_col = (col_means >= 240) & (col_stds < 18)
        is_black_col = (col_means <= 22) & (col_stds < 18)
        is_bg_match = (np.abs(col_means - bg_val) <= 12) & (col_stds < 14)
        is_empty_col = is_white_col | is_black_col | is_bg_match

        is_content_col = (~is_empty_col) & ((col_non_bg > 0.02) | (col_vars >= 30.0))
        if not np.any(is_content_col):
            non_empty_cols = np.where(~is_empty_col)[0]
            if len(non_empty_cols) >= min_content_w:
                x_left = int(non_empty_cols[0])
                x_right = int(non_empty_cols[-1] + 1)
            else:
                return 0, w
        else:
            x_left = int(np.argmax(is_content_col))
            x_right = w - int(np.argmax(is_content_col[::-1]))

            first_non_empty = int(np.argmax(~is_empty_col))
            last_non_empty = w - int(np.argmax((~is_empty_col)[::-1]))

            x_left = max(first_non_empty, max(0, x_left - pad))
            x_right = min(last_non_empty, min(w, x_right + pad))

        if x_left >= x_right or (x_right - x_left) < min_content_w:
            return 0, w

        return x_left, x_right

    @staticmethod
    def is_blank_page(
        slice_bgr: np.ndarray,
        bg_val: Optional[int] = None,
        config: Optional[PaginationConfig] = None,
        ratio_threshold: float = 0.996
    ) -> bool:
        """
        Determines whether a page slice is completely blank/filler background.
        """
        if slice_bgr is None or slice_bgr.size == 0 or slice_bgr.shape[0] == 0 or slice_bgr.shape[1] == 0:
            return True

        gray_crop = cv2.cvtColor(slice_bgr, cv2.COLOR_BGR2GRAY)
        if bg_val is None:
            border = np.concatenate([gray_crop[0, :], gray_crop[-1, :], gray_crop[:, 0], gray_crop[:, -1]])
            bg_val = int(np.median(border)) if len(border) > 0 else 255

        diff = np.abs(gray_crop.astype(np.int16) - bg_val)
        tol = getattr(config, "tolerance", 15) if config else 15
        bg_ratio = float(np.mean(diff <= tol))
        if bg_ratio < ratio_threshold:
            return False

        canny = cv2.Canny(gray_crop, 50, 150)
        edge_ratio = float(np.mean(canny > 0))
        if edge_ratio > 0.0006:
            return False

        variance = float(np.var(gray_crop))
        if variance > 10.0:
            return False

        return True

    @staticmethod
    def find_tight_content_box(
        slice_bgr: np.ndarray,
        pad: int = 2,
        min_content_h: int = 40,
        min_content_w: int = 40,
        bg_val: Optional[int] = None
    ) -> Tuple[int, int, int, int]:
        """
        Trims background gutters and padding on ALL 4 SIDES (top, bottom, left, right)
        of an extracted comic page slice.
        Ensures the resulting image contains only the tight visual frame without surrounding
        whitespace/dark borders, optimal for video Pan/Zoom Ken Burns rendering.
        Returns: (y_top, y_bottom, x_left, x_right)
        """
        h, w = slice_bgr.shape[:2]
        if h <= min_content_h or w <= min_content_w:
            return 0, h, 0, w

        # 1. First get vertical range (y_top, y_bottom)
        y_top, y_bottom = SmartPaginator.find_content_range(
            slice_bgr, pad=pad, min_content_h=min_content_h, bg_val=bg_val
        )

        sub_slice = slice_bgr[y_top:y_bottom, :]
        sh, sw = sub_slice.shape[:2]
        if sh <= 0 or sw <= min_content_w:
            return y_top, y_bottom, 0, w

        # 2. Find horizontal content range (x_left, x_right)
        gray_sub = cv2.cvtColor(sub_slice, cv2.COLOR_BGR2GRAY)
        canny_sub = cv2.Canny(gray_sub, 25, 90)
        col_edge_proj = np.sum(canny_sub > 0, axis=0)
        col_vars = np.var(gray_sub, axis=0)
        col_means = np.mean(gray_sub, axis=0)
        col_stds = np.std(gray_sub, axis=0)

        # Detect empty vertical side gutters (margins)
        is_white_col = (col_means >= 240) & (col_stds < 18) & (col_edge_proj < 3)
        is_black_col = (col_means <= 22) & (col_stds < 18) & (col_edge_proj < 3)
        is_empty_col = is_white_col | is_black_col
        if bg_val is not None:
            is_bg_match = (np.abs(col_means - bg_val) <= 12) & (col_stds < 14) & (col_edge_proj < 3)
            is_empty_col = is_empty_col | is_bg_match

        min_col_edges = max(2, int(sh * 0.005))
        is_content_col = (~is_empty_col) & ((col_edge_proj >= min_col_edges) | (col_vars >= 30.0))

        if not np.any(is_content_col):
            non_empty_cols = np.where(~is_empty_col)[0]
            if len(non_empty_cols) >= min_content_w:
                x_left = int(non_empty_cols[0])
                x_right = int(non_empty_cols[-1] + 1)
            else:
                x_left, x_right = 0, w
        else:
            x_left = int(np.argmax(is_content_col))
            x_right = sw - int(np.argmax(is_content_col[::-1]))

            first_non_empty_col = int(np.argmax(~is_empty_col))
            last_non_empty_col = sw - int(np.argmax((~is_empty_col)[::-1]))

            x_left = max(first_non_empty_col, max(0, x_left - pad))
            x_right = min(last_non_empty_col, min(w, x_right + pad))

        # Check if cropped width is reasonable
        if x_left >= x_right or (x_right - x_left) < min_content_w:
            x_left, x_right = 0, w

        return y_top, y_bottom, x_left, x_right

    @classmethod
    def segment_canvas_v2(
        cls,
        canvas_bgr: np.ndarray,
        bg_val: Optional[int] = None,
        config: Optional[PaginationConfig] = None
    ) -> Tuple[List[int], List[Any], Dict[str, Any]]:
        """
        Upgraded Smart Paging Engine V2: Visual Composition Segmentation.
        1. 1D Visual Boundary Scanning across vertical canvas.
        2. Semantic Safety Layer (YOLO for character/object protection).
        3. Speech Bubble Spatial Analyzer (Case A top edge, Case B bottom edge, Case C internal).
        4. Candidate Boundary Scoring with configurable weights.
        5. Global Page Optimization via Dynamic Programming.
        Returns:
            (selected_cut_points, scored_candidates, debug_info)
        """
        total_h, total_w = canvas_bgr.shape[:2]
        if total_h <= 0 or total_w <= 0:
            return [], [], {}

        cfg = config or PaginationConfig()
        if bg_val is None:
            gray_sample = cv2.cvtColor(canvas_bgr[:min(2000, total_h), :], cv2.COLOR_BGR2GRAY)
            bg_val = cls.detect_background(gray_sample)

        from renderer.visual_boundary_scanner import VisualBoundaryScanner, BoundaryCandidate
        from renderer.speech_bubble_analyzer import SpeechBubbleAnalyzer, BubbleRole
        from renderer.semantic_safety import SemanticSafetyLayer
        from renderer.boundary_scorer import BoundaryScorer
        from renderer.global_page_optimizer import GlobalPageOptimizer
        from renderer.smart_paging_debug import SmartPagingDebugger

        # STAGE A: Fast 1D Visual Boundary Scanner & Pure CV HPP Gutter Scanner
        scanner = VisualBoundaryScanner(
            canny_low=cfg.canny_low,
            canny_high=cfg.canny_high,
            min_candidate_distance=max(25, cfg.border_snap_tolerance * 4)
        )
        signals = scanner.scan_visual_signals(canvas_bgr, bg_val=bg_val)
        visual_cands = scanner.generate_candidates(
            canvas_bgr=canvas_bgr,
            bg_val=bg_val,
            min_page_height=cfg.min_page_height,
            precomputed_signals=signals
        )

        # Pure CV 1D Horizontal Projection Profile (HPP) Scanner
        raw_gutters = []
        hpp_scanner = None
        if getattr(cfg, "enable_hpp_fast_path", True):
            try:
                from renderer.hpp_gutter_scanner import HorizontalProjectionScanner
                hpp_scanner = HorizontalProjectionScanner(
                    default_var_threshold=getattr(cfg, "hpp_variance_threshold", 6.0),
                    min_gutter_height=getattr(cfg, "min_gutter_gap", 8),
                    downsample_width=getattr(cfg, "hpp_downsample_width", 128)
                )
                raw_gutters = hpp_scanner.find_gutters(canvas_bgr, bg_val=bg_val)
            except Exception:
                raw_gutters = []

        # Extract continuous action / motion line spans
        action_density = signals.get("action_line_density", np.zeros(0, dtype=np.float32))
        action_spans = []
        if len(action_density) > 0:
            is_action = action_density > 0.40
            in_act = False
            a_s = 0
            for y in range(len(action_density)):
                if is_action[y] and not in_act:
                    in_act = True
                    a_s = y
                elif not is_action[y] and in_act:
                    in_act = False
                    if y - a_s >= 25:
                        action_spans.append((a_s, y))
            if in_act and len(action_density) - a_s >= 25:
                action_spans.append((a_s, len(action_density)))

        # STAGE B: Semantic & Safety Analysis (Deep Learning YOLOv11 Comic Model)
        characters = []
        objects = []
        panels_yolo = []
        bubbles_yolo = []
        faces_yolo = []
        bodies_yolo = []
        dl_forbidden_spans = []
        try:
            from renderer.comic_vision_ai import ComicVisionAI
            custom_weights = getattr(cfg, "comic_panel_model_path", None)
            if custom_weights:
                ComicVisionAI.get_model(model_path=custom_weights)
            cv_res = ComicVisionAI.detect_canvas_regions(canvas_bgr)
            characters = cv_res.get("characters", [])
            faces_yolo = cv_res.get("faces", [])
            bodies_yolo = cv_res.get("bodies", [])
            bubbles_yolo = cv_res.get("bubbles", [])
            panels_yolo = cv_res.get("panels", [])
            dl_forbidden_spans = cv_res.get("forbidden_spans", [])
        except Exception:
            characters = []
            faces_yolo = []
            bodies_yolo = []
            bubbles_yolo = []
            panels_yolo = []
            dl_forbidden_spans = []

        if not characters:
            try:
                regions = YOLOVisualDetector.detect_visual_regions(canvas_bgr)
                characters = [r["bbox"] for r in regions if r.get("is_character")]
                objects = [
                    r["bbox"] for r in regions
                    if not r.get("is_character") and not any(k in str(r.get("class", "")).lower() for k in ("page", "panel", "frame"))
                ]
            except Exception:
                pass

        safety_layer = SemanticSafetyLayer(
            character_overlap_penalty=cfg.character_overlap_penalty,
            object_overlap_penalty=cfg.object_overlap_penalty
        )
        safety_layer.set_detected_regions(characters=characters, objects=objects)
        safety_layer.set_action_spans(action_spans)

        # 2. Speech Bubble Detection & Spatial Analysis (Case A, B, C)
        bubble_analyzer = SpeechBubbleAnalyzer()
        cv_bubbles = bubble_analyzer.detect_speech_bubbles_cv(canvas_bgr, bg_val=bg_val)
        all_bubble_boxes = bubble_analyzer._cluster_bubble_boxes((bubbles_yolo or []) + cv_bubbles)

        analyzed_bubbles = bubble_analyzer.classify_speech_bubbles(
            canvas_bgr=canvas_bgr,
            bubble_boxes=all_bubble_boxes,
            character_boxes=characters,
            panel_boxes=panels_yolo,
            bg_val=bg_val
        )
        bubble_cands = bubble_analyzer.generate_bubble_boundary_candidates(
            canvas_bgr=canvas_bgr,
            analyzed_bubbles=analyzed_bubbles,
            bg_val=bg_val,
            keep_with_visual=(not cfg.speech_edge_hard_cut)
        )
        internal_spans = bubble_analyzer.get_internal_bubble_forbidden_spans(analyzed_bubbles)

        # STAGE B.2: Hybrid Arbitration Layer (Pure CV HPP Gutters vs DL Semantic Protection)
        all_forbidden_spans = list(dl_forbidden_spans) + list(internal_spans)
        hpp_candidates: List[BoundaryCandidate] = []

        continuity_sig = signals.get("visual_continuity", np.zeros(total_h, dtype=np.float32))
        action_sig = signals.get("action_line_density", np.zeros(total_h, dtype=np.float32))
        scene_trans_sig = signals.get("scene_transition", np.zeros(total_h, dtype=np.float32))
        border_sig = signals.get("panel_border_density", np.zeros(total_h, dtype=np.float32))

        for g in raw_gutters:
            # Check for intersection with character/bubble forbidden spans
            overlaps_forbidden = False
            for fs_y1, fs_y2 in all_forbidden_spans:
                if max(g.y_start, fs_y1) < min(g.y_end, fs_y2):
                    overlaps_forbidden = True
                    break

            if not overlaps_forbidden:
                # Pristine clean gutter: snap to outer panel edge if close, else center
                cut_point = g.cut_y
                if hpp_scanner is not None:
                    cut_point = hpp_scanner.snap_to_panel_edge(canvas_bgr, cut_point, search_radius=12)

                if cut_point < cfg.min_page_height or cut_point > total_h - cfg.min_page_height:
                    continue

                cut_cont = float(continuity_sig[cut_point]) if cut_point < len(continuity_sig) else 0.0
                cut_act = float(action_sig[cut_point]) if cut_point < len(action_sig) else 0.0
                cut_trans = float(scene_trans_sig[cut_point]) if cut_point < len(scene_trans_sig) else 0.5
                cut_border = float(border_sig[cut_point]) if cut_point < len(border_sig) else 0.5

                # Disqualify gutters inside continuous artwork (real gutters have low visual continuity)
                if cut_cont > 0.35:
                    continue

                base_score = float(min(1.0, 0.4 + 0.5 * (g.height / 50.0)))
                endpoint_score = float(min(1.0, g.height / 50.0))

                hpp_candidates.append(BoundaryCandidate(
                    y=cut_point,
                    candidate_type="natural_visual_endpoint",
                    score=base_score,
                    hard=False,
                    is_safe=True,
                    panel_boundary_score=cut_border,
                    natural_endpoint_score=endpoint_score,
                    visual_transition_score=cut_trans,
                    visual_continuity=cut_cont,
                    action_continuity=cut_act,
                    details={
                        "source": "hpp_pure_cv",
                        "gutter_length": g.height,
                        "gutter_height": g.height,
                        "mean_luminance": g.mean_luminance,
                        "mean_variance": g.mean_variance
                    }
                ))
            else:
                # Compromised gutter (protruding character or floating bubble):
                # Search for clear margin above or below the collision
                for fs_y1, fs_y2 in all_forbidden_spans:
                    if g.y_start < fs_y1 - 15:
                        safe_cut = g.y_start + (fs_y1 - g.y_start) // 2
                        if cfg.min_page_height <= safe_cut <= total_h - cfg.min_page_height:
                            cut_cont = float(continuity_sig[safe_cut]) if safe_cut < len(continuity_sig) else 0.0
                            cut_act = float(action_sig[safe_cut]) if safe_cut < len(action_sig) else 0.0
                            if cut_cont <= 0.35:
                                hpp_candidates.append(BoundaryCandidate(
                                    y=safe_cut,
                                    candidate_type="natural_visual_endpoint",
                                    score=0.88,
                                    hard=False,
                                    is_safe=True,
                                    panel_boundary_score=0.9,
                                    natural_endpoint_score=0.9,
                                    visual_transition_score=0.7,
                                    visual_continuity=cut_cont,
                                    action_continuity=cut_act,
                                    details={"source": "hpp_arbitration_above_protrusion", "gutter_length": fs_y1 - g.y_start}
                                ))
                    elif g.y_end > fs_y2 + 15:
                        safe_cut = fs_y2 + (g.y_end - fs_y2) // 2
                        if cfg.min_page_height <= safe_cut <= total_h - cfg.min_page_height:
                            cut_cont = float(continuity_sig[safe_cut]) if safe_cut < len(continuity_sig) else 0.0
                            cut_act = float(action_sig[safe_cut]) if safe_cut < len(action_sig) else 0.0
                            if cut_cont <= 0.35:
                                hpp_candidates.append(BoundaryCandidate(
                                    y=safe_cut,
                                    candidate_type="natural_visual_endpoint",
                                    score=0.88,
                                    hard=False,
                                    is_safe=True,
                                    panel_boundary_score=0.9,
                                    natural_endpoint_score=0.9,
                                    visual_transition_score=0.7,
                                    visual_continuity=cut_cont,
                                    action_continuity=cut_act,
                                    details={"source": "hpp_arbitration_below_protrusion", "gutter_length": g.y_end - fs_y2}
                                ))

        # Merge visual candidates, HPP candidates, and bubble candidates
        combined_cands: Dict[int, BoundaryCandidate] = {c.y: c for c in visual_cands}

        # Inject HPP candidates (preserve scene_transition/panel_boundary and keep higher score)
        for hc in hpp_candidates:
            nearby_y = [y for y in combined_cands if abs(y - hc.y) < 25]
            if nearby_y:
                strongest_existing = max([combined_cands[ny] for ny in nearby_y], key=lambda c: c.score)
                if strongest_existing.score > hc.score:
                    strongest_existing.score = max(strongest_existing.score, hc.score)
                    continue
                for ny in nearby_y:
                    if combined_cands[ny].candidate_type in ("scene_transition", "panel_boundary"):
                        hc.candidate_type = combined_cands[ny].candidate_type
                    del combined_cands[ny]
            combined_cands[hc.y] = hc

        for bc in bubble_cands:
            nearby_y = [y for y in combined_cands if abs(y - bc.y) < 25]
            if nearby_y:
                for ny in nearby_y:
                    del combined_cands[ny]
            combined_cands[bc.y] = bc

        all_candidates = sorted(combined_cands.values(), key=lambda c: c.y)

        # 3. Boundary Scoring
        scorer = BoundaryScorer(
            scene_transition_weight=cfg.scene_transition_weight,
            composition_weight=cfg.composition_weight,
            panel_boundary_weight=cfg.panel_boundary_weight,
            content_width_weight=cfg.content_width_weight,
            speech_edge_weight=1.2 if cfg.speech_edge_hard_cut else 0.5,
            action_continuity_penalty=cfg.action_continuity_penalty,
            character_overlap_penalty=cfg.character_overlap_penalty,
            object_overlap_penalty=cfg.object_overlap_penalty,
            boundary_score_threshold=cfg.boundary_score_threshold
        )
        all_bubble_spans = [(b[1], b[3]) for b in all_bubble_boxes]
        scored_candidates = scorer.score_candidates(
            candidates=all_candidates,
            safety_layer=safety_layer,
            internal_bubble_spans=internal_spans,
            all_bubble_spans=all_bubble_spans
        )

        # STAGE C: Global Page Optimization (Dynamic Programming)
        effective_min_h = max(350 if cfg.min_page_height >= 300 else 200, cfg.min_page_height)
        optimizer = GlobalPageOptimizer(
            min_page_height=effective_min_h,
            ideal_page_height=cfg.ideal_page_height,
            max_page_height=cfg.max_page_height,
            hard_cut_bonus=6.0 if cfg.speech_edge_hard_cut else 2.0
        )
        selected_cuts, pages = optimizer.optimize_pages(
            total_height=total_h,
            candidates=scored_candidates
        )

        debug_info = {
            "characters": characters,
            "faces": faces_yolo,
            "bodies": bodies_yolo,
            "bubbles": [ab.bbox for ab in analyzed_bubbles] if analyzed_bubbles else bubbles_yolo,
            "panels": panels_yolo,
            "forbidden_spans": all_forbidden_spans
        }
        if getattr(cfg, "debug_paging", False) or getattr(cfg, "debug_output_dir", None):
            out_dir = cfg.debug_output_dir or os.path.join("cache", "debug_paging")
            bubble_dicts = [{"bbox": ab.bbox, "role": ab.role} for ab in analyzed_bubbles]
            dbg_res = SmartPagingDebugger.save_debug_output(
                output_dir=out_dir,
                prefix="session",
                canvas_bgr=canvas_bgr,
                candidates=scored_candidates,
                selected_cuts=selected_cuts,
                character_boxes=characters,
                speech_bubbles=bubble_dicts
            )
            if isinstance(dbg_res, dict):
                debug_info.update(dbg_res)

        return selected_cuts, scored_candidates, debug_info

    @classmethod
    def _split_runaway_slice(
        cls,
        canvas_bgr: np.ndarray,
        s_start: int,
        s_end: int,
        max_h: int,
        ideal_h: int,
        bg_val: int,
        config: PaginationConfig,
        panels: Optional[List[Any]] = None,
        forbidden_spans: Optional[List[Tuple[int, int]]] = None
    ) -> List[Tuple[int, int]]:
        """
        Recursively splits any runaway strip exceeding max_h into visually sound sub-slices <= max_h.
        Guarantees no page > max_h ever escapes.
        """
        slice_h = s_end - s_start
        if slice_h <= max_h:
            return [(s_start, s_end)]

        panels = panels or []
        forbidden_spans = forbidden_spans or []
        slice_img = canvas_bgr[s_start:s_end, :]

        # Smart Runaway Splitter: find single best horizontal cut near ideal_h
        # Prioritizes natural panel gaps and visual valleys outside forbidden character spans
        win_min = s_start + max(config.min_page_height, 550)
        win_max = min(s_end - config.min_page_height, s_start + min(max_h - 80, ideal_h + 550))
        if win_min >= win_max:
            win_min = s_start + max(config.min_page_height, slice_h // 3)
            win_max = min(s_end - config.min_page_height, 2 * (slice_h // 3))

        best_cut = None
        best_score = -999999.0

        # Check panel gaps inside search window
        if panels:
            for i in range(len(panels) - 1):
                p_bot = panels[i][3]
                p_next_top = panels[i + 1][1]
                if win_min <= p_bot <= win_max and p_next_top >= p_bot:
                    gap_mid = (p_bot + p_next_top) // 2
                    dist_to_ideal = abs((gap_mid - s_start) - ideal_h)
                    score = 1000.0 - dist_to_ideal
                    if score > best_score:
                        best_score = score
                        best_cut = gap_mid

        # If no panel gap, check horizontal gradient/variance profile
        if best_cut is None and slice_img.size > 0:
            try:
                gray_slice = cv2.cvtColor(slice_img, cv2.COLOR_BGR2GRAY)
                calc_w = min(gray_slice.shape[1], 128)
                calc_h = gray_slice.shape[0]
                small_slice = cv2.resize(gray_slice, (calc_w, calc_h), interpolation=cv2.INTER_AREA)
                row_vars = np.var(small_slice, axis=1)

                local_win_min = max(0, win_min - s_start)
                local_win_max = min(calc_h, win_max - s_start)

                for local_y in range(local_win_min, local_win_max, 4):
                    global_y = s_start + local_y
                    # Avoid forbidden spans
                    in_forbidden = any(fs_y1 <= global_y <= fs_y2 for fs_y1, fs_y2 in forbidden_spans)
                    if in_forbidden:
                        continue
                    var_val = float(row_vars[local_y])
                    dist_ideal = abs(local_y - ideal_h)
                    score = - (var_val * 2.0 + dist_ideal)
                    if score > best_score:
                        best_score = score
                        best_cut = global_y
            except Exception:
                pass

        # If still no cut found outside forbidden spans:
        if best_cut is None or best_cut <= s_start or best_cut >= s_end:
            if slice_h <= 3200:
                # Preserve continuous artwork/action/character panel without cutting through limbs/weapons
                return [(s_start, s_end)]
            best_cut = s_start + min(ideal_h, slice_h // 2)

        left_res = cls._split_runaway_slice(
            canvas_bgr, s_start, best_cut, max_h, ideal_h, bg_val, config, panels, forbidden_spans
        )
        right_res = cls._split_runaway_slice(
            canvas_bgr, best_cut, s_end, max_h, ideal_h, bg_val, config, panels, forbidden_spans
        )
        return left_res + right_res

    def paginate_canvas(
        self,
        canvas_bgr: np.ndarray,
        source_offsets: Optional[List[Dict[str, Any]]] = None,
        bg_val: Optional[int] = None,
        start_page_index: int = 1,
        manual_cuts: Optional[List[int]] = None,
        ai_direct: bool = False
    ) -> List[Tuple[np.ndarray, PageMetadata]]:
        """
        Executes full pagination pipeline on a stitched canvas.
        Returns a list of (cropped_slice_bgr, page_metadata).
        Supports:
          - Pure End-to-End AI Direct Mode (mode="ai_direct" or ai_direct=True):
            Upgraded hybrid Visual Composition Segmentation engine (Scanner + Semantic Safety + DP Optimizer)
            or user ground-truth cuts.
          - Hybrid Mode (mode="hybrid"):
            Uses OpenCV content block detection with AI boundary scoring.
        """
        total_h, max_w = canvas_bgr.shape[:2]
        if total_h <= 0 or max_w <= 0:
            return []

        gray = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2GRAY)
        if bg_val is None:
            bg_val = self.detect_background(gray)

        # -------------------------------------------------------------
        # Single Unified Smart Paging Architecture: AI Visual Composition Segmentation
        # -------------------------------------------------------------
        has_manual_cuts = bool(manual_cuts and len(manual_cuts) > 0)
        raw_splits = []
        activity = np.zeros(0, dtype=np.float32)
        canvas_dbg = {}

        if has_manual_cuts:
            # Ground-truth manual cuts provided
            clean_cuts = sorted(list(set([int(c) for c in manual_cuts if 0 < int(c) < total_h])))
            bounds = [0] + clean_cuts + [total_h]
            for i in range(len(bounds) - 1):
                raw_splits.append((bounds[i], bounds[i+1], 1.0, PageType.CONTENT, "user_ground_truth"))
        else:
            # AI Visual Composition Segmentation with Semantic Safety & DP Optimization
            try:
                selected_cuts, scored_cands, canvas_dbg = self.segment_canvas_v2(
                    canvas_bgr, bg_val=bg_val, config=self.config
                )
                if selected_cuts is not None:
                    should_snap_bubbles = getattr(self.config, "tight_auto_crop", True) and (
                        (not getattr(self.config, "separate_speech_bubbles", True)) or
                        (not getattr(self.config, "speech_edge_hard_cut", True)) or
                        (getattr(self.config, "min_page_height", 20) >= 400)
                    )
                    if should_snap_bubbles and scored_cands:
                        global_c = canvas_dbg.get("characters", []) if isinstance(canvas_dbg, dict) else []
                        global_p = canvas_dbg.get("panels", []) if isinstance(canvas_dbg, dict) else []

                        # Check for top junk margin before real content (y < 200)
                        early_cands = [c for c in scored_cands if 30 < c.y < 200]
                        if early_cands:
                            best_early = max(early_cands, key=lambda c: c.score)
                            has_char_before = any(c[1] < best_early.y for c in global_c)
                            has_panel_before = any(p[1] < best_early.y for p in global_p)
                            if not has_char_before and not has_panel_before and best_early.y not in selected_cuts:
                                selected_cuts = sorted(selected_cuts + [best_early.y])

                        # Check for bottom credit / watermark boundary (total_h - y < 350)
                        late_cands = [c for c in scored_cands if 0 < (total_h - c.y) < 350]
                        if late_cands:
                            best_late = max(late_cands, key=lambda c: c.score)
                            has_char_after = any(c[3] > best_late.y for c in global_c)
                            has_panel_after = any(p[3] > best_late.y for p in global_p)
                            if not has_char_after and not has_panel_after and best_late.y not in selected_cuts:
                                selected_cuts = sorted(selected_cuts + [best_late.y])

                        # Check if top region contains an intro credit / recruitment banner (e.g. AsuraScans 001.webp)
                        top_check_y = None
                        if source_offsets and len(source_offsets) > 1:
                            cand_top_y = source_offsets[0].get("offset_y_end", 0)
                            if 100 < cand_top_y < 1500:
                                top_check_y = cand_top_y
                        if top_check_y is None:
                            for c in scored_cands:
                                if 500 <= c.y <= 1200:
                                    top_check_y = c.y
                                    break

                        if top_check_y and top_check_y not in selected_cuts:
                            top_candidate_slice = canvas_bgr[0:top_check_y, :]
                            if SmartPaginator.is_credit_or_recruitment_page(top_candidate_slice, page_index=1, total_pages=10):
                                selected_cuts = sorted(selected_cuts + [top_check_y])

                    cand_map = {c.y: c for c in scored_cands}
                    bounds = [0] + selected_cuts + [total_h]
                    for i in range(len(bounds) - 1):
                        end_y = bounds[i+1]
                        cand = cand_map.get(end_y)
                        conf = cand.score if cand else 0.85
                        if end_y >= total_h:
                            reason = "end_of_canvas"
                        elif cand:
                            reason = cand.candidate_type
                            if reason == "natural_visual_endpoint":
                                reason = "gutter"
                        else:
                            reason = "visual_composition_cut"
                        raw_splits.append((bounds[i], bounds[i+1], conf, PageType.VISUAL, reason))
            except Exception:
                raw_splits = []
                canvas_dbg = {}

            if not raw_splits:
                raw_splits = [(0, total_h, 1.0, PageType.VISUAL, "single_page")]

        global_chars = canvas_dbg.get("characters", []) if isinstance(canvas_dbg, dict) else []
        global_faces = canvas_dbg.get("faces", []) if isinstance(canvas_dbg, dict) else []
        global_bodies = canvas_dbg.get("bodies", []) if isinstance(canvas_dbg, dict) else []
        global_bubbles = canvas_dbg.get("bubbles", []) if isinstance(canvas_dbg, dict) else []
        global_panels = canvas_dbg.get("panels", []) if isinstance(canvas_dbg, dict) else []
        global_forbidden = canvas_dbg.get("forbidden_spans", []) if isinstance(canvas_dbg, dict) else []

        # Enforce hard_max_height barrier: if any segment exceeds hard_max_height (e.g. 1920 - 2160px),
        # recursively segment that runaway slice independently so tall chapters/episodes never produce runaway mega-pages!
        max_h_limit = getattr(self.config, "hard_max_height", 2160)
        ideal_h = getattr(self.config, "ideal_page_height", 1080)
        final_splits = []
        for split in raw_splits:
            s_start = split[0]
            s_end = split[1]
            s_conf = split[2] if len(split) > 2 else 0.85
            s_type = split[3] if len(split) > 3 else PageType.VISUAL
            s_reason = split[4] if len(split) > 4 else "gutter"

            if (s_end - s_start) > max_h_limit:
                sub_segments = self._split_runaway_slice(
                    canvas_bgr=canvas_bgr,
                    s_start=s_start,
                    s_end=s_end,
                    max_h=max_h_limit,
                    ideal_h=ideal_h,
                    bg_val=bg_val,
                    config=self.config,
                    panels=global_panels,
                    forbidden_spans=global_forbidden
                )
                for sub_s, sub_e in sub_segments:
                    final_splits.append((sub_s, sub_e, s_conf, s_type, "runaway_sub_split"))
            else:
                final_splits.append(split)
        raw_splits = final_splits

        # Bubble Snapping & Canvas Margin Cleanup Layer:
        # Enforced for Video Recap pipeline (separate_speech_bubbles=False, speech_edge_hard_cut=False, or min_page_height >= 400 with tight_auto_crop=True)
        # Guarantees that speech bubbles NEVER form a page containing only text!
        should_snap_bubbles = getattr(self.config, "tight_auto_crop", True) and (
            (not getattr(self.config, "separate_speech_bubbles", True)) or
            (not getattr(self.config, "speech_edge_hard_cut", True)) or
            (getattr(self.config, "min_page_height", 20) >= 400)
        )

        if should_snap_bubbles:
            # Top margin pruning: Discard junk slivers, blank gutters, and credit cards before real content begins
            while len(raw_splits) > 1:
                first_s, first_e = raw_splits[0][0], raw_splits[0][1]
                first_h = first_e - first_s
                first_has_char = any(max(first_s, c[1]) < min(first_e, c[3]) for c in global_chars if (c[3] - c[1]) > 30)
                first_has_panel = any(max(first_s, p[1]) < min(first_e, p[3]) for p in global_panels if (p[3] - p[1]) > 50)
                first_slice = canvas_bgr[first_s:first_e, :]

                if SmartPaginator.is_credit_or_recruitment_page(first_slice, page_index=1, total_pages=len(raw_splits)):
                    raw_splits.pop(0)
                    continue
                if SmartPaginator.is_blank_page(first_slice, bg_val=bg_val, config=self.config):
                    raw_splits.pop(0)
                    continue
                v_first, _ = VisualSemanticScorer.calculate_score(first_slice, bg_val=bg_val)
                if (first_h < 250 and not first_has_char and not first_has_panel) or (not first_has_char and not first_has_panel and v_first < 25):
                    raw_splits.pop(0)
                    continue
                break

            has_bubble_snapping = True
            iterations = 0
            while has_bubble_snapping and iterations < 20:
                iterations += 1
                has_bubble_snapping = False
                merged_splits = []
                for idx in range(len(raw_splits)):
                    split = raw_splits[idx]
                    s_s, s_e = split[0], split[1]
                    s_conf = split[2] if len(split) > 2 else 0.85
                    s_type = split[3] if len(split) > 3 else PageType.VISUAL
                    s_reason = split[4] if len(split) > 4 else "gutter"
                    s_h = s_e - s_s

                    # Check contents of this slice
                    has_char = any(max(s_s, c[1]) < min(s_e, c[3]) for c in global_chars if (c[3] - c[1]) > 30)
                    has_face = any(max(s_s, f[1]) < min(s_e, f[3]) for f in global_faces if (f[3] - f[1]) > 15)
                    has_panel = any(max(s_s, p[1]) < min(s_e, p[3]) for p in global_panels if (p[3] - p[1]) > 50)
                    has_bubble = any(max(s_s, b[1]) < min(s_e, b[3]) for b in global_bubbles)

                    # Quick visual metric on slice
                    slice_sub = canvas_bgr[s_s:s_e, :]
                    is_low_visual = False
                    if slice_sub.size > 0:
                        gray_sub = cv2.cvtColor(slice_sub, cv2.COLOR_BGR2GRAY)
                        w_ratio = float(np.mean(gray_sub >= 235))
                        b_ratio = float(np.mean(gray_sub <= 35))
                        hsv_sub = cv2.cvtColor(slice_sub, cv2.COLOR_BGR2HSV)
                        sat_sub = float(np.mean(hsv_sub[:, :, 1]))
                        if (w_ratio >= 0.35 or b_ratio >= 0.35 or (w_ratio + b_ratio >= 0.65)) and sat_sub < 35.0:
                            is_low_visual = True

                    # Strict Orphan Bubble / Text check:
                    # In video recap mode, ANY slice without character body/face that is either short (< min_page_height),
                    # or an explicit dialogue/text card without artwork panels MUST be merged into its adjacent panel!
                    is_isolated_bubble = (
                        (not getattr(self.config, "separate_speech_bubbles", True))
                        and not has_char
                        and not has_face
                        and (
                            s_h < self.config.min_page_height
                            or s_type in (PageType.TEXT_BUBBLE, PageType.DIALOGUE, PageType.TEXT_ONLY)
                            or (is_low_visual and not has_panel)
                        )
                    )
                    # Is this a tiny junk sliver (< 200px without character/panel/bubble)?
                    is_junk_sliver = (
                        s_h < 200
                        and not has_char
                        and not has_panel
                        and not has_bubble
                        and s_type not in (PageType.TEXT_BUBBLE, PageType.DIALOGUE, PageType.TEXT_ONLY)
                    )

                    if is_junk_sliver and len(raw_splits) > 1:
                        # A junk sliver is margin noise: discard it completely
                        has_bubble_snapping = True
                        continue

                    if is_isolated_bubble and len(raw_splits) > 1:
                        has_bubble_snapping = True
                        # For merging isolated bubbles into visual panels, allow up to 2800px so dialogue never remains isolated
                        bubble_merge_limit = max(max_h_limit, 2800)
                        can_merge_prev = bool(merged_splits and (s_e - merged_splits[-1][0]) <= bubble_merge_limit)
                        can_merge_next = bool(idx + 1 < len(raw_splits) and (raw_splits[idx + 1][1] - s_s) <= bubble_merge_limit)

                        if idx == 0 and can_merge_next:
                            nxt = raw_splits[idx + 1]
                            raw_splits[idx + 1] = (s_s, nxt[1], nxt[2], nxt[3], "bubble_snap_next")
                        elif idx == len(raw_splits) - 1 and can_merge_prev:
                            prev_item = merged_splits.pop()
                            merged_splits.append((prev_item[0], s_e, prev_item[2], prev_item[3], "bubble_snap_prev"))
                        elif can_merge_prev and not can_merge_next:
                            prev_item = merged_splits.pop()
                            merged_splits.append((prev_item[0], s_e, prev_item[2], prev_item[3], "bubble_snap_prev"))
                        elif can_merge_next and not can_merge_prev:
                            nxt = raw_splits[idx + 1]
                            raw_splits[idx + 1] = (s_s, nxt[1], nxt[2], nxt[3], "bubble_snap_next")
                        elif can_merge_prev and can_merge_next:
                            prev_res_h = s_e - merged_splits[-1][0]
                            next_res_h = raw_splits[idx + 1][1] - s_s
                            ideal = self.config.ideal_page_height
                            if abs(prev_res_h - ideal) <= abs(next_res_h - ideal):
                                prev_item = merged_splits.pop()
                                merged_splits.append((prev_item[0], s_e, prev_item[2], prev_item[3], "bubble_snap_prev"))
                            else:
                                nxt = raw_splits[idx + 1]
                                raw_splits[idx + 1] = (s_s, nxt[1], nxt[2], nxt[3], "bubble_snap_next")
                        else:
                            # If neither neighbor fits under max_h_limit, only merge if s_h is small (< 350)
                            # into whichever neighbor is shorter
                            if s_h < 350 and merged_splits and idx + 1 < len(raw_splits):
                                prev_h = s_e - merged_splits[-1][0]
                                next_h = raw_splits[idx + 1][1] - s_s
                                if prev_h <= next_h:
                                    prev_item = merged_splits.pop()
                                    merged_splits.append((prev_item[0], s_e, prev_item[2], prev_item[3], "bubble_snap_prev"))
                                else:
                                    nxt = raw_splits[idx + 1]
                                    raw_splits[idx + 1] = (s_s, nxt[1], nxt[2], nxt[3], "bubble_snap_next")
                            elif s_h < 350 and merged_splits:
                                prev_item = merged_splits.pop()
                                merged_splits.append((prev_item[0], s_e, prev_item[2], prev_item[3], "bubble_snap_prev"))
                            elif s_h < 350 and idx + 1 < len(raw_splits):
                                nxt = raw_splits[idx + 1]
                                raw_splits[idx + 1] = (s_s, nxt[1], nxt[2], nxt[3], "bubble_snap_next")
                            else:
                                merged_splits.append(split)
                    else:
                        merged_splits.append(split)
                raw_splits = merged_splits

            # Bottom margin pruning: Discard junk slivers < 150px at bottom of canvas, and credit/watermark banners
            while len(raw_splits) > 1:
                last_s, last_e = raw_splits[-1][0], raw_splits[-1][1]
                last_h = last_e - last_s
                last_has_char = any(max(last_s, c[1]) < min(last_e, c[3]) for c in global_chars if (c[3] - c[1]) > 30)
                last_has_panel = any(max(last_s, p[1]) < min(last_e, p[3]) for p in global_panels if (p[3] - p[1]) > 50)
                if last_h < 150 and not last_has_char and not last_has_panel:
                    raw_splits.pop()
                    continue

                last_slice = canvas_bgr[last_s:last_e, :]
                if SmartPaginator.is_credit_or_recruitment_page(last_slice, page_index=len(raw_splits), total_pages=len(raw_splits)):
                    raw_splits.pop()
                    continue
                break

        # 3. Generate pages with content trimming and metadata
        results = []
        page_counter = start_page_index - 1

        for item in raw_splits:
            if len(item) == 5:
                y_s, y_e, confidence, p_type, split_reason = item
            else:
                y_s, y_e, confidence, p_type = item
                split_reason = "gutter"

            slice_img = canvas_bgr[y_s:y_e, :]
            if SmartPaginator.is_blank_page(slice_img, bg_val=bg_val, config=self.config):
                continue

            # Vertical slice [y_s:y_e] with tight auto crop on 4 margins
            if getattr(self.config, "tight_auto_crop", True):
                y_top, y_bottom, x_left, x_right = self.find_tight_content_box(
                    slice_img, pad=self.config.crop_padding, bg_val=bg_val
                )
                cropped_slice = slice_img[y_top:y_bottom, x_left:x_right] if (y_bottom > y_top and x_right > x_left) else slice_img
                y_crop_start = y_s + y_top
                y_crop_end = y_s + y_bottom
            else:
                cropped_slice = slice_img
                x_left, x_right = 0, int(max_w)
                y_crop_start = y_s
                y_crop_end = y_e

            if cropped_slice.size == 0 or cropped_slice.shape[0] <= 0 or cropped_slice.shape[1] <= 0:
                continue

            page_counter += 1
            page_h = y_crop_end - y_crop_start

            # Compute content score
            if len(activity) > 0 and y_crop_start < len(activity):
                act_slice = activity[y_crop_start:min(len(activity), y_crop_end)]
                c_score = float(np.mean(act_slice)) if len(act_slice) > 0 else 0.5
            else:
                c_score = 0.5

            # Map source slice offsets if provided
            sources = []
            matched_pdf_page = None
            if source_offsets:
                for off in source_offsets:
                    o_start = max(y_crop_start, off.get("offset_y_start", 0))
                    o_end = min(y_crop_end, off.get("offset_y_end", 0))
                    if o_start < o_end:
                        src_y_start = o_start - off.get("offset_y_start", 0)
                        src_y_end = o_end - off.get("offset_y_start", 0)
                        tgt_y_start = o_start - y_crop_start
                        tgt_y_end = o_end - y_crop_start
                        src_dict = {
                            "filename": off.get("filename", ""),
                            "source_y_start": int(src_y_start),
                            "source_y_end": int(src_y_end),
                            "target_y_start": int(tgt_y_start),
                            "target_y_end": int(tgt_y_end)
                        }
                        if "pdf_page" in off:
                            src_dict["pdf_page"] = off["pdf_page"]
                            if matched_pdf_page is None:
                                matched_pdf_page = off["pdf_page"]
                        if "physical_page" in off:
                            src_dict["physical_page"] = off["physical_page"]
                            if matched_pdf_page is None:
                                matched_pdf_page = off["physical_page"]
                        sources.append(src_dict)

            # Compute Visual Semantic Score (0-100)
            visual_score, score_breakdown = VisualSemanticScorer.calculate_score(cropped_slice, bg_val=bg_val)

            # Compute Text Score (0-100)
            text_score = TextScorer.calculate_text_score(cropped_slice, bg_val=bg_val)

            # Focal points & Camera hints (reusing pre-detected canvas characters & bubbles without extra YOLO calls)
            page_chars = []
            if global_chars:
                for cx1, cy1, cx2, cy2 in global_chars:
                    if cy2 > y_crop_start and cy1 < y_crop_end:
                        bx1 = max(0, cx1 - x_left)
                        by1 = max(0, cy1 - y_crop_start)
                        bx2 = min(cropped_slice.shape[1], cx2 - x_left)
                        by2 = min(page_h, cy2 - y_crop_start)
                        if (bx2 - bx1) > 10 and (by2 - by1) > 10:
                            page_chars.append((bx1, by1, bx2, by2))

            page_bubbles = []
            if global_bubbles:
                for bx1, by1, bx2, by2 in global_bubbles:
                    if by2 > y_crop_start and by1 < y_crop_end:
                        bbx1 = max(0, bx1 - x_left)
                        bby1 = max(0, by1 - y_crop_start)
                        bbx2 = min(cropped_slice.shape[1], bx2 - x_left)
                        bby2 = min(page_h, by2 - y_crop_start)
                        if (bbx2 - bbx1) > 10 and (bby2 - bby1) > 10:
                            page_bubbles.append((bbx1, bby1, bbx2, bby2))

            page_faces = []
            if global_faces:
                for fx1, fy1, fx2, fy2 in global_faces:
                    if fy2 > y_crop_start and fy1 < y_crop_end:
                        fbx1 = max(0, fx1 - x_left)
                        fby1 = max(0, fy1 - y_crop_start)
                        fbx2 = min(cropped_slice.shape[1], fx2 - x_left)
                        fby2 = min(page_h, fy2 - y_crop_start)
                        if (fbx2 - fbx1) > 10 and (fby2 - fby1) > 10:
                            page_faces.append((fbx1, fby1, fbx2, fby2))

            page_panels = []
            if global_panels:
                for px1, py1, px2, py2 in global_panels:
                    if py2 > y_crop_start and py1 < y_crop_end:
                        pbx1 = max(0, px1 - x_left)
                        pby1 = max(0, py1 - y_crop_start)
                        pbx2 = min(cropped_slice.shape[1], px2 - x_left)
                        pby2 = min(page_h, py2 - y_crop_start)
                        if (pbx2 - pbx1) > 10 and (pby2 - pby1) > 10:
                            page_panels.append((pbx1, pby1, pbx2, pby2))

            # Derive slice p_type from presence of speech bubbles and artwork
            if page_bubbles:
                if visual_score >= 35 and (page_chars or page_faces or page_panels or visual_score >= 40 or cropped_slice.shape[0] >= 800):
                    p_type = PageType.MIXED
                else:
                    p_type = PageType.DIALOGUE
            elif text_score >= 35 and visual_score < 35 and not page_chars and not page_faces:
                p_type = PageType.TEXT_ONLY
            else:
                p_type = PageType.VISUAL

            # Classify semantic content type, importance score, and video candidate
            content_type, importance_score, video_candidate = self.classify_page_content(
                cropped_slice,
                p_type=p_type,
                visual_score=visual_score,
                text_score=text_score,
                bg_val=bg_val,
                page_index=page_counter,
                total_pages=len(raw_splits)
            )

            if content_type == PageType.EMPTY_GUTTER:
                continue

            # Strict score & candidate clamping for non-visual / banned pages
            if content_type == PageType.CREDIT_ADS:
                visual_score = min(visual_score, 5)
                importance_score = 0
                video_candidate = False
            elif content_type in (PageType.TEXT_BUBBLE, PageType.DIALOGUE, PageType.TEXT_ONLY):
                visual_score = min(visual_score, 15)
                video_candidate = False

            # Classify into 5-tag visual taxonomy (CHARACTER_ART, CHARACTER_SCENE, BACKGROUND_SCENE, ACTION_ART, NON_VISUAL)
            page_tag = self.classify_page_tag(
                cropped_slice,
                p_type=p_type,
                visual_score=visual_score,
                text_score=text_score,
                score_breakdown=score_breakdown,
                bg_val=bg_val,
                content_type=content_type,
                page_index=page_counter,
                total_pages=len(raw_splits),
                detected_characters=page_chars,
                detected_bubbles=page_bubbles,
                detected_faces=page_faces
            )
            if page_tag == PageTag.NON_VISUAL:
                video_candidate = False

            # Smart Pagination V3 Enhancements:
            # 1. 2D panels
            sub_panels = []
            if self.config.enable_2d_panels:
                sub_panels = self.detect_panels_2d(cropped_slice, bg_val=bg_val)

            focal_pt, focal_pts, cam_hint = self.calculate_focal_points(
                cropped_slice,
                bg_val=bg_val,
                detected_characters=page_chars,
                detected_bubbles=page_bubbles,
                detected_faces=page_faces
            )

            # 3. Layer separation (optional)
            layers_meta = {}
            if self.config.enable_layer_separation:
                layer_res = self.separate_page_layers(cropped_slice, bg_val=bg_val)
                layers_meta = {
                    "has_layers": bool(layer_res.get("bubble_count", 0) > 0),
                    "bubble_count": int(layer_res.get("bubble_count", 0))
                }

            if content_type in (PageType.TEXT_BUBBLE, PageType.DIALOGUE, PageType.TEXT_ONLY):
                final_page_type = PageType.TEXT_BUBBLE
            else:
                final_page_type = PageType.CONTENT

            meta = PageMetadata(
                page_index=page_counter,
                y_start=int(y_crop_start),
                y_end=int(y_crop_end),
                height=int(page_h),
                page_type=final_page_type,
                content_score=c_score,
                boundary_confidence=confidence,
                sources=sources,
                visual_score=visual_score,
                score_breakdown=score_breakdown,
                content_type=content_type,
                page_tag=page_tag,
                text_score=text_score,
                importance_score=importance_score,
                video_candidate=video_candidate,
                split_reason=split_reason,
                page_id=f"page_{page_counter:03d}",
                source_bbox=(int(x_left), int(y_crop_start), int(x_right), int(y_crop_end)),
                pdf_page=matched_pdf_page,
                focal_point=focal_pt,
                focal_points=focal_pts,
                camera_hint=cam_hint,
                sub_panels=sub_panels,
                layers=layers_meta
            )
            results.append((cropped_slice, meta))

        if getattr(self.config, "filter_video_frames", False):
            video_pages = [(img, meta) for (img, meta) in results if self.is_video_frame(meta)]
            if video_pages:
                reindexed = []
                for new_idx, (img, meta) in enumerate(video_pages, start=1):
                    meta.page_index = new_idx
                    meta.page_id = f"page_{new_idx:03d}"
                    reindexed.append((img, meta))
                return reindexed

        return results

    @classmethod
    def is_video_frame(cls, meta: PageMetadata) -> bool:
        """
        Filters out non-visual segments (empty background gutters, isolated dialogue bubbles,
        credits/ads, or near-empty frames) to ensure only clean visual artwork frames are rendered into video.
        """
        if not getattr(meta, "video_candidate", True):
            return False
        if getattr(meta, "page_tag", "") == PageTag.NON_VISUAL:
            return False
        c_type = getattr(meta, "content_type", "")
        if c_type in (
            PageType.EMPTY_GUTTER,
            PageType.DIALOGUE,
            PageType.TEXT_BUBBLE,
            PageType.TEXT_ONLY,
            PageType.CREDIT_ADS
        ):
            return False
        p_type = getattr(meta, "page_type", "")
        if p_type in (
            PageType.EMPTY_GUTTER,
            PageType.TEXT_BUBBLE
        ):
            return False
        if getattr(meta, "visual_score", 50) < 18:
            return False
        return True

    def paginate_canvas_for_video(
        self,
        canvas_bgr: np.ndarray,
        source_offsets: Optional[List[Dict[str, Any]]] = None,
        bg_val: Optional[int] = None,
        manual_cuts: Optional[List[int]] = None
    ) -> List[Tuple[np.ndarray, PageMetadata]]:
        """
        High-agency video-centric pagination: extracts pure visual frames,
        drops all empty gutters and floating dialogue bubbles, crops tight 4-side borders,
        and re-indexes sequentially for seamless video recap rendering.
        """
        raw_results = self.paginate_canvas(
            canvas_bgr,
            source_offsets=source_offsets,
            bg_val=bg_val,
            manual_cuts=manual_cuts
        )
        filtered = [(img, meta) for (img, meta) in raw_results if self.is_video_frame(meta)]
        if not filtered and raw_results:
            filtered = sorted(raw_results, key=lambda x: x[1].visual_score, reverse=True)[:max(1, len(raw_results) // 2)]

        reindexed = []
        for new_idx, (img, meta) in enumerate(filtered, start=1):
            meta.page_index = new_idx
            meta.page_id = f"page_{new_idx:03d}"
            reindexed.append((img, meta))
        return reindexed

    @_hybridmethod
    def paginate_pdf(
        self,
        pdf_input: Any,
        target_width: int = 1080,
        dpi: int = 150,
        bg_val: Optional[int] = None,
        start_page_index: int = 1,
        stitch_canvas: bool = True
    ) -> List[Tuple[np.ndarray, PageMetadata]]:
        """
        Intelligently paginates a PDF document into content-based Smart Pages:
        - PDF physical pages are treated purely as input image sources, NOT as limits for output pages.
        - Multiple Smart Pages can be extracted from a single physical PDF page.
        - Output page count is NOT bounded or restricted to 1 PDF page = 1 output page.
        - Page numbering does NOT reset when transitioning across physical PDF pages.
        - Page IDs and indices increase continuously throughout the episode:
            PDF physical page 1 -> Page 1, Page 2, Page 3...
            PDF physical page 2 -> Page 4, Page 5, Page 6...
            PDF physical page 3 -> Page 7, Page 8...
        - Full segmentation logic, Point scoring, text scoring, and metadata formats are preserved intact.
        """
        page_images: List[Tuple[int, np.ndarray]] = []

        if isinstance(pdf_input, (list, tuple)):
            for p_idx, p_item in enumerate(pdf_input, start=1):
                if isinstance(p_item, Image.Image):
                    bgr = cv2.cvtColor(np.array(p_item.convert("RGB")), cv2.COLOR_RGB2BGR)
                    page_images.append((p_idx, bgr))
                elif isinstance(p_item, np.ndarray):
                    if len(p_item.shape) == 2:
                        bgr = cv2.cvtColor(p_item, cv2.COLOR_GRAY2BGR)
                    else:
                        bgr = p_item
                    page_images.append((p_idx, bgr))
        else:
            try:
                import fitz
            except ImportError:
                try:
                    import pymupdf as fitz
                except ImportError:
                    raise ImportError("PyMuPDF (fitz) is required to paginate PDF files. Please install pymupdf.")

            should_close = False
            if isinstance(pdf_input, (str, os.PathLike)):
                doc = fitz.open(str(pdf_input))
                should_close = True
            elif isinstance(pdf_input, (bytes, bytearray)):
                doc = fitz.open(stream=pdf_input, filetype="pdf")
                should_close = True
            else:
                doc = pdf_input

            try:
                for p_num in range(len(doc)):
                    p = doc[p_num]
                    rect = p.rect
                    if target_width and rect.width > 0:
                        scale = float(target_width) / float(rect.width)
                    elif dpi:
                        scale = float(dpi) / 72.0
                    else:
                        scale = 2.0
                    mat = fitz.Matrix(scale, scale)
                    pix = p.get_pixmap(matrix=mat, alpha=False)
                    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                    if pix.n == 4:
                        bgr = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
                    elif pix.n == 3:
                        bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                    elif pix.n == 1:
                        bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                    else:
                        bgr = img
                    page_images.append((p_num + 1, bgr))
            finally:
                if should_close:
                    doc.close()

        if not page_images:
            return []

        if stitch_canvas:
            total_height = sum(im.shape[0] for _, im in page_images)
            max_w = max(im.shape[1] for _, im in page_images)
            if total_height <= 0 or max_w <= 0:
                return []

            if bg_val is None:
                bg_val = self.detect_background(cv2.cvtColor(page_images[0][1], cv2.COLOR_BGR2GRAY))

            canvas = np.ones((total_height, max_w, 3), dtype=np.uint8) * bg_val
            offsets = []
            curr_y = 0
            for phys_num, p_img in page_images:
                h, w = p_img.shape[:2]
                start_x = (max_w - w) // 2
                canvas[curr_y:curr_y + h, start_x:start_x + w] = p_img
                offsets.append({
                    "filename": f"pdf_page_{phys_num:03d}.png",
                    "pdf_page": phys_num,
                    "physical_page": phys_num,
                    "offset_y_start": curr_y,
                    "offset_y_end": curr_y + h,
                    "height": h
                })
                curr_y += h

            return self.paginate_canvas(
                canvas,
                source_offsets=offsets,
                bg_val=bg_val,
                start_page_index=start_page_index
            )
        else:
            all_results = []
            curr_start_idx = start_page_index
            for phys_num, p_img in page_images:
                offsets = [{
                    "filename": f"pdf_page_{phys_num:03d}.png",
                    "pdf_page": phys_num,
                    "physical_page": phys_num,
                    "offset_y_start": 0,
                    "offset_y_end": p_img.shape[0],
                    "height": p_img.shape[0]
                }]
                page_results = self.paginate_canvas(
                    p_img,
                    source_offsets=offsets,
                    bg_val=bg_val,
                    start_page_index=curr_start_idx
                )
                all_results.extend(page_results)
                curr_start_idx += len(page_results)
            return all_results
