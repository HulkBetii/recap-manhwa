import enum
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any


class MotionTier(str, enum.Enum):
    MICRO = "micro"           # < 0.7s
    SUBTLE = "subtle"         # 0.7s - 2.0s
    STANDARD = "standard"     # 2.0s - 5.0s
    MULTI_PHASE = "multi"     # 5.0s - 10.0s
    EXTENDED = "extended"     # > 10.0s


class AspectRatioCategory(str, enum.Enum):
    PORTRAIT_TALL = "portrait_tall"       # ratio < 0.5 (tall strip manhwa)
    PORTRAIT_STANDARD = "portrait_std"    # 0.5 <= ratio < 0.95
    SQUARE = "square"                     # 0.95 <= ratio <= 1.05
    LANDSCAPE_STANDARD = "landscape_std"  # 1.05 < ratio <= 1.85 (16:9 is ~1.78)
    LANDSCAPE_WIDE = "landscape_wide"     # ratio > 1.85 (ultrawide panoramic)


class BackgroundMode(str, enum.Enum):
    BLURRED_SOURCE = "blurred_source"     # Ambient blurred & darkened background derived from source
    SOLID_DARK = "solid_dark"             # Solid dark/charcoal cinema background
    GRADIENT = "gradient"                 # Smooth dark vignette/gradient background
    FIT_CANVAS = "fit_canvas"             # Center in canvas


@dataclass
class Keyframe:
    time: float
    x: float
    y: float
    scale: float


@dataclass
class MotionPlan:
    page_id: Any
    duration: float
    tier: MotionTier
    animation_type: str
    easing: str
    keyframes: List[Keyframe]
    transition: str = "cross_fade"


@dataclass
class ImageClip:
    image_file: str                       # filename or absolute path
    duration: float                       # display duration in seconds
    start_time: float = 0.0               # cumulative start time
    end_time: float = 0.0                 # cumulative end time
    page_num: int = 1                     # 1-indexed page/panel identifier
    segment_index: int = 0
    priority: float = 1.0
    bounds: Optional[Tuple[int, int, int, int]] = None
    custom_motion: Optional[str] = None


@dataclass
class SubtitleItem:
    index: int
    start: float
    end: float
    text: str


@dataclass
class RenderConfig:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    encoder: str = "libx264"
    background_mode: BackgroundMode = BackgroundMode.BLURRED_SOURCE
    bg_brightness: float = 0.55
    bg_blur_radius: int = 6
    transition_duration: float = 0.22
    min_fg_width: int = 960
    seed: int = 42
    max_cached_images: int = 8
    max_downscale_height: int = 4000
    max_downscale_width: int = 4000
    subtitles_enabled: bool = False
    logo_path: Optional[str] = None
    overlay_path: Optional[str] = None
    film_grain: bool = True
    grain_strength: int = 8
    flip_horizontal: bool = False
    vignette_enabled: bool = True
    vignette_strength: float = 0.38
    color_tint_enabled: bool = True
    color_tint_type: str = "warm_cinema"
    color_tint_opacity: float = 0.035
    fit_height_full: bool = True
    max_scroll_speed: float = 320.0
    max_zoom_scale: float = 1.20
    extra_encoder_args: Optional[List[str]] = None
