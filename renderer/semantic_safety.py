# -*- coding: utf-8 -*-
"""
Semantic Safety Layer: YOLO-Driven Character and Object Protection.

Re-purposes YOLO from a page splitter to a Semantic Safety validator:
- Identifies characters, faces/heads, monsters, weapons, and major visual subjects.
- Protects characters and major subjects from being sliced across page cuts.
- Applies strict rejection to cuts through faces/heads.
- Evaluates candidate boundaries and assigns safety penalties or marks them as unsafe.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional
import numpy as np


@dataclass
class SemanticSubject:
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2
    category: str                    # "character", "face", "monster", "weapon", "object"
    confidence: float = 0.8
    is_primary: bool = True
    head_span: Optional[Tuple[int, int]] = None
    body_span: Optional[Tuple[int, int]] = None

    def __post_init__(self):
        x1, y1, x2, y2 = self.bbox
        h = max(1, y2 - y1)
        if self.category in ("character", "person", "monster"):
            # Head/face is typically top 35% of character height
            self.head_span = (y1, y1 + int(h * 0.35))
            self.body_span = (y1, y2)
        else:
            self.head_span = None
            self.body_span = (y1, y2)


class SemanticSafetyLayer:
    """
    Semantic safety validator. Prevents candidate cuts from slicing through characters,
    faces, weapons, or important visual subjects.
    """

    def __init__(
        self,
        character_overlap_penalty: float = 5.0,
        object_overlap_penalty: float = 2.5,
        safety_margin: int = 25
    ):
        self.character_overlap_penalty = character_overlap_penalty
        self.object_overlap_penalty = object_overlap_penalty
        self.safety_margin = safety_margin
        self.subjects: List[SemanticSubject] = []
        self.action_spans: List[Tuple[int, int]] = []

    def set_action_spans(self, spans: Optional[List[Tuple[int, int]]]):
        """Sets vertical spans where continuous ongoing action (speed lines, motion, attack effects) takes place."""
        self.action_spans = []
        if spans:
            for s, e in spans:
                if e > s:
                    self.action_spans.append((int(s), int(e)))

    def set_detected_regions(
        self,
        characters: Optional[List[Tuple[int, int, int, int]]] = None,
        objects: Optional[List[Tuple[int, int, int, int]]] = None,
        faces: Optional[List[Tuple[int, int, int, int]]] = None,
        yolo_detections: Optional[List[Dict[str, Any]]] = None
    ):
        """Loads detected subjects from YOLO or detection dictionaries."""
        self.subjects = []

        def _is_valid_dim(b):
            bx1, by1, bx2, by2 = b
            return (by2 - by1) >= 35 and (bx2 - bx1) >= 25

        if yolo_detections:
            for d in yolo_detections:
                bbox = d.get("bbox", (0, 0, 0, 0))
                if not _is_valid_dim(bbox):
                    continue
                cls_name = d.get("label", d.get("class", "character")).lower()
                if any(k in cls_name for k in ("page", "panel", "frame")):
                    continue
                conf = float(d.get("confidence", d.get("conf", 0.8)))
                cat = "character" if any(k in cls_name for k in ("person", "char", "body", "monster")) else "object"
                if "face" in cls_name or "head" in cls_name:
                    cat = "face"
                self.subjects.append(SemanticSubject(bbox=bbox, category=cat, confidence=conf))

        if characters:
            for bbox in characters:
                if _is_valid_dim(bbox):
                    self.subjects.append(SemanticSubject(bbox=bbox, category="character", confidence=0.85))

        if objects:
            for bbox in objects:
                if _is_valid_dim(bbox):
                    self.subjects.append(SemanticSubject(bbox=bbox, category="object", confidence=0.70))

        if faces:
            for bbox in faces:
                if (bbox[3] - bbox[1]) >= 15:
                    self.subjects.append(SemanticSubject(bbox=bbox, category="face", confidence=0.90))

    def evaluate_cut_safety(
        self,
        candidate_y: int
    ) -> Tuple[bool, float, str, Dict[str, Any]]:
        """
        Evaluates safety of a candidate cut Y against all detected semantic subjects.
        Returns:
            (is_safe: bool, penalty: float, reason: str, details: dict)
        """
        if not self.subjects and not self.action_spans:
            return True, 0.0, "", {}

        total_penalty = 0.0
        is_safe = True
        reasons = []
        matched_subjects = []

        # Check ongoing action intersection: strictly unsafe
        for as_start, as_end in self.action_spans:
            if as_start <= candidate_y <= as_end:
                is_safe = False
                total_penalty += self.character_overlap_penalty * 1.5
                reasons.append("cuts_ongoing_action")
                break

        for s in self.subjects:
            x1, y1, x2, y2 = s.bbox
            if y2 <= y1:
                continue

            # Check head/face intersection: strictly unsafe
            if s.head_span:
                hy1, hy2 = s.head_span
                if hy1 <= candidate_y <= hy2:
                    is_safe = False
                    total_penalty += self.character_overlap_penalty * 2.0
                    reasons.append("cuts_character_head")
                    matched_subjects.append(s.bbox)
                    continue

            # Check full body / character / object intersection
            if y1 <= candidate_y <= y2:
                # Direct intersection through character, face, or important object
                sub_h = max(1, y2 - y1)
                rel_pos = round((candidate_y - y1) / float(sub_h), 3)
                if s.category in ("character", "person", "monster"):
                    is_safe = False
                    total_penalty += self.character_overlap_penalty
                    reasons.append("character_overlap")
                    matched_subjects.append({
                        "bbox": s.bbox,
                        "category": s.category,
                        "relative_cut_pos": rel_pos
                    })
                elif s.category == "face":
                    is_safe = False
                    total_penalty += self.character_overlap_penalty * 2.0
                    reasons.append("face_overlap")
                    matched_subjects.append({
                        "bbox": s.bbox,
                        "category": s.category,
                        "relative_cut_pos": rel_pos
                    })
                else:
                    # Object / weapon / prop / vehicle overlap: strictly protected
                    is_safe = False
                    total_penalty += self.object_overlap_penalty * 2.0
                    reasons.append("object_overlap")
                    matched_subjects.append({
                        "bbox": s.bbox,
                        "category": s.category,
                        "relative_cut_pos": rel_pos
                    })
                continue

            # Check margin buffer zone
            margin = self.safety_margin
            if (y1 - margin <= candidate_y < y1) or (y2 < candidate_y <= y2 + margin):
                total_penalty += 0.3
                reasons.append("near_character_margin")

        primary_reason = reasons[0] if reasons else ""
        details = {
            "matched_subjects_count": len(matched_subjects),
            "reasons": reasons,
            "is_character_overlap": any(r in reasons for r in ("character_overlap", "cuts_character_head", "face_overlap")),
            "is_object_overlap": "object_overlap" in reasons,
            "is_action_overlap": "cuts_ongoing_action" in reasons,
            "matched_subjects": matched_subjects,
        }

        return is_safe, total_penalty, primary_reason, details

    def get_all_forbidden_spans(self) -> List[Tuple[int, int]]:
        """Returns list of (y1, y2) intervals where characters, faces, objects, or ongoing actions are located, padded by safety_margin."""
        spans: List[Tuple[int, int]] = []
        pad = self.safety_margin
        for s in self.subjects:
            x1, y1, x2, y2 = s.bbox
            if y2 > y1:
                spans.append((max(0, y1 - pad), y2 + pad))
        for as_s, as_e in self.action_spans:
            if as_e > as_s:
                spans.append((max(0, as_s - pad), as_e + pad))

        if not spans:
            return []

        spans.sort(key=lambda x: x[0])
        merged = [spans[0]]
        for s, e in spans[1:]:
            last_s, last_e = merged[-1]
            if s <= last_e + 4:
                merged[-1] = (last_s, max(last_e, e))
            else:
                merged.append((s, e))

        return merged
