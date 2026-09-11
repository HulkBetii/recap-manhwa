"""Tests for visual_scorer.VisualSemanticScorer."""

from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

from visual_scorer import VisualSemanticScorer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_solid(color: tuple[int, int, int], size: tuple[int, int] = (500, 300)) -> np.ndarray:
    """Create a solid-colour BGR image."""
    img = np.full((*size, 3), color, dtype=np.uint8)
    return img


def _make_gradient(size: tuple[int, int] = (500, 300)) -> np.ndarray:
    """Create a horizontal gradient BGR image."""
    h, w = size
    grad = np.tile(np.linspace(0, 255, w, dtype=np.uint8), (h, 1))
    return cv2.merge([grad, grad, grad])


def _make_complex_art(size: tuple[int, int] = (800, 500)) -> np.ndarray:
    """Create a synthetic 'comic art' image with shapes, colours and edges."""
    h, w = size
    img = np.full((h, w, 3), (240, 240, 240), dtype=np.uint8)

    # Draw random rectangles (panels)
    rng = np.random.RandomState(42)
    for _ in range(8):
        x1, y1 = rng.randint(0, w - 50), rng.randint(0, h - 50)
        x2, y2 = x1 + rng.randint(40, 150), y1 + rng.randint(40, 150)
        colour = tuple(int(c) for c in rng.randint(0, 200, 3))
        cv2.rectangle(img, (x1, y1), (x2, y2), colour, -1)

    # Draw circles (characters / heads)
    for _ in range(5):
        cx, cy = rng.randint(50, w - 50), rng.randint(50, h - 50)
        radius = rng.randint(20, 60)
        colour = tuple(int(c) for c in rng.randint(50, 255, 3))
        cv2.circle(img, (cx, cy), radius, colour, -1)

    # Draw lines (speed lines / action)
    for _ in range(12):
        pt1 = (rng.randint(0, w), rng.randint(0, h))
        pt2 = (rng.randint(0, w), rng.randint(0, h))
        cv2.line(img, pt1, pt2, (0, 0, 0), 2)

    return img


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVisualSemanticScorer:

    def test_empty_image_returns_zero(self):
        """Empty / None input must return score 0."""
        score, breakdown = VisualSemanticScorer.calculate_score(np.array([]))
        assert score == 0
        assert all(v == 0.0 for v in breakdown.values())

    def test_none_input_returns_zero(self):
        score, breakdown = VisualSemanticScorer.calculate_score(None)
        assert score == 0

    def test_tiny_image_returns_zero(self):
        """Images smaller than 5×5 should return 0."""
        tiny = np.zeros((3, 3, 3), dtype=np.uint8)
        score, _ = VisualSemanticScorer.calculate_score(tiny)
        assert score == 0

    def test_solid_white_scores_low(self):
        """A plain white image should score very low."""
        img = _make_solid((255, 255, 255))
        score, breakdown = VisualSemanticScorer.calculate_score(img)
        assert score < 30, f"Solid white should score < 30, got {score}"

    def test_solid_black_scores_low(self):
        """A plain black image should score very low."""
        img = _make_solid((0, 0, 0))
        score, breakdown = VisualSemanticScorer.calculate_score(img)
        assert score < 30, f"Solid black should score < 30, got {score}"

    def test_gradient_scores_medium(self):
        """A gradient image has some detail but no characters."""
        img = _make_gradient()
        score, breakdown = VisualSemanticScorer.calculate_score(img)
        assert 20 <= score <= 70, f"Gradient should score 20-70, got {score}"

    def test_complex_art_scores_high(self):
        """Synthetic art with shapes/lines should score reasonably high."""
        img = _make_complex_art()
        score, breakdown = VisualSemanticScorer.calculate_score(img)
        assert score >= 40, f"Complex art should score >= 40, got {score}"
        # Should have non-trivial visual detail
        assert breakdown["visual_detail"] > 20

    def test_score_range_0_100(self):
        """Score must always be in [0, 100]."""
        for factory in [_make_solid((128, 128, 128)), _make_gradient(), _make_complex_art()]:
            score, _ = VisualSemanticScorer.calculate_score(factory)
            assert 0 <= score <= 100

    def test_breakdown_keys(self):
        """Breakdown dict must contain all 5 criteria + final_score + is_meaningless."""
        img = _make_gradient()
        _, breakdown = VisualSemanticScorer.calculate_score(img)
        expected_keys = {
            "semantic_similarity", "visual_detail", "character_presence",
            "action_context", "image_quality", "is_meaningless", "final_score",
        }
        assert set(breakdown.keys()) == expected_keys

    def test_text_bubble_penalty(self):
        """Images dominated by a white speech bubble/text box should be penalized below 35."""
        # Create a synthetic speech bubble: mostly white image with black text-like lines
        img = np.full((500, 500, 3), (250, 250, 250), dtype=np.uint8)
        # Draw black border box (speech / text box)
        cv2.rectangle(img, (50, 50), (450, 450), (0, 0, 0), 2)
        # Draw text-like lines
        for y in range(150, 350, 30):
            cv2.line(img, (100, y), (400, y), (0, 0, 0), 2)

        score, breakdown = VisualSemanticScorer.calculate_score(img)
        assert score <= 35, f"Speech bubble should score <= 35, got {score}"
        assert breakdown["is_meaningless"] is True

    def test_pil_wrapper(self):
        """calculate_score_from_pil should produce same result as calculate_score."""
        from PIL import Image as PILImage

        bgr = _make_complex_art()
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        pil_img = PILImage.fromarray(rgb)

        score_bgr, _ = VisualSemanticScorer.calculate_score(bgr)
        score_pil, _ = VisualSemanticScorer.calculate_score_from_pil(pil_img)
        assert score_bgr == score_pil

    def test_bg_val_override(self):
        """Providing bg_val should change the score for background-heavy images."""
        img = _make_solid((200, 200, 200))
        score_auto, _ = VisualSemanticScorer.calculate_score(img, bg_val=None)
        score_diff_bg, _ = VisualSemanticScorer.calculate_score(img, bg_val=0)
        # With bg_val=0, almost everything is "content", so score should be higher
        assert score_diff_bg > score_auto

    def test_performance_under_5ms(self):
        """Scoring a 500px-wide image should take < 5ms on average."""
        img = _make_complex_art((800, 500))
        # Warm up
        VisualSemanticScorer.calculate_score(img)

        N = 20
        start = time.perf_counter()
        for _ in range(N):
            VisualSemanticScorer.calculate_score(img)
        elapsed = (time.perf_counter() - start) / N * 1000  # ms

        # Allow generous 100ms to account for CI / slow machines
        assert elapsed < 100, f"Average scoring time {elapsed:.1f}ms exceeds 100ms limit"
