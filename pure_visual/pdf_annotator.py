# -*- coding: utf-8 -*-
"""
PURE VISUAL REGION DETECTION: PDF ANNOTATOR & EXPORTER
Annotates visual regions with prominent green bounding boxes, Start/End badges,
and compiles physical pages into a high-fidelity PDF document using PyMuPDF.
"""
import os
import logging
from typing import List, Tuple, Dict, Any, Optional
import cv2
import numpy as np
from PIL import Image

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None

from pure_visual.types import PureVisualRegion, BBox
from pure_visual.config import DetectionConfig

logger = logging.getLogger("PDFAnnotator")


class PDFAnnotator:
    """
    Renders visual bounding boxes, Start: R{idx} / End: R{idx} badges,
    and outputs multi-page PDF documents.
    """

    def __init__(self, config: Optional[DetectionConfig] = None):
        self.config = config or DetectionConfig()

    def annotate_frame(
        self,
        img: np.ndarray,
        region_id: Any,
        custom_label: Optional[str] = None,
        score: Optional[Any] = None
    ) -> np.ndarray:
        """
        Draws prominent green bounding box and Start/End badges on a visual frame.
        
        Args:
            img: BGR numpy image array of the visual region.
            region_id: Index or ID of the region (e.g. 1 or 'R1').
            custom_label: Optional label override.
            score: Optional visual quality score (0-100 or 0.0-1.0).
            
        Returns:
            Annotated BGR numpy image array.
        """
        if img is None or img.size == 0:
            return img

        annotated = img.copy()
        h, w = annotated.shape[:2]
        if h <= 0 or w <= 0:
            return annotated

        # Normalize region ID string
        r_str = str(region_id).strip()
        if not r_str.upper().startswith("R") and r_str.isdigit():
            r_str = f"R{r_str}"
        elif not r_str.upper().startswith("R"):
            r_str = f"R{r_str}"

        # Check if score is <= min_annotation_score
        score_int = None
        if score is not None:
            if isinstance(score, float) and score <= 1.0:
                score_int = int(round(score * 100))
            else:
                score_int = int(round(score))

        min_score = getattr(self.config, "min_annotation_score", 55)
        if score_int is not None and score_int <= min_score:
            # Skip bounding box and badges for regions with score <= 55
            return annotated

        if custom_label:
            start_text = custom_label
        else:
            start_text = f"Start: {r_str}"

        end_text = f"End: {r_str}"

        # 1. Dynamic scale calculation based on image width
        # Reference width: 1000px -> scale 1.0, thickness 6px
        scale_ref = max(0.6, min(3.0, w / 900.0))
        box_thickness = max(4, int(round(self.config.box_thickness * scale_ref)))
        font_scale = max(0.65, min(2.5, 0.95 * scale_ref))
        font_thickness = max(2, int(round(2.2 * scale_ref)))
        pad_x = max(10, int(round(self.config.badge_padding_x * scale_ref)))
        pad_y = max(8, int(round(self.config.badge_padding_y * scale_ref)))
        margin = max(6, int(round(8 * scale_ref)))

        # Colors (BGR)
        green_box_bgr = (0, 255, 0)         # Bright Neon Green
        black_bgr = (0, 0, 0)
        badge_bg_bgr = (0, 150, 0)          # Solid dark-green container
        badge_border_bgr = (255, 255, 255)  # White crisp border
        text_color_bgr = (255, 255, 255)    # White bold text
        font = cv2.FONT_HERSHEY_DUPLEX

        # 2. Draw Prominent Green Bounding Box (Inner border so it doesn't get clipped)
        half_thick = box_thickness // 2
        # Outer contrast shadow for border
        cv2.rectangle(
            annotated,
            (half_thick - 1, half_thick - 1),
            (w - 1 - half_thick + 1, h - 1 - half_thick + 1),
            black_bgr,
            thickness=box_thickness + 4
        )
        # Main Bright Green Box
        cv2.rectangle(
            annotated,
            (half_thick, half_thick),
            (w - 1 - half_thick, h - 1 - half_thick),
            green_box_bgr,
            thickness=box_thickness
        )

        # 3. Helper to draw Badge Pill/Box
        def draw_badge(text: str, pos_top_left: Tuple[int, int], is_bottom_right: bool = False):
            (t_w, t_h), baseline = cv2.getTextSize(text, font, font_scale, font_thickness)
            badge_w = t_w + 2 * pad_x
            badge_h = t_h + 2 * pad_y

            if is_bottom_right:
                bx1 = w - margin - badge_w
                by1 = h - margin - badge_h
            else:
                bx1 = margin + box_thickness
                by1 = margin + box_thickness

            bx2 = bx1 + badge_w
            by2 = by1 + badge_h

            # Clip coordinates
            bx1 = max(0, min(w - 1, bx1))
            by1 = max(0, min(h - 1, by1))
            bx2 = max(0, min(w - 1, bx2))
            by2 = max(0, min(h - 1, by2))

            # Drop shadow / Dark outline
            shadow_offset = max(2, int(3 * scale_ref))
            cv2.rectangle(
                annotated,
                (bx1 + shadow_offset, by1 + shadow_offset),
                (bx2 + shadow_offset, by2 + shadow_offset),
                (20, 20, 20),
                -1
            )

            # Badge Body (Solid Green)
            cv2.rectangle(annotated, (bx1, by1), (bx2, by2), badge_bg_bgr, -1)
            # Badge Border (Bright Green + White Accent)
            cv2.rectangle(annotated, (bx1, by1), (bx2, by2), green_box_bgr, max(2, int(2 * scale_ref)))

            # Text Position (baseline aligned)
            tx = bx1 + pad_x
            ty = by1 + pad_y + t_h

            # Text shadow for maximum legibility
            cv2.putText(annotated, text, (tx + 1, ty + 1), font, font_scale, black_bgr, font_thickness + 1, cv2.LINE_AA)
            # Main Text
            cv2.putText(annotated, text, (tx, ty), font, font_scale, text_color_bgr, font_thickness, cv2.LINE_AA)

        # Draw Top-Left Start Badge
        draw_badge(start_text, (margin, margin), is_bottom_right=False)

        # Draw Bottom-Right End Badge
        draw_badge(end_text, (0, 0), is_bottom_right=True)

        return annotated

    def annotate_canvas_slice(
        self,
        slice_img: np.ndarray,
        slice_y_start: int,
        slice_y_end: int,
        regions: List[PureVisualRegion]
    ) -> np.ndarray:
        """
        Draws prominent green bounding boxes and Start: R{idx} / End: R{idx} badges
        for all pure visual regions that intersect with the given original canvas slice.

        Args:
            slice_img: BGR numpy image array of the canvas slice / comic page.
            slice_y_start: Global Y start coordinate of the slice on the canvas.
            slice_y_end: Global Y end coordinate of the slice on the canvas.
            regions: List of detected PureVisualRegion objects.

        Returns:
            Annotated BGR numpy image array of the slice.
        """
        if slice_img is None or slice_img.size == 0:
            return slice_img

        annotated = slice_img.copy()
        h, w = annotated.shape[:2]
        if h <= 0 or w <= 0:
            return annotated

        scale_ref = max(0.6, min(3.0, w / 900.0))
        box_thickness = max(4, int(round(self.config.box_thickness * scale_ref)))
        font_scale = max(0.65, min(2.5, 0.95 * scale_ref))
        font_thickness = max(2, int(round(2.2 * scale_ref)))
        pad_x = max(10, int(round(self.config.badge_padding_x * scale_ref)))
        pad_y = max(8, int(round(self.config.badge_padding_y * scale_ref)))

        green_box_bgr = (0, 255, 0)         # Bright Neon Green
        black_bgr = (0, 0, 0)
        badge_bg_bgr = (0, 150, 0)          # Solid dark-green container
        text_color_bgr = (255, 255, 255)    # White bold text
        font = cv2.FONT_HERSHEY_DUPLEX

        def draw_badge(text: str, bx: int, by: int, is_bottom_right: bool = False):
            (t_w, t_h), baseline = cv2.getTextSize(text, font, font_scale, font_thickness)
            badge_w = t_w + 2 * pad_x
            badge_h = t_h + 2 * pad_y

            if is_bottom_right:
                bx1 = bx - badge_w - box_thickness
                by1 = by - badge_h - box_thickness
            else:
                bx1 = bx + box_thickness
                by1 = by + box_thickness

            bx2 = bx1 + badge_w
            by2 = by1 + badge_h

            bx1 = max(0, min(w - 1, bx1))
            by1 = max(0, min(h - 1, by1))
            bx2 = max(0, min(w - 1, bx2))
            by2 = max(0, min(h - 1, by2))

            # Drop shadow
            shadow_offset = max(2, int(3 * scale_ref))
            cv2.rectangle(
                annotated,
                (bx1 + shadow_offset, by1 + shadow_offset),
                (bx2 + shadow_offset, by2 + shadow_offset),
                (20, 20, 20),
                -1
            )
            # Solid green container
            cv2.rectangle(annotated, (bx1, by1), (bx2, by2), badge_bg_bgr, -1)
            # Green border
            cv2.rectangle(annotated, (bx1, by1), (bx2, by2), green_box_bgr, max(2, int(2 * scale_ref)))

            # Text
            tx = bx1 + pad_x
            ty = by1 + pad_y + t_h
            cv2.putText(annotated, text, (tx + 1, ty + 1), font, font_scale, black_bgr, font_thickness + 1, cv2.LINE_AA)
            cv2.putText(annotated, text, (tx, ty), font, font_scale, text_color_bgr, font_thickness, cv2.LINE_AA)

        for reg in regions:
            ob = reg.original_bbox if hasattr(reg, "original_bbox") else reg.get("original_bbox")
            if isinstance(ob, BBox):
                rx1, ry1, rx2, ry2 = ob.x1, ob.y1, ob.x2, ob.y2
            else:
                rx1, ry1, rx2, ry2 = ob[0], ob[1], ob[2], ob[3]

            rid = getattr(reg, "region_id", 1) if hasattr(reg, "region_id") else reg.get("region_id", 1)
            r_str = f"R{rid}" if str(rid).isdigit() else str(rid)

            # Extract point score if available
            score_val = None
            if isinstance(reg, PureVisualRegion):
                if reg.details:
                    score_val = reg.details.get("score_100")
                    if score_val is None:
                        score_val = reg.details.get("pure_visual_score")
            elif isinstance(reg, dict):
                details = reg.get("details", {})
                score_val = details.get("score_100") or details.get("pure_visual_score") or reg.get("score_100")

            score_int = None
            if score_val is not None:
                if isinstance(score_val, float) and score_val <= 1.0:
                    score_int = int(round(score_val * 100))
                else:
                    score_int = int(round(score_val))

            min_score = getattr(self.config, "min_annotation_score", 55)
            if score_int is not None and score_int <= min_score:
                # Do not draw bounding box / badges for regions with score <= 55
                continue

            start_label = f"Start: {r_str}"

            # Check if this visual region intersects the current slice
            if ry2 > slice_y_start and ry1 < slice_y_end:
                bx1 = max(0, min(w - 1, rx1))
                bx2 = max(0, min(w - 1, rx2))
                by1 = max(0, min(h - 1, ry1 - slice_y_start))
                by2 = max(0, min(h - 1, ry2 - slice_y_start))

                if by2 <= by1 or bx2 <= bx1:
                    continue

                # Outer contrast shadow for border
                cv2.rectangle(annotated, (bx1 - 2, by1 - 2), (bx2 + 2, by2 + 2), black_bgr, thickness=box_thickness + 4)
                # Main Bright Green Box
                cv2.rectangle(annotated, (bx1, by1), (bx2, by2), green_box_bgr, thickness=box_thickness)

                # Draw Start Badge:
                # If top of region starts on this slice (ry1 >= slice_y_start): draw at by1
                # If top of region started on a previous slice (ry1 < slice_y_start): draw at by1=0 as (Cont.)
                if ry1 >= slice_y_start:
                    draw_badge(start_label, bx1, by1, is_bottom_right=False)
                else:
                    draw_badge(f"{start_label} (Cont.)", bx1, 0, is_bottom_right=False)

                # Draw End Badge:
                # If bottom of region ends on this slice (ry2 <= slice_y_end): draw at by2
                # If bottom of region continues to next slice (ry2 > slice_y_end): draw at by2=h-1 as (Cont.)
                if ry2 <= slice_y_end:
                    draw_badge(f"End: {r_str}", bx2, by2, is_bottom_right=True)
                else:
                    draw_badge(f"End: {r_str} (Cont.)", bx2, h - 1, is_bottom_right=True)

        return annotated

    def export_canvas_annotated_pdf(
        self,
        canvas: np.ndarray,
        regions: List[PureVisualRegion],
        output_pdf_path: str,
        source_offsets: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """
        Exports the entire original comic image canvas to a multi-page PDF,
        with each page being an original slice/page annotated with visual region green boxes and badges.

        Args:
            canvas: Complete stitched comic canvas.
            regions: List of detected PureVisualRegion objects.
            output_pdf_path: Target path for the output PDF file.
            source_offsets: Optional list of original slice offset dicts.

        Returns:
            True if PDF export succeeded, False otherwise.
        """
        if canvas is None or canvas.size == 0:
            logger.warning("[PDFAnnotator] Empty canvas provided for PDF export.")
            return False

        h_canvas, w_canvas = canvas.shape[:2]
        out_dir = os.path.dirname(output_pdf_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        # Determine slice segments
        slice_segments: List[Tuple[int, int]] = []
        if source_offsets:
            for item in source_offsets:
                sy1 = int(item.get("y_start", item.get("offset_y_start", item.get("yStart", 0))))
                sy2 = int(item.get("y_end", item.get("offset_y_end", item.get("yEnd", sy1 + item.get("height", 0)))))
                if sy2 > sy1:
                    slice_segments.append((sy1, sy2))

        if not slice_segments:
            # Fallback: slice into standard 2500px tall pages
            page_h = 2500
            for sy1 in range(0, h_canvas, page_h):
                sy2 = min(h_canvas, sy1 + page_h)
                slice_segments.append((sy1, sy2))

        logger.info(f"[PDFAnnotator] Exporting {len(slice_segments)} original canvas pages with visual regions to PDF: {output_pdf_path}")

        try:
            import concurrent.futures

            def _render_and_encode_slice(item):
                p_idx, (sy1, sy2) = item
                slice_img = canvas[sy1:sy2, :]
                annotated_slice = self.annotate_canvas_slice(slice_img, sy1, sy2, regions)
                h, w = annotated_slice.shape[:2]

                # Max width optimization for fast VLM reading (1000px)
                if w > 1000:
                    target_w = 1000
                    target_h = max(1, int(round(h * (1000.0 / float(w)))))
                    annotated_slice = cv2.resize(annotated_slice, (target_w, target_h), interpolation=cv2.INTER_AREA)
                    h, w = target_h, target_w

                success, buffer = cv2.imencode('.jpg', annotated_slice, [cv2.IMWRITE_JPEG_QUALITY, self.config.pdf_quality])
                if not success:
                    return p_idx, None, 0, 0
                return p_idx, buffer.tobytes(), w, h

            workers = min(12, os.cpu_count() or 6)
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                encoded_slices = list(pool.map(_render_and_encode_slice, enumerate(slice_segments, start=1)))

            # Sort back in sequential page order
            encoded_slices.sort(key=lambda x: x[0])

            if fitz is not None:
                doc = fitz.open()
                for p_idx, buf_bytes, w, h in encoded_slices:
                    if buf_bytes is None:
                        continue
                    page = doc.new_page(width=float(w), height=float(h))
                    rect = fitz.Rect(0, 0, float(w), float(h))
                    page.insert_image(rect, stream=buf_bytes)

                doc.save(output_pdf_path, deflate=True, garbage=4, clean=True)
                doc.close()
                logger.info(f"[PDFAnnotator] Successfully saved compressed original canvas PDF via PyMuPDF ({len(slice_segments)} pages): {output_pdf_path}")
                return True
            else:
                pil_images = []
                import io
                for p_idx, buf_bytes, w, h in encoded_slices:
                    if buf_bytes is None:
                        continue
                    pil_images.append(Image.open(io.BytesIO(buf_bytes)))

                if pil_images:
                    pil_images[0].save(
                        output_pdf_path,
                        save_all=True,
                        append_images=pil_images[1:],
                        quality=self.config.pdf_quality
                    )
                    logger.info(f"[PDFAnnotator] Successfully saved original canvas PDF via PIL ({len(pil_images)} pages): {output_pdf_path}")
                    return True
                return False
        except Exception as e:
            logger.error(f"[PDFAnnotator] Failed to export canvas PDF to {output_pdf_path}: {e}", exc_info=True)
            return False

    def export_pdf(
        self,
        frames: List[Tuple[np.ndarray, Any]],
        output_pdf_path: str,
        annotate: bool = True
    ) -> bool:
        """
        Exports a sequence of visual frames into a multi-page PDF document.
        Each frame corresponds to 1 physical page.

        Args:
            frames: List of (image_array, region_id_or_meta) tuples.
            output_pdf_path: Path where the output PDF file will be saved.
            annotate: If True, draws green bounding boxes and Start/End badges.

        Returns:
            True if PDF export succeeded, False otherwise.
        """
        if not frames:
            logger.warning("[PDFAnnotator] No visual frames provided to export PDF.")
            return False

        out_dir = os.path.dirname(output_pdf_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        logger.info(f"[PDFAnnotator] Exporting {len(frames)} visual pages to PDF: {output_pdf_path}")

        try:
            if fitz is not None:
                # Use PyMuPDF for fast, direct PDF generation
                doc = fitz.open()
                for idx, (img, meta) in enumerate(frames, start=1):
                    if img is None or img.size == 0:
                        continue

                    region_id = getattr(meta, "region_id", idx) if hasattr(meta, "region_id") else idx
                    score_val = None
                    if hasattr(meta, "details") and meta.details:
                        score_val = meta.details.get("score_100") or meta.details.get("pure_visual_score")
                    elif isinstance(meta, dict):
                        details = meta.get("details", {})
                        score_val = details.get("score_100") or details.get("pure_visual_score") or meta.get("score_100")

                    if annotate:
                        render_img = self.annotate_frame(img, region_id, score=score_val)
                    else:
                        render_img = img

                    h, w = render_img.shape[:2]
                    # Encode to JPEG in memory for PDF embedding
                    success, buffer = cv2.imencode('.jpg', render_img, [cv2.IMWRITE_JPEG_QUALITY, self.config.pdf_quality])
                    if not success:
                        continue

                    # Insert physical page with exact pixel dimensions
                    page = doc.new_page(width=float(w), height=float(h))
                    rect = fitz.Rect(0, 0, float(w), float(h))
                    page.insert_image(rect, stream=buffer.tobytes())

                doc.save(output_pdf_path)
                doc.close()
                logger.info(f"[PDFAnnotator] Successfully saved PDF via PyMuPDF ({len(frames)} pages): {output_pdf_path}")
                return True
            else:
                # Fallback to PIL Image PDF export
                pil_images = []
                for idx, (img, meta) in enumerate(frames, start=1):
                    if img is None or img.size == 0:
                        continue
                    region_id = getattr(meta, "region_id", idx) if hasattr(meta, "region_id") else idx
                    score_val = None
                    if hasattr(meta, "details") and meta.details:
                        score_val = meta.details.get("score_100") or meta.details.get("pure_visual_score")
                    elif isinstance(meta, dict):
                        details = meta.get("details", {})
                        score_val = details.get("score_100") or details.get("pure_visual_score") or meta.get("score_100")

                    if annotate:
                        render_img = self.annotate_frame(img, region_id, score=score_val)
                    else:
                        render_img = img
                    # Convert BGR to RGB
                    rgb = cv2.cvtColor(render_img, cv2.COLOR_BGR2RGB)
                    pil_images.append(Image.fromarray(rgb))

                if pil_images:
                    pil_images[0].save(
                        output_pdf_path,
                        save_all=True,
                        append_images=pil_images[1:],
                        quality=self.config.pdf_quality
                    )
                    logger.info(f"[PDFAnnotator] Successfully saved PDF via PIL ({len(pil_images)} pages): {output_pdf_path}")
                    return True
                return False
        except Exception as e:
            logger.error(f"[PDFAnnotator] Failed to export PDF to {output_pdf_path}: {e}", exc_info=True)
            return False

