import unittest
import numpy as np
import cv2
from renderer.smart_pagination import SmartPaginator, PaginationConfig, PageType, PageMetadata

class TestSmartVideoFilter(unittest.TestCase):
    def setUp(self):
        self.config = PaginationConfig(
            preferred_min_height=100,
            preferred_max_height=1000,
            hard_max_height=2000,
            min_page_height=30,
            target_height=400,
            isolate_visual_frames=True,
            tight_auto_crop=True
        )
        self.paginator = SmartPaginator(config=self.config)

    def test_isolate_visual_frames_default_is_true(self):
        cfg = PaginationConfig()
        self.assertTrue(cfg.isolate_visual_frames)
        self.assertTrue(cfg.tight_auto_crop)

    def test_is_video_frame_filtering(self):
        # 1. VISUAL should pass
        meta_visual = PageMetadata(
            page_index=1, y_start=0, y_end=200, height=200,
            page_type=PageType.VISUAL, content_score=0.8, boundary_confidence=0.9,
            visual_score=75, content_type=PageType.VISUAL, video_candidate=True
        )
        self.assertTrue(SmartPaginator.is_video_frame(meta_visual))

        # 2. MIXED should pass
        meta_mixed = PageMetadata(
            page_index=2, y_start=200, y_end=400, height=200,
            page_type=PageType.MIXED, content_score=0.7, boundary_confidence=0.8,
            visual_score=60, content_type=PageType.MIXED, video_candidate=True
        )
        self.assertTrue(SmartPaginator.is_video_frame(meta_mixed))

        # 3. EMPTY_GUTTER should fail
        meta_gutter = PageMetadata(
            page_index=3, y_start=400, y_end=480, height=80,
            page_type=PageType.EMPTY_GUTTER, content_score=0.1, boundary_confidence=0.5,
            visual_score=5, content_type=PageType.EMPTY_GUTTER, video_candidate=False
        )
        self.assertFalse(SmartPaginator.is_video_frame(meta_gutter))

        # 4. DIALOGUE / speech bubble should fail
        meta_dialogue = PageMetadata(
            page_index=4, y_start=480, y_end=580, height=100,
            page_type=PageType.TEXT_BUBBLE, content_score=0.3, boundary_confidence=0.6,
            visual_score=10, content_type=PageType.DIALOGUE, video_candidate=False
        )
        self.assertFalse(SmartPaginator.is_video_frame(meta_dialogue))

        # 5. CREDIT_ADS should fail
        meta_ads = PageMetadata(
            page_index=5, y_start=580, y_end=800, height=220,
            page_type=PageType.CONTENT, content_score=0.4, boundary_confidence=0.5,
            visual_score=5, content_type=PageType.CREDIT_ADS, video_candidate=False
        )
        self.assertFalse(SmartPaginator.is_video_frame(meta_ads))

    def test_find_tight_content_box_4_sides(self):
        canvas = np.ones((400, 400, 3), dtype=np.uint8) * 255
        cv2.rectangle(canvas, (80, 50), (320, 350), (50, 120, 200), -1)
        cv2.putText(canvas, "ARTWORK PANEL", (100, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

        y_top, y_bot, x_left, x_right = SmartPaginator.find_tight_content_box(canvas, pad=2, bg_val=255)

        self.assertAlmostEqual(y_top, 50, delta=10)
        self.assertAlmostEqual(y_bot, 350, delta=10)
        self.assertAlmostEqual(x_left, 80, delta=15)
        self.assertAlmostEqual(x_right, 320, delta=15)

    def test_paginate_canvas_for_video_filters_and_reindexes(self):
        h, w = 600, 400
        canvas = np.ones((h, w, 3), dtype=np.uint8) * 255

        # Panel 1
        cv2.rectangle(canvas, (20, 10), (380, 190), (40, 60, 220), -1)
        cv2.putText(canvas, "PANEL 1", (100, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        # Bubble
        cv2.ellipse(canvas, (200, 300), (80, 30), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "Hi!", (185, 305), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        # Panel 2
        cv2.rectangle(canvas, (20, 410), (380, 590), (220, 80, 40), -1)
        cv2.putText(canvas, "PANEL 2", (100, 500), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        video_pages = self.paginator.paginate_canvas_for_video(canvas, bg_val=255)

        self.assertEqual(len(video_pages), 2)
        p1_img, p1_meta = video_pages[0]
        p2_img, p2_meta = video_pages[1]

        self.assertEqual(p1_meta.page_index, 1)
        self.assertEqual(p2_meta.page_index, 2)
        self.assertIn(p1_meta.content_type, (PageType.VISUAL, PageType.MIXED))
        self.assertIn(p2_meta.content_type, (PageType.VISUAL, PageType.MIXED))

if __name__ == "__main__":
    unittest.main()
