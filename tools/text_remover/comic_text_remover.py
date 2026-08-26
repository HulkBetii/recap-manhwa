import os
import sys
# Optimize CUDA memory allocation to avoid fragmentation and OOM
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
# Enable CPU fallback for unsupported MPS operators on macOS
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
import argparse
import time
import logging
import json
import csv
import numpy as np
import cv2
from PIL import Image

import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ComicTextRemover")

import threading

# Lazy loading of optional heavy packages
easyocr_reader = None
ocr_lock = threading.Lock()

def get_easyocr_reader(languages=['en']):
    global easyocr_reader
    if easyocr_reader is None:
        try:
            import easyocr
            logger.info(f"Initializing EasyOCR reader for languages: {languages}...")
            import torch
            has_cuda = torch.cuda.is_available()
            if has_cuda:
                torch.backends.cudnn.benchmark = True
            has_mps = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
            gpu_available = has_cuda or has_mps
            logger.info(f"GPU acceleration available for PyTorch: {gpu_available} (CUDA: {has_cuda}, MPS: {has_mps})")
            easyocr_reader = easyocr.Reader(languages, gpu=gpu_available)
            if has_mps:
                try:
                    easyocr_reader.device = 'mps'
                    easyocr_reader.detector.to('mps')
                    easyocr_reader.recognizer.to('mps')
                    logger.info("EasyOCR successfully mapped to Apple Silicon GPU (MPS)")
                except Exception as mps_err:
                    logger.warning(f"Failed to map EasyOCR to MPS: {mps_err}. Running on CPU fallback.")
        except Exception as e:
            logger.error(f"Failed to initialize EasyOCR: {e}")
            raise e
    return easyocr_reader


def classical_detect_text_regions(gray_img):
    """
    Classical computer vision text region detector using morphological operations
    as a fallback if EasyOCR is unavailable.
    """
    h, w = gray_img.shape
    # Highlight high-contrast edge regions (character strokes)
    grad = cv2.morphologyEx(
        gray_img, 
        cv2.MORPH_GRADIENT, 
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    )
    
    # Threshold to binarize
    _, thresh = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Close gaps horizontally and vertically to merge text lines/paragraphs
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    
    # Find contours of candidate regions
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    bboxes = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        # Filter regions that are likely to be text blocks
        # (width between 12px and 400px, height between 10px and 120px, aspect ratio)
        if 12 <= cw <= 400 and 10 <= ch <= 120:
            area_ratio = cv2.contourArea(cnt) / (cw * ch)
            if area_ratio > 0.3:
                bboxes.append((x, y, x + cw, y + ch))
                
    return bboxes


def segment_bubble_floodfill(gray_img, seed_point, max_area_ratio=0.20):
    """
    Finds the speech bubble mask containing seed_point using a flood-fill algorithm.
    If the seed point is dark (part of text stroke), we search locally for a bright pixel.
    """
    h, w = gray_img.shape
    cx, cy = seed_point
    
    # Clamp seed coordinates
    cx = max(0, min(w - 1, cx))
    cy = max(0, min(h - 1, cy))
    
    # If the seed pixel is dark, search in a small local window for the brightest pixel
    if gray_img[cy, cx] < 128:
        win = 10
        x_min = max(0, cx - win)
        x_max = min(w - 1, cx + win)
        y_min = max(0, cy - win)
        y_max = min(h - 1, cy + win)
        
        local_roi = gray_img[y_min:y_max+1, x_min:x_max+1]
        _, _, _, max_loc = cv2.minMaxLoc(local_roi)
        cx = x_min + max_loc[0]
        cy = y_min + max_loc[1]
        
    # Check if the seed pixel is sufficiently bright (speech bubbles are white/light)
    if gray_img[cy, cx] < 170:
        return None
        
    # Setup flood fill mask (must be h+2, w+2)
    ff_mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
    temp_img = gray_img.copy()
    
    # Perform flood fill with intensity tolerance (loDiff, upDiff) to stop at bubble outline
    cv2.floodFill(
        temp_img, ff_mask, (cx, cy), 255, 
        loDiff=25, upDiff=25, 
        flags=4 | cv2.FLOODFILL_MASK_ONLY
    )
    
    bubble_mask = ff_mask[1:-1, 1:-1]
    
    # Safety Check: If the bubble mask spans too much area (flood-fill spilled to background), reject it
    mask_pixels = np.sum(bubble_mask == 255)
    if mask_pixels > (h * w * max_area_ratio) or mask_pixels == 0:
        return None
        
    return bubble_mask


def generate_rectangular_mask(img_shape, bbox, padding=25):
    """
    Generates a fallback localized rectangular mask around the text bounding box.
    Used if flood-fill fails or spills over.
    """
    h, w = img_shape[:2]
    x1, y1, x2, y2 = bbox
    
    px1 = max(0, x1 - padding)
    py1 = max(0, y1 - padding)
    px2 = min(w, x2 + padding)
    py2 = min(h, y2 + padding)
    
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[py1:py2, px1:px2] = 255
    return mask


def create_text_stroke_mask(gray_img, bubble_mask, fallback_bbox, brightness_clip=120):
    """
    Isolates text strokes inside the bubble mask using localized Otsu thresholding.
    """
    h, w = gray_img.shape
    active_mask = bubble_mask if bubble_mask is not None else generate_rectangular_mask((h, w), fallback_bbox, padding=10)
    
    # Extract intensity distribution inside the masked region
    pixels = gray_img[active_mask > 0]
    if len(pixels) > 0:
        # Compute threshold to isolate text strokes (which are dark characters on white bg)
        ret, _ = cv2.threshold(pixels, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        thresh_val = min(ret, brightness_clip)
    else:
        thresh_val = brightness_clip
        
    # Mask dark pixels inside the active bubble area
    text_mask = np.zeros((h, w), dtype=np.uint8)
    text_mask[(active_mask > 0) & (gray_img < thresh_val)] = 255
    
    # Dilate text stroke mask slightly to fully cover characters and anti-aliased margins
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    dilated_mask = cv2.dilate(text_mask, kernel, iterations=1)
    
    return dilated_mask


def compute_metrics(original_img, cleaned_img, text_mask):
    """
    Computes quantitative evaluation metrics between the original and processed images.
    """
    from skimage.metrics import peak_signal_noise_ratio, structural_similarity
    
    # Convert BGR to Grayscale for fast/stable metric calculations
    gray_orig = cv2.cvtColor(original_img, cv2.COLOR_BGR2GRAY)
    gray_clean = cv2.cvtColor(cleaned_img, cv2.COLOR_BGR2GRAY)
    
    def safe_psnr(img1, img2):
        if np.array_equal(img1, img2):
            return float('inf')
        return peak_signal_noise_ratio(img1, img2)

    # Overall metrics
    overall_psnr = safe_psnr(gray_orig, gray_clean)
    overall_ssim = structural_similarity(gray_orig, gray_clean)
    
    # Background preservation metrics (exclude the modified inpainted pixels)
    gray_orig_bg = gray_orig.copy()
    gray_clean_bg = gray_clean.copy()
    gray_orig_bg[text_mask > 0] = 0
    gray_clean_bg[text_mask > 0] = 0
    
    bg_psnr = safe_psnr(gray_orig_bg, gray_clean_bg)
    bg_ssim = structural_similarity(gray_orig_bg, gray_clean_bg)
    
    # Inpainted pixel ratio
    inpainted_ratio = float(np.sum(text_mask > 0) / (gray_orig.shape[0] * gray_orig.shape[1]))
    
    return {
        "overall_psnr": overall_psnr,
        "overall_ssim": overall_ssim,
        "bg_psnr": bg_psnr,
        "bg_ssim": bg_ssim,
        "inpainted_pixel_ratio": inpainted_ratio
    }


def process_image(img_path, output_path, debug_dir=None, conf_threshold=0.3, inpaint_radius=3, languages=['en'], use_fallback=True, verify_ocr=False):
    """
    Processes a single comic image: detects text, segments bubbles, inpaints text, and returns metrics.
    """
    start_time = time.time()
    
    original_img = cv2.imread(img_path)
    if original_img is None:
        raise ValueError(f"Could not load image at {img_path}")
        
    gray_img = cv2.cvtColor(original_img, cv2.COLOR_BGR2GRAY)
    h, w = gray_img.shape
    
    # 1. Text Bounding Boxes Detection
    text_regions = []  # List of bboxes as (x_min, y_min, x_max, y_max)
    ocr_texts = []
    
    ocr_successful = False
    try:
        reader = get_easyocr_reader(languages)
        with ocr_lock:
            ocr_results = reader.readtext(original_img)
        for bbox, text, conf in ocr_results:
            if conf >= conf_threshold:
                # bbox format is [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
                xs = [pt[0] for pt in bbox]
                ys = [pt[1] for pt in bbox]
                x_min, y_min = int(min(xs)), int(min(ys))
                x_max, y_max = int(max(xs)), int(max(ys))
                text_regions.append((x_min, y_min, x_max, y_max))
                ocr_texts.append(text)
        ocr_successful = True
    except Exception as e:
        logger.warning(f"EasyOCR detection failed or skipped: {e}. Falling back to classical CV detection: {use_fallback}")
        
    if not ocr_successful and use_fallback:
        text_regions = classical_detect_text_regions(gray_img)
        ocr_texts = ["" for _ in text_regions]
        
    # 2. Adaptive text region cleaning
    cleaned_img = original_img.copy()
    global_text_mask = np.zeros((h, w), dtype=np.uint8)
    global_bubble_mask = np.zeros((h, w), dtype=np.uint8)
    
    padding = 2  # 2 pixels of padding to cover anti-aliasing edges
    
    for idx, bbox in enumerate(text_regions):
        x_min, y_min, x_max, y_max = bbox
        
        # Clamp coordinates
        x1 = max(0, x_min - padding)
        y1 = max(0, y_min - padding)
        x2 = min(w, x_max + padding)
        y2 = min(h, y_max + padding)
        
        # Sample border pixels (e.g. 3px margin around the box)
        border_pixels = []
        b_margin = 3
        
        # Top border
        bx1 = max(0, x1 - b_margin)
        bx2 = min(w, x2 + b_margin)
        by1 = max(0, y1 - b_margin)
        by2 = y1
        if by2 > by1 and bx2 > bx1:
            border_pixels.append(original_img[by1:by2, bx1:bx2].reshape(-1, 3))
            
        # Bottom border
        by1 = y2
        by2 = min(h, y2 + b_margin)
        if by2 > by1 and bx2 > bx1:
            border_pixels.append(original_img[by1:by2, bx1:bx2].reshape(-1, 3))
            
        # Left border
        bx1 = max(0, x1 - b_margin)
        bx2 = x1
        by1 = y1
        by2 = y2
        if bx2 > bx1 and by2 > by1:
            border_pixels.append(original_img[by1:by2, bx1:bx2].reshape(-1, 3))
            
        # Right border
        bx1 = x2
        bx2 = min(w, x2 + b_margin)
        if bx2 > bx1 and by2 > by1:
            border_pixels.append(original_img[by1:by2, bx1:bx2].reshape(-1, 3))
            
        # If we successfully collected border pixels, compute background color and variance
        if border_pixels:
            all_borders = np.vstack(border_pixels)
            # Compute median BGR color
            median_color = np.median(all_borders, axis=0).astype(np.uint8)
            # Convert border pixels to Grayscale to calculate standard deviation
            gray_borders = 0.299 * all_borders[:, 2] + 0.587 * all_borders[:, 1] + 0.114 * all_borders[:, 0]
            std_dev = np.std(gray_borders)
        else:
            median_color = np.array([255, 255, 255], dtype=np.uint8)  # Default to white
            std_dev = 0.0
            
        # Accumulate mask for metric calculation
        cv2.rectangle(global_text_mask, (x1, y1), (x2, y2), 255, -1)
        
        # If the background is uniform (standard deviation < 18), fill with solid background color.
        # Otherwise, inpaint locally.
        if std_dev < 18.0:
            color_tuple = (int(median_color[0]), int(median_color[1]), int(median_color[2]))
            cv2.rectangle(cleaned_img, (x1, y1), (x2, y2), color_tuple, -1)
        else:
            local_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.rectangle(local_mask, (x1, y1), (x2, y2), 255, -1)
            cleaned_img = cv2.inpaint(cleaned_img, local_mask, inpaintRadius=inpaint_radius, flags=cv2.INPAINT_TELEA)
    
    # Save cleaned image
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cv2.imwrite(output_path, cleaned_img)
    
    # 4. Evaluation Metrics
    metrics = compute_metrics(original_img, cleaned_img, global_text_mask)
    metrics["text_count_detected_before"] = len(text_regions)
    
    # Verify text removal by running OCR again on the cleaned image
    metrics["text_count_detected_after"] = 0
    if verify_ocr and ocr_successful:
        try:
            reader = get_easyocr_reader(languages)
            with ocr_lock:
                post_ocr = reader.readtext(cleaned_img)
            post_regions = [r for r in post_ocr if r[2] >= conf_threshold]
            metrics["text_count_detected_after"] = len(post_regions)
        except Exception:
            pass
            
    metrics["processing_time_sec"] = time.time() - start_time
    
    # 5. Output Debugging assets if requested
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(img_path))[0]
        
        # Save raw masks
        cv2.imwrite(os.path.join(debug_dir, f"{base_name}_text_mask.png"), global_text_mask)
        cv2.imwrite(os.path.join(debug_dir, f"{base_name}_bubble_mask.png"), global_bubble_mask)
        
        # Save Bounding Box Overlay for review
        bbox_overlay = original_img.copy()
        for idx, (x_min, y_min, x_max, y_max) in enumerate(text_regions):
            cv2.rectangle(bbox_overlay, (x_min, y_min), (x_max, y_max), (0, 0, 255), 2)
            if ocr_texts[idx]:
                cv2.putText(
                    bbox_overlay, ocr_texts[idx], (x_min, y_min - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1
                )
        cv2.imwrite(os.path.join(debug_dir, f"{base_name}_detections_overlay.png"), bbox_overlay)
        
    return metrics


def batch_process_directory(input_dir, output_dir, debug_dir=None, conf_threshold=0.3, inpaint_radius=3, languages=['en'], use_fallback=True):
    """
    Processes all images inside input_dir and generates a summary CSV report.
    """
    valid_exts = ('.jpg', '.jpeg', '.png', '.webp')
    image_files = sorted([
        f for f in os.listdir(input_dir)
        if os.path.isfile(os.path.join(input_dir, f)) and f.lower().endswith(valid_exts)
    ])
    
    if not image_files:
        logger.warning(f"No valid images found in input directory: {input_dir}")
        return []
        
    logger.info(f"Found {len(image_files)} images to process.")
    os.makedirs(output_dir, exist_ok=True)
    
    results = []
    
    for idx, f_name in enumerate(image_files, 1):
        in_path = os.path.join(input_dir, f_name)
        out_path = os.path.join(output_dir, f_name)
        img_debug_dir = os.path.join(debug_dir, os.path.splitext(f_name)[0]) if debug_dir else None
        
        logger.info(f"[{idx}/{len(image_files)}] Processing {f_name}...")
        try:
            metrics = process_image(
                img_path=in_path,
                output_path=out_path,
                debug_dir=img_debug_dir,
                conf_threshold=conf_threshold,
                inpaint_radius=inpaint_radius,
                languages=languages,
                use_fallback=use_fallback
            )
            metrics["filename"] = f_name
            metrics["status"] = "SUCCESS"
            results.append(metrics)
            
            logger.info(
                f"Completed {f_name}: Status={metrics['status']}, "
                f"Detections={metrics['text_count_detected_before']} -> {metrics['text_count_detected_after']}, "
                f"SSIM={metrics['overall_ssim']:.4f}, PSNR={metrics['overall_psnr']:.2f}dB"
            )
        except Exception as e:
            logger.error(f"Failed processing {f_name}: {e}", exc_info=True)
            results.append({
                "filename": f_name,
                "status": f"FAILED: {str(e)}",
                "overall_psnr": 0.0,
                "overall_ssim": 0.0,
                "bg_psnr": 0.0,
                "bg_ssim": 0.0,
                "inpainted_pixel_ratio": 0.0,
                "text_count_detected_before": 0,
                "text_count_detected_after": 0,
                "processing_time_sec": 0.0
            })
            
    # Write summary CSV report
    report_csv = os.path.join(output_dir, "processing_report.csv")
    if results:
        headers = list(results[0].keys())
        # Move filename to first column
        if "filename" in headers:
            headers.remove("filename")
            headers.insert(0, "filename")
            
        with open(report_csv, "w", newline="", encoding="utf-8") as rf:
            writer = csv.DictWriter(rf, fieldnames=headers)
            writer.writeheader()
            writer.writerows(results)
            
        logger.info(f"Metrics report saved successfully to: {report_csv}")
        
        # Compute and print average statistics of successful operations
        success_runs = [r for r in results if r["status"] == "SUCCESS"]
        if success_runs:
            avg_ssim = np.mean([r["overall_ssim"] for r in success_runs])
            avg_psnr = np.mean([r["overall_psnr"] for r in success_runs])
            avg_bg_ssim = np.mean([r["bg_ssim"] for r in success_runs])
            avg_erased = np.mean([r["text_count_detected_before"] - r["text_count_detected_after"] for r in success_runs])
            
            logger.info("==================================================")
            logger.info("SUMMARY REPORT - SUCCESSFUL RUNS:")
            logger.info(f"Total Successful Images: {len(success_runs)}")
            logger.info(f"Average Overall SSIM:    {avg_ssim:.4f}")
            logger.info(f"Average Background SSIM: {avg_bg_ssim:.4f} (Expected: 1.0000)")
            logger.info(f"Average Overall PSNR:    {avg_psnr:.2f} dB")
            logger.info(f"Average Text Erasures:   {avg_erased:.1f} lines per page")
            logger.info("==================================================")
            
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Automatic speech bubble text detection and inpainting preprocessing pipeline."
    )
    parser.add_argument(
        "--input-dir", required=True,
        help="Directory containing input comic/manga pages."
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="Directory to save the cleaned images."
    )
    parser.add_argument(
        "--debug-dir", default=None,
        help="Optional directory to save bounding boxes and intermediate segmentation masks."
    )
    parser.add_argument(
        "--conf-threshold", type=float, default=0.3,
        help="Confidence threshold for OCR text detection (default: 0.3)."
    )
    parser.add_argument(
        "--inpainting-radius", type=int, default=3,
        help="Inpainting radius for OpenCV FAST_MARCHING (default: 3)."
    )
    parser.add_argument(
        "--languages", default="en",
        help="Comma-separated language codes for EasyOCR model (default: 'en')."
    )
    parser.add_argument(
        "--disable-fallback", action="store_true",
        help="Disable classical CV layout analysis text detection fallback if EasyOCR is not loaded."
    )
    
    args = parser.parse_args()
    
    lang_list = [l.strip() for l in args.languages.split(",") if l.strip()]
    
    logger.info("Starting Comic Speech Bubble Text Remover...")
    batch_process_directory(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        debug_dir=args.debug_dir,
        conf_threshold=args.conf_threshold,
        inpaint_radius=args.inpainting_radius,
        languages=lang_list,
        use_fallback=not args.disable_fallback
    )

if __name__ == "__main__":
    main()
