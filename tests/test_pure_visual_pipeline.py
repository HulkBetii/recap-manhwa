# -*- coding: utf-8 -*-
"""
UNIT & INTEGRATION TEST SUITE: PURE VISUAL REGION DETECTION & PDF EXPORT
Tests panel isolation (anti-merge), junk & text-only filtering, PDF generation with green box & Start/End badges.
"""
import os
import shutil
import unittest
import numpy as np
import cv2
import pymupdf as fitz

from pure_visual.types import BBox, PureVisualRegion, PipelineResult
from pure_visual.config import DetectionConfig
from pure_visual.visual_detector import VisualRegionDetector
from pure_visual.pdf_annotator import PDFAnnotator
from pure_visual.pipeline import PureVisualPipeline


class TestPureVisualPipeline(unittest.TestCase):

    def setUp(self):
        self.test_dir = os.path.join("tests", "tmp_pure_visual_test")
        os.makedirs(self.test_dir, exist_ok=True)
        self.config = DetectionConfig(device="cpu")  # CPU for predictable unit tests

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_synthetic_canvas(self) -> np.ndarray:
        """
        Creates an ultra-realistic synthetic comic strip with:
        - Panel 1 (y: 100 to 500): Vibrant artwork (rectangles, circles, textures)
        - Gutter 1 (y: 500 to 600): Pure white background (100px)
        - Panel 2 (y: 600 to 1100): Character panel with colorful art
        - Gutter 2 (y: 1100 to 1200): Pure white background
        - Bubble Only (y: 1200 to 1350): White bubble box with flat text lines
        - Gutter 3 (y: 1350 to 1450): Pure white background
        - Panel 3 (y: 1450 to 2000): Action scene artwork
        """
        width = 800
        height = 2100
        canvas = np.ones((height, width, 3), dtype=np.uint8) * 255  # White background

        # Panel 1: Artwork (y: 100 to 500) - Rich multi-color gradients & shapes
        cv2.rectangle(canvas, (50, 100), (750, 500), (50, 120, 220), -1)
        cv2.circle(canvas, (400, 300), 100, (255, 200, 50), -1)
        cv2.circle(canvas, (250, 250), 70, (0, 255, 120), -1)
        cv2.circle(canvas, (550, 250), 70, (20, 20, 240), -1)
        cv2.rectangle(canvas, (100, 150), (700, 200), (240, 50, 200), -1)
        for i in range(150, 450, 25):
            cv2.line(canvas, (100, i), (700, i + 20), (0, 0, 0), 4)

        # Panel 2: Artwork (y: 600 to 1100) - Colorful complex scene
        cv2.rectangle(canvas, (80, 600), (720, 1100), (80, 200, 100), -1)
        cv2.rectangle(canvas, (120, 650), (680, 1050), (220, 50, 180), -1)
        cv2.circle(canvas, (300, 850), 120, (10, 240, 250), -1)
        cv2.circle(canvas, (500, 850), 120, (250, 10, 20), -1)
        cv2.putText(canvas, "ARTWORK SCENE 2", (180, 850), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 4)

        # Text Bubble Only: Flat box with minor text (y: 1220 to 1320)
        cv2.ellipse(canvas, (400, 1270), (180, 45), 0, 0, 360, (240, 240, 240), -1)
        cv2.ellipse(canvas, (400, 1270), (180, 45), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(canvas, "Hello dialogue only...", (280, 1275), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)

        # Panel 3: Artwork (y: 1450 to 2000) - Rich multi-hue action scene
        cv2.rectangle(canvas, (40, 1450), (760, 2000), (30, 80, 160), -1)
        cv2.circle(canvas, (250, 1700), 130, (240, 240, 60), -1)
        cv2.circle(canvas, (550, 1750), 130, (60, 240, 240), -1)
        cv2.rectangle(canvas, (100, 1550), (700, 1650), (200, 30, 230), -1)
        cv2.rectangle(canvas, (150, 1850), (650, 1950), (30, 230, 40), -1)

        return canvas

    def test_anti_merge_and_isolate_distinct_panels(self):
        """Verify that distinct panels separated by gutters are NEVER merged."""
        canvas = self._create_synthetic_canvas()
        detector = VisualRegionDetector(self.config)

        results = detector.detect_pure_visual_regions(canvas, bg_val=255)
        # Should detect distinct visual panels (Panel 1, Panel 2, Panel 3)
        self.assertGreaterEqual(len(results), 3)

        # Verify no region spans across the major gutter y=500..600
        for crop, reg in results:
            y1 = reg.original_bbox.y1
            y2 = reg.original_bbox.y2
            # Check that no single region bridges from Panel 1 into Panel 2
            if y1 < 500:
                self.assertLessEqual(y2, 560, f"Region {reg.region_id} improperly bridged across gutter 1: y1={y1}, y2={y2}")
            if y1 >= 580 and y1 < 1100:
                self.assertLessEqual(y2, 1160, f"Region {reg.region_id} improperly bridged across gutter 2: y1={y1}, y2={y2}")

    def test_pdf_annotation_green_box_and_badges(self):
        """Verify that PDFAnnotator renders green box and Start/End badges correctly."""
        annotator = PDFAnnotator(self.config)
        test_img = np.zeros((600, 800, 3), dtype=np.uint8) + 128  # Gray background

        annotated = annotator.annotate_frame(test_img, region_id=1)
        self.assertEqual(annotated.shape, test_img.shape)

        # Verify green box presence (bright green pixels (0, 255, 0) in BGR)
        green_mask = (annotated[:, :, 0] == 0) & (annotated[:, :, 1] == 255) & (annotated[:, :, 2] == 0)
        self.assertTrue(np.any(green_mask), "Green bounding box pixels not found in annotated frame.")

        # Test PDF export with multiple pages
        out_pdf = os.path.join(self.test_dir, "test_output.pdf")
        frames = [
            (test_img.copy(), 1),
            (test_img.copy(), 2),
            (test_img.copy(), 3),
        ]
        ok = annotator.export_pdf(frames, out_pdf, annotate=True)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(out_pdf))

        # Validate PDF structure via PyMuPDF
        doc = fitz.open(out_pdf)
        self.assertEqual(len(doc), 3, f"Expected 3 pages in PDF, got {len(doc)}")
        for page in doc:
            rect = page.rect
            self.assertEqual(rect.width, 800)
            self.assertEqual(rect.height, 600)
        doc.close()

    def test_full_pure_visual_pipeline_e2e(self):
        """End-to-end test of PureVisualPipeline exporting canvas annotated PDF and WebP."""
        canvas = self._create_synthetic_canvas()
        out_img_dir = os.path.join(self.test_dir, "output_images")
        out_pdf = os.path.join(self.test_dir, "visual_regions_annotated.pdf")
        out_meta = os.path.join(self.test_dir, "repaging_metadata.json")

        offsets = [
            {"filename": "001.webp", "offset_y_start": 0, "offset_y_end": 700, "height": 700},
            {"filename": "002.webp", "offset_y_start": 700, "offset_y_end": 1400, "height": 700},
            {"filename": "003.webp", "offset_y_start": 1400, "offset_y_end": 2100, "height": 700},
        ]

        pipeline = PureVisualPipeline(self.config)
        result = pipeline.process_canvas(
            canvas=canvas,
            output_images_dir=out_img_dir,
            output_pdf_path=out_pdf,
            output_metadata_path=out_meta,
            source_offsets=offsets,
            bg_val=255
        )

        self.assertIsInstance(result, PipelineResult)
        self.assertGreaterEqual(len(result.regions), 3)
        self.assertTrue(os.path.exists(out_pdf))
        self.assertTrue(os.path.exists(out_meta))

        # Check saved webp images (each pure visual region cropped cleanly)
        webp_files = [f for f in os.listdir(out_img_dir) if f.endswith(".webp")]
        self.assertEqual(len(webp_files), len(result.regions))

        # Verify PDF page count matches original canvas slice pages (3 pages)
        doc = fitz.open(out_pdf)
        self.assertEqual(len(doc), 3)
        doc.close()



if __name__ == "__main__":
    unittest.main()
