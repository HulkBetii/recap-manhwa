# -*- coding: utf-8 -*-
"""
PURE VISUAL REGION DETECTION: SCORING ENGINE
Calculates multi-criteria visual storytelling and quality scores (0-100) for pure visual regions.
Considers Character & Face Salience (30%), Sharpness & Richness (25%), Visual Purity (20%),
Composition & Aspect Ratio (15%), and Dynamic Contrast (10%).
Optimized for high-performance sub-millisecond calculation with strided sampling.
"""
import math
import logging
from typing import Dict, Any, Optional
import cv2
import numpy as np

from pure_visual.types import PureVisualRegion, BBox

logger = logging.getLogger("VisualRegionScorer")


def calculate_pure_visual_score(
    img_bgr: np.ndarray,
    region: Optional[PureVisualRegion] = None,
    entities: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Computes a comprehensive visual quality & storytelling score (0 to 100) for a pure visual region.

    Args:
        img_bgr: BGR numpy image of the pure visual region.
        region: PureVisualRegion dataclass instance or None.
        entities: Optional dict with detected faces, bodies, bubbles.

    Returns:
        Dictionary containing:
        - pure_visual_score: float (0.0 to 1.0)
        - score_100: int (0 to 100)
        - quality_tier: str ("S", "A", "B", "C")
        - breakdown: dict of component scores and raw metrics
    """
    if img_bgr is None or img_bgr.size == 0:
        return {
            "pure_visual_score": 0.0,
            "score_100": 0,
            "quality_tier": "C",
            "breakdown": {}
        }

    h, w = img_bgr.shape[:2]
    if h <= 0 or w <= 0:
        return {
            "pure_visual_score": 0.0,
            "score_100": 0,
            "quality_tier": "C",
            "breakdown": {}
        }

    # Strided 2x sampling for sub-millisecond performance
    sub = img_bgr[::2, ::2] if (h > 400 or w > 400) else img_bgr
    gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY) if sub.ndim == 3 else sub

    # -------------------------------------------------------------------------
    # 1. Visual Complexity & Sharpness (Weight: 25%)
    # -------------------------------------------------------------------------
    lap_var = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    s_lap = 1.0 / (1.0 + math.exp(-0.005 * (lap_var - 220.0)))
    color_std = float(np.mean(np.std(sub, axis=(0, 1))))
    s_color = min(1.0, color_std / 50.0)

    canny = cv2.Canny(gray, 40, 140)
    edge_density = float(np.mean(canny > 0))
    s_edge = min(1.0, edge_density / 0.040)

    s_sharpness = 0.45 * s_lap + 0.35 * s_color + 0.20 * s_edge

    # -------------------------------------------------------------------------
    # 2. Content Fill & Dynamic Range (Weight: 10%)
    # -------------------------------------------------------------------------
    white_ratio = float(np.mean(gray >= 240))
    dark_ratio = float(np.mean(gray <= 18))
    content_fill = max(0.0, 1.0 - (white_ratio + dark_ratio))
    s_fill = min(1.0, content_fill / 0.55)

    p5, p95 = np.percentile(gray, [5, 95])
    s_contrast = min(1.0, float(p95 - p5) / 180.0)
    s_dynamics = 0.60 * s_contrast + 0.40 * s_fill

    # -------------------------------------------------------------------------
    # 3. Visual Richness / Scenery / Environmental Art Engine
    # -------------------------------------------------------------------------
    art_richness = (0.35 * s_color + 0.30 * s_contrast + 0.20 * s_lap + 0.15 * s_edge) * (0.25 + 0.75 * s_fill)
    is_scenery_or_rich_art = (art_richness >= 0.50)

    if art_richness >= 0.50:
        s_scenery_art = min(1.0, art_richness * 1.15)
    else:
        s_scenery_art = art_richness * 0.60

    # -------------------------------------------------------------------------
    # 4. Character & Narrative Salience (Weight: 30%)
    # -------------------------------------------------------------------------
    faces = 0
    bodies = 0
    if region is not None:
        faces = getattr(region, "face_count", 0) or 0
        bodies = getattr(region, "body_count", 0) or 0
    elif entities:
        faces = len(entities.get("faces", []))
        bodies = len(entities.get("bodies", []))

    has_character = (faces > 0 or bodies > 0)
    if has_character:
        s_char = min(1.0, 0.55 * min(faces, 2) + 0.35 * min(bodies, 2))
    else:
        s_char = 0.05

    # Narrative/Visual Salience is the maximum of character presence or environmental art
    s_salience = max(s_char, s_scenery_art)

    # -------------------------------------------------------------------------
    # 5. Visual Purity / Freedom from Residual Text (Weight: 20%)
    # -------------------------------------------------------------------------
    top_text_count = len(getattr(region, "top_text_boxes", [])) if region else 0
    bot_text_count = len(getattr(region, "bottom_text_boxes", [])) if region else 0
    total_text = top_text_count + bot_text_count

    s_purity = max(0.0, 1.0 - (total_text * 0.15))
    if not has_character and not is_scenery_or_rich_art:
        # Check white ratio indicative of residual speech bubbles / blank gutters
        if white_ratio > 0.40:
            s_purity = min(s_purity, 0.20)

    # -------------------------------------------------------------------------
    # 6. Composition & Aspect Ratio (Weight: 15%)
    # -------------------------------------------------------------------------
    aspect = float(w) / max(1.0, float(h))
    if 0.35 <= aspect <= 1.7:
        s_aspect = 1.0
    elif 0.25 <= aspect <= 2.2:
        s_aspect = 0.80
    else:
        s_aspect = 0.45

    h_factor = min(1.0, float(h) / 500.0)
    s_comp = s_aspect * (0.30 + 0.70 * h_factor)

    if not has_character and not is_scenery_or_rich_art:
        s_comp = min(s_comp, 0.40)

    # -------------------------------------------------------------------------
    # Weighted Final Score (0.0 to 1.0) -> Point: 0 to 100
    # -------------------------------------------------------------------------
    total_score = (
        0.30 * s_salience +
        0.25 * s_sharpness +
        0.20 * s_purity +
        0.15 * s_comp +
        0.10 * s_dynamics
    )
    total_score = max(0.0, min(1.0, total_score))
    score_100 = int(round(total_score * 100))

    if score_100 >= 80:
        tier = "S"
    elif score_100 >= 65:
        tier = "A"
    elif score_100 >= 50:
        tier = "B"
    else:
        tier = "C"

    return {
        "pure_visual_score": round(float(total_score), 4),
        "score_100": score_100,
        "quality_tier": tier,
        "breakdown": {
            "salience_score": round(float(s_salience), 3),
            "character_score": round(float(s_char), 3),
            "scenery_art_score": round(float(s_scenery_art), 3),
            "art_richness": round(float(art_richness), 3),
            "sharpness_score": round(float(s_sharpness), 3),
            "purity_score": round(float(s_purity), 3),
            "composition_score": round(float(s_comp), 3),
            "dynamics_score": round(float(s_dynamics), 3),
            "contrast_score": round(float(s_contrast), 3),
            "content_fill": round(float(content_fill), 3),
            "laplacian_var": round(float(lap_var), 1),
            "color_std": round(float(color_std), 1),
            "edge_density": round(float(edge_density), 4)
        }
    }
