# -*- coding: utf-8 -*-
"""
Boundary Scorer: Multi-signal weighted boundary evaluation.

Combines:
- Visual transition score
- Composition transition score
- Panel boundary score
- Content width score
- Natural endpoint score
- Speech bubble edge score
- Action/visual continuity penalty
- Character and object overlap safety penalties

All weights are fully configurable via PaginationConfig.
"""

from typing import List, Tuple, Dict, Any, Optional
import numpy as np

from renderer.visual_boundary_scanner import (
    BoundaryCandidate,
    BoundaryClassification,
    BoundaryRecommendation,
    BoundaryEvaluation,
)
from renderer.semantic_safety import SemanticSafetyLayer


class BoundaryScorer:
    """
    Evaluates and scores candidate boundaries by synthesizing visual, structural,
    and semantic safety signals into structured 10-type semantic boundary evaluations.
    """

    def __init__(
        self,
        scene_transition_weight: float = 1.0,
        composition_weight: float = 0.8,
        panel_boundary_weight: float = 0.9,
        content_width_weight: float = 0.6,
        natural_endpoint_weight: float = 0.7,
        speech_edge_weight: float = 1.2,
        action_continuity_penalty: float = 3.0,
        character_overlap_penalty: float = 5.0,
        object_overlap_penalty: float = 2.5,
        boundary_score_threshold: float = 0.35
    ):
        self.scene_transition_weight = scene_transition_weight
        self.composition_weight = composition_weight
        self.panel_boundary_weight = panel_boundary_weight
        self.content_width_weight = content_width_weight
        self.natural_endpoint_weight = natural_endpoint_weight
        self.speech_edge_weight = speech_edge_weight
        self.action_continuity_penalty = action_continuity_penalty
        self.character_overlap_penalty = character_overlap_penalty
        self.object_overlap_penalty = object_overlap_penalty
        self.boundary_score_threshold = boundary_score_threshold

    def score_candidates(
        self,
        candidates: List[BoundaryCandidate],
        safety_layer: Optional[SemanticSafetyLayer] = None,
        internal_bubble_spans: Optional[List[Tuple[int, int]]] = None,
        all_bubble_spans: Optional[List[Tuple[int, int]]] = None
    ) -> List[BoundaryCandidate]:
        """
        Scores all candidate boundaries, applies semantic safety gates, and updates
        their composite score, safety attributes, and structured semantic classification.
        """
        if not candidates:
            return []

        internal_spans = internal_bubble_spans or []
        bubble_spans = all_bubble_spans or []
        w_sum = (
            self.scene_transition_weight +
            self.composition_weight +
            self.panel_boundary_weight +
            self.content_width_weight +
            self.natural_endpoint_weight +
            self.speech_edge_weight
        )
        norm_w = max(1.0, w_sum)

        for c in candidates:
            # 0. Check if candidate slices strictly through the interior of ANY speech bubble
            # (speech_bubble_edge candidates are placed specifically to separate edge bubbles and should not be suppressed)
            slices_bubble = False
            if c.candidate_type != "speech_bubble_edge":
                for bs, be in bubble_spans:
                    if bs + 18 <= c.y <= be - 18:
                        slices_bubble = True
                        break

            if slices_bubble:
                c.is_safe = False
                c.rejection_reason = "cuts_through_speech_bubble"
                c.score = 0.0
                c.penalties["bubble_slice"] = 15.0
                c.classification = BoundaryClassification.INTERNAL_BUBBLE
                c.recommendation = BoundaryRecommendation.FORBID_CUT
                c.confidence = 0.99
                c.reason = "cuts_through_speech_bubble"
                c.evaluation = BoundaryEvaluation(
                    classification=c.classification,
                    recommendation=c.recommendation,
                    confidence=c.confidence,
                    reason=c.reason,
                    details=dict(c.details)
                )
                continue

            # 1. Check if candidate falls inside an INTERNAL speech bubble (Case C)
            # Internal bubbles are part of the visual composition and must NEVER be cut through!
            inside_internal_bubble = False
            for bs, be in internal_spans:
                if bs <= c.y <= be:
                    inside_internal_bubble = True
                    break

            if inside_internal_bubble:
                c.is_safe = False
                c.rejection_reason = "inside_internal_speech_bubble"
                c.score = 0.0
                c.penalties["internal_bubble"] = 10.0
                c.classification = BoundaryClassification.INTERNAL_BUBBLE
                c.recommendation = BoundaryRecommendation.FORBID_CUT
                c.confidence = 0.98
                c.reason = "inside_internal_speech_bubble"
                c.evaluation = BoundaryEvaluation(
                    classification=c.classification,
                    recommendation=c.recommendation,
                    confidence=c.confidence,
                    reason=c.reason,
                    details=dict(c.details)
                )
                continue

            # 2. Check semantic safety (characters, faces, monsters, objects from YOLO)
            is_safe = True
            char_penalty = 0.0
            rejection_reason = ""
            if safety_layer is not None:
                is_safe, char_penalty, rejection_reason, details = safety_layer.evaluate_cut_safety(c.y)
                c.details.update(details)

            c.is_safe = is_safe
            if not is_safe:
                c.rejection_reason = rejection_reason

            # 3. Hard cut handling (e.g. Edge speech bubble above/below visual)
            if c.hard and c.candidate_type == "speech_bubble_edge":
                if is_safe:
                    c.score = 1.0
                    c.speech_edge_score = 1.0
                    c.classification = BoundaryClassification.EDGE_BUBBLE
                    c.recommendation = BoundaryRecommendation.RECOMMEND_CUT
                    c.confidence = 1.0
                    c.reason = "speech_bubble_edge"
                else:
                    c.score = 0.0
                    c.classification = (
                        BoundaryClassification.CONTINUOUS_CHARACTER
                        if any(k in rejection_reason for k in ("character", "face", "head"))
                        else (
                            BoundaryClassification.OBJECT_CONTINUATION
                            if "object" in rejection_reason
                            else (
                                BoundaryClassification.CONTINUOUS_ACTION
                                if "action" in rejection_reason
                                else BoundaryClassification.UNSAFE_CUT
                            )
                        )
                    )
                    c.recommendation = BoundaryRecommendation.FORBID_CUT
                    c.confidence = 0.95
                    c.reason = rejection_reason
                c.evaluation = BoundaryEvaluation(
                    classification=c.classification,
                    recommendation=c.recommendation,
                    confidence=c.confidence,
                    reason=c.reason,
                    details=dict(c.details)
                )
                continue

            # 4. Same Visual Composition Evaluation
            # Decides whether content above and below candidate boundary belongs to the SAME visual composition.
            # Strong visual continuity must have higher priority than weak panel/border signals.
            gutter_len = c.details.get("gutter_length", 0) or c.details.get("gutter_height", 0)
            is_real_gutter = (c.candidate_type == "natural_visual_endpoint" and (gutter_len >= 35 or c.visual_transition_score >= 0.35) and c.visual_continuity < 0.40)

            same_comp_score = float(np.clip(
                c.visual_continuity * 0.65 +
                c.action_continuity * 0.45 +
                (0.20 if c.details.get("is_connected_panel", False) else 0.0) +
                (0.15 if c.details.get("is_internal_whitespace", False) else 0.0),
                0.0, 1.0
            ))
            c.same_composition_score = same_comp_score

            is_same_comp = False
            if not is_real_gutter:
                if c.visual_transition_score >= 0.50 or c.candidate_type == "scene_transition":
                    is_same_comp = False
                elif c.panel_boundary_score >= 0.50 and c.visual_transition_score >= 0.35 and c.action_continuity < 0.25:
                    is_same_comp = False
                elif same_comp_score >= 0.50 or c.visual_continuity >= 0.35 or c.action_continuity >= 0.30 or c.visual_transition_score < 0.30:
                    is_same_comp = True

            if is_same_comp:
                c.details["same_visual_composition"] = True
                if not c.rejection_reason:
                    c.rejection_reason = "same_visual_composition" if c.action_continuity < 0.35 else "continuous_action_sequence"
                c.score = 0.0
                c.penalties["same_composition"] = 10.0
                if not is_safe:
                    if any(k in rejection_reason for k in ("character", "face", "head")):
                        c.classification = BoundaryClassification.CONTINUOUS_CHARACTER
                    elif "object" in rejection_reason:
                        c.classification = BoundaryClassification.OBJECT_CONTINUATION
                    elif "action" in rejection_reason:
                        c.classification = BoundaryClassification.CONTINUOUS_ACTION
                    else:
                        c.classification = BoundaryClassification.UNSAFE_CUT
                    c.reason = rejection_reason
                    c.confidence = 0.95
                elif c.action_continuity >= 0.35 or "action" in c.rejection_reason:
                    c.classification = BoundaryClassification.CONTINUOUS_ACTION
                    c.reason = "continuous_action_sequence"
                    c.confidence = max(0.85, same_comp_score)
                else:
                    c.classification = BoundaryClassification.CONTINUOUS_SCENE
                    c.reason = "same_visual_composition"
                    c.confidence = max(0.85, same_comp_score)
                c.recommendation = BoundaryRecommendation.FORBID_CUT
                c.evaluation = BoundaryEvaluation(
                    classification=c.classification,
                    recommendation=c.recommendation,
                    confidence=c.confidence,
                    reason=c.reason,
                    details=dict(c.details)
                )
                continue

            # 5. Positive feature signal synthesis for genuine composition boundaries
            pos_score = (
                self.scene_transition_weight * c.visual_transition_score +
                self.composition_weight * c.composition_score +
                self.panel_boundary_weight * c.panel_boundary_score +
                self.content_width_weight * c.content_width_score +
                self.natural_endpoint_weight * c.natural_endpoint_score +
                self.speech_edge_weight * c.speech_edge_score
            ) / norm_w

            # If this is a panel boundary or natural endpoint at a true composition transition
            if c.candidate_type == "panel_boundary":
                pos_score = max(pos_score, 0.45 + 0.35 * c.panel_boundary_score)
            elif c.candidate_type == "natural_visual_endpoint":
                pos_score = max(pos_score, 0.45 + 0.40 * c.natural_endpoint_score)
            elif c.candidate_type == "scene_transition":
                pos_score = max(pos_score, 0.50 + 0.50 * c.visual_transition_score)

            # 6. Visual Continuity Penalty / Bonus
            continuity_penalty = 0.0
            if c.visual_continuity > 0.40:
                continuity_penalty = ((c.visual_continuity - 0.40) / 0.60) * (self.action_continuity_penalty / 4.0)
            elif c.visual_continuity < 0.30:
                # Low continuity indicates strong natural scene break => bonus
                pos_score += 0.15 * (0.30 - c.visual_continuity) / 0.30

            # 7. Apply Penalties
            total_penalty = continuity_penalty + min(1.0, char_penalty / 8.0)
            c.penalties["continuity"] = continuity_penalty
            c.penalties["character_safety"] = char_penalty

            final_score = max(0.0, min(1.0, pos_score - total_penalty))
            if not is_safe:
                final_score = 0.0

            c.score = float(final_score)

            # 8. Structured Semantic Classification & Recommendation
            if not is_safe:
                if any(k in rejection_reason for k in ("character", "face", "head")):
                    c.classification = BoundaryClassification.CONTINUOUS_CHARACTER
                elif "object" in rejection_reason:
                    c.classification = BoundaryClassification.OBJECT_CONTINUATION
                elif "action" in rejection_reason:
                    c.classification = BoundaryClassification.CONTINUOUS_ACTION
                else:
                    c.classification = BoundaryClassification.UNSAFE_CUT
                c.recommendation = BoundaryRecommendation.FORBID_CUT
                c.confidence = 0.95
                c.reason = rejection_reason or "unsafe_boundary"
            elif c.candidate_type == "speech_bubble_edge":
                c.classification = BoundaryClassification.EDGE_BUBBLE
                c.recommendation = BoundaryRecommendation.RECOMMEND_CUT
                c.confidence = max(0.90, c.score)
                c.reason = "speech_bubble_edge"
            elif c.candidate_type == "scene_transition" or c.visual_transition_score >= 0.60:
                c.classification = BoundaryClassification.SCENE_TRANSITION
                c.recommendation = (
                    BoundaryRecommendation.RECOMMEND_CUT if c.score >= self.boundary_score_threshold
                    else BoundaryRecommendation.OPTIONAL_CUT
                )
                c.confidence = max(0.80, c.score)
                c.reason = "scene_transition"
            elif c.candidate_type in ("panel_boundary", "composition_transition") or c.composition_score >= 0.45:
                c.classification = BoundaryClassification.COMPOSITION_TRANSITION
                c.recommendation = (
                    BoundaryRecommendation.RECOMMEND_CUT if c.score >= self.boundary_score_threshold
                    else BoundaryRecommendation.OPTIONAL_CUT
                )
                c.confidence = max(0.70, c.score)
                c.reason = "composition_transition"
            else:
                c.classification = BoundaryClassification.SAFE_CUT
                c.recommendation = (
                    BoundaryRecommendation.RECOMMEND_CUT if c.score >= self.boundary_score_threshold
                    else BoundaryRecommendation.OPTIONAL_CUT
                )
                c.confidence = c.score
                c.reason = "safe_visual_cut"

            c.evaluation = BoundaryEvaluation(
                classification=c.classification,
                recommendation=c.recommendation,
                confidence=c.confidence,
                reason=c.reason,
                details=dict(c.details)
            )

        return candidates
