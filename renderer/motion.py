import math
import random
import numpy as np
import cv2
from typing import Tuple, List, Dict, Any, Optional
from renderer.types import MotionTier, AspectRatioCategory, Keyframe, MotionPlan, RenderConfig
from renderer.composition import ImageComposer


def ease_in_out_sine(t: float) -> float:
    return 0.5 * (1.0 - math.cos(t * math.pi))


def ease_out_quart(t: float) -> float:
    return 1.0 - (1.0 - t) ** 4


def ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4.0 * (t ** 3)
    else:
        return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


def ease_in_out_quad(t: float) -> float:
    if t < 0.5:
        return 2.0 * t * t
    else:
        return 1.0 - ((-2.0 * t + 2.0) ** 2) / 2.0


def linear(t: float) -> float:
    return t


EASING_FUNCS = {
    "easeInOutSine": ease_in_out_sine,
    "easeOutQuart": ease_out_quart,
    "easeInOutCubic": ease_in_out_cubic,
    "easeInOutQuad": ease_in_out_quad,
    "linear": linear,
}


def apply_motion_blur(img_np: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """
    Applies subtle physical directional motion blur during camera movement.
    """
    dist = math.sqrt(dx * dx + dy * dy)
    if dist < 0.6:
        return img_np

    raw_size = int(np.clip(dist * 0.35, 3, 7))
    blur_size = raw_size if raw_size % 2 == 1 else raw_size + 1
    if blur_size < 3:
        return img_np

    kernel = np.zeros((blur_size, blur_size), dtype=np.float32)
    center = blur_size // 2

    # Vertical dominant
    if abs(dy) > abs(dx) * 1.5:
        kernel[:, center] = 1.0
    # Horizontal dominant
    elif abs(dx) > abs(dy) * 1.5:
        kernel[center, :] = 1.0
    # Diagonal
    else:
        for i in range(blur_size):
            kernel[i, i] = 1.0

    kernel /= kernel.sum()
    return cv2.filter2D(img_np, -1, kernel)


class AdaptiveMotionPlanner:
    """
    Generates intelligent multi-tier adaptive camera animation plans based on duration,
    aspect ratio, focal areas, and seeded randomness.
    """

    @staticmethod
    def get_duration_tier(duration: float) -> MotionTier:
        if duration < 0.7:
            return MotionTier.MICRO
        elif duration <= 2.0:
            return MotionTier.SUBTLE
        elif duration <= 5.0:
            return MotionTier.STANDARD
        elif duration <= 10.0:
            return MotionTier.MULTI_PHASE
        else:
            return MotionTier.EXTENDED

    @classmethod
    def generate_plan(
        cls,
        page_id: Any,
        duration: float,
        bounds: Tuple[int, int, int, int],
        seed: int = 42,
        transition: str = "cross_fade",
        custom_motion: Optional[str] = None,
        focal_point: Optional[Tuple[float, float]] = None,
        camera_hint: Optional[str] = None
    ) -> MotionPlan:
        cb_x, cb_y, W_c, H_c = bounds
        W_c = max(10, W_c)
        H_c = max(10, H_c)

        # Seeded determinism per page
        seed_offset = hash(str(page_id)) % (2**31 - 1)
        rng = random.Random((seed + seed_offset) & 0xFFFFFFFF)

        tier = cls.get_duration_tier(duration)
        aspect_cat = ImageComposer.categorize_aspect_ratio(W_c, H_c)
        
        ratio = float(H_c) / float(W_c) if W_c > 0 else 1.0
        # Canvas: 1920x1080. Base width for tall slide is 960px (center half width).
        base_fg_w = 960.0
        h_cam = float(W_c) * (1080.0 / base_fg_w) if W_c > 0 else 1080.0
        is_tall = (ratio >= 1.8) and (H_c > h_cam * 1.1)

        # Base camera viewport in page coordinates
        if is_tall:
            w_base = float(W_c)
            h_base = h_cam
        else:
            w_base = float(W_c)
            h_base = float(H_c)

        center_x = W_c / 2.0
        center_y = H_c / 2.0

        # Subject / Face focal bias (upper third for vertical manhwa or detected focal point)
        if focal_point is not None:
            fx, fy = focal_point
            face_focal_x = fx * W_c if fx <= 1.0 else fx
            face_focal_y = fy * H_c if fy <= 1.0 else fy
        else:
            face_focal_x = center_x
            face_focal_y = H_c * 0.35 if is_tall or aspect_cat in (AspectRatioCategory.PORTRAIT_TALL, AspectRatioCategory.PORTRAIT_STANDARD) else center_y

        # Normalize custom_motion or camera_hint to strictly allowed set only
        req_motion = None
        motion_source = custom_motion or camera_hint
        if motion_source:
            c_low = motion_source.lower()
            if "static" in c_low or "hold" in c_low:
                req_motion = "static_hold"
            elif "slide" in c_low or "scroll" in c_low or "top_to_bottom" in c_low or "pan_down" in c_low:
                req_motion = "slow_slide_down"
            elif "left_to_right" in c_low or "pan_right" in c_low:
                req_motion = "pan_left_to_right"
            elif "zoom" in c_low:
                req_motion = "slow_zoom_in"

        # Select primary smooth easing curve with continuous natural momentum
        easing = "easeInOutQuad"

        # -------------------------------------------------------------
        # ANIMATION 1: SLIDE DOWN (for Tall / Vertical Manhwa Panels)
        # -------------------------------------------------------------
        if is_tall:
            travel_total = max(0.0, H_c - h_cam)
            animation_type = "slide_down"
            y_start = h_cam / 2.0
            max_speed = 200.0  # px/sec - lively, fluid reading pace on 60 FPS
            scroll_dist = min(travel_total, max(60.0, max_speed * duration)) if travel_total >= 35.0 else travel_total
            y_end = y_start + scroll_dist

            target_x = center_x
            max_zoom = min(1.06, max(1.0, 1.0 + 0.012 * duration))
            keyframes = [
                Keyframe(time=0.0, x=target_x, y=y_start, scale=1.0),
                Keyframe(time=duration, x=target_x, y=y_end, scale=max_zoom)
            ]

            return MotionPlan(
                page_id=page_id,
                duration=duration,
                tier=tier,
                animation_type=animation_type,
                easing=easing,
                keyframes=keyframes,
                transition=transition
            )

        # -------------------------------------------------------------
        # ANIMATION 2: ZOOM / PAN (for Standard / Short / Wide Panels)
        # -------------------------------------------------------------
        focal_x = face_focal_x if req_motion == "zoom_in_face" else center_x
        focal_y = face_focal_y if req_motion == "zoom_in_face" else center_y

        max_zoom = min(1.15, max(1.06, 1.0 + 0.030 * duration))
        
        if req_motion == "static_hold":
            animation_type = "static"
            keyframes = [
                Keyframe(time=0.0, x=focal_x, y=focal_y, scale=1.0),
                Keyframe(time=duration, x=focal_x, y=focal_y, scale=1.0)
            ]
        elif req_motion == "zoom_out":
            animation_type = "zoom_out"
            keyframes = [
                Keyframe(time=0.0, x=focal_x, y=focal_y, scale=max_zoom),
                Keyframe(time=duration, x=focal_x, y=focal_y, scale=1.0)
            ]
        else: # Default zoom_in
            animation_type = "zoom_in"
            keyframes = [
                Keyframe(time=0.0, x=focal_x, y=focal_y, scale=1.0),
                Keyframe(time=duration, x=focal_x, y=focal_y, scale=max_zoom)
            ]

        return MotionPlan(
            page_id=page_id,
            duration=duration,
            tier=tier,
            animation_type=animation_type,
            easing=easing,
            keyframes=keyframes,
            transition=transition
        )


    @staticmethod
    def interpolate(plan: MotionPlan, t_local: float) -> Tuple[float, float, float]:
        """
        Interpolates the camera state (x, y, scale) at time t_local using the plan's easing curve.
        """
        kfs = plan.keyframes
        if not kfs:
            return 0.0, 0.0, 1.0

        if t_local <= kfs[0].time:
            return kfs[0].x, kfs[0].y, kfs[0].scale
        if t_local >= kfs[-1].time:
            return kfs[-1].x, kfs[-1].y, kfs[-1].scale

        ease_func = EASING_FUNCS.get(plan.easing, ease_in_out_sine)

        for i in range(len(kfs) - 1):
            kf1 = kfs[i]
            kf2 = kfs[i + 1]
            if kf1.time <= t_local <= kf2.time:
                segment_dur = kf2.time - kf1.time
                if segment_dur <= 0.0:
                    return kf2.x, kf2.y, kf2.scale
                norm_t = (t_local - kf1.time) / segment_dur
                norm_t = max(0.0, min(1.0, norm_t))
                eased_t = ease_func(norm_t)

                x = kf1.x + (kf2.x - kf1.x) * eased_t
                y = kf1.y + (kf2.y - kf1.y) * eased_t
                scale = kf1.scale + (kf2.scale - kf1.scale) * eased_t
                return x, y, scale

        return kfs[-1].x, kfs[-1].y, kfs[-1].scale


# Backward-compatible alias
MotionPlanner = AdaptiveMotionPlanner
