# -*- coding: utf-8 -*-
"""
PURE VISUAL REGION DETECTION: DATA TYPES & STRUCTURES
Defines BBox, TextDetection, VisualRegionCandidate, PureVisualRegion, and PipelineResult.
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional
import numpy as np


@dataclass
class BBox:
    """
    Standard integer bounding box [x1, y1, x2, y2].
    Provides coordinate transformation, area, IoU, containment, and clipping helpers.
    """
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def x(self) -> int:
        return self.x1

    @property
    def y(self) -> int:
        return self.y1

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def aspect_ratio(self) -> float:
        return float(self.width) / max(1.0, float(self.height))

    def is_valid(self, min_w: int = 1, min_h: int = 1) -> bool:
        return self.width >= min_w and self.height >= min_h and self.x2 > self.x1 and self.y2 > self.y1

    def clip_to(self, max_w: int, max_h: int) -> 'BBox':
        return BBox(
            x1=max(0, min(max_w, self.x1)),
            y1=max(0, min(max_h, self.y1)),
            x2=max(0, min(max_w, self.x2)),
            y2=max(0, min(max_h, self.y2))
        )

    def scale(self, scale_x: float, scale_y: float) -> 'BBox':
        return BBox(
            x1=int(round(self.x1 * scale_x)),
            y1=int(round(self.y1 * scale_y)),
            x2=int(round(self.x2 * scale_x)),
            y2=int(round(self.y2 * scale_y))
        )

    def shift(self, dx: int, dy: int) -> 'BBox':
        return BBox(
            x1=self.x1 + dx,
            y1=self.y1 + dy,
            x2=self.x2 + dx,
            y2=self.y2 + dy
        )

    def intersection(self, other: 'BBox') -> Optional['BBox']:
        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)
        if ix2 > ix1 and iy2 > iy1:
            return BBox(ix1, iy1, ix2, iy2)
        return None

    def union(self, other: 'BBox') -> 'BBox':
        return BBox(
            min(self.x1, other.x1),
            min(self.y1, other.y1),
            max(self.x2, other.x2),
            max(self.y2, other.y2)
        )

    def iou(self, other: 'BBox') -> float:
        inter = self.intersection(other)
        if not inter:
            return 0.0
        union_area = self.area + other.area - inter.area
        return float(inter.area) / max(1.0, float(union_area))

    def contains(self, other: 'BBox') -> bool:
        return self.x1 <= other.x1 and self.y1 <= other.y1 and self.x2 >= other.x2 and self.y2 >= other.y2

    def to_list(self) -> List[int]:
        return [self.x1, self.y1, self.x2, self.y2]

    def to_dict(self) -> Dict[str, int]:
        return {
            "x": self.x1,
            "y": self.y1,
            "width": self.width,
            "height": self.height,
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2
        }

    @classmethod
    def from_list(cls, coords: List[int]) -> 'BBox':
        return cls(x1=int(coords[0]), y1=int(coords[1]), x2=int(coords[2]), y2=int(coords[3]))


@dataclass
class TextDetection:
    """
    Text or speech-bubble obstacle detected within a top/bottom search zone.
    """
    bbox: BBox
    text_type: str = "text"  # "text", "speech_bubble", "caption", "sfx"
    confidence: float = 1.0
    zone: str = "top"        # "top" or "bottom"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bbox": self.bbox.to_list(),
            "type": self.text_type,
            "confidence": round(float(self.confidence), 4),
            "zone": self.zone
        }


@dataclass
class VisualRegionCandidate:
    """
    Initial semantic visual region detected by layout model before dynamic shrinking.
    """
    region_id: int
    bbox: BBox
    confidence: float = 0.90
    region_type: str = "visual"  # "visual", "character", "scene", "action"
    bodies: List[BBox] = field(default_factory=list)
    faces: List[BBox] = field(default_factory=list)


@dataclass
class PureVisualRegion:
    """
    Final validated pure visual region with dynamic boundaries and complete audit metadata.
    """
    region_id: int
    original_bbox: BBox
    pure_visual_bbox: BBox
    top_text_detected: bool = False
    bottom_text_detected: bool = False
    top_text_boxes: List[TextDetection] = field(default_factory=list)
    bottom_text_boxes: List[TextDetection] = field(default_factory=list)
    crop_reason: List[str] = field(default_factory=list)
    confidence: float = 0.95
    status: str = "PURE_VISUAL"  # "PURE_VISUAL", "LOW_VISUAL_AREA", "AMBIGUOUS_TEXT_OVERLAP", "INVALID_BOUNDARIES"
    visual_ratio: float = 1.0
    top_zone_bbox: Optional[BBox] = None
    bottom_zone_bbox: Optional[BBox] = None
    file_name: str = ""
    file_path: str = ""
    body_count: int = 0
    face_count: int = 0
    horizontal_cleaning: Dict[str, Any] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_id": f"R{self.region_id}" if isinstance(self.region_id, int) else str(self.region_id),
            "source_file": self.details.get("source_file", self.file_name or "001.webp"),
            "source_bbox": self.original_bbox.to_list(),
            "original_bbox": self.original_bbox.to_list(),
            "local_bbox": self.details.get("local_bbox", self.pure_visual_bbox.to_list()),
            "smart_crop_box": self.details.get("smart_crop_box", self.pure_visual_bbox.to_list()),
            "page_tag": self.details.get("page_tag", "CHARACTER_ART" if self.face_count > 0 else "CHARACTER_SCENE"),
            "pure_visual_bbox": self.pure_visual_bbox.to_list(),
            "width": self.pure_visual_bbox.width,
            "height": self.pure_visual_bbox.height,
            "aspect_ratio": round(self.pure_visual_bbox.aspect_ratio, 3),
            "visual_ratio": round(float(self.visual_ratio), 4),
            "top_text_detected": bool(self.top_text_detected),
            "bottom_text_detected": bool(self.bottom_text_detected),
            "top_text_boxes": [t.to_dict() for t in self.top_text_boxes],
            "bottom_text_boxes": [b.to_dict() for b in self.bottom_text_boxes],
            "crop_reason": self.crop_reason,
            "confidence": round(float(self.confidence), 4),
            "status": self.status,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "horizontal_cleaning": self.horizontal_cleaning,
            "character_count": {
                "bodies": self.body_count,
                "faces": self.face_count
            },
            "details": self.details
        }



@dataclass
class PipelineResult:
    """
    Overall execution result of Pure Visual Region Detection pipeline.
    """
    canvas_width: int
    canvas_height: int
    regions: List[PureVisualRegion]
    scale_x: float = 1.0
    scale_y: float = 1.0
    detection_width: int = 0
    detection_height: int = 0
    timing: Dict[str, float] = field(default_factory=dict)
    statistics: Dict[str, Any] = field(default_factory=dict)
    status: str = "success"
