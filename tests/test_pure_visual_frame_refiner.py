# -*- coding: utf-8 -*-
"""
Tests for PureVisualFrameRefiner (Pre-Render Video Frame Cleaner)
"""
import unittest
import numpy as np
import cv2
from pure_visual.frame_refiner import PureVisualFrameRefiner, FrameRefinerConfig


class TestPureVisualFrameRefiner(unittest.TestCase):
    def setUp(self):
        self.refiner = PureVisualFrameRefiner()

    def test_zero_variance_gutter_trim(self):
        img = np.ones((400, 400, 3), dtype=np.uint8) * 255
        img[50:350, 40:360] = np.random.randint(50, 200, (300, 320, 3), dtype=np.uint8)
        
        x, y, w, h = self.refiner.refine_frame(img)
        self.assertGreaterEqual(y, 50)
        self.assertLessEqual(y + h, 350)
        self.assertGreaterEqual(x, 40)
        self.assertLessEqual(x + w, 360)

    def test_panel_border_detection(self):
        img = np.zeros((500, 500, 3), dtype=np.uint8)
        cv2.rectangle(img, (50, 60), (450, 440), (255, 255, 255), 3)
        img[63:437, 53:447] = np.random.randint(40, 220, (374, 394, 3), dtype=np.uint8)
        
        x, y, w, h = self.refiner.refine_frame(img)
        self.assertGreaterEqual(x, 45)
        self.assertGreaterEqual(y, 55)
        self.assertLessEqual(x + w, 455)
        self.assertLessEqual(y + h, 445)


    def test_top_20_percent_box_text_and_divider_crop(self):
        # 600x400 image: top 20% (0..120) has divider line and a narration box with text at y=30
        img = np.ones((600, 400, 3), dtype=np.uint8) * 240
        # Top black divider line at y=0..2
        img[0:3, :] = 10
        # Narration box in top margin (y=0..60, x=30..200)
        cv2.rectangle(img, (30, 0), (200, 60), (255, 255, 255), -1)
        cv2.rectangle(img, (30, 0), (200, 60), (40, 40, 50), 2)
        cv2.putText(img, "NARRATION TEXT", (35, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (10, 10, 10), 1)
        # Visual scene in center (y=150..550)
        cv2.circle(img, (200, 350), 80, (50, 120, 200), -1)

        x, y, w, h = self.refiner.refine_frame(img)
        # Must crop past the top narration text boundary (y >= 30)
        self.assertGreaterEqual(y, 30)
        self.assertLessEqual(y + h, 600)

    def test_bottom_20_percent_box_text_crop(self):
        # 600x400 image: bottom 20% (480..600) has dialogue box with text at y=580
        img = np.ones((600, 400, 3), dtype=np.uint8) * 240
        # Visual scene in top/center (y=50..450)
        cv2.circle(img, (200, 250), 80, (50, 120, 200), -1)
        # Narration box in bottom margin (y=540..600)
        cv2.rectangle(img, (50, 540), (350, 600), (255, 255, 255), -1)
        cv2.rectangle(img, (50, 540), (350, 600), (40, 40, 50), 2)
        cv2.putText(img, "BOTTOM DIALOGUE", (60, 580), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (10, 10, 10), 1)

        x, y, w, h = self.refiner.refine_frame(img)
        # Must crop before the bottom dialogue text boundary (y + h <= 575)
        self.assertLessEqual(y + h, 575)

    def test_internal_bubble_beyond_20_percent_not_cropped(self):
        # 1000x500 image: Top panel at y=0..400 has character artwork and internal dialogue
        img = np.ones((1000, 500, 3), dtype=np.uint8) * 200
        # Character panel in top region with artwork
        cv2.circle(img, (250, 200), 120, (140, 100, 80), -1)
        # Bubble inside panel at y=150
        cv2.ellipse(img, (250, 150), (80, 50), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(img, (250, 150), (80, 50), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(img, "INTERNAL BUBBLE", (180, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)

        x, y, w, h = self.refiner.refine_frame(img)
        # y1 must NOT jump past 20% (y <= 200) to ensure the top panel is preserved
        self.assertLessEqual(y, 200)

    def test_top_speech_bubble_overhang_crop(self):
        # 600x400 image: Top black panel line at y=0, text hanging down to y=65
        img = np.ones((600, 400, 3), dtype=np.uint8) * 180
        # Top black border line
        img[0:3, :] = 0
        # Speech bubble in top region with text up to y=65
        cv2.rectangle(img, (50, 0), (350, 180), (255, 255, 255), -1)
        cv2.rectangle(img, (50, 0), (350, 180), (0, 0, 0), 2)
        cv2.putText(img, "TOP OVERHANG SPEECH", (60, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        cv2.putText(img, "DIALOGUE BUBBLE", (60, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        # Visual scene in lower half (y=220..580)
        cv2.circle(img, (200, 400), 80, (50, 120, 200), -1)

        x, y, w, h = self.refiner.refine_frame(img)
        # Must crop down past the bottom of the text (y >= 50)
        self.assertGreaterEqual(y, 50)
        self.assertLessEqual(y + h, 600)

    def test_multiline_tall_speech_bubble_overhang_crop(self):
        # 1080x1459 image: large 6-line speech bubble hanging from y=0 to y=350
        img = np.ones((1080, 1459, 3), dtype=np.uint8) * 180
        cv2.rectangle(img, (200, 0), (900, 350), (255, 255, 255), -1)
        cv2.rectangle(img, (200, 0), (900, 350), (0, 0, 0), 4)
        for i, line in enumerate(['YOUR CONTRIBUTION IN', 'CREATING THE ELIXIR OF', 'LIFE, A DRAUGHT THAT', 'GRANTS FREEDOM FROM', 'AGE AND DEATH HAS BEEN', 'OFFICIALLY RECOGNIZED.']):
            cv2.putText(img, line, (240, 60 + i * 45), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
        cv2.circle(img, (700, 700), 200, (50, 100, 200), -1)

        x, y, w, h = self.refiner.refine_frame(img)
        # Bounded by 20% margin envelope (y <= 1080 * 0.20 = 216) to avoid cutting into artwork
        self.assertGreaterEqual(y, 150)
        self.assertLessEqual(y, 220)
        self.assertLessEqual(y + h, 1080)

    def test_complex_artwork_hair_and_textures_not_cropped(self):
        # 1600x900 image with dark hair and fine line textures on top, no speech bubble
        img = np.ones((1600, 900, 3), dtype=np.uint8) * 120
        # Dark hair strokes and shading in top region (y=0..600)
        cv2.ellipse(img, (450, 300), (350, 250), 0, 0, 360, (20, 20, 25), -1)
        for i in range(20):
            cv2.line(img, (200 + i * 25, 50), (250 + i * 20, 400), (60, 60, 70), 2)
            cv2.line(img, (150 + i * 30, 200), (300 + i * 15, 500), (10, 10, 15), 3)

        x, y, w, h = self.refiner.refine_frame(img)
        # Artwork with character hair should NOT be falsely cropped as text overhang (y <= 50)
        self.assertLessEqual(y, 50)
        self.assertGreaterEqual(h, 1500)

    def test_safety_guard_fallback(self):
        img = np.ones((10, 10, 3), dtype=np.uint8) * 100
        x, y, w, h = self.refiner.refine_frame(img)
        self.assertEqual((x, y, w, h), (0, 0, 10, 10))


if __name__ == '__main__':
    unittest.main()
