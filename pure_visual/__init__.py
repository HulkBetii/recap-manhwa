# -*- coding: utf-8 -*-
"""
Pure Visual Region Detection Package for Ultra-Tall Manhwa & Comics.
"""
from pure_visual.types import BBox, PureVisualRegion, VisualRegionCandidate, TextDetection, PipelineResult
from pure_visual.config import DetectionConfig
from pure_visual.visual_detector import VisualRegionDetector
from pure_visual.pdf_annotator import PDFAnnotator
from pure_visual.pipeline import PureVisualPipeline
from pure_visual.scorer import calculate_pure_visual_score

__all__ = [
    "BBox",
    "PureVisualRegion",
    "VisualRegionCandidate",
    "TextDetection",
    "PipelineResult",
    "DetectionConfig",
    "VisualRegionDetector",
    "PDFAnnotator",
    "PureVisualPipeline",
    "calculate_pure_visual_score"
]
