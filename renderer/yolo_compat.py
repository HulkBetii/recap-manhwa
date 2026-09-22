# -*- coding: utf-8 -*-
"""
Centralized YOLO import guard for recap_comics.
Provides graceful fallback and error reporting when ultralytics is not installed.
"""
import logging

logger = logging.getLogger("YOLOCompat")

_YOLO_AVAILABLE = False
YOLO = None

try:
    from ultralytics import YOLO as _YOLO
    YOLO = _YOLO
    _YOLO_AVAILABLE = True
    logger.info("ultralytics YOLO loaded successfully.")
except ImportError:
    logger.warning(
        "ultralytics is not installed — YOLO inference will be skipped or fall back to pure CV. "
        "Run: pip install ultralytics"
    )
except Exception as e:
    logger.error(f"Error loading ultralytics YOLO: {e}")

def is_yolo_available() -> bool:
    """Check if ultralytics YOLO is imported and available for inference."""
    return _YOLO_AVAILABLE and YOLO is not None
