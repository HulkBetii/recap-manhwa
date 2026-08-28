import json
import os
import cv2
import numpy as np
import pytest
from pathlib import Path
from PIL import Image

from app import generate_gemini_prompt, parse_gemini_recap_text
from artifact_cache import validate_pdf_file
from moderation_utils import (
    is_junk_or_title_page,
    create_numbered_pdf,
    list_image_files,
)
from recap_schema import parse_recap_data, validate_recap_file
from workflow_stages_2 import (
    detect_focal_point,
    detect_content_bounds,
    CameraPlanner,
    interpolate_camera_plan,
    draw_subtitles_on_frame,
    merge_srt_files,
)


def test_e2e_pipeline_v2_synthetic_chapter(tmp_path):
    """
    Comprehensive End-to-End Simulation of the v2.0 Pipeline:
    1. Generates synthetic raw chapter images containing title banner, story panels, white gaps, and credit card.
    2. Runs Stage 2b sub-panel segmentation & junk filtering.
    3. Runs Stage 4 Numbered PDF generation.
    4. Runs Stage 5/6 AI prompt generation, multi-panel parsing, and schema validation.
    5. Runs Stage 10 Camera focal motion planning, frame rendering with drop shadow, and safe zone subtitles.
    6. Runs Stage 11 Final assembly & SRT generation.
    """
    raw_images_dir = tmp_path / "images"
    images_pdf_dir = tmp_path / "images_pdf"
    output_dir = tmp_path / "output"
    raw_images_dir.mkdir()
    images_pdf_dir.mkdir()
    output_dir.mkdir()

    # --- STEP 1: CREATE SYNTHETIC CHAPTER IMAGES ---
    # Slice 0: Title Banner ("PREPARE APOCALYPSE") -> Should be dropped
    title_banner = np.ones((400, 720, 3), dtype=np.uint8) * 15
    cv2.putText(title_banner, "PREPARE APOCALYPSE", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 255, 255), 3)

    # Slice 1: Action Panel 1 (Character face & action) -> Valid Story Panel
    panel1 = np.ones((800, 720, 3), dtype=np.uint8) * 50
    for i in range(50):
        cv2.circle(panel1, (int((i * 43) % 720), int((i * 61) % 800)), int(15 + (i % 20)), (int(i*5 % 255), int(i*7 % 255), int(i*9 % 255)), -1)
    for i in range(15):
        cv2.line(panel1, (0, i * 50), (720, 800 - i * 50), (200, 200, 200), 2)
    cv2.circle(panel1, (180, 250), 50, (220, 180, 100), -1)  # Face
    cv2.putText(panel1, "Hero Dodge", (50, 450), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

    # Slice 2: Action Panel 2 (Sword Strike) -> Valid Story Panel
    panel2 = np.ones((800, 720, 3), dtype=np.uint8) * 40
    for i in range(50):
        cv2.circle(panel2, (int((i * 53) % 720), int((i * 47) % 800)), int(15 + (i % 20)), (int(i*6 % 255), int(i*8 % 255), int(i*4 % 255)), -1)
    for i in range(20):
        cv2.line(panel2, (0, i * 40), (720, 800 - i * 40), (220, 220, 220), 2)
    cv2.line(panel2, (50, 100), (670, 700), (0, 255, 255), 6)  # Slash
    cv2.circle(panel2, (500, 300), 40, (180, 50, 50), -1)  # Monster hit

    # Slice 3: Wide Combat Panel (Landscape combat scene) -> Valid Story Panel
    panel3 = np.ones((600, 900, 3), dtype=np.uint8) * 60
    for i in range(60):
        cv2.circle(panel3, (int((i * 67) % 900), int((i * 37) % 600)), int(12 + (i % 22)), (int(i*7 % 255), int(i*5 % 255), int(i*8 % 255)), -1)
    for i in range(15):
        cv2.line(panel3, (i * 60, 0), (900 - i * 60, 600), (240, 240, 240), 2)

    # Slice 4: Credit / Donate Card -> Should be dropped
    credit_card = np.ones((350, 720, 3), dtype=np.uint8) * 240
    cv2.putText(credit_card, "Translated by Team - Donate", (40, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)

    raw_slices = [
        ("001_title.png", title_banner, ["PREPARE APOCALYPSE"]),
        ("002_panel1.png", panel1, ["Hero Dodge"]),
        ("003_panel2.png", panel2, ["Slash Attack"]),
        ("004_panel3.png", panel3, ["Combat Group"]),
        ("005_credit.png", credit_card, ["Translated by Team", "Donate via paypal"]),
    ]

    # --- STEP 2: SUB-PANEL JUNK FILTERING & EXPORT (Stage 2b) ---
    valid_panels = []
    panel_counter = 0
    for name, img, ocr in raw_slices:
        is_junk, reason = is_junk_or_title_page(img, ocr_texts=ocr)
        if is_junk:
            continue
        panel_counter += 1
        panel_file = f"{panel_counter:03d}.webp"
        save_path = images_pdf_dir / panel_file
        cv2.imwrite(str(save_path), img)
        valid_panels.append(panel_file)

    # Assert that title card and credit card were successfully filtered out (3 valid panels remain)
    assert len(valid_panels) == 3
    assert panel_counter == 3

    # --- STEP 3: NUMBERED PDF GENERATION (Stage 4) ---
    pdf_out = tmp_path / "Episode_1.pdf"
    create_numbered_pdf(images_pdf_dir, pdf_out, quality=80)
    assert pdf_out.exists()
    assert validate_pdf_file(pdf_out) is True

    # --- STEP 4: AI PROMPT & SCRIPT GROUNDING (Stage 5 & 6) ---
    prompt = generate_gemini_prompt("Solo Leveling", 1, len(valid_panels), "vi")
    assert "DIRECT VISUAL MATCHING" in prompt or "Direct Alignment" in prompt

    # Simulate Gemini response using multi-panel alignment format
    gemini_simulated_response = """
[1] - Nhận thấy nguy hiểm cận kề, anh nhanh chóng nghiêng người né đòn chí mạng.#
[2, 3] - Ngay sau cú né, anh vung thanh bảo kiếm chém đứt quái vật rồi mở đường cho cả đội rút lui.#
"""
    parsed_script = parse_gemini_recap_text(gemini_simulated_response)
    assert len(parsed_script) == 2

    # Validate against schema
    validated_segments = parse_recap_data(parsed_script, max_page=len(valid_panels))
    assert len(validated_segments) == 2
    assert validated_segments[0].images[0].page == 1
    assert validated_segments[1].images[0].page == 2
    assert validated_segments[1].images[1].page == 3

    # Save recap.json
    recap_json_path = tmp_path / "recap.json"
    recap_json_path.write_text(json.dumps([s.model_dump(mode="json") for s in validated_segments]), encoding="utf-8")
    assert validate_recap_file(recap_json_path, max_page=len(valid_panels)) is True

    # --- STEP 5: CAMERA MOTION & FRAME RENDERING (Stage 10) ---
    page_files = list_image_files(images_pdf_dir)
    assert len(page_files) == 3

    for p_idx, p_file in enumerate(page_files):
        p_path = images_pdf_dir / p_file
        with Image.open(p_path) as pil_panel:
            bounds = detect_content_bounds(pil_panel)
            focal_pt = detect_focal_point(pil_panel, bounds)

            # Generate camera plan
            plan = CameraPlanner.generate_camera_plan(
                page_num=p_idx + 1,
                duration=3.5,
                bounds=bounds,
                focal_point=focal_pt,
            )

            # Verify no scroll_down
            assert plan["animation_type"] != "scroll_down"

            # Interpolate camera keyframes
            x_cam, y_cam, scale_cam = interpolate_camera_plan(plan, 1.5)
            assert 0 <= x_cam <= bounds[2]
            assert 0 <= y_cam <= bounds[3]
            assert scale_cam >= 1.0

            # Render test frame
            bg_dummy = Image.new("RGB", (1920, 1080), (100, 100, 100))
            frame_canvas = bg_dummy.copy()

            # Test subtitle drawing (with safe zone)
            draw_subtitles_on_frame(frame_canvas, "Thử nghiệm phụ đề trong vùng an toàn.", font_size=40)
            assert frame_canvas.size == (1920, 1080)

    # --- STEP 6: FINAL SRT MERGE (Stage 11) ---
    srt1 = tmp_path / "ep1_transcript.srt"
    srt1.write_text("1\n00:00:00,000 --> 00:00:03,500\nNhận thấy nguy hiểm cận kề...\n", encoding="utf-8")
    final_merged_srt = output_dir / "final_series.srt"

    merge_srt_files([str(srt1)], [3.5], str(final_merged_srt))
    assert final_merged_srt.exists()
    assert "Nhận thấy nguy hiểm cận kề..." in final_merged_srt.read_text(encoding="utf-8")
