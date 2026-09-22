# -*- coding: utf-8 -*-
"""
Tests for PureVisualImageEnhancer (Upscaling & Cinematic Color Grading)
"""
import unittest
import numpy as np
from pure_visual.image_enhancer import PureVisualImageEnhancer, EnhancerConfig


class TestPureVisualImageEnhancer(unittest.TestCase):
    def setUp(self):
        self.enhancer = PureVisualImageEnhancer()

    def test_upscale_and_coordinate_scaling(self):
        # 500x300 image with bounds (50, 40, 400, 200)
        img = np.random.randint(50, 200, (300, 500, 3), dtype=np.uint8)
        bounds = (50, 40, 400, 200)
        
        enhanced, scaled_bounds = self.enhancer.enhance_image(img, bounds)
        eh, ew = enhanced.shape[:2]
        
        # Target min width is at least min_target_width (1280)
        self.assertGreaterEqual(ew, 1280)
        
        # Scaled bounds must scale proportionally
        sx = ew / 500.0
        sy = eh / 300.0
        self.assertAlmostEqual(scaled_bounds[0], int(round(50 * sx)), delta=1)
        self.assertAlmostEqual(scaled_bounds[1], int(round(40 * sy)), delta=1)
        self.assertAlmostEqual(scaled_bounds[2], int(round(400 * sx)), delta=1)
        self.assertAlmostEqual(scaled_bounds[3], int(round(200 * sy)), delta=1)


    def test_color_grading_and_sharpening_output_shape(self):
        img = np.random.randint(20, 240, (600, 800, 3), dtype=np.uint8)
        enhanced, scaled_bounds = self.enhancer.enhance_image(img)
        self.assertEqual(enhanced.dtype, np.uint8)
        self.assertEqual(enhanced.ndim, 3)
        self.assertEqual(enhanced.shape[2], 3)


if __name__ == '__main__':
    unittest.main()
