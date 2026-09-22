# -*- coding: utf-8 -*-
import unittest
import numpy as np
import cv2

from pure_visual.text_inpainter import TextInpainter, get_text_inpainter


class TestTextInpainter(unittest.TestCase):
    def test_inpaint_white_bubble_text(self):
        inpainter = TextInpainter()
        
        # Create a white speech bubble with dark text inside
        img = np.full((300, 300, 3), 250, dtype=np.uint8)
        # Add black text inside bubble
        cv2.putText(img, "HELLO WORLD", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (10, 10, 10), 2)
        
        # Inpaint
        inpainted = inpainter.inpaint_image(img)
        self.assertEqual(inpainted.shape, img.shape)
        
        # Check that the text region is now close to background white
        text_crop = inpainted[130:160, 60:240]
        self.assertGreater(np.mean(text_crop), 185)

    def test_skip_complex_background(self):
        inpainter = TextInpainter()
        
        # Complex colored background (skin tone / artwork) — should NOT be modified
        img = np.full((300, 300, 3), 0, dtype=np.uint8)
        img[:, :, 0] = 180  # Red channel (skin-like BGR)
        img[:, :, 1] = 120
        img[:, :, 2] = 100
        cv2.putText(img, "SWORD!!", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        
        original = img.copy()
        result = inpainter.inpaint_image(img)
        # Should return unchanged (no bubble region detected)
        self.assertTrue(np.array_equal(result, original))

    def test_singleton_getter(self):
        inpainter1 = get_text_inpainter()
        inpainter2 = get_text_inpainter()
        self.assertIs(inpainter1, inpainter2)


if __name__ == "__main__":
    unittest.main()
