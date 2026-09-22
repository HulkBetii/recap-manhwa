import os
import unittest
import numpy as np
import cv2


from pure_visual.config import DetectionConfig
from pure_visual.types import PureVisualRegion, BBox
from pure_visual.cleaner import VisualRegionCleaner


class TestPureVisualCleaner(unittest.TestCase):
    def test_micro_sfx_filtered(self):
        config = DetectionConfig(min_clean_height=380)
        cleaner = VisualRegionCleaner(config)
        
        # Create small SFX dummy frame (H=200, W=600)
        dummy_img = np.full((200, 600, 3), 240, dtype=np.uint8)
        # Add some high-contrast text lines
        cv2.putText(dummy_img, "SWOOSH", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        
        region = PureVisualRegion(
            region_id=8,
            original_bbox=BBox(0, 1000, 600, 1200),
            pure_visual_bbox=BBox(0, 0, 600, 200),
            face_count=0,
            body_count=0,
            details={"visual_complexity": {"edge_density": 0.10, "color_variance": 50.0}}
        )
        
        filtered, dropped = cleaner.clean_regions([(dummy_img, region)])
        self.assertEqual(len(filtered), 0)
        self.assertEqual(len(dropped), 1)
        self.assertIn(dropped[0]["reason"], ["DROP_MICRO_SFX_FRAGMENT", "DROP_LOW_VISUAL_DENSITY", "DROP_ISOLATED_SPEECH_BUBBLE"])

    def test_character_frame_preserved_even_if_short(self):
        config = DetectionConfig(min_clean_height=380)
        cleaner = VisualRegionCleaner(config)
        
        # Small frame with face
        dummy_img = np.full((250, 600, 3), 200, dtype=np.uint8)
        cv2.circle(dummy_img, (300, 125), 50, (50, 50, 50), -1)
        
        region = PureVisualRegion(
            region_id=1,
            original_bbox=BBox(0, 1000, 600, 1250),
            pure_visual_bbox=BBox(0, 0, 600, 250),
            face_count=1,
            body_count=0,
            details={"visual_complexity": {"edge_density": 0.08, "color_variance": 60.0}}
        )
        
        filtered, dropped = cleaner.clean_regions([(dummy_img, region)])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(len(dropped), 0)

    def test_blank_dark_gutter_filtered(self):
        config = DetectionConfig(min_laplacian_var=250.0)
        cleaner = VisualRegionCleaner(config)
        
        # Pure dark blank frame (H=1400, W=900)
        blank_dark = np.zeros((1400, 900, 3), dtype=np.uint8)
        
        region = PureVisualRegion(
            region_id=38,
            original_bbox=BBox(0, 50000, 900, 51400),
            pure_visual_bbox=BBox(0, 0, 900, 1400),
            face_count=0,
            body_count=0,
            details={"visual_complexity": {"edge_density": 0.005, "color_variance": 5.0}}
        )
        
        filtered, dropped = cleaner.clean_regions([(blank_dark, region)])
        self.assertEqual(len(filtered), 0)
        self.assertEqual(len(dropped), 1)
        self.assertIn(dropped[0]["reason"], ["DROP_BLANK_OR_LOW_CONTRAST_GUTTER", "DROP_DARK_VOID_OR_FLAT_SLICE", "DROP_LOW_VISUAL_DENSITY"])

    def test_floating_title_logo_credit_filtered(self):
        config = DetectionConfig()
        cleaner = VisualRegionCleaner(config)

        # Title logo on dark background (H=500, W=800)
        title_img = np.zeros((500, 800, 3), dtype=np.uint8)
        # Red splash in center
        cv2.circle(title_img, (400, 250), 120, (0, 0, 200), -1)
        # Calligraphy title in center
        cv2.putText(title_img, "MANHWA TITLE", (200, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)

        region = PureVisualRegion(
            region_id=28,
            original_bbox=BBox(0, 20000, 800, 20500),
            pure_visual_bbox=BBox(0, 0, 800, 500),
            face_count=0,
            body_count=0,
            details={"visual_complexity": {"edge_density": 0.08, "color_variance": 60.0}}
        )

        filtered, dropped = cleaner.clean_regions([(title_img, region)])
        self.assertEqual(len(filtered), 0)
        self.assertEqual(len(dropped), 1)
        self.assertIn(dropped[0]["reason"], ["DROP_FLOATING_TITLE_LOGO_OR_CREDIT", "DROP_LOW_VISUAL_DENSITY", "DROP_ISOLATED_SPEECH_BUBBLE", "DROP_NARRATION_TEXT_CARD"])


