# -*- coding: utf-8 -*-
"""
PURE VISUAL REGION DETECTION: CONFIGURATION
Defines hyper-parameters for visual panel segmentation, junk/text filtering, and PDF badging.
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional
import os


@dataclass
class DetectionConfig:
    """Configuration for Pure Visual Region Detection pipeline."""
    # Model Weights
    yolo_weights: str = "weights/manga109_yolo11m.pt"
    rtdetr_weights: str = "weights/rtdetrv4_x_manga109s_v2.onnx"
    anime_face_weights: str = "weights/anime_face_yolov8s.pt"
    bubble_detector_weights: str = "weights/comic_text_bubble_detector.onnx"
    
    # Primary Layout Engine
    primary_engine: str = "gpu_layout"  # "gpu_layout" (YOLO11m/RT-DETR on CUDA)
    
    # Device
    device: str = "cuda"  # "cuda" or "cpu"
    
    # Canvas & Tiling settings
    tile_size: int = 1024
    tile_overlap: int = 200
    downsample_target_w: int = 450
    
    # Detection Thresholds
    face_conf_threshold: float = 0.35
    layout_conf_threshold: float = 0.30
    
    # Visual Region Filtering & Split Limits
    min_region_height: int = 240              # Drop visual regions shorter than this (px)
    max_region_height: int = 4500             # Max height before evaluating soft sub-splits
    target_region_height: int = 1400          # Ideal video frame height
    min_visual_score: float = 0.15            # Minimum visual score to be considered pure visual
    max_text_only_ratio: float = 0.50         # Drop if text covers >50% (all text/bubble regions)
    min_gutter_gap: int = 12                  # Minimum whitespace/background gap to force separate panels
    
    # Guardrail settings
    zero_character_cut: bool = True           # Strictly forbid cutting through character face/body
    face_protection_padding: int = 40         # Extra px margin above/below face to forbid cutting
    body_protection_padding: int = 20         # Extra px margin above/below body to forbid cutting
    
    # Horizontal Cleaning settings
    horizontal_auto_crop: bool = True         # Automatically trim black/white padding bars on sides
    horizontal_tolerance: int = 15            # Color tolerance for side padding removal
    
    # Gutter & Background detection
    bg_tolerance: int = 18
    bg_threshold: float = 0.96
    enable_dual_bg_gutter: bool = True        # Automatically recognize both White and Black gutters
    dark_bg_threshold: int = 25               # Values <= 25 considered dark background
    light_bg_threshold: int = 230             # Values >= 230 considered light background
    
    # Junk Frame Filtering & Quality Gate Settings
    min_clean_height: int = 350               # Standalone non-character frames shorter than this are dropped
    min_laplacian_var: float = 250.0          # Minimum Laplacian variance for non-character panels
    min_edge_density_no_char: float = 0.010   # Minimum edge density for non-character panels
    min_color_variance_no_char: float = 35.0  # Minimum color std dev for non-character panels
    max_aspect_ratio_no_char: float = 2.8     # Drop wide flat ribbons (W/H > 2.8) without characters
    max_text_density_no_char: float = 0.50    # Drop if bubble/text area > 50%
    max_text_area_ratio_drop: float = 0.50    # Drop visual region if total text/bubble area > 50%
    max_isolated_bubble_bg_ratio: float = 0.58 # Drop isolated speech bubbles surrounded by background gutters
    
    # Badge & Annotation settings
    min_annotation_score: int = 55                         # Do not draw bounding box / badges for regions with score <= 55
    box_color_bgr: Tuple[int, int, int] = (0, 255, 0)      # Bright Green (0, 255, 0) in BGR
    box_thickness: int = 6                                 # Base border thickness
    badge_bg_color_bgr: Tuple[int, int, int] = (0, 160, 0) # Green background for badge
    badge_text_color_bgr: Tuple[int, int, int] = (255, 255, 255) # White text
    badge_border_color_bgr: Tuple[int, int, int] = (0, 0, 0) # Black outline
    badge_font_scale: float = 1.0                          # Adaptive scaling applied at runtime
    badge_padding_x: int = 14
    badge_padding_y: int = 10
    
    # PDF Settings
    pdf_quality: int = 95
    export_annotated_pdf: bool = True
    export_webp_frames: bool = True

