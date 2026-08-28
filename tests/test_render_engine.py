import os
import cv2
import numpy as np
import pytest
from PIL import Image

from workflow_stages_2 import (
    draw_subtitles_on_frame,
    detect_content_bounds,
    CameraPlanner,
    shift_srt_time,
    merge_srt_files,
)


def test_draw_subtitles_on_frame_safe_zone():
    canvas = Image.new("RGB", (1920, 1080), (255, 255, 255))
    text = "Jin-woo bất ngờ nhận được nhiệm vụ bí ẩn từ hệ thống và lập tức vung kiếm chém đứt quái vật."
    draw_subtitles_on_frame(canvas, text, font_size=42)

    # Convert to numpy array to check pixel modifications
    np_canvas = np.array(canvas)
    
    # Check that pixels below y=1000 or modified pixels obey safe zone
    # Safe zone bottom boundary is at y <= 960 (1080 - 120)
    # So region y >= 960 should have minimal or no text
    # Let's inspect the bounding box of modified pixels
    diff = np.any(np_canvas != 255, axis=-1)
    modified_rows = np.where(diff)[0]
    
    assert len(modified_rows) > 0
    max_y = np.max(modified_rows)
    # The bottom-most modified pixel should not exceed 965 (1080 - 120 + small margin)
    assert max_y <= 970, f"Subtitle bottom {max_y} violated bottom safe zone (should be <= 970)"


def test_draw_subtitles_empty_text():
    canvas = Image.new("RGB", (1920, 1080), (200, 200, 200))
    orig_np = np.array(canvas)
    draw_subtitles_on_frame(canvas, "")
    assert np.array_equal(np.array(canvas), orig_np)


def test_shift_srt_time():
    # 00:01:23,456 + 10.5 seconds -> 00:01:33,956
    shifted = shift_srt_time("00:01:23,456", 10.5)
    assert shifted == "00:01:33,956"

    # Minute rollover: 00:00:55,000 + 10.0 seconds -> 00:01:05,000
    shifted2 = shift_srt_time("00:00:55,000", 10.0)
    assert shifted2 == "00:01:05,000"


def test_merge_srt_files(tmp_path):
    srt1_path = tmp_path / "ep1.srt"
    srt2_path = tmp_path / "ep2.srt"
    out_srt = tmp_path / "merged.srt"

    srt1_content = """1
00:00:01,000 --> 00:00:03,500
Tập 1: Mở đầu câu chuyện.

2
00:00:04,000 --> 00:00:06,000
Nhân vật chính xuất hiện.
"""
    srt2_content = """1
00:00:01,500 --> 00:00:04,000
Tập 2: Trận chiến bắt đầu.
"""

    srt1_path.write_text(srt1_content, encoding="utf-8")
    srt2_path.write_text(srt2_content, encoding="utf-8")

    merge_srt_files([str(srt1_path), str(srt2_path)], [6.0, 5.0], str(out_srt))
    assert out_srt.exists()

    merged_text = out_srt.read_text(encoding="utf-8")
    assert "Tập 1: Mở đầu câu chuyện." in merged_text
    assert "Tập 2: Trận chiến bắt đầu." in merged_text
    # Check that second episode subtitle is offset by 6.0 seconds: 01,500 + 6s -> 07,500
    assert "00:00:07,500 --> 00:00:10,000" in merged_text
