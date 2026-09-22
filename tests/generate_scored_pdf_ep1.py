# -*- coding: utf-8 -*-
"""
Generates annotated PDF with Pure Visual Point Scores for Episode 1.
"""
import os
import sys
import logging
import cv2
import numpy as np

# Ensure root in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pure_visual.pipeline import PureVisualPipeline
from pure_visual.config import DetectionConfig

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("GenerateScoredPDF")

def main():
    ep_dir = r"C:\Users\USA\Documents\Workspace\recap_comics\downloads\the_time_limited_baby_doctor_doesnt_hide_the_fact_that_shes_a_genius_1_1_vi\episode_1"
    raw_images_dir = os.path.join(ep_dir, "images_source_raw")
    images_dir = os.path.join(ep_dir, "images")
    pdf_dir = os.path.join(ep_dir, "pdf")
    debug_dir = os.path.join(ep_dir, "debug_repaging")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(debug_dir, exist_ok=True)

    raw_files = sorted([f for f in os.listdir(raw_images_dir) if f.lower().endswith(('.webp', '.png', '.jpg', '.jpeg'))])
    logger.info(f"Loading {len(raw_files)} raw slice images from {raw_images_dir}...")

    loaded_images = []
    for f in raw_files:
        fp = os.path.join(raw_images_dir, f)
        img = cv2.imread(fp)
        if img is not None and img.size > 0:
            loaded_images.append((f, img))

    if not loaded_images:
        logger.error("No images loaded.")
        return

    # Normalize width to common width (e.g. 800)
    target_w = loaded_images[0][1].shape[1]
    logger.info(f"Target canvas width: {target_w}px")

    offsets = []
    normalized_slices = []
    for fname, img in loaded_images:
        h, w = img.shape[:2]
        if w != target_w:
            new_h = int(round(h * (float(target_w) / float(w))))
            img = cv2.resize(img, (target_w, new_h), interpolation=cv2.INTER_AREA)
        normalized_slices.append((fname, img))

    total_canvas_h = sum(img.shape[0] for _, img in normalized_slices)
    logger.info(f"Building stitched canvas ({target_w}x{total_canvas_h}px)...")

    canvas = np.zeros((total_canvas_h, target_w, 3), dtype=np.uint8)
    cur_y = 0
    for fname, img in normalized_slices:
        h = img.shape[0]
        canvas[cur_y:cur_y+h, :] = img
        offsets.append({
            "filename": fname,
            "y_start": cur_y,
            "y_end": cur_y + h,
            "height": h
        })
        cur_y += h

    logger.info(f"Executing Pure Visual Pipeline with point scoring...")
    config = DetectionConfig(
        device="cuda",
        export_annotated_pdf=True,
        export_webp_frames=True
    )
    pipeline = PureVisualPipeline(config)

    pdf_out_path = os.path.join(pdf_dir, "The_Time_Limited_Baby_Doctor_Doesnt_Hide_The_Fact_That_Shes_a_Genius_Tap_1.pdf")
    meta_json_path = os.path.join(debug_dir, "pure_visual_regions_metadata.json")

    res = pipeline.process_canvas(
        canvas=canvas,
        output_images_dir=images_dir,
        output_pdf_path=pdf_out_path,
        output_metadata_path=meta_json_path,
        source_offsets=offsets
    )

    logger.info(f"Done! Pipeline result: {len(res.regions)} regions detected and scored.")
    logger.info(f"PDF successfully saved to: {pdf_out_path}")

    # Print first 10 and last 5 regions with scores
    for r in res.regions[:10]:
        score_100 = r.details.get("score_100", 0)
        tier = r.details.get("quality_tier", "?")
        logger.info(f"Region R{r.region_id}: Point = {score_100}/100 ({tier}) - Dimensions: {r.pure_visual_bbox.width}x{r.pure_visual_bbox.height}px")

    for r in res.regions[-5:]:
        score_100 = r.details.get("score_100", 0)
        tier = r.details.get("quality_tier", "?")
        logger.info(f"Region R{r.region_id}: Point = {score_100}/100 ({tier}) - Dimensions: {r.pure_visual_bbox.width}x{r.pure_visual_bbox.height}px")

if __name__ == "__main__":
    main()
