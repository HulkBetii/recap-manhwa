import os
import math
import cv2
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw, ImageFont
from typing import Tuple, Optional, Dict
from renderer.types import AspectRatioCategory, BackgroundMode, RenderConfig


class ImageComposer:
    """
    Handles image aspect ratio detection, content bounding box detection,
    safe downscaling/upscaling, and background generation (ambient blur / dark canvas).
    """

    @staticmethod
    def categorize_aspect_ratio(width: int, height: int) -> AspectRatioCategory:
        if height <= 0 or width <= 0:
            return AspectRatioCategory.PORTRAIT_STANDARD
        ratio = width / height
        if ratio < 0.5:
            return AspectRatioCategory.PORTRAIT_TALL
        elif ratio < 0.95:
            return AspectRatioCategory.PORTRAIT_STANDARD
        elif ratio <= 1.05:
            return AspectRatioCategory.SQUARE
        elif ratio <= 1.85:
            return AspectRatioCategory.LANDSCAPE_STANDARD
        else:
            return AspectRatioCategory.LANDSCAPE_WIDE

    @staticmethod
    def detect_content_bounds(img: Image.Image) -> Tuple[int, int, int, int]:
        """
        Detect the active content bounding box (x, y, w, h) of a manhwa page/panel,
        stripping solid white/black margin bars if present.
        """
        try:
            from pure_visual.frame_refiner import PureVisualFrameRefiner
            refiner = PureVisualFrameRefiner()
            img_np = np.array(img.convert("RGB"))
            x, y, w, h = refiner.refine_frame(img_np)
            if w > 10 and h > 10:
                return int(x), int(y), int(w), int(h)
        except Exception:
            pass

        try:
            w, h = img.size
            if h < 20 or w < 20:
                return (0, 0, w, h)

            # Sample border pixels to detect background / gutter tone
            gray = np.array(img.convert("L"))
            border_pixels = np.concatenate([
                gray[0, :],          # top row
                gray[-1, :],         # bottom row
                gray[:, 0],          # left column
                gray[:, -1]          # right column
            ])
            bg_color = float(np.median(border_pixels))

            # Threshold for foreground detection
            if bg_color > 127:
                foreground_mask = gray < (bg_color - 18)
            else:
                foreground_mask = gray > (bg_color + 18)

            coords = np.argwhere(foreground_mask)
            if coords.size > 0:
                y_min, x_min = coords.min(axis=0)
                y_max, x_max = coords.max(axis=0)
                
                pad = 12
                x = max(0, int(x_min - pad))
                y = max(0, int(y_min - pad))
                width = min(w - x, int(x_max - x_min + 2 * pad))
                height = min(h - y, int(y_max - y_min + 2 * pad))
                
                # Ensure detected content is sufficiently large
                if width > w * 0.4 and height > h * 0.2:
                    return (x, y, width, height)
        except Exception:
            pass

        return (0, 0, img.width, img.height)

    @staticmethod
    def safe_prepare_image(img: Image.Image, config: RenderConfig) -> Image.Image:
        """
        Ensures RGB mode, downscales extremely oversized images to bounded resolution,
        and optionally applies horizontal flip (mirroring) for copyright protection.
        """
        if img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size
        max_w = config.max_downscale_width
        max_h = config.max_downscale_height

        if w > max_w or h > max_h:
            scale_w = max_w / w if w > max_w else 1.0
            scale_h = max_h / h if h > max_h else 1.0
            scale = min(scale_w, scale_h)
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            resized = img.resize((new_w, new_h), resample=Image.Resampling.LANCZOS)
            img.close()
            img = resized

        # Anti-copyright: Mirror / Horizontal Flip
        if config.flip_horizontal:
            flipped = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            img.close()
            img = flipped

        return img

    @staticmethod
    def apply_subtle_color_tint(img: Image.Image, config: RenderConfig) -> Image.Image:
        """
        Applies a subtle cinematic color tint overlay to alter color histograms/hashes
        for anti-copyright evasion while maintaining optimal contrast and visual clarity.
        """
        if not config.color_tint_enabled or config.color_tint_opacity <= 0.0:
            return img

        opacity = float(np.clip(config.color_tint_opacity, 0.01, 0.12))
        tint_type = (config.color_tint_type or "warm_cinema").lower()

        if "cool" in tint_type:
            tint_color = (232, 244, 255)
        elif "vintage" in tint_type or "sepia" in tint_type:
            tint_color = (255, 238, 218)
        else: # warm_cinema default
            tint_color = (255, 246, 235)

        # Create overlay layer and blend
        overlay = Image.new("RGB", img.size, tint_color)
        blended = Image.blend(img, overlay, opacity)
        overlay.close()
        img.close()

        # Slight contrast and color punch to preserve vividness
        enhancer_c = ImageEnhance.Contrast(blended)
        boosted = enhancer_c.enhance(1.02)
        blended.close()
        return boosted

    @staticmethod
    def generate_background(
        img: Image.Image,
        bounds: Tuple[int, int, int, int],
        config: RenderConfig
    ) -> Image.Image:
        """
        Generates a 1920x1080 background canvas (blurred source, solid dark, or gradient).
        """
        target_w, target_h = config.width, config.height

        if config.background_mode == BackgroundMode.SOLID_DARK:
            return Image.new("RGB", (target_w, target_h), (14, 15, 18))

        if config.background_mode == BackgroundMode.GRADIENT:
            # Create dark gradient
            canvas = Image.new("RGB", (target_w, target_h), (10, 11, 14))
            draw = ImageDraw.Draw(canvas)
            for y in range(target_h):
                alpha = int(25 * math.sin(math.pi * y / target_h))
                draw.line([(0, y), (target_w, y)], fill=(15 + alpha, 16 + alpha, 20 + alpha))
            return canvas

        # Default: BLURRED_SOURCE
        cb_x, cb_y, W_c, H_c = bounds
        W_c = max(1, min(W_c, img.width - cb_x))
        H_c = max(1, min(H_c, img.height - cb_y))

        cropped = img.crop((cb_x, cb_y, cb_x + W_c, cb_y + H_c))

        bg_scale = max(target_w / W_c, target_h / H_c)
        bg_w = max(target_w, int(math.ceil(W_c * bg_scale)))
        bg_h = max(target_h, int(math.ceil(H_c * bg_scale)))

        # Fast 2-step resize & blur to optimize CPU/RAM
        bg_resized = cropped.resize((bg_w, bg_h), Image.Resampling.BOX)
        cropped.close()

        bg_x1 = (bg_w - target_w) // 2
        bg_y1 = (bg_h - target_h) // 2
        bg_cropped = bg_resized.crop((bg_x1, bg_y1, bg_x1 + target_w, bg_y1 + target_h))
        bg_resized.close()

        # Low-res blur pass for speed and silky smoothness
        thumb_w, thumb_h = target_w // 8, target_h // 8
        bg_small = bg_cropped.resize((thumb_w, thumb_h), Image.Resampling.BOX)
        bg_cropped.close()

        bg_blurred_small = bg_small.filter(ImageFilter.GaussianBlur(radius=config.bg_blur_radius))
        bg_small.close()

        bg_blurred = bg_blurred_small.resize((target_w, target_h), Image.Resampling.BILINEAR)
        bg_blurred_small.close()

        # Adjust ambient brightness & saturation
        enhancer = ImageEnhance.Brightness(bg_blurred)
        bg_final = enhancer.enhance(config.bg_brightness)
        bg_blurred.close()

        return bg_final

    @staticmethod
    def generate_background_canvas(
        img: Image.Image,
        bounds: Tuple[int, int, int, int],
        config: RenderConfig,
        margin: float = 1.25
    ) -> np.ndarray:
        """
        Generates an extended blurred background canvas (or solid/gradient) supporting
        dynamic camera tracking (pan, tilt, vertical scroll, and zoom) with scroll and zoom speeds
        strictly equivalent to the main foreground image frame.
        """
        target_w, target_h = config.width, config.height

        if config.background_mode == BackgroundMode.SOLID_DARK:
            canvas_w = int(round(target_w * margin))
            canvas_h = int(round(target_h * margin))
            return np.full((canvas_h, canvas_w, 3), (14, 15, 18), dtype=np.uint8)

        if config.background_mode == BackgroundMode.GRADIENT:
            canvas_w = int(round(target_w * margin))
            canvas_h = int(round(target_h * margin))
            canvas = np.empty((canvas_h, canvas_w, 3), dtype=np.uint8)
            y_indices = np.arange(canvas_h, dtype=np.float32)
            alpha = (25.0 * np.sin(np.pi * y_indices / canvas_h)).astype(np.uint8)
            canvas[:, :, 0] = 15 + alpha
            canvas[:, :, 1] = 16 + alpha
            canvas[:, :, 2] = 20 + alpha
            return canvas

        # Default: BLURRED_SOURCE
        cb_x, cb_y, W_c, H_c = bounds
        img_w, img_h = img.size
        cb_x = max(0, min(img_w - 1, cb_x))
        cb_y = max(0, min(img_h - 1, cb_y))
        W_c = max(1, min(W_c, img_w - cb_x))
        H_c = max(1, min(H_c, img_h - cb_y))

        ratio = float(H_c) / float(W_c) if W_c > 0 else 1.0
        h_cam_960 = float(W_c) * (1080.0 / 960.0) if W_c > 0 else float(target_h)
        is_tall = (ratio >= 1.8) and (H_c > h_cam_960 * 1.1)

        # Calculate exact 16:9 base viewport size in content coordinates matching foreground screen scale
        if is_tall:
            needed_w = 2.0 * float(W_c)
            needed_h = float(h_cam_960)
            pad_x = max(10, int(round((needed_w * margin - W_c) / 2.0)))
            pad_y = max(10, int(round(needed_h * (margin - 1.0) / 2.0)))
        else:
            needed_h = float(H_c)
            needed_w = float(H_c) * (16.0 / 9.0)
            pad_x = max(10, int(round((needed_w * margin - W_c) / 2.0)))
            pad_y = max(10, int(round((needed_h * margin - H_c) / 2.0)))

        cropped = img.crop((cb_x, cb_y, cb_x + W_c, cb_y + H_c))
        cropped_np = np.asarray(cropped)

        # Pad with mirror reflect border to provide smooth outer background matching foreground edges
        padded = cv2.copyMakeBorder(cropped_np, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_REFLECT_101)
        cropped.close()

        ph, pw = padded.shape[:2]
        small_w = 320
        small_h = max(180, int(round(ph * (small_w / pw))))
        small = cv2.resize(padded, (small_w, small_h), interpolation=cv2.INTER_AREA)

        ksize = int(round(config.bg_blur_radius * 0.8)) | 1
        ksize = max(5, min(51, ksize))
        blurred_small = cv2.GaussianBlur(small, (ksize, ksize), config.bg_blur_radius * 0.4)

        canvas_np = cv2.resize(blurred_small, (pw, ph), interpolation=cv2.INTER_LINEAR)
        if config.bg_brightness != 1.0:
            canvas_np = cv2.convertScaleAbs(canvas_np, alpha=config.bg_brightness, beta=0)

        return np.ascontiguousarray(canvas_np, dtype=np.uint8)

    @staticmethod
    def render_animated_background_np(
        bg_canvas: np.ndarray,
        bounds: Tuple[int, int, int, int],
        x: float,
        y: float,
        scale: float,
        target_w: int,
        target_h: int,
        out_buffer: np.ndarray,
        margin: float = 1.25
    ) -> None:
        """
        Samples the blurred background canvas according to camera position (x, y, scale)
        with scroll and zoom speeds strictly equivalent to the foreground frame.
        """
        canvas_h, canvas_w = bg_canvas.shape[:2]
        if canvas_w == target_w and canvas_h == target_h:
            np.copyto(out_buffer, bg_canvas)
            return

        cb_x, cb_y, W_c, H_c = bounds
        W_c = max(1, W_c)
        H_c = max(1, H_c)

        ratio = float(H_c) / float(W_c) if W_c > 0 else 1.0
        h_cam_960 = float(W_c) * (1080.0 / 960.0) if W_c > 0 else float(target_h)
        is_tall = (ratio >= 1.8) and (H_c > h_cam_960 * 1.1)

        if is_tall:
            needed_w = 2.0 * float(W_c)
            needed_h = float(h_cam_960)
            pad_x = max(10, int(round((needed_w * margin - W_c) / 2.0)))
            pad_y = max(10, int(round(needed_h * (margin - 1.0) / 2.0)))
        else:
            needed_h = float(H_c)
            needed_w = float(H_c) * (16.0 / 9.0)
            pad_x = max(10, int(round((needed_w * margin - W_c) / 2.0)))
            pad_y = max(10, int(round((needed_h * margin - H_c) / 2.0)))

        bg_cx = pad_x + x
        bg_cy = pad_y + y

        clamped_scale = max(0.5, min(1.35, scale))
        vw = min(float(canvas_w), needed_w / clamped_scale)
        vh = min(float(canvas_h), needed_h / clamped_scale)

        int_vw = max(1, int(round(vw)))
        int_vh = max(1, int(round(vh)))

        x1 = max(0, min(canvas_w - int_vw, int(round(bg_cx - vw / 2.0))))
        y1 = max(0, min(canvas_h - int_vh, int(round(bg_cy - vh / 2.0))))
        x2 = min(canvas_w, x1 + int_vw)
        y2 = min(canvas_h, y1 + int_vh)

        bg_crop = bg_canvas[y1:y2, x1:x2]
        cv2.resize(bg_crop, (target_w, target_h), dst=out_buffer, interpolation=cv2.INTER_LINEAR)

    @staticmethod
    def create_fallback_image(
        width: int = 1920,
        height: int = 1080,
        label: str = "Image Missing"
    ) -> Image.Image:
        """
        Creates a high-aesthetic placeholder card when an image is missing or corrupted.
        """
        img = Image.new("RGB", (width, height), (18, 18, 24))
        draw = ImageDraw.Draw(img)

        # Subtle card border
        margin_x = width // 6
        margin_y = height // 6
        draw.rectangle(
            [margin_x, margin_y, width - margin_x, height - margin_y],
            outline=(60, 65, 80),
            width=3
        )
        
        # Text
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        text_str = f"[{label}]"
        draw.text((width // 2 - 40, height // 2 - 10), text_str, fill=(160, 165, 180), font=font)
        return img
