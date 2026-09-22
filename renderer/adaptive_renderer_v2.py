import os
import sys
import math
import subprocess
import asyncio
from typing import List, Dict, Any, Optional, Tuple, Callable
import numpy as np
import cv2
from PIL import Image, ImageFile

from renderer.types import (
    ImageClip,
    MotionPlan,
    RenderConfig,
    BackgroundMode,
    SubtitleItem,
)
from renderer.composition import ImageComposer
from renderer.motion import AdaptiveMotionPlanner, apply_motion_blur
from renderer.timeline import TimelineManager, parse_time_to_seconds

# Allow loading truncated images safely
ImageFile.LOAD_TRUNCATED_IMAGES = True


class AdaptiveManhwaRendererV2:
    """
    Adaptive Manhwa Video Renderer V2:
    High-performance video renderer with decoupled image dimensions and display duration,
    adaptive multi-tier motion, aspect-ratio-preserving composition, memory-bounded lazy loading,
    and direct FFmpeg rawvideo pipe streaming.
    """

    def __init__(self, config: Optional[RenderConfig] = None):
        self.config = config or RenderConfig()

    @staticmethod
    def get_video_duration(video_or_audio_path: str, ffmpeg_exe: str) -> float:
        """
        Retrieves media duration in seconds via ffprobe or ffmpeg.
        """
        if not video_or_audio_path or not os.path.exists(video_or_audio_path):
            return 0.0

        potential_ffprobe = ffmpeg_exe.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")
        if os.path.exists(potential_ffprobe):
            try:
                cmd = [
                    potential_ffprobe, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    video_or_audio_path
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
                dur = float(res.stdout.strip())
                if dur > 0:
                    return dur
            except Exception:
                pass

        try:
            cmd = [ffmpeg_exe, "-i", video_or_audio_path]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            import re
            m = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}\.\d+)", res.stderr)
            if m:
                h, mi, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
                return h * 3600.0 + mi * 60.0 + s
        except Exception:
            pass

        return 0.0

    def render_single_frame_np(
        self,
        img: Image.Image,
        bg_np: np.ndarray,
        bounds: Tuple[int, int, int, int],
        plan: MotionPlan,
        t_local: float,
        dx: float,
        dy: float,
        out_buffer: np.ndarray
    ) -> None:
        """
        Renders a single video frame directly into the provided contiguous out_buffer
        using fast memory copying and optimized SIMD compositing.
        """
        target_w, target_h = self.config.width, self.config.height
        cb_x, cb_y, W_c, H_c = bounds
        W_c = max(1, min(W_c, img.width - cb_x))
        H_c = max(1, min(H_c, img.height - cb_y))

        # Interpolate camera keyframes
        x, y, scale = AdaptiveMotionPlanner.interpolate(plan, t_local)
        scale = max(0.5, min(1.25, scale))

        # Render dynamically animated background blur matching camera motion (x, y, scale)
        ImageComposer.render_animated_background_np(
            bg_np, bounds, x, y, scale, target_w, target_h, out_buffer
        )

        ratio = float(H_c) / float(W_c) if W_c > 0 else 1.0
        h_cam_960 = float(W_c) * (1080.0 / 960.0) if W_c > 0 else float(target_h)
        is_tall = (ratio >= 1.8) and (H_c > h_cam_960 * 1.1)

        if not is_tall:
            # Case 2: Page height <= 115% -> display full height without width limit
            box_to_crop = (cb_x, cb_y, cb_x + W_c, cb_y + H_c)
            w_crop = float(W_c)
            h_crop = float(H_c)

            # Full image zoom (scales image to full height target_h * scale, width scales proportionally)
            scale_factor = (target_h * scale) / h_crop
            fg_w = max(1, int(round(w_crop * scale_factor)))
            fg_h = max(1, int(round(h_crop * scale_factor)))
        else:
            # Case 1: Tall page (> 115%) -> slide + zoom in from 960px -> 1150px
            # scale goes from 1.0 (960px) to 1150.0 / 960.0 (1150px)
            fg_w = max(1, int(round(960.0 * scale)))
            fg_h = target_h  # 1080px (full height of video frame)

            # Camera viewport in content coordinates:
            # Full comic width W_c is always visible (no horizontal cut)
            # Camera aspect ratio matches fg_w / fg_h
            w_cam = float(W_c)
            h_cam = float(W_c) * (float(fg_h) / float(fg_w))

            x_img = float(cb_x) + x
            y_img = float(cb_y) + y

            x1 = x_img - w_cam / 2.0
            y1 = y_img - h_cam / 2.0
            x2 = x_img + w_cam / 2.0
            y2 = y_img + h_cam / 2.0

            x1_clamped = max(float(cb_x), min(float(cb_x + W_c - 1), x1))
            y1_clamped = max(float(cb_y), min(float(cb_y + H_c - 1), y1))
            x2_clamped = min(float(cb_x + W_c), max(x1_clamped + 1.0, x2))
            y2_clamped = min(float(cb_y + H_c), max(y1_clamped + 1.0, y2))

            box_to_crop = (x1_clamped, y1_clamped, x2_clamped, y2_clamped)

        # Crop and resize with sub-pixel float box
        fg_resized = img.resize((fg_w, fg_h), resample=Image.Resampling.BILINEAR, box=box_to_crop)
        fg_np = np.asarray(fg_resized)

        # Apply motion blur only during substantial camera motion
        if abs(dx) > 1.0 or abs(dy) > 1.0:
            fg_np = apply_motion_blur(fg_np, dx, dy)

        paste_x = (target_w - fg_w) // 2
        paste_y = (target_h - fg_h) // 2

        # Fast direct slice compositing into preallocated buffer
        bx1 = max(0, paste_x)
        bx2 = min(target_w, paste_x + fg_w)
        by1 = max(0, paste_y)
        by2 = min(target_h, paste_y + fg_h)

        sx1 = max(0, -paste_x)
        sy1 = max(0, -paste_y)
        sx2 = sx1 + (bx2 - bx1)
        sy2 = sy1 + (by2 - by1)

        if bx2 > bx1 and by2 > by1:
            out_buffer[by1:by2, bx1:bx2] = fg_np[sy1:sy2, sx1:sx2]

    def render_single_frame(
        self,
        img: Image.Image,
        bg_image: Image.Image,
        bounds: Tuple[int, int, int, int],
        plan: MotionPlan,
        t_local: float,
        dx: float,
        dy: float
    ) -> Image.Image:
        """
        Legacy/Convenience wrapper: Renders a single video frame and returns a PIL Image.
        """
        bg_np = np.ascontiguousarray(np.asarray(bg_image))
        buf = np.empty((self.config.height, self.config.width, 3), dtype=np.uint8)
        self.render_single_frame_np(img, bg_np, bounds, plan, t_local, dx, dy, buf)
        return Image.fromarray(buf)

    def render(
        self,
        clips: List[ImageClip],
        output_video_path: str,
        ffmpeg_exe: str,
        audio_path: Optional[str] = None,
        subtitles: Optional[List[SubtitleItem]] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> bool:
        """
        High-performance synchronous main render execution.
        Streams zero-copy raw memory frames into FFmpeg process stdin.
        """
        if not clips:
            raise ValueError("No image clips provided for rendering.")

        out_dir = os.path.dirname(os.path.abspath(output_video_path))
        os.makedirs(out_dir, exist_ok=True)

        target_w = self.config.width
        target_h = self.config.height
        fps = self.config.fps

        # Align total duration with audio if present
        audio_dur = 0.0
        if audio_path and os.path.exists(audio_path):
            audio_dur = self.get_video_duration(audio_path, ffmpeg_exe)

        total_duration = TimelineManager.calculate_cumulative_timeline(clips)
        tail_padding = 1.0
        target_duration = max(total_duration, audio_dur + tail_padding) if audio_dur > 0 else (total_duration + tail_padding)
        if target_duration > total_duration and clips:
            # Extend final clip duration to match audio length + tail padding
            diff = target_duration - total_duration
            clips[-1].duration += diff
            clips[-1].end_time += diff
            total_duration = target_duration

        num_frames = max(1, int(math.ceil(total_duration * fps)))

        # Precompute bounds and motion plans
        plans: List[MotionPlan] = []
        bounds_map: Dict[int, Tuple[int, int, int, int]] = {}

        for idx, clip in enumerate(clips):
            is_last = (idx == len(clips) - 1)
            trans = "dip_to_black" if is_last else "cross_fade"

            # Quick inspect image bounds
            bounds = clip.bounds
            if bounds is None:
                if clip.image_file and os.path.exists(clip.image_file):
                    try:
                        with Image.open(clip.image_file) as img_inspect:
                            if img_inspect.mode != "RGB":
                                img_inspect = img_inspect.convert("RGB")
                            if self.config.flip_horizontal:
                                img_inspect = img_inspect.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                            bounds = ImageComposer.detect_content_bounds(img_inspect)
                    except Exception:
                        bounds = (0, 0, target_w, target_h)
                else:
                    bounds = (0, 0, target_w, target_h)
            bounds_map[idx] = bounds

            plan = AdaptiveMotionPlanner.generate_plan(
                page_id=clip.page_num,
                duration=clip.duration,
                bounds=bounds,
                seed=self.config.seed,
                transition=trans,
                custom_motion=clip.custom_motion
            )
            plans.append(plan)

        # Build FFmpeg command with GPU-optimized presets & 1-second keyframe GOP for instant seeking
        encoder = self.config.encoder.lower()
        if "nvenc" in encoder:
            extra_args = [
                "-preset", "p3",
                "-tune", "hq",
                "-rc", "vbr",
                "-cq", "26",
                "-g", str(fps),
                "-keyint_min", str(fps),
                "-b:v", "2200k",
                "-maxrate", "3800k",
                "-bufsize", "6000k",
                "-spatial_aq", "1",
                "-temporal_aq", "1",
                "-threads", "0"
            ]
        elif "qsv" in encoder:
            extra_args = ["-preset", "veryfast", "-global_quality", "25", "-g", str(fps), "-keyint_min", str(fps), "-b:v", "2200k", "-maxrate", "3800k", "-threads", "0"]
        elif "amf" in encoder:
            extra_args = ["-quality", "speed", "-rc", "cqp", "-qp_i", "24", "-qp_p", "24", "-g", str(fps), "-keyint_min", str(fps), "-b:v", "2200k", "-maxrate", "3800k", "-threads", "0"]
        elif "videotoolbox" in encoder:
            extra_args = ["-b:v", "2500k", "-g", str(fps), "-realtime", "1"]
        elif "libx264" in encoder:
            extra_args = ["-crf", "23", "-preset", "veryfast", "-g", str(fps), "-keyint_min", str(fps), "-maxrate", "3500k", "-bufsize", "6000k", "-threads", "0"]
        else:
            extra_args = ["-b:v", "2500k", "-g", str(fps), "-threads", "0"]

        if self.config.extra_encoder_args:
            extra_args = self.config.extra_encoder_args

        # Construct filter complex
        cmd_inputs = [
            ffmpeg_exe, "-y",
            "-threads", "0",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{target_w}x{target_h}",
            "-r", str(fps),
            "-i", "-" # raw video stdin [0:v]
        ]

        filter_parts = []
        last_v_tag = "[0:v]"

        if self.config.overlay_path and os.path.exists(self.config.overlay_path):
            ol_rel = os.path.relpath(self.config.overlay_path, out_dir).replace('\\', '/')
            filter_parts.append(f"movie={ol_rel} [ol_raw]; [ol_raw]scale={target_w}:{target_h},format=rgba,colorchannelmixer=aa=0.005[ol]; {last_v_tag}[ol]overlay[v_ol]")
            last_v_tag = "[v_ol]"

        if self.config.logo_path and os.path.exists(self.config.logo_path):
            logo_rel = os.path.relpath(self.config.logo_path, out_dir).replace('\\', '/')
            filter_parts.append(f"movie={logo_rel} [logo_raw]; [logo_raw]scale=50:50[logo]; {last_v_tag}[logo]overlay=25:25[v_logo]")
            last_v_tag = "[v_logo]"

        # Hardware/SIMD accelerated color grading & tint via FFmpeg filtergraph
        if self.config.color_tint_enabled:
            tint_type = (self.config.color_tint_type or "warm_cinema").lower()
            if "cool" in tint_type:
                filter_parts.append(f"{last_v_tag}eq=contrast=1.02:brightness=0.005:saturation=1.03,colorbalance=bs=0.03:gs=0.01:rs=-0.02[v_tint]")
            elif "vintage" in tint_type or "sepia" in tint_type:
                filter_parts.append(f"{last_v_tag}eq=contrast=1.02:brightness=0.01:saturation=0.95,colorbalance=rs=0.05:gs=0.02:bs=-0.04[v_tint]")
            else: # warm_cinema
                filter_parts.append(f"{last_v_tag}eq=contrast=1.02:brightness=0.008:saturation=1.03,colorbalance=rs=0.03:gs=0.01:bs=-0.02[v_tint]")
            last_v_tag = "[v_tint]"

        if self.config.film_grain and self.config.grain_strength > 0:
            g_val = max(1, min(30, int(self.config.grain_strength)))
            filter_parts.append(f"{last_v_tag}noise=alls={g_val}:allf=t+u[v_grain]")
            last_v_tag = "[v_grain]"

        # Anti-copyright: Soft cinematic vignette to disrupt corner frame hashes
        if getattr(self.config, "vignette_enabled", True):
            v_angle = getattr(self.config, "vignette_strength", 0.38)
            # Create a static vignette PNG once if not exists to avoid CPU-heavy trigonometric filter
            vig_dir = os.path.join(out_dir, ".cache_render")
            os.makedirs(vig_dir, exist_ok=True)
            vig_png = os.path.join(vig_dir, f"vignette_{target_w}x{target_h}_{int(v_angle*100)}.png")
            if not os.path.exists(vig_png):
                x_c = np.linspace(-1, 1, target_w)
                y_c = np.linspace(-1, 1, target_h)
                xx, yy = np.meshgrid(x_c, y_c)
                rad = np.sqrt(xx**2 + yy**2)
                alpha = np.clip((rad - 0.45) / 0.75, 0, 1) * float(v_angle) * 255.0
                vig_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
                vig_rgba[:, :, 3] = alpha.astype(np.uint8)
                Image.fromarray(vig_rgba).save(vig_png, "PNG")
            
            vig_rel = os.path.relpath(vig_png, out_dir).replace('\\', '/')
            filter_parts.append(f"movie='{vig_rel}'[vig_overlay]; {last_v_tag}[vig_overlay]overlay=shortest=1[v_vig]")
            last_v_tag = "[v_vig]"

        has_audio = bool(audio_path and os.path.exists(audio_path))
        if has_audio:
            cmd_inputs.extend(["-i", audio_path])
            filter_parts.append("[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]")

        if filter_parts:
            if last_v_tag == "0:v":
                filter_parts.insert(0, "[0:v]null[v]")
                last_v_tag = "[v]"
            filter_str = "; ".join(filter_parts)
            cmd_inputs.extend(["-filter_complex", filter_str, "-map", last_v_tag])
            if has_audio:
                cmd_inputs.extend(["-map", "[a]"])
        else:
            cmd_inputs.extend(["-map", "0:v"])
            if has_audio:
                cmd_inputs.extend(["-map", "1:a"])

        if has_audio:
            cmd_inputs.extend(["-c:a", "aac", "-b:a", "192k"])

        cmd_inputs.extend([
            "-c:v", self.config.encoder,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            *extra_args,
            output_video_path
        ])

        stderr_log_path = os.path.join(out_dir, "ffmpeg_render_stderr.log")
        stderr_file = open(stderr_log_path, "w", encoding="utf-8")

        proc = subprocess.Popen(
            cmd_inputs,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            cwd=out_dir,
            bufsize=10485760
        )

        # Lazy loading cache & pre-allocated zero-copy buffers
        loaded_images: Dict[int, Image.Image] = {}
        cached_bgs_np: Dict[int, np.ndarray] = {}
        prev_coords: Dict[int, Tuple[float, float]] = {}

        frame_buf = np.empty((target_h, target_w, 3), dtype=np.uint8)
        frame_buf_next = np.empty((target_h, target_w, 3), dtype=np.uint8)

        def get_clip_image(clip_idx: int, t_now: float) -> Image.Image:
            if clip_idx not in loaded_images:
                clip_obj = clips[clip_idx]
                img_path = clip_obj.image_file
                if img_path and os.path.exists(img_path):
                    try:
                        raw_img = Image.open(img_path)
                        prepared_img = ImageComposer.safe_prepare_image(raw_img, self.config)
                        loaded_images[clip_idx] = prepared_img
                    except Exception:
                        loaded_images[clip_idx] = ImageComposer.create_fallback_image(target_w, target_h, f"Page {clip_obj.page_num}")
                else:
                    loaded_images[clip_idx] = ImageComposer.create_fallback_image(target_w, target_h, f"Page {clip_obj.page_num}")

            return loaded_images[clip_idx]

        def get_clip_bg_np(clip_idx: int, img_obj: Image.Image) -> np.ndarray:
            if clip_idx not in cached_bgs_np:
                bounds = bounds_map.get(clip_idx, (0, 0, img_obj.width, img_obj.height))
                cached_bgs_np[clip_idx] = ImageComposer.generate_background_canvas(img_obj, bounds, self.config)
            return cached_bgs_np[clip_idx]

        active_idx = 0
        active_sub_idx = 0
        pipe_broken = False
        last_progress_pct = -1.0

        try:
            for f_idx in range(num_frames):
                if cancel_check and cancel_check():
                    raise RuntimeError("Render cancelled by user.")

                if pipe_broken:
                    break

                t = f_idx / fps

                # Sequential clip tracking
                while active_idx < len(clips) - 1 and t >= clips[active_idx].end_time:
                    active_idx += 1

                clip_curr = clips[active_idx]

                # Subtitle matching
                active_sub_text = ""
                if self.config.subtitles_enabled and subtitles:
                    while active_sub_idx < len(subtitles) and t > subtitles[active_sub_idx].end:
                        active_sub_idx += 1
                    if active_sub_idx < len(subtitles) and subtitles[active_sub_idx].start <= t <= subtitles[active_sub_idx].end:
                        active_sub_text = subtitles[active_sub_idx].text

                # Adaptive transition check
                next_idx = active_idx + 1
                in_transition = False
                t_trans_dur = 0.0
                t_trans_start = 0.0

                if next_idx < len(clips):
                    clip_next = clips[next_idx]
                    t_trans_dur = TimelineManager.get_adaptive_transition_duration(
                        clip_curr, clip_next, self.config.transition_duration
                    )
                    if t >= clip_curr.end_time - t_trans_dur:
                        in_transition = True
                        t_trans_start = clip_curr.end_time - t_trans_dur

                if in_transition:
                    # Current clip frame into frame_buf
                    t_local_curr = t - clip_curr.start_time
                    plan_curr = plans[active_idx]
                    x_curr, y_curr, _ = AdaptiveMotionPlanner.interpolate(plan_curr, t_local_curr)
                    if active_idx in prev_coords:
                        x_p, y_p = prev_coords[active_idx]
                        dx_curr, dy_curr = x_curr - x_p, y_curr - y_p
                    else:
                        dx_curr, dy_curr = 0.0, 0.0
                    prev_coords[active_idx] = (x_curr, y_curr)

                    img_curr = get_clip_image(active_idx, t)
                    bg_curr_np = get_clip_bg_np(active_idx, img_curr)
                    self.render_single_frame_np(
                        img_curr, bg_curr_np, bounds_map[active_idx], plan_curr, t_local_curr, dx_curr, dy_curr, frame_buf
                    )

                    # Next clip frame into frame_buf_next
                    t_local_next = t - t_trans_start
                    plan_next = plans[next_idx]
                    x_next, y_next, _ = AdaptiveMotionPlanner.interpolate(plan_next, t_local_next)
                    if next_idx in prev_coords:
                        x_pn, y_pn = prev_coords[next_idx]
                        dx_next, dy_next = x_next - x_pn, y_next - y_pn
                    else:
                        dx_next, dy_next = 0.0, 0.0
                    prev_coords[next_idx] = (x_next, y_next)

                    img_next = get_clip_image(next_idx, t)
                    bg_next_np = get_clip_bg_np(next_idx, img_next)
                    self.render_single_frame_np(
                        img_next, bg_next_np, bounds_map[next_idx], plan_next, t_local_next, dx_next, dy_next, frame_buf_next
                    )

                    # In-place C-accelerated alpha blend
                    alpha = (t - t_trans_start) / max(0.001, t_trans_dur)
                    alpha = float(np.clip(alpha, 0.0, 1.0))
                    cv2.addWeighted(frame_buf, 1.0 - alpha, frame_buf_next, alpha, 0, dst=frame_buf)
                else:
                    # Single active clip
                    t_local = t - clip_curr.start_time
                    plan_curr = plans[active_idx]
                    x_curr, y_curr, _ = AdaptiveMotionPlanner.interpolate(plan_curr, t_local)
                    if active_idx in prev_coords:
                        x_p, y_p = prev_coords[active_idx]
                        dx, dy = x_curr - x_p, y_curr - y_p
                    else:
                        dx, dy = 0.0, 0.0
                    prev_coords[active_idx] = (x_curr, y_curr)

                    img_curr = get_clip_image(active_idx, t)
                    bg_curr_np = get_clip_bg_np(active_idx, img_curr)
                    self.render_single_frame_np(
                        img_curr, bg_curr_np, bounds_map[active_idx], plan_curr, t_local, dx, dy, frame_buf
                    )

                # Final Dip to Black at end of video
                fade_dur = self.config.transition_duration
                if t >= total_duration - fade_dur:
                    fade_alpha = (t - (total_duration - fade_dur)) / max(0.001, fade_dur)
                    fade_alpha = float(np.clip(fade_alpha, 0.0, 1.0))
                    cv2.convertScaleAbs(frame_buf, dst=frame_buf, alpha=1.0 - fade_alpha, beta=0)

                # Draw subtitles if enabled
                if active_sub_text:
                    sub_img = Image.fromarray(frame_buf)
                    TimelineManager.draw_subtitles_on_frame(sub_img, active_sub_text, font_size=40, target_w=target_w, target_h=target_h)
                    np.copyto(frame_buf, np.asarray(sub_img))
                    sub_img.close()

                # Stream raw frame bytes to FFmpeg stdin
                try:
                    proc.stdin.write(frame_buf.tobytes())
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
                    pipe_broken = True
                    break

                # Report progress
                if progress_callback:
                    pct = round((f_idx + 1) / num_frames * 100.0, 1)
                    if pct != last_progress_pct and (f_idx % 15 == 0 or f_idx == num_frames - 1):
                        progress_callback(pct)
                        last_progress_pct = pct

        finally:
            # Clean up all loaded images
            for img in loaded_images.values():
                try:
                    img.close()
                except Exception:
                    pass
            loaded_images.clear()
            cached_bgs_np.clear()

        # Close stdin pipe and wait for FFmpeg to finish encoding
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass

        proc.wait()
        stderr_file.close()

        if proc.returncode != 0:
            err_msg = ""
            try:
                with open(stderr_log_path, "r", encoding="utf-8") as f:
                    err_msg = f.read().strip()
            except Exception:
                err_msg = "Unknown error reading ffmpeg log"
            raise RuntimeError(f"FFmpeg render failed with code {proc.returncode}: {err_msg}")
        else:
            try:
                if os.path.exists(stderr_log_path):
                    os.remove(stderr_log_path)
            except Exception:
                pass

        return True

    async def render_async(
        self,
        clips: List[ImageClip],
        output_video_path: str,
        ffmpeg_exe: str,
        audio_path: Optional[str] = None,
        subtitles: Optional[List[SubtitleItem]] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> bool:
        """
        Asynchronous wrapper executing the render pipeline in a worker thread.
        """
        return await asyncio.to_thread(
            self.render,
            clips,
            output_video_path,
            ffmpeg_exe,
            audio_path,
            subtitles,
            progress_callback,
            cancel_check
        )
