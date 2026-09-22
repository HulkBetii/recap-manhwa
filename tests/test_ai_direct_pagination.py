import unittest
import numpy as np
import cv2
from renderer.smart_pagination import SmartPaginator, PaginationConfig, PageTag, PageType


class TestAIDirectPagination(unittest.TestCase):
    def setUp(self):
        self.canvas_h = 3000
        self.canvas_w = 800
        self.canvas = np.full((self.canvas_h, self.canvas_w, 3), 255, dtype=np.uint8)

        # Panel 1 (0 to 1000)
        self.canvas[200:800, 100:700] = [160, 180, 230]
        cv2.circle(self.canvas, (400, 500), 100, (40, 40, 40), -1)

        # Panel 2 (1000 to 2000)
        self.canvas[1200:1800, 100:700] = [30, 30, 200]
        for offset in range(0, 500, 30):
            cv2.line(self.canvas, (100 + offset, 1200), (300 + offset, 1800), (255, 255, 255), 3)

        # Panel 3 (2000 to 3000) - full artwork to ensure not blank
        self.canvas[2200:2800, 100:700] = [100, 200, 100]
        cv2.rectangle(self.canvas, (150, 2300), (650, 2700), (10, 50, 10), -1)

    def test_direct_cuts_exact_slicing(self):
        paginator = SmartPaginator(config=PaginationConfig(mode="ai_direct", tight_auto_crop=False, skip_blank=False))
        cuts = [1000, 2000]
        results = paginator.paginate_canvas(self.canvas, manual_cuts=cuts, ai_direct=True)

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0][1].y_start, 0)
        self.assertEqual(results[0][1].y_end, 1000)
        self.assertEqual(results[0][0].shape[0], 1000)

        self.assertEqual(results[1][1].y_start, 1000)
        self.assertEqual(results[1][1].y_end, 2000)
        self.assertEqual(results[1][0].shape[0], 1000)

        self.assertEqual(results[2][1].y_start, 2000)
        self.assertEqual(results[2][1].y_end, 3000)
        self.assertEqual(results[2][0].shape[0], 1000)

    def test_5_tag_assignment_in_direct_mode(self):
        paginator = SmartPaginator(config=PaginationConfig(mode="ai_direct", tight_auto_crop=False, skip_blank=False))
        cuts = [1000, 2000]
        results = paginator.paginate_canvas(self.canvas, manual_cuts=cuts, ai_direct=True)

        for img, meta in results:
            self.assertIn(meta.page_tag, PageTag.ALL_TAGS)
            self.assertIn("page_tag", meta.to_dict())
            self.assertIn("visual_score", meta.to_dict())
            self.assertIn("boundary_confidence", meta.to_dict())


if __name__ == "__main__":
    unittest.main()
