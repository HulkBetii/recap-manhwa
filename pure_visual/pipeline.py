# -*- coding: utf-8 -*-
"""
PURE VISUAL REGION DETECTION: FULL PIPELINE COORDINATOR
Executes detection, filtering, WebP staging, PDF generation, and metadata export.
"""
import os
import json
import shutil
import logging
from typing import List, Tuple, Dict, Any, Optional
import cv2
import numpy as np

from pure_visual.types import PureVisualRegion, BBox, PipelineResult
from pure_visual.config import DetectionConfig
from pure_visual.visual_detector import VisualRegionDetector
from pure_visual.cleaner import VisualRegionCleaner
from pure_visual.pdf_annotator import PDFAnnotator
from pure_visual.scorer import calculate_pure_visual_score
from pure_visual.frame_refiner import PureVisualFrameRefiner, FrameRefinerConfig

logger = logging.getLogger("PureVisualPipeline")


class PureVisualPipeline:
    """
    End-to-end pipeline for extracting pure visual regions,
    filtering junk/empty/SFX frames, calculating quality/storytelling scores,
    annotating with green boxes & Start/End badges, and exporting to PDF & WebP.
    """

    def __init__(self, config: Optional[DetectionConfig] = None):
        self.config = config or DetectionConfig()
        self.detector = VisualRegionDetector(self.config)
        self.cleaner = VisualRegionCleaner(self.config)
        self.annotator = PDFAnnotator(self.config)
        self.refiner = PureVisualFrameRefiner(FrameRefinerConfig(
            margin_top_ratio=0.20,
            margin_bot_ratio=0.20,
            margin_side_ratio=0.10,
            enable_zero_variance_trim=True,
            enable_panel_border_crop=True,
            enable_border_text_crop=True
        ))

    def process_canvas(
        self,
        canvas: np.ndarray,
        output_images_dir: str,
        output_pdf_path: str,
        output_metadata_path: Optional[str] = None,
        source_offsets: Optional[List[Dict[str, Any]]] = None,
        bg_val: Optional[int] = None
    ) -> PipelineResult:
        """
        Executes pure visual region detection on a comic canvas.

        Args:
            canvas: Complete stitched BGR numpy image canvas.
            output_images_dir: Target directory to save clean WebP pages (001.webp...).
            output_pdf_path: Target path for the multi-page annotated PDF file.
            output_metadata_path: Optional path for debug JSON metadata.
            source_offsets: Source slice bounding offsets.
            bg_val: Background color value.

        Returns:
            PipelineResult summary object.
        """
        h_canvas, w_canvas = canvas.shape[:2]
        logger.info(f"[PureVisualPipeline] Starting pipeline on canvas ({w_canvas}x{h_canvas} px)...")

        # 1. Detect Candidate Pure Visual Regions
        raw_results = self.detector.detect_pure_visual_regions(
            canvas=canvas,
            bg_val=bg_val,
            source_offsets=source_offsets
        )

        # 2. Quality Gate: Clean Junk Frames (Micro-SFX, Blank Gutters, Floating Text Bubbles)
        visual_results, dropped_audit = self.cleaner.clean_regions(raw_results)

        if not visual_results:
            logger.warning("[PureVisualPipeline] No pure visual regions survived cleaning, using fallback full canvas.")
            fallback_region = PureVisualRegion(
                region_id=1,
                original_bbox=BBox(0, 0, w_canvas, h_canvas),
                pure_visual_bbox=BBox(0, 0, w_canvas, h_canvas),
                file_name="001.webp"
            )
            visual_results = [(canvas, fallback_region)]

        # 2B. Frame Refinement (Parallelized Multi-core CPU)
        import concurrent.futures

        def _refine_single_item(item):
            img, reg = item
            try:
                bubbles = reg.details.get("bubbles", []) if (isinstance(reg.details, dict)) else []
                (rx, ry, rw, rh), _ = self.refiner.refine_frame_ex(img, known_text_boxes=bubbles)
                if rw >= 100 and rh >= 100 and (rw < img.shape[1] or rh < img.shape[0]):
                    refined_img = img[ry:ry + rh, rx:rx + rw].copy()
                    reg.pure_visual_bbox = BBox(0, 0, rw, rh)
                    if hasattr(reg, "original_bbox") and reg.original_bbox:
                        orig_x1 = reg.original_bbox.x1 + rx
                        orig_y1 = reg.original_bbox.y1 + ry
                        orig_x2 = orig_x1 + rw
                        orig_y2 = orig_y1 + rh
                        reg.original_bbox = BBox(orig_x1, orig_y1, orig_x2, orig_y2)
                    return refined_img, reg
                else:
                    return img, reg
            except Exception as ref_err:
                logger.debug(f"[PureVisualPipeline] Refiner bypassed for region {reg.region_id}: {ref_err}")
                return img, reg

        workers = min(16, os.cpu_count() or 8)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            visual_results = list(pool.map(_refine_single_item, visual_results))

        # 3. Parallel Quality/Storytelling Scoring & Sequential Re-Indexing
        def _score_single_item(item):
            new_idx, (img, reg) = item
            reg.region_id = new_idx
            reg.file_name = f"{new_idx:03d}.webp"
            score_data = calculate_pure_visual_score(img, reg)
            reg.visual_ratio = score_data["pure_visual_score"]
            if not isinstance(reg.details, dict):
                reg.details = {}
            reg.details["pure_visual_score"] = score_data["pure_visual_score"]
            reg.details["score_100"] = score_data["score_100"]
            reg.details["quality_tier"] = score_data["quality_tier"]
            reg.details["score_breakdown"] = score_data["breakdown"]
            return img, reg

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            visual_results = list(pool.map(_score_single_item, enumerate(visual_results, start=1)))

        # 4. Export Annotated Original Canvas PDF (Original pages with Green Boxes + Badges)
        pdf_export_ok = False
        if self.config.export_annotated_pdf and output_pdf_path:
            pdf_export_ok = self.annotator.export_canvas_annotated_pdf(
                canvas=canvas,
                regions=[reg for _, reg in visual_results],
                output_pdf_path=output_pdf_path,
                source_offsets=source_offsets
            )


        # 5. Export Clean WebP Frames to Images Directory
        saved_pages_meta = []
        if self.config.export_webp_frames and output_images_dir:
            temp_staging_dir = output_images_dir + "_staging_pure_visual"
            if os.path.exists(temp_staging_dir):
                shutil.rmtree(temp_staging_dir, ignore_errors=True)
            os.makedirs(temp_staging_dir, exist_ok=True)

            import concurrent.futures

            def save_single_webp(item):
                idx, (crop_img, region_meta) = item
                filename = f"{idx:03d}.webp"
                file_path = os.path.join(temp_staging_dir, filename)
                cv2.imwrite(file_path, crop_img, [cv2.IMWRITE_WEBP_QUALITY, 85])
                region_meta.file_name = filename
                region_meta.file_path = file_path
                return region_meta.to_dict()

            with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, os.cpu_count() or 8)) as pool:
                saved_pages_meta = list(pool.map(save_single_webp, enumerate(visual_results, start=1)))

            # Atomically replace destination images directory
            os.makedirs(output_images_dir, exist_ok=True)
            for f in os.listdir(output_images_dir):
                fp = os.path.join(output_images_dir, f)
                if os.path.isfile(fp):
                    try:
                        os.remove(fp)
                    except Exception:
                        pass

            for f in os.listdir(temp_staging_dir):
                src = os.path.join(temp_staging_dir, f)
                dst = os.path.join(output_images_dir, f)
                shutil.move(src, dst)

            shutil.rmtree(temp_staging_dir, ignore_errors=True)
            logger.info(f"[PureVisualPipeline] Successfully saved {len(saved_pages_meta)} clean WebP frames in {output_images_dir}")

        # 6. Export Metadata JSON with Junk Audit
        if output_metadata_path:
            meta_dir = os.path.dirname(output_metadata_path)
            if meta_dir:
                os.makedirs(meta_dir, exist_ok=True)

            audit_data = {
                "canvas_width": w_canvas,
                "canvas_height": h_canvas,
                "total_candidate_regions": len(raw_results),
                "total_pure_visual_regions": len(visual_results),
                "total_junk_dropped": len(dropped_audit),
                "filtered_junk_regions": dropped_audit,
                "pdf_exported": pdf_export_ok,
                "pdf_path": output_pdf_path,
                "regions": [r.to_dict() for _, r in visual_results]
            }
            with open(output_metadata_path, "w", encoding="utf-8") as f:
                json.dump(audit_data, f, ensure_ascii=False, indent=2)

        return PipelineResult(
            canvas_width=w_canvas,
            canvas_height=h_canvas,
            regions=[r for _, r in visual_results],
            statistics={
                "total_regions": len(visual_results),
                "total_candidates": len(raw_results),
                "total_junk_dropped": len(dropped_audit),
                "pdf_exported": pdf_export_ok
            }
        )

