import os
import shutil
import cv2
import numpy as np
import pytest
from pathlib import Path
from PIL import Image

from artifact_cache import validate_pdf_file
from moderation_utils import (
    is_blank_or_solid_page,
    is_junk_or_title_page,
    create_numbered_pdf,
    list_image_files,
)


def test_is_blank_or_solid_page():
    # 1. Empty image
    empty_img = np.zeros((0, 0, 3), dtype=np.uint8)
    is_blank, reason = is_blank_or_solid_page(empty_img)
    assert is_blank is True
    assert reason == "empty_image"

    # 2. Too small image
    small_img = np.ones((10, 10, 3), dtype=np.uint8) * 255
    is_blank, reason = is_blank_or_solid_page(small_img)
    assert is_blank is True
    assert reason == "dimension_too_small"

    # 3. Solid white page
    white_img = np.ones((600, 400, 3), dtype=np.uint8) * 255
    is_blank, reason = is_blank_or_solid_page(white_img)
    assert is_blank is True
    assert reason in ("solid_background", "low_edge_density", "low_variance")

    # 4. Solid black page
    black_img = np.zeros((600, 400, 3), dtype=np.uint8)
    is_blank, reason = is_blank_or_solid_page(black_img)
    assert is_blank is True
    assert reason in ("solid_background", "low_edge_density", "low_variance")


def test_is_junk_or_title_page():
    # 1. Sparse title banner (e.g. Chapter 1: PREPARE APOCALYPSE) on dark background
    title_banner = np.ones((400, 800, 3), dtype=np.uint8) * 20
    cv2.putText(
        title_banner,
        "PREPARE APOCALYPSE",
        (50, 200),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.5,
        (255, 255, 255),
        3,
    )
    is_junk, reason = is_junk_or_title_page(title_banner)
    assert is_junk is True
    assert "title" in reason or "sparse" in reason or "solid" in reason

    # 2. Junk keywords detected via OCR
    dummy_card = np.ones((500, 500, 3), dtype=np.uint8) * 240
    cv2.rectangle(dummy_card, (50, 50), (450, 450), (100, 100, 100), 2)
    is_junk, reason = is_junk_or_title_page(
        dummy_card,
        ocr_texts=["Chapter 12", "Translated by Scanlation Team", "Discord: discord.gg/test"],
    )
    assert is_junk is True
    assert "junk_keyword" in reason

    # 3. Valid rich comic story panel (character artwork with texture)
    story_panel = np.zeros((600, 500, 3), dtype=np.uint8)
    for i in range(80):
        cv2.circle(
            story_panel,
            (int((i * 37) % 500), int((i * 43) % 600)),
            int(15 + (i % 25)),
            (int((i * 50) % 255), int((i * 80) % 255), int((i * 110) % 255)),
            -1,
        )
    for i in range(20):
        cv2.line(
            story_panel,
            (0, i * 30),
            (500, 600 - i * 30),
            (255, 255, 255),
            2,
        )

    is_junk, reason = is_junk_or_title_page(story_panel, ocr_texts=["He launched a heavy punch!"])
    assert is_junk is False
    assert reason == "valid_story_panel"


def test_create_numbered_pdf(tmp_path):
    images_dir = tmp_path / "images_pdf"
    images_dir.mkdir()
    pdf_out = tmp_path / "test_output.pdf"

    for i in range(1, 4):
        panel = np.ones((800, 600, 3), dtype=np.uint8) * (i * 60)
        cv2.putText(
            panel,
            f"Panel {i} Action Scene",
            (50, 400),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            2,
        )
        img_path = images_dir / f"{i:03d}.webp"
        cv2.imwrite(str(img_path), panel)

    create_numbered_pdf(images_dir, pdf_out, quality=80)
    assert pdf_out.exists()
    assert pdf_out.stat().st_size > 0
    assert validate_pdf_file(pdf_out) is True

    # Validate that PDF has 3 page objects
    pdf_bytes = pdf_out.read_bytes()
    assert pdf_bytes.count(b"/Type /Page\n") + pdf_bytes.count(b"/Type /Page ") + pdf_bytes.count(b"/Type/Page") >= 3
