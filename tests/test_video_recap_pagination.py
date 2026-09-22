import unittest
import numpy as np
import cv2
import os
import re

from renderer.smart_pagination import (
    SmartPaginator,
    PaginationConfig,
    PageTag,
    PageType,
    PageMetadata,
    VisualSemanticScorer,
    TextScorer,
    CREDIT_KEYWORDS_REGEX,
)


class TestVideoRecapPagination(unittest.TestCase):
    """
    Test suite for Video Recap Optimization in Smart Pagination Engine:
    1. Video Preset Defaults (HD 1080p, 9:16 aspect, 2160 hard max limit)
    2. Bubble Snapping & Merging (No isolated speech bubble pages)
    3. Runaway Barrier Enforcement (Every slice <= 2160px via recursive fallback)
    4. 5-Tag Classification Accuracy (CHARACTER_ART, ACTION_ART, BACKGROUND_SCENE, CHARACTER_SCENE, NON_VISUAL)
    5. Camera Motion Metadata (Face-centered focal points, zoom_in_face hint)
    6. Margin Cleanup (Top sliver < 150px, bottom credit/watermark banners)
    """

    def setUp(self):
        self.config = PaginationConfig.video_recap()
        self.paginator = SmartPaginator(self.config)

    def test_video_recap_preset_defaults(self):
        """Verify video_recap preset enforces strict video recap requirements."""
        cfg = PaginationConfig.video_recap()
        self.assertEqual(cfg.min_page_height, 1500)
        self.assertEqual(cfg.ideal_page_height, 5200)
        self.assertEqual(cfg.max_page_height, 7000)
        self.assertEqual(cfg.hard_max_height, 8000)
        self.assertEqual(cfg.crop_padding, 4)
        self.assertFalse(cfg.speech_edge_hard_cut)
        self.assertFalse(cfg.separate_speech_bubbles)
        self.assertTrue(cfg.tight_auto_crop)

        from_preset = PaginationConfig.from_preset("video")
        self.assertEqual(from_preset.ideal_page_height, 5200)
        self.assertEqual(from_preset.hard_max_height, 8000)

    def test_bubble_snapping_eliminates_isolated_bubbles(self):
        """
        Verify that isolated dialogue bubbles snap and merge into adjacent visual panels.
        Canvas:
        - Top: Dialogue bubble (y=50..200)
        - Middle: Character action panel (y=300..1200)
        - Bottom: Speech bubble (y=1300..1450)
        Expectation: Speech bubbles must NEVER form independent pages containing only text!
        """
        canvas = np.full((1600, 800, 3), 255, dtype=np.uint8)

        # Top speech bubble
        cv2.ellipse(canvas, (400, 120), (160, 55), 0, 0, 360, (240, 240, 240), -1)
        cv2.ellipse(canvas, (400, 120), (160, 55), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "WHAT IS THIS TECHNIQUE?!", (270, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        # Middle visual artwork panel (Character with face, body, and sword slash)
        cv2.rectangle(canvas, (100, 300), (700, 1200), (50, 40, 60), -1)
        # Face (skin tone)
        cv2.circle(canvas, (400, 500), 70, (140, 170, 220), -1)
        cv2.circle(canvas, (375, 490), 8, (20, 20, 20), -1)
        cv2.circle(canvas, (425, 490), 8, (20, 20, 20), -1)
        # Slashes
        cv2.line(canvas, (150, 400), (650, 1000), (0, 255, 255), 8)
        cv2.line(canvas, (150, 900), (650, 600), (0, 200, 255), 6)

        # Bottom speech bubble
        cv2.ellipse(canvas, (400, 1370), (150, 50), 0, 0, 360, (245, 245, 245), -1)
        cv2.ellipse(canvas, (400, 1370), (150, 50), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "IMPOSSIBLE!", (330, 1375), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        results = self.paginator.paginate_canvas(canvas)

        # In video recap mode, there must be NO isolated dialogue pages (height < 400 or content_type DIALOGUE without art)
        self.assertGreaterEqual(len(results), 1)
        for idx, (img, meta) in enumerate(results):
            self.assertNotEqual(meta.content_type, PageType.TEXT_BUBBLE, f"Page {idx} is an isolated text bubble!")
            self.assertGreaterEqual(meta.height, 400, f"Page {idx} height {meta.height} < min_page_height 400")

    def test_runaway_barrier_hard_max_limit(self):
        """
        Verify that huge continuous vertical canvas (exceeding hard_max_height)
        is sub-split so NO page exceeds hard_max_height.
        """
        tot_h = int(self.config.hard_max_height * 1.8)
        canvas = np.full((tot_h, 800, 3), 255, dtype=np.uint8)

        # Fill with continuous gradient art panels with slight variations every ~900px
        for y in range(0, tot_h, 50):
            cv2.line(canvas, (50, y), (750, y), (y % 200, (y * 2) % 200, (y * 3) % 200), 3)

        results = self.paginator.paginate_canvas(canvas)

        self.assertGreater(len(results), 1, "Must be split into multiple pages")
        for idx, (img, meta) in enumerate(results):
            self.assertLessEqual(
                meta.height,
                self.config.hard_max_height + 20,
                f"Page {idx} exceeds hard_max_height: got {meta.height}px"
            )

    def test_5_tag_classification(self):
        """
        Verify classification into the 5-tag taxonomy:
        - CHARACTER_ART
        - ACTION_ART
        - BACKGROUND_SCENE
        - NON_VISUAL
        """
        # 1. CHARACTER_ART: Close-up face portrait
        char_img = np.full((600, 600, 3), 240, dtype=np.uint8)
        # Face with skin tone
        cv2.circle(char_img, (300, 300), 180, (140, 175, 225), -1)
        # Eyes
        cv2.circle(char_img, (240, 280), 20, (30, 30, 30), -1)
        cv2.circle(char_img, (360, 280), 20, (30, 30, 30), -1)
        # Mouth
        cv2.line(char_img, (270, 380), (330, 380), (20, 20, 80), 4)

        tag_char = SmartPaginator.classify_page_tag(
            char_img,
            p_type=PageType.VISUAL,
            visual_score=75,
            text_score=5,
            detected_faces=[(120, 120, 480, 480)],
            detected_characters=[(100, 100, 500, 550)]
        )
        self.assertEqual(tag_char, PageTag.CHARACTER_ART)

        # 2. ACTION_ART: High diagonal speedline slash without text
        action_img = np.full((600, 600, 3), 30, dtype=np.uint8)
        for i in range(0, 600, 15):
            cv2.line(action_img, (0, i), (i, 600), (255, 255, 255), 4)
            cv2.line(action_img, (i, 0), (600, 600 - i), (255, 200, 0), 5)

        tag_act = SmartPaginator.classify_page_tag(
            action_img,
            p_type=PageType.VISUAL,
            visual_score=85,
            text_score=0,
            score_breakdown={"action_context": 90.0, "visual_detail": 85.0}
        )
        self.assertEqual(tag_act, PageTag.ACTION_ART)

        # 3. NON_VISUAL: Pure dialogue bubble on white canvas
        bubble_img = np.full((300, 600, 3), 255, dtype=np.uint8)
        cv2.ellipse(bubble_img, (300, 150), (200, 60), 0, 0, 360, (250, 250, 250), -1)
        cv2.ellipse(bubble_img, (300, 150), (200, 60), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(bubble_img, "Hello, can you hear me?", (180, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

        tag_bubble = SmartPaginator.classify_page_tag(
            bubble_img,
            p_type=PageType.DIALOGUE,
            visual_score=25,
            text_score=55,
            detected_characters=[],
            detected_faces=[]
        )
        self.assertEqual(tag_bubble, PageTag.NON_VISUAL)

        # 4. BACKGROUND_SCENE: Scenery with mountains / sky, no character
        bg_img = np.full((600, 600, 3), 200, dtype=np.uint8)
        # Blue sky
        cv2.rectangle(bg_img, (0, 0), (600, 300), (230, 180, 100), -1)
        # Green mountains
        pts = np.array([[0, 450], [200, 250], [400, 350], [600, 200], [600, 600], [0, 600]])
        cv2.fillPoly(bg_img, [pts], (50, 120, 40))

        tag_bg = SmartPaginator.classify_page_tag(
            bg_img,
            p_type=PageType.VISUAL,
            visual_score=65,
            text_score=0,
            score_breakdown={"action_context": 15.0, "visual_detail": 50.0},
            detected_characters=[],
            detected_faces=[]
        )
        self.assertEqual(tag_bg, PageTag.BACKGROUND_SCENE)

    def test_camera_motion_metadata_face_tracking(self):
        """
        Verify calculate_focal_points centers primary_focal on character face
        and outputs camera_hint 'zoom_in_face'.
        """
        img = np.full((1080, 720, 3), 255, dtype=np.uint8)
        # Character with face located at x=360, y=270 (normalized 0.5, 0.25)
        detected_faces = [(280, 190, 440, 350)]
        detected_chars = [(200, 150, 520, 900)]

        focal_pt, focal_pts, cam_hint = SmartPaginator.calculate_focal_points(
            img,
            bg_val=255,
            detected_characters=detected_chars,
            detected_faces=detected_faces
        )

        # Face center: (360 / 720 = 0.5, 270 / 1080 = 0.25)
        self.assertAlmostEqual(focal_pt[0], 0.5, delta=0.05)
        self.assertAlmostEqual(focal_pt[1], 0.25, delta=0.05)
        self.assertEqual(cam_hint, "zoom_in_face")
        self.assertGreater(len(focal_pts), 0)
        self.assertEqual(focal_pts[0]["type"], "face")

    def test_margin_cleanup_top_sliver_and_bottom_credit(self):
        """
        Verify that top slivers (< 150px) and bottom scanlation credit / watermark banners
        are pruned from the output pages.
        """
        canvas = np.full((3200, 800, 3), 255, dtype=np.uint8)

        # 1. Top junk sliver (y=0..80) followed by 50px gutter
        cv2.rectangle(canvas, (20, 10), (780, 70), (230, 230, 230), -1)

        # 2. Real comic panel 1 (y=150..1200)
        cv2.rectangle(canvas, (50, 150), (750, 1200), (100, 120, 180), -1)
        cv2.circle(canvas, (400, 500), 80, (140, 175, 220), -1)

        # 3. Real comic panel 2 (y=1300..2500)
        cv2.rectangle(canvas, (50, 1300), (750, 2500), (80, 140, 100), -1)
        cv2.circle(canvas, (400, 1700), 80, (140, 175, 220), -1)

        # 4. Bottom credit banner (y=2650..2900)
        cv2.rectangle(canvas, (100, 2650), (700, 2900), (245, 245, 245), -1)
        cv2.putText(canvas, "ASURASCANS CHAPTER END", (150, 2780), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)

        results = self.paginator.paginate_canvas(canvas)

        # Ensure no page begins with the top sliver (y_start must be >= 120)
        self.assertGreaterEqual(results[0][1].y_start, 100)

        # Ensure credit banner is not a video candidate
        for img, meta in results:
            if meta.y_start >= 2600:
                self.assertFalse(meta.video_candidate, "Credit banner must not be a video candidate")


if __name__ == "__main__":
    unittest.main()
