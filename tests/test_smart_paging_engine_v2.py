# -*- coding: utf-8 -*-
"""
Comprehensive Unit Test Suite for Upgraded Smart Paging Engine V2.

Verifies:
1. 1D Visual Boundary Scanner (luminance, color transition, margins, edge density, continuity).
2. Speech Bubble Spatial Rules:
   - Case A: Speech bubble ABOVE visual -> HARD cut
   - Case B: Speech bubble BELOW visual -> HARD cut
   - Case C: Speech bubble INSIDE visual -> IGNORED / suppressed from splitting
3. Semantic Safety Layer (YOLO character/head/object protection).
4. Boundary Scorer (multi-signal weighted scoring & continuity penalties).
5. Global Page Optimizer (Dynamic Programming over global canvas).
6. Smart Paging Debugger (5-color overlay & decision logging).
7. End-to-End integration into SmartPaginator and original resolution cropping.
"""

import unittest
import numpy as np
import cv2
import os

from renderer.visual_boundary_scanner import VisualBoundaryScanner, BoundaryCandidate
from renderer.speech_bubble_analyzer import SpeechBubbleAnalyzer, BubbleRole, AnalyzedBubble
from renderer.semantic_safety import SemanticSafetyLayer, SemanticSubject
from renderer.boundary_scorer import BoundaryScorer
from renderer.global_page_optimizer import GlobalPageOptimizer
from renderer.smart_paging_debug import SmartPagingDebugger
from renderer.smart_pagination import SmartPaginator, PaginationConfig, PageType, PageTag


class TestVisualBoundaryScanner(unittest.TestCase):
    def setUp(self):
        self.canvas_h = 4000
        self.canvas_w = 800
        self.canvas = np.full((self.canvas_h, self.canvas_w, 3), 255, dtype=np.uint8)

        # Panel 1: 300 to 1200 (Blue scene)
        self.canvas[300:1200, 50:750] = [200, 100, 50]
        cv2.rectangle(self.canvas, (100, 400), (700, 1100), (180, 80, 40), -1)

        # Gutter 1: 1200 to 1500 (White gutter)

        # Panel 2: 1500 to 2500 (Red combat scene with continuous motion lines)
        self.canvas[1500:2500, 50:750] = [30, 40, 220]
        for offset in range(0, 700, 40):
            cv2.line(self.canvas, (50 + offset, 1500), (100 + offset, 2500), (255, 255, 255), 2)

        # Panel 3: 2700 to 3700 (Green forest scene)
        self.canvas[2700:3700, 50:750] = [40, 180, 50]

        self.scanner = VisualBoundaryScanner(scan_width=200, window_size=60)

    def test_scan_visual_signals_dimensions(self):
        signals = self.scanner.scan_visual_signals(self.canvas, bg_val=255)
        self.assertIn("visual_continuity", signals)
        self.assertIn("color_transition", signals)
        self.assertIn("edge_density", signals)
        self.assertIn("content_width", signals)
        self.assertIn("gutter_strength", signals)

        self.assertEqual(len(signals["visual_continuity"]), self.canvas_h)
        self.assertEqual(len(signals["color_transition"]), self.canvas_h)
        self.assertEqual(len(signals["gutter_strength"]), self.canvas_h)

    def test_gutter_detection(self):
        signals = self.scanner.scan_visual_signals(self.canvas, bg_val=255)
        gutter_str = signals["gutter_strength"]
        # The gutter between 1200 and 1500 should have high gutter strength
        mid_gutter_y = 1350
        self.assertGreater(gutter_str[mid_gutter_y], 0.6)
        # Inside panel 2 (red scene) gutter strength should be near zero
        self.assertLess(gutter_str[1800], 0.2)

    def test_generate_candidates_detects_natural_cut_points(self):
        cands = self.scanner.generate_candidates(self.canvas, bg_val=255)
        self.assertGreater(len(cands), 0)
        # Verify a candidate was detected near the 1200-1500 gutter
        gutter_cand = [c for c in cands if 1200 <= c.y <= 1500]
        self.assertTrue(len(gutter_cand) > 0)

        # Check candidate metadata structure
        cand = cands[0]
        self.assertIsInstance(cand.y, int)
        self.assertIsInstance(cand.score, float)
        self.assertIn(cand.candidate_type, [
            "panel_boundary", "natural_visual_endpoint",
            "scene_transition", "composition_transition"
        ])


class TestSpeechBubbleRules(unittest.TestCase):
    def setUp(self):
        self.h = 3000
        self.w = 800
        self.canvas = np.full((self.h, self.w, 3), 255, dtype=np.uint8)

        # Artwork panel from 600 to 2000
        self.canvas[600:2000, 60:740] = [100, 150, 220]
        cv2.circle(self.canvas, (400, 1200), 180, (40, 40, 180), -1)

        self.analyzer = SpeechBubbleAnalyzer()

    def test_case_a_speech_bubble_above_visual(self):
        # Case A: Bubble above the artwork (e.g. y=450 to 550)
        bubble_a = (100, 450, 300, 550)
        bubbles = [bubble_a]

        classified = self.analyzer.classify_speech_bubbles(self.canvas, bubbles, bg_val=255)
        self.assertEqual(len(classified), 1)
        self.assertEqual(classified[0].role, BubbleRole.EDGE_TOP)

        # Generates HARD boundary cut immediately below the bubble
        cands = self.analyzer.generate_bubble_boundary_candidates(self.canvas, classified, bg_val=255)
        self.assertEqual(len(cands), 1)
        self.assertTrue(cands[0].hard)
        self.assertEqual(cands[0].candidate_type, "speech_bubble_edge")
        self.assertEqual(cands[0].score, 1.0)
        self.assertGreaterEqual(cands[0].y, 550)
        self.assertLessEqual(cands[0].y, 600)

    def test_case_b_speech_bubble_below_visual(self):
        # Case B: Bubble below the artwork (e.g. y=2050 to 2150)
        bubble_b = (100, 2050, 300, 2150)
        bubbles = [bubble_b]

        classified = self.analyzer.classify_speech_bubbles(self.canvas, bubbles, bg_val=255)
        self.assertEqual(len(classified), 1)
        self.assertEqual(classified[0].role, BubbleRole.EDGE_BOTTOM)

        # Generates HARD boundary cut immediately above the bubble
        cands = self.analyzer.generate_bubble_boundary_candidates(self.canvas, classified, bg_val=255)
        self.assertEqual(len(cands), 1)
        self.assertTrue(cands[0].hard)
        self.assertEqual(cands[0].candidate_type, "speech_bubble_edge")
        self.assertEqual(cands[0].score, 1.0)
        self.assertLessEqual(cands[0].y, 2050)
        self.assertGreaterEqual(cands[0].y, 2000)

    def test_case_c_speech_bubble_inside_visual(self):
        # Case C: Bubble inside the artwork (e.g. y=900 to 1000)
        bubble_c = (150, 900, 350, 1000)
        bubbles = [bubble_c]

        classified = self.analyzer.classify_speech_bubbles(self.canvas, bubbles, bg_val=255)
        self.assertEqual(len(classified), 1)
        self.assertEqual(classified[0].role, BubbleRole.INTERNAL)

        # Case C must NOT generate any candidate cut!
        cands = self.analyzer.generate_bubble_boundary_candidates(self.canvas, classified, bg_val=255)
        self.assertEqual(len(cands), 0)

        # Internal bubble must produce forbidden spans to prevent accidental cuts through it
        spans = self.analyzer.get_internal_bubble_forbidden_spans(classified)
        self.assertEqual(len(spans), 1)
        self.assertLessEqual(spans[0][0], 900)
        self.assertGreaterEqual(spans[0][1], 1000)


class TestSemanticSafetyLayer(unittest.TestCase):
    def setUp(self):
        self.safety = SemanticSafetyLayer(character_overlap_penalty=6.0, object_overlap_penalty=3.0)
        # Character from y=800 to 1800 (head at top ~35%: 800 to 1150)
        self.char_box = (150, 800, 650, 1800)
        self.safety.set_detected_regions(characters=[self.char_box])

    def test_safe_region_outside_character(self):
        is_safe, penalty, reason, _ = self.safety.evaluate_cut_safety(500)
        self.assertTrue(is_safe)
        self.assertEqual(penalty, 0.0)
        self.assertEqual(reason, "")

    def test_cuts_character_head_strictly_rejected(self):
        # Cut at y=950 is inside the character's head
        is_safe, penalty, reason, _ = self.safety.evaluate_cut_safety(950)
        self.assertFalse(is_safe)
        self.assertGreaterEqual(penalty, 12.0)
        self.assertEqual(reason, "cuts_character_head")

    def test_cuts_character_body_rejected(self):
        # Cut at y=1400 is inside the character's body
        is_safe, penalty, reason, _ = self.safety.evaluate_cut_safety(1400)
        self.assertFalse(is_safe)
        self.assertGreaterEqual(penalty, 6.0)
        self.assertEqual(reason, "character_overlap")


class TestBoundaryScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = BoundaryScorer()
        self.safety = SemanticSafetyLayer()
        self.safety.set_detected_regions(characters=[(100, 800, 600, 1600)])

    def test_scene_transition_with_low_continuity_scores_high(self):
        cand = BoundaryCandidate(
            y=400,
            candidate_type="scene_transition",
            visual_transition_score=0.9,
            visual_continuity=0.15  # Low continuity => clear scene break!
        )
        scored = self.scorer.score_candidates([cand], safety_layer=self.safety)
        self.assertTrue(scored[0].is_safe)
        self.assertGreater(scored[0].score, 0.85)

    def test_action_continuity_penalty_applied(self):
        cand = BoundaryCandidate(
            y=500,
            candidate_type="panel_boundary",
            panel_boundary_score=0.6,
            visual_continuity=0.95  # High continuity => ongoing continuous action!
        )
        scored = self.scorer.score_candidates([cand], safety_layer=self.safety)
        self.assertTrue(scored[0].is_safe)
        # High continuity should penalize the score
        self.assertLess(scored[0].score, 0.5)

    def test_character_overlap_is_marked_unsafe_and_score_zero(self):
        cand = BoundaryCandidate(
            y=1200,
            candidate_type="scene_transition",
            visual_transition_score=0.9
        )
        scored = self.scorer.score_candidates([cand], safety_layer=self.safety)
        self.assertFalse(scored[0].is_safe)
        self.assertEqual(scored[0].score, 0.0)
        self.assertEqual(scored[0].rejection_reason, "character_overlap")


class TestGlobalPageOptimizer(unittest.TestCase):
    def setUp(self):
        self.optimizer = GlobalPageOptimizer(
            min_page_height=400,
            ideal_page_height=1000,
            max_page_height=2200
        )

    def test_avoids_overly_short_pages(self):
        # Candidates spaced every 100px
        candidates = [
            BoundaryCandidate(y=y, candidate_type="panel_boundary", score=0.8)
            for y in range(100, 3000, 100)
        ]
        cuts, pages = self.optimizer.optimize_pages(3000, candidates)
        self.assertTrue(len(cuts) > 0)
        # No normal page should be shorter than min_page_height
        for s, e in pages:
            self.assertGreaterEqual(e - s, 400)

    def test_never_selects_unsafe_candidates(self):
        candidates = [
            BoundaryCandidate(y=500, candidate_type="panel_boundary", score=0.85, is_safe=True),
            # Unsafe candidate with high score
            BoundaryCandidate(y=1000, candidate_type="panel_boundary", score=0.99, is_safe=False, rejection_reason="character_overlap"),
            BoundaryCandidate(y=1500, candidate_type="panel_boundary", score=0.85, is_safe=True)
        ]
        cuts, pages = self.optimizer.optimize_pages(2000, candidates)
        self.assertNotIn(1000, cuts)

    def test_honors_hard_speech_bubble_cuts(self):
        candidates = [
            # Hard edge speech bubble cut at y=300
            BoundaryCandidate(y=300, candidate_type="speech_bubble_edge", score=1.0, hard=True, is_safe=True),
            BoundaryCandidate(y=1400, candidate_type="scene_transition", score=0.90, is_safe=True)
        ]
        cuts, pages = self.optimizer.optimize_pages(2500, candidates)
        self.assertIn(300, cuts)


class TestSmartPagingDebugger(unittest.TestCase):
    def test_decision_log_format(self):
        cands = [
            BoundaryCandidate(
                y=3820, candidate_type="scene_transition", score=0.91,
                visual_continuity=0.18, is_safe=True
            ),
            BoundaryCandidate(
                y=4210, candidate_type="panel_boundary", score=0.84,
                visual_continuity=0.50, is_safe=False, rejection_reason="character_overlap"
            )
        ]
        res = SmartPagingDebugger.generate_decision_log(cands, selected_cuts=[3820])
        self.assertEqual(res["total_candidates"], 2)
        self.assertEqual(res["selected_count"], 1)
        self.assertEqual(res["rejected_count"], 1)

        # Check exact string format required by specification
        log_text = res["log_text"]
        self.assertIn("Y=3820", log_text)
        self.assertIn("type=scene_transition", log_text)
        self.assertIn("decision=SELECTED", log_text)
        self.assertIn("Y=4210", log_text)
        self.assertIn("decision=REJECTED", log_text)
        self.assertIn("reason=character_overlap", log_text)

    def test_overlay_image_dimensions(self):
        canvas = np.full((1500, 600, 3), 255, dtype=np.uint8)
        cands = [
            BoundaryCandidate(y=400, candidate_type="scene_transition", score=0.9),
            BoundaryCandidate(y=800, candidate_type="panel_boundary", score=0.0, is_safe=False, rejection_reason="character_overlap")
        ]
        overlay = SmartPagingDebugger.generate_debug_overlay(
            canvas_bgr=canvas,
            candidates=cands,
            selected_cuts=[400],
            character_boxes=[(100, 750, 500, 1000)],
            speech_bubbles=[{"bbox": (100, 200, 300, 300), "role": "EDGE_TOP"}]
        )
        self.assertEqual(len(overlay.shape), 3)
        self.assertGreater(overlay.shape[0], 0)
        self.assertGreater(overlay.shape[1], 0)


class TestSmartPaginatorEndToEnd(unittest.TestCase):
    def setUp(self):
        self.h = 3500
        self.w = 700
        self.canvas = np.full((self.h, self.w, 3), 255, dtype=np.uint8)

        # Panel 1: 200 to 1100
        self.canvas[200:1100, 50:650] = [180, 120, 40]
        # Speech bubble above panel 1 (Case A)
        self.canvas[60:160, 200:450] = [250, 250, 250]
        cv2.rectangle(self.canvas, (200, 60), (450, 160), (0, 0, 0), 2)

        # Panel 2: 1400 to 2400
        self.canvas[1400:2400, 50:650] = [40, 150, 200]

        # Panel 3: 2600 to 3300
        self.canvas[2600:3300, 50:650] = [50, 180, 80]

        self.paginator = SmartPaginator(config=PaginationConfig(
            mode="ai_direct",
            tight_auto_crop=False,
            min_page_height=300
        ))

    def test_end_to_end_slicing_original_resolution(self):
        results = self.paginator.paginate_canvas(self.canvas, ai_direct=True)
        self.assertGreater(len(results), 1)

        # Verify all crops retain exact width of the original canvas
        total_height_sliced = 0
        for crop_img, meta in results:
            self.assertEqual(crop_img.shape[1], self.w)
            self.assertGreater(crop_img.shape[0], 0)
            self.assertIn(meta.page_tag, PageTag.ALL_TAGS)
            self.assertIsInstance(meta.visual_score, int)
            self.assertGreaterEqual(meta.visual_score, 0)
            self.assertLessEqual(meta.visual_score, 100)
            total_height_sliced += (meta.y_end - meta.y_start)

        # Verify full height is spanned by pages
        self.assertEqual(results[0][1].y_start, 0)
        self.assertEqual(results[-1][1].y_end, self.h)


if __name__ == "__main__":
    unittest.main()
