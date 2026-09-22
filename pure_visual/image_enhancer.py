import os
import cv2
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from dataclasses import dataclass
from typing import Tuple, Optional
import logging

logger = logging.getLogger("PureVisualImageEnhancer")


class SRVGGNetCompact(nn.Module):
    """Real-ESRGAN Compact architecture for Anime/Manhwa 4x Super-Resolution."""
    def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=18, upscale=4, act_type='prelu'):
        super().__init__()
        self.upscale = upscale
        self.body = nn.ModuleList()
        self.body.append(nn.Conv2d(num_in_ch, num_feat, 3, 1, 1))
        self.body.append(nn.PReLU(num_parameters=num_feat))
        for _ in range(num_conv - 2):
            self.body.append(nn.Conv2d(num_feat, num_feat, 3, 1, 1))
            self.body.append(nn.PReLU(num_parameters=num_feat))
        self.body.append(nn.Conv2d(num_feat, num_out_ch * upscale * upscale, 3, 1, 1))
        self.upsampler = nn.PixelShuffle(upscale)

    def forward(self, x):
        out = x
        for i in range(len(self.body)):
            out = self.body[i](out)
        out = self.upsampler(out)
        base = F.interpolate(x, scale_factor=self.upscale, mode='nearest')
        out = out + base
        return out


@dataclass
class EnhancerConfig:
    # 1. Upscale / Super-Resolution
    enable_upscale: bool = True
    model_path: str = "weights/realesr-animevideov3.pth"
    use_ai_sr: bool = True                # Enable Real-ESRGAN 4x AI Super-Resolution by default
    min_target_width: int = 1920          # Ensure at least standard Full HD width for crisp panning
    max_target_width: int = 2560          # 2.5K crisp resolution cap for high-fidelity zoom
    scale_multiplier: float = 2.0         # 2x minimum multiplier for standard interpolation fallback
    
    # 2. Cinematic Color Grading & Tone Mapping
    enable_color_grading: bool = True
    clahe_clip_limit: float = 1.8         # Adaptive histogram equalization on luminance
    clahe_grid_size: Tuple[int, int] = (8, 8)
    vibrance_boost: float = 0.12          # Saturation boost factor (+12%)
    black_level_offset: int = 4           # Pull down deep blacks for contrast depth
    
    # 3. Smart Line-Art Sharpening
    enable_sharpening: bool = True
    sharpen_strength: float = 0.45        # Crisp unsharp mask weight for comic ink lines
    sharpen_radius: float = 1.0           # Gaussian blur sigma for unsharp mask


class PureVisualImageEnhancer:
    """
    Super-Resolution Upscaling (Real-ESRGAN AI + Lanczos4) and Cinematic Color Grading engine.
    Also provides dynamic coordinate scaling for video renderers and camera planners.
    """
    _sr_model = None
    _sr_device = None

    def __init__(self, config: Optional[EnhancerConfig] = None):
        self.config = config or EnhancerConfig()
        self._clahe = cv2.createCLAHE(
            clipLimit=self.config.clahe_clip_limit,
            tileGridSize=self.config.clahe_grid_size
        )
        self._init_sr_model()

    def _init_sr_model(self):
        """Initializes Real-ESRGAN anime super-resolution model on GPU if available."""
        if not self.config.use_ai_sr or PureVisualImageEnhancer._sr_model is not None:
            return

        model_p = self.config.model_path
        if not os.path.exists(model_p):
            alt_p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "weights", "realesr-animevideov3.pth")
            if os.path.exists(alt_p):
                model_p = alt_p

        if os.path.exists(model_p):
            try:
                dev = "cuda" if torch.cuda.is_available() else "cpu"
                model = SRVGGNetCompact(num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=18, upscale=4, act_type='prelu')
                ckpt = torch.load(model_p, map_location=dev, weights_only=False)
                weights = ckpt['params'] if 'params' in ckpt else ckpt
                model.load_state_dict(weights)
                model.eval()
                if dev == "cuda":
                    model.half().to(dev)
                else:
                    model.to(dev)
                PureVisualImageEnhancer._sr_model = model
                PureVisualImageEnhancer._sr_device = dev
                logger.info(f"[PureVisualImageEnhancer] Loaded Real-ESRGAN Anime model ({model_p}) on {dev}")
            except Exception as e:
                logger.warning(f"[PureVisualImageEnhancer] Could not load Real-ESRGAN model: {e}")

    def _run_ai_super_resolution(self, img_bgr: np.ndarray) -> np.ndarray:
        """Runs Real-ESRGAN super-resolution inference on CUDA with tile support."""
        if PureVisualImageEnhancer._sr_model is None:
            return img_bgr

        dev = PureVisualImageEnhancer._sr_device
        model = PureVisualImageEnhancer._sr_model
        h, w = img_bgr.shape[:2]

        try:
            # For tall images, process in overlapping horizontal tiles to avoid VRAM overflow
            tile_size = 1024
            overlap = 32

            if h <= tile_size:
                with torch.no_grad():
                    inp = torch.from_numpy(img_bgr).permute(2, 0, 1).div(255.0).unsqueeze(0)
                    inp = inp.half().to(dev) if dev == "cuda" else inp.float().to(dev)
                    out = model(inp)
                    out_np = (out.squeeze(0).permute(1, 2, 0).clamp(0, 1).float().cpu().numpy() * 255.0).astype(np.uint8)
                    return out_np
            else:
                out_h, out_w = h * 4, w * 4
                out_full = np.zeros((out_h, out_w, 3), dtype=np.uint8)
                step = tile_size - overlap

                for y in range(0, h, step):
                    y_end = min(h, y + tile_size)
                    tile = img_bgr[y:y_end, :]
                    th = tile.shape[0]

                    with torch.no_grad():
                        inp = torch.from_numpy(tile).permute(2, 0, 1).div(255.0).unsqueeze(0)
                        inp = inp.half().to(dev) if dev == "cuda" else inp.float().to(dev)
                        out = model(inp)
                        out_tile = (out.squeeze(0).permute(1, 2, 0).clamp(0, 1).float().cpu().numpy() * 255.0).astype(np.uint8)

                    out_y = y * 4
                    out_y_end = min(out_h, (y + th) * 4)
                    out_full[out_y:out_y_end, :] = out_tile[:out_y_end - out_y, :]

                return out_full
        except Exception as e:
            logger.warning(f"[PureVisualImageEnhancer] AI SR failed, falling back to Lanczos4: {e}")
            return img_bgr

    def enhance_image(
        self,
        image_np: np.ndarray,
        content_bounds: Optional[Tuple[int, int, int, int]] = None
    ) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        """
        Enhances frame quality via Real-ESRGAN / Lanczos4, CLAHE color grading, and ink-line sharpening.
        """
        if image_np is None or image_np.size == 0:
            return image_np, (0, 0, 0, 0)

        orig_h, orig_w = image_np.shape[:2]
        if content_bounds is None:
            content_bounds = (0, 0, orig_w, orig_h)

        cb_x, cb_y, cb_w, cb_h = content_bounds

        # -----------------------------------------------------------------
        # STEP 1: AI Super-Resolution (Real-ESRGAN / Lanczos4)
        # -----------------------------------------------------------------
        if self.config.enable_upscale:
            # Smart Skip: If image already exceeds Full HD / 2K dimensions, skip heavy 4x Real-ESRGAN
            needs_sr = (orig_w < self.config.min_target_width and orig_h < 1080)
            if self.config.use_ai_sr and PureVisualImageEnhancer._sr_model is not None and needs_sr:
                enhanced = self._run_ai_super_resolution(image_np)
                sr_h, sr_w = enhanced.shape[:2]
                
                # If the upscaled image is excessively wide (> max_target_width), downsample cleanly to high-res
                if sr_w > self.config.max_target_width:
                    target_w = self.config.max_target_width
                    target_h = int(round(sr_h * (float(target_w) / float(sr_w))))
                    enhanced = cv2.resize(enhanced, (target_w, target_h), interpolation=cv2.INTER_AREA)
            elif needs_sr:
                # High-quality Lanczos4 interpolation fallback
                target_w = max(int(orig_w * self.config.scale_multiplier), self.config.min_target_width)
                target_w = min(target_w, self.config.max_target_width)
                scale_factor = float(target_w) / float(orig_w)
                if abs(scale_factor - 1.0) > 0.05:
                    target_h = int(round(orig_h * scale_factor))
                    enhanced = cv2.resize(image_np, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
                else:
                    enhanced = image_np.copy()
            else:
                enhanced = image_np.copy()
        else:
            enhanced = image_np.copy()

        new_h, new_w = enhanced.shape[:2]
        sx = float(new_w) / float(orig_w)
        sy = float(new_h) / float(orig_h)

        # Scale content bounds
        new_cb_x = int(round(cb_x * sx))
        new_cb_y = int(round(cb_y * sy))
        new_cb_w = int(round(cb_w * sx))
        new_cb_h = int(round(cb_h * sy))
        scaled_bounds = (new_cb_x, new_cb_y, new_cb_w, new_cb_h)

        # -----------------------------------------------------------------
        # STEP 2: Cinematic Color Grading & Tone Mapping
        # -----------------------------------------------------------------
        if self.config.enable_color_grading and enhanced.ndim == 3 and enhanced.shape[2] == 3:
            enhanced = self._apply_color_grading(enhanced)

        # -----------------------------------------------------------------
        # STEP 3: Smart Ink-Line Sharpening (Unsharp Masking)
        # -----------------------------------------------------------------
        if self.config.enable_sharpening and enhanced.ndim == 3:
            enhanced = self._apply_smart_sharpen(enhanced)

        return enhanced, scaled_bounds

    def _apply_color_grading(self, img: np.ndarray) -> np.ndarray:
        """Applies CLAHE on luminance and selective vibrance boost."""
        # 1. LAB CLAHE for local contrast / dynamic range enhancement
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        l_enhanced = self._clahe.apply(l_channel)

        # Black level adjustment (deepen dark shadows)
        if self.config.black_level_offset > 0:
            l_enhanced = np.clip(l_enhanced.astype(np.int16) - self.config.black_level_offset, 0, 255).astype(np.uint8)

        lab_merged = cv2.merge([l_enhanced, a_channel, b_channel])
        graded = cv2.cvtColor(lab_merged, cv2.COLOR_LAB2BGR)

        # 2. HSV Vibrance / Saturation Boost
        if self.config.vibrance_boost > 0.001:
            hsv = cv2.cvtColor(graded, cv2.COLOR_BGR2HSV).astype(np.float32)
            h_c, s_c, v_c = cv2.split(hsv)
            
            # Selective saturation boost: Boost mid-to-high saturated pixels more than muted gray pixels
            vibrance_mask = s_c / 255.0
            boost_factor = 1.0 + (self.config.vibrance_boost * (1.0 + vibrance_mask * 0.5))
            s_boosted = np.clip(s_c * boost_factor, 0, 255.0)

            hsv_boosted = cv2.merge([h_c, s_boosted, v_c]).astype(np.uint8)
            graded = cv2.cvtColor(hsv_boosted, cv2.COLOR_HSV2BGR)

        return graded

    def _apply_smart_sharpen(self, img: np.ndarray) -> np.ndarray:
        """Applies fast unsharp masking to enhance ink lines and crisp outlines."""
        radius = self.config.sharpen_radius
        amount = self.config.sharpen_strength
        
        # Gaussian blur for high-frequency isolation
        blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=radius, sigmaY=radius)
        
        # Fast weighted addition: sharp = img * (1 + amount) - blurred * amount
        sharp = cv2.addWeighted(img, 1.0 + amount, blurred, -amount, 0)
        return np.clip(sharp, 0, 255).astype(np.uint8)
