# -*- coding: utf-8 -*-
"""
Unit Tests for Hybrid Deep Learning & Pure CV (HPP) Segmentation Pipeline.
Tests:
- HorizontalProjectionScanner (row variance, mean, gutter extraction, edge snapping)
- ComicVisionAI Manga109 model loading and class mappings (body, face, frame, text)
- Hybrid arbitration: protecting protruding characters from being cut
- Fine-tuning script environment check and template creation
- End-to-end SmartPaginator execution with HPP + ComicVisionAI
"""

import unittest
import numpy as np
import cv2
import os

from renderer.hpp_gutter_scanner import HorizontalProjectionScanner, GutterInterval
from renderer.comic_vision_ai import ComicVisionAI
from renderer.smart_pagination import SmartPaginator, PaginationConfig
from tools.finetune_comic_yolo import check_cuda_environment, create_dataset_template


class TestHybridSegmentation(unittest.TestCase):

    def setUp(self):
        # Create a synthetic canvas:
        # Height = 1000, Width = 400
        # 0 - 100: White gutter
        # 100 - 450: Panel 1 (random image content)
        # 450 - 550: White gutter (100px)
        # 550 - 900: Panel 2 (random image content)
        # 900 - 1000: White gutter
        np.random.seed(42)
        self.canvas = np.full((1000, 400, 3), 255, dtype=np.uint8)
        self.canvas[100:450, 20:380] = np.random.randint(20, 220, (350, 360, 3), dtype=np.uint8)
        # Add black borders around Panel 1
        self.canvas[98:100, 20:380] = 0
        self.canvas[450:452, 20:380] = 0

        self.canvas[550:900, 20:380] = np.random.randint(20, 220, (350, 360, 3), dtype=np.uint8)
        # Add black borders around Panel 2
        self.canvas[548:550, 20:380] = 0
        self.canvas[900:902, 20:380] = 0

    def test_hpp_scanner_gutter_detection(self):
        """Tests that HorizontalProjectionScanner accurately detects gutters."""
        scanner = HorizontalProjectionScanner(default_var_threshold=6.0, min_gutter_height=15)
        profile = scanner.compute_profile(self.canvas)

        self.assertEqual(profile.canvas_height, 1000)
        self.assertEqual(len(profile.row_variance), 1000)

        gutters = scanner.find_gutters(self.canvas, profile=profile)
        self.assertGreaterEqual(len(gutters), 2)

        # Center gutter is between ~452 and 548
        center_gutters = [g for g in gutters if 440 <= g.y_start and g.y_end <= 560]
        self.assertTrue(len(center_gutters) > 0)
        g = center_gutters[0]
        self.assertAlmostEqual(g.mean_luminance, 255.0, delta=5.0)
        self.assertTrue(450 <= g.cut_y <= 550)

    def test_hpp_snap_to_panel_edge(self):
        """Tests that snap_to_panel_edge snaps cuts to high-contrast borders."""
        scanner = HorizontalProjectionScanner()
        # Cut at 455 is close to border at 451
        snapped = scanner.snap_to_panel_edge(self.canvas, cut_y=455, search_radius=10)
        self.assertTrue(449 <= snapped <= 453)

    def test_comic_vision_ai_manga_model_loading(self):
        """Tests that ComicVisionAI properly loads manga109_yolo11m and reports correct metadata."""
        info = ComicVisionAI.get_device_info()
        self.assertIn("device", info)
        self.assertIn("vram_total_gb", info)

        model = ComicVisionAI.get_model()
        self.assertIsNotNone(model)
        classes = model.names
        # Check that Manga109 classes are recognized
        self.assertTrue(any(c in ("frame", "body", "text", "face") for c in classes.values()))

    def test_hybrid_arbitration_protects_protruding_character(self):
        """
        Tests that when a character protrudes across a gutter (e.g. y=420 to y=520),
        the arbitration layer protects the character and shifts or rejects the cut.
        """
        cfg = PaginationConfig(
            enable_hpp_fast_path=True,
            ideal_page_height=500,
            max_page_height=800,
            hard_max_height=900
        )
        paginator = SmartPaginator(config=cfg)

        # Draw a simulated protruding character across the gutter (y=430 to 520)
        mock_canvas = self.canvas.copy()
        mock_canvas[430:520, 150:250] = [30, 45, 180] # Colored character body/leg

        cuts, cands, dbg = paginator.segment_canvas_v2(mock_canvas, config=cfg)
        self.assertTrue(len(cuts) > 0)

        # Verify no cut point falls strictly inside the character body (435 to 515)
        for cut in cuts:
            self.assertFalse(
                435 < cut < 515,
                f"Cut {cut} dangerously cut through the protruding character body (430-520)!"
            )

    def test_finetune_environment_and_template(self):
        """Tests the finetuning environment checker and dataset template generator."""
        env = check_cuda_environment()
        self.assertIn("cuda_available", env)
        self.assertIn("device_name", env)
        self.assertGreaterEqual(env["recommended_batch"], 4)

        tmp_yaml = "test_comic_dataset_template.yaml"
        try:
            res_path = create_dataset_template(tmp_yaml)
            self.assertTrue(os.path.exists(res_path))
            with open(res_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("frame", content)
            self.assertIn("text", content)
            self.assertIn("body", content)
        finally:
            if os.path.exists(tmp_yaml):
                os.remove(tmp_yaml)


if __name__ == "__main__":
    unittest.main()
