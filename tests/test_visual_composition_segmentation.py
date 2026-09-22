# -*- coding: utf-8 -*-
"""
Unit Test Suite for AI Visual Composition Segmentation in Smart Paging.

Explicitly verifies all 9 core architectural requirements:
1. Character continuity: character spanning across boundary -> NO CUT
2. Character head/body: character across candidate cut -> NO CUT
3. Continuous action: continuous motion/action -> NO CUT
4. Multiple connected panels: action sequence -> ONE PAGE
5. Scene transition: clear scene shift -> CUT ALLOWED
6. Edge speech bubble: bubble above/below visual -> SEPARATED
7. Internal speech bubble: bubble inside visual -> PRESERVED WITH VISUAL
8. Important object: weapon/prop across boundary -> NO CUT
9. Boundary with no visible whitespace: valid transition without gutter -> CLEAN CUT
"""

import unittest
import numpy as np
import cv2

from renderer.visual_boundary_scanner import (
    VisualBoundaryScanner,
    BoundaryCandidate,
    BoundaryClassification,
    BoundaryRecommendation,
    BoundaryEvaluation,
)
from renderer.speech_bubble_analyzer import SpeechBubbleAnalyzer, BubbleRole, AnalyzedBubble
from renderer.semantic_safety import SemanticSafetyLayer, SemanticSubject
from renderer.boundary_scorer import BoundaryScorer
from renderer.global_page_optimizer import GlobalPageOptimizer
from renderer.smart_pagination import SmartPaginator, PaginationConfig, PageType, PageTag


class TestVisualCompositionSegmentation(unittest.TestCase):

    def setUp(self):
        self.width = 800
        self.bg_val = 255

    # -------------------------------------------------------------------------
    # Scenario 1: Character continuity: character spanning across boundary -> NO CUT
    # -------------------------------------------------------------------------
    def test_character_continuity_spanning_boundary_no_cut(self):
        """
        Verify that when a character spans across a candidate boundary,
        the boundary is classified as CONTINUOUS_CHARACTER and FORBID_CUT,
        yielding score=0.0 and is_safe=False.
        """
        safety = SemanticSafetyLayer()
        # Character spanning y=900 to y=1500
        safety.set_detected_regions(characters=[(100, 900, 400, 1500)])

        scorer = BoundaryScorer()
        cand = BoundaryCandidate(
            y=1200,
            candidate_type="panel_boundary",
            score=0.8,
            visual_continuity=0.7
        )

        scored = scorer.score_candidates([cand], safety_layer=safety)
        res = scored[0]

        self.assertFalse(res.is_safe)
        self.assertEqual(res.score, 0.0)
        self.assertEqual(res.classification, BoundaryClassification.CONTINUOUS_CHARACTER)
        self.assertEqual(res.recommendation, BoundaryRecommendation.FORBID_CUT)
        self.assertIn("character_overlap", res.reason)
        self.assertGreaterEqual(res.confidence, 0.90)

    # -------------------------------------------------------------------------
    # Scenario 2: Character head/body: character across candidate cut -> NO CUT
    # -------------------------------------------------------------------------
    def test_character_head_body_cut_protection(self):
        """
        Verify that a candidate cut through a character's head/face or upper body
        is strictly rejected with cuts_character_head / face_overlap and FORBID_CUT.
        """
        safety = SemanticSafetyLayer()
        # Character from y=1000 to y=1600; head span is top 35% (1000 to 1210)
        safety.set_detected_regions(
            characters=[(200, 1000, 500, 1600)],
            faces=[(250, 1010, 450, 1180)]
        )

        # Test cut through head/face
        is_safe_head, pen_head, rsn_head, det_head = safety.evaluate_cut_safety(1100)
        self.assertFalse(is_safe_head)
        self.assertIn(rsn_head, ["cuts_character_head", "face_overlap"])
        self.assertTrue(det_head["is_character_overlap"])

        # Test cut through body
        is_safe_body, pen_body, rsn_body, det_body = safety.evaluate_cut_safety(1400)
        self.assertFalse(is_safe_body)
        self.assertIn(rsn_body, ["character_overlap"])

        # Test cut outside character
        is_safe_out, _, _, _ = safety.evaluate_cut_safety(850)
        self.assertTrue(is_safe_out)

    # -------------------------------------------------------------------------
    # Scenario 3: Continuous action: continuous motion/action -> NO CUT
    # -------------------------------------------------------------------------
    def test_continuous_action_never_split(self):
        """
        Verify that an ongoing action sequence (speed lines, motion streaks, action spans)
        crossing a candidate cut is classified as CONTINUOUS_ACTION with FORBID_CUT.
        """
        safety = SemanticSafetyLayer()
        safety.set_action_spans([(800, 1600)])

        scorer = BoundaryScorer()
        cand = BoundaryCandidate(
            y=1200,
            candidate_type="panel_boundary",
            score=0.75,
            action_continuity=0.55
        )

        scored = scorer.score_candidates([cand], safety_layer=safety)
        res = scored[0]

        self.assertFalse(res.is_safe)
        self.assertEqual(res.score, 0.0)
        self.assertEqual(res.classification, BoundaryClassification.CONTINUOUS_ACTION)
        self.assertEqual(res.recommendation, BoundaryRecommendation.FORBID_CUT)
        self.assertIn(res.reason, ["cuts_ongoing_action", "continuous_action_sequence"])

    # -------------------------------------------------------------------------
    # Scenario 4: Multiple connected panels: action sequence -> ONE PAGE
    # -------------------------------------------------------------------------
    def test_multiple_connected_panels_form_one_visual_page(self):
        """
        Verify that connected panels in an action sequence with internal borders
        and micro-whitespaces remain unified as one visual page.
        """
        total_h = 3200
        canvas = np.full((total_h, self.width, 3), 255, dtype=np.uint8)

        # Panel 1: Combat action 400..1100
        canvas[400:1100, 60:740] = [30, 40, 210]
        for x in range(80, 720, 25):
            cv2.line(canvas, (x, 400), (x + 30, 1100), (255, 255, 255), 2)

        # Thin border at 1100
        cv2.line(canvas, (60, 1100), (740, 1100), (0, 0, 0), 4)

        # Panel 2: Continuation of combat 1130..1900
        canvas[1130:1900, 60:740] = [20, 30, 190]
        for x in range(80, 720, 25):
            cv2.line(canvas, (x + 30, 1130), (x, 1900), (255, 255, 255), 2)

        # Deep narrative gutter between 1900 and 2200 (300px white space)
        # Panel 3: Peaceful conversation scene 2200..3000
        canvas[2200:3000, 60:740] = [60, 180, 60]

        paginator = SmartPaginator(config=PaginationConfig(
            mode="ai_direct",
            tight_auto_crop=False,
            min_page_height=300,
            ideal_page_height=1000,
            max_page_height=2500
        ))

        cuts, scored_cands, _ = paginator.segment_canvas_v2(canvas, bg_val=255)

        # The internal border at y ~ 1100-1130 must NOT be selected as a cut!
        internal_cuts = [c for c in cuts if 1080 <= c <= 1150]
        self.assertEqual(len(internal_cuts), 0, f"Internal panel border in action sequence was cut: {internal_cuts}")

        # The deep narrative gutter between 1900 and 2200 SHOULD be cut
        gutter_cuts = [c for c in cuts if 1900 <= c <= 2200]
        self.assertGreater(len(gutter_cuts), 0, "Deep narrative gutter was not cut")

    # -------------------------------------------------------------------------
    # Scenario 5: Scene transition: clear scene shift -> CUT ALLOWED
    # -------------------------------------------------------------------------
    def test_scene_transition_cut_allowed(self):
        """
        Verify that a clear scene transition (significant background color shift,
        contrast change, or narrative break) is classified as SCENE_TRANSITION
        with RECOMMEND_CUT.
        """
        scorer = BoundaryScorer()
        safety = SemanticSafetyLayer()

        cand = BoundaryCandidate(
            y=1500,
            candidate_type="scene_transition",
            score=0.85,
            visual_transition_score=0.80,
            visual_continuity=0.15,
            action_continuity=0.0
        )

        scored = scorer.score_candidates([cand], safety_layer=safety)
        res = scored[0]

        self.assertTrue(res.is_safe)
        self.assertGreaterEqual(res.score, 0.40)
        self.assertEqual(res.classification, BoundaryClassification.SCENE_TRANSITION)
        self.assertEqual(res.recommendation, BoundaryRecommendation.RECOMMEND_CUT)

    # -------------------------------------------------------------------------
    # Scenario 6: Edge speech bubble: bubble above/below visual -> SEPARATED
    # -------------------------------------------------------------------------
    def test_edge_speech_bubble_separated(self):
        """
        Verify that speech bubbles situated above (Case A) or below (Case B)
        a visual composition are classified as EDGE_BUBBLE with RECOMMEND_CUT
        at the boundary between the bubble and the visual.
        """
        analyzer = SpeechBubbleAnalyzer()
        canvas = np.full((3500, 800, 3), 255, dtype=np.uint8)

        # Visual composition spanning 700 to 2200
        canvas[700:2200, 50:750] = [80, 120, 200]

        # Bubble A: situated ABOVE visual composition (500 to 620)
        bubble_a = (150, 500, 350, 620)
        # Bubble B: situated BELOW visual composition (2280 to 2400)
        bubble_b = (150, 2280, 350, 2400)

        classified = analyzer.classify_speech_bubbles(canvas, [bubble_a, bubble_b], bg_val=255)
        self.assertEqual(classified[0].role, BubbleRole.EDGE_TOP)
        self.assertEqual(classified[1].role, BubbleRole.EDGE_BOTTOM)

        cands = analyzer.generate_bubble_boundary_candidates(canvas, classified, bg_val=255)
        self.assertEqual(len(cands), 2)
        for c in cands:
            self.assertEqual(c.candidate_type, "speech_bubble_edge")
            self.assertTrue(c.hard)

        scorer = BoundaryScorer()
        safety = SemanticSafetyLayer()
        scored = scorer.score_candidates(cands, safety_layer=safety)

        for sc in scored:
            self.assertTrue(sc.is_safe)
            self.assertEqual(sc.classification, BoundaryClassification.EDGE_BUBBLE)
            self.assertEqual(sc.recommendation, BoundaryRecommendation.RECOMMEND_CUT)
            self.assertEqual(sc.score, 1.0)

    # -------------------------------------------------------------------------
    # Scenario 7: Internal speech bubble: bubble inside visual -> PRESERVED WITH VISUAL
    # -------------------------------------------------------------------------
    def test_internal_speech_bubble_preserved_with_visual(self):
        """
        Verify that speech bubbles inside a visual composition (Case C)
        are classified as INTERNAL, generate 0 cuts, and any candidate cut
        falling inside them is strictly rejected as INTERNAL_BUBBLE with FORBID_CUT.
        """
        analyzer = SpeechBubbleAnalyzer()
        canvas = np.full((3500, 800, 3), 255, dtype=np.uint8)

        # Visual composition spanning 700 to 2200
        canvas[700:2200, 50:750] = [80, 120, 200]

        # Bubble C: situated INSIDE visual composition (1200 to 1320)
        bubble_c = (200, 1200, 400, 1320)

        classified = analyzer.classify_speech_bubbles(canvas, [bubble_c], bg_val=255)
        self.assertEqual(classified[0].role, BubbleRole.INTERNAL)

        # Generates NO edge cuts
        cands = analyzer.generate_bubble_boundary_candidates(canvas, classified, bg_val=255)
        self.assertEqual(len(cands), 0)

        # If a candidate boundary happens to fall inside the internal bubble span:
        internal_spans = analyzer.get_internal_bubble_forbidden_spans(classified)
        self.assertTrue(any(s <= 1200 and e >= 1320 for s, e in internal_spans))

        scorer = BoundaryScorer()
        test_cand = BoundaryCandidate(y=1250, candidate_type="natural_visual_endpoint")
        scored = scorer.score_candidates([test_cand], internal_bubble_spans=internal_spans)
        res = scored[0]

        self.assertFalse(res.is_safe)
        self.assertEqual(res.score, 0.0)
        self.assertEqual(res.classification, BoundaryClassification.INTERNAL_BUBBLE)
        self.assertEqual(res.recommendation, BoundaryRecommendation.FORBID_CUT)
        self.assertEqual(res.reason, "inside_internal_speech_bubble")

    # -------------------------------------------------------------------------
    # Scenario 8: Important object: weapon/prop across boundary -> NO CUT
    # -------------------------------------------------------------------------
    def test_important_object_weapon_continuity_no_cut(self):
        """
        Verify that an important object (weapon, shield, prop, vehicle)
        spanning a candidate boundary is strictly protected from being cut
        with OBJECT_CONTINUATION and FORBID_CUT.
        """
        safety = SemanticSafetyLayer()
        # Sword/weapon spanning 950 to 1350
        safety.set_detected_regions(objects=[(300, 950, 350, 1350)])

        scorer = BoundaryScorer()
        cand = BoundaryCandidate(
            y=1150,
            candidate_type="panel_boundary",
            score=0.80
        )

        scored = scorer.score_candidates([cand], safety_layer=safety)
        res = scored[0]

        self.assertFalse(res.is_safe)
        self.assertEqual(res.score, 0.0)
        self.assertEqual(res.classification, BoundaryClassification.OBJECT_CONTINUATION)
        self.assertEqual(res.recommendation, BoundaryRecommendation.FORBID_CUT)
        self.assertEqual(res.reason, "object_overlap")
        self.assertTrue(res.details["is_object_overlap"])
        self.assertGreaterEqual(len(res.details["matched_subjects"]), 1)

    # -------------------------------------------------------------------------
    # Scenario 9: Boundary with no visible whitespace: valid transition without gutter -> CLEAN CUT
    # -------------------------------------------------------------------------
    def test_boundary_with_no_visible_whitespace_clean_cut(self):
        """
        Verify that a valid scene or composition transition with 0px gutter whitespace
        (e.g. sharp background color shift or abutting panels without white margin)
        is detected by VisualBoundaryScanner and evaluated as RECOMMEND_CUT.
        """
        # Canvas with zero gutter:
        # Scene 1: y=0 to 1200 is deep dark nighttime blue
        # Scene 2: y=1200 to 2400 is bright sunny daytime yellow/orange
        canvas = np.full((2400, 800, 3), 0, dtype=np.uint8)
        canvas[:1200, :] = [80, 20, 20]     # Dark blue (BGR)
        canvas[1200:, :] = [30, 210, 230]   # Bright orange/yellow (BGR)

        scanner = VisualBoundaryScanner(min_candidate_distance=30)
        cands = scanner.generate_candidates(canvas, bg_val=255, min_page_height=300)

        # Must detect candidate near y=1200
        zero_gutter_cands = [c for c in cands if abs(c.y - 1200) <= 20]
        self.assertGreater(len(zero_gutter_cands), 0, "No candidate detected at zero-gutter scene boundary")

        target_cand = zero_gutter_cands[0]
        scorer = BoundaryScorer()
        safety = SemanticSafetyLayer()
        scored = scorer.score_candidates([target_cand], safety_layer=safety)
        res = scored[0]

        self.assertTrue(res.is_safe)
        self.assertIn(res.classification, [BoundaryClassification.SCENE_TRANSITION, BoundaryClassification.COMPOSITION_TRANSITION, BoundaryClassification.SAFE_CUT])
        self.assertEqual(res.recommendation, BoundaryRecommendation.RECOMMEND_CUT)
        self.assertGreaterEqual(res.score, 0.40)


if __name__ == "__main__":
    unittest.main()
