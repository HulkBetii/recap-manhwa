# -*- coding: utf-8 -*-
"""
Comic Vision AI: High-Performance Comic & Manhwa Vision AI Engine
Powered by PyTorch, CUDA, and Ultralytics YOLO on NVIDIA GeForce RTX 4070 SUPER.

Provides:
- Comic Panel Detection (framed and borderless manhwa panels)
- Speech Bubble & Text Balloon Detection (round, rectangular, scream/shout bubbles)
- Character & Face Segmentation (protects characters from being sliced)
- GPU-Accelerated Batched Inference for ultra-tall manhwa canvases
- Transfer Learning & Fine-tuning support from user-annotated dataset
"""

import os
import sys
import time
import logging
from typing import List, Tuple, Dict, Any, Optional

import cv2
import numpy as np

logger = logging.getLogger("ComicVisionAI")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

def get_default_model_path() -> str:
    """Returns the best available model path for comic and manhwa detection."""
    candidate_paths = [
        os.path.join("weights", "manga109_yolo11m.pt"),
        "yolo11x.pt",
        os.path.join("weights", "yolo26n.pt"),
        "yolo11n.pt"
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            return p
    return "yolo11n.pt"


DEFAULT_MODEL_NAME = get_default_model_path()


class ComicVisionAI:
    _instance = None
    _model = None
    _device = "cpu"
    _model_path = DEFAULT_MODEL_NAME
    _is_finetuned = False
    _is_manga_model = False
    _initialized = False

    @classmethod
    def get_device(cls) -> str:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda:0"
        except Exception:
            pass
        return "cpu"

    @classmethod
    def is_finetuned(cls) -> bool:
        return cls._is_finetuned or cls._is_manga_model

    @classmethod
    def get_device_info(cls) -> Dict[str, Any]:
        info = {
            "device": cls.get_device(),
            "cuda_available": False,
            "device_name": "CPU",
            "vram_total_gb": 0.0,
            "vram_used_gb": 0.0,
            "is_finetuned": cls.is_finetuned(),
            "model_path": cls._model_path,
            "base_model": DEFAULT_MODEL_NAME
        }
        try:
            import torch
            if torch.cuda.is_available():
                info["cuda_available"] = True
                info["device_name"] = torch.cuda.get_device_name(0)
                total_mem = torch.cuda.get_device_properties(0).total_memory
                allocated = torch.cuda.memory_allocated(0)
                info["vram_total_gb"] = round(total_mem / (1024 ** 3), 2)
                info["vram_used_gb"] = round(allocated / (1024 ** 3), 2)
        except Exception as e:
            logger.warning(f"Error checking CUDA info: {e}")
        return info

    @classmethod
    def get_model(cls, model_path: Optional[str] = None, force_reload: bool = False):
        target_path = model_path or cls._model_path or DEFAULT_MODEL_NAME
        if cls._model is None or force_reload or not cls._initialized or (cls._model_path != target_path):
            cls._initialized = True
            cls._device = cls.get_device()
            cls._model_path = target_path

            try:
                from renderer.yolo_compat import YOLO, is_yolo_available
                if not is_yolo_available():
                    logger.warning(f"[ComicVisionAI] ultralytics YOLO not available. Model '{target_path}' will be skipped.")
                    cls._model = None
                    return None

                cls._model = YOLO(target_path)
                if "cuda" in str(cls._device).lower():
                    try:
                        cls._model.to(cls._device)
                        if hasattr(cls._model, "model") and hasattr(cls._model.model, "half"):
                            cls._model.model.half()
                            logger.info(f"[ComicVisionAI] Enabled FP16 (half-precision) mode for YOLO on {cls._device}")
                    except Exception as fp16_err:
                        logger.warning(f"[ComicVisionAI] Could not enable FP16: {fp16_err}")

                cls._is_manga_model = any("frame" in str(v).lower() or "text" in str(v).lower() for v in cls._model.names.values())
                cls._is_finetuned = cls._is_manga_model or ("comic" in target_path.lower() or "manga" in target_path.lower())
                logger.info(f"[ComicVisionAI] Loaded model '{target_path}' on {cls._device} (manga_specialized={cls._is_manga_model}, classes={cls._model.names})")
            except Exception as e:
                logger.error(f"[ComicVisionAI] Failed to load YOLO model '{target_path}': {e}")
                cls._model = None

        return cls._model


    @classmethod
    def detect_canvas_regions(
        cls,
        canvas_bgr: np.ndarray,
        conf_threshold: Optional[float] = None,
        tile_size: int = 640,
        stride: int = 480
    ) -> Dict[str, Any]:
        """
        Runs GPU-accelerated batched inference across a tall manhwa canvas using YOLOv8x.
        Matches 640px training tile resolution for maximum detection accuracy.
        Returns:
            {
                "panels": List[Tuple[x1, y1, x2, y2]],
                "bubbles": List[Tuple[x1, y1, x2, y2]],
                "characters": List[Tuple[x1, y1, x2, y2]],
                "cut_boundaries": List[Tuple[x1, y1, x2, y2, conf]],
                "forbidden_spans": List[Tuple[y1, y2]],
                "inference_time_ms": float,
                "device": str
            }
        """
        h, w = canvas_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return {
                "panels": [],
                "bubbles": [],
                "characters": [],
                "faces": [],
                "bodies": [],
                "cut_boundaries": [],
                "forbidden_spans": [],
                "inference_time_ms": 0.0,
                "device": "none"
            }

        t0 = time.time()
        model = cls.get_model()
        device = cls._device

        if conf_threshold is None:
            conf_threshold = 0.20

        if model is None:
            return {
                "panels": [],
                "bubbles": [],
                "characters": [],
                "faces": [],
                "bodies": [],
                "cut_boundaries": [],
                "forbidden_spans": [],
                "inference_time_ms": 0.0,
                "device": "none"
            }

        # Generate overlapping vertical tiles
        tiles: List[np.ndarray] = []
        tile_offsets: List[int] = []

        if h > tile_size:
            y_pos = 0
            while y_pos < h:
                y_end = min(h, y_pos + tile_size)
                tile = canvas_bgr[y_pos:y_end]
                tiles.append(tile)
                tile_offsets.append(y_pos)
                if y_end >= h:
                    break
                y_pos += stride
        else:
            tiles.append(canvas_bgr)
            tile_offsets.append(0)

        # Batched inference in mini-batches on RTX 4070 Super (or CPU fallback)
        results = []
        mini_batch_size = 16 if ("cuda" in str(device).lower()) else 6
        for i in range(0, len(tiles), mini_batch_size):
            b_tiles = tiles[i:i + mini_batch_size]
            try:
                b_res = model(b_tiles, device=device, conf=conf_threshold, verbose=False)
                results.extend(b_res)
            except Exception as e:
                logger.warning(f"[ComicVisionAI] Inference batch failed on {device}, falling back to CPU: {e}")
                b_res = [model(t, device="cpu", conf=conf_threshold, verbose=False)[0] for t in b_tiles]
                results.extend(b_res)

        raw_panels = []
        raw_bubbles = []
        raw_characters = []
        raw_faces = []
        raw_bodies = []
        raw_cuts = []

        # Parse detections based on class names
        for idx, (res, y_off) in enumerate(zip(results, tile_offsets)):
            boxes = res.boxes
            if boxes is None:
                continue

            for box in boxes:
                xyxy = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0].cpu().numpy())
                cls_id = int(box.cls[0].cpu().numpy())
                cls_name = model.names.get(cls_id, "").lower()

                gx1 = int(xyxy[0])
                gy1 = int(xyxy[1]) + y_off
                gx2 = int(xyxy[2])
                gy2 = int(xyxy[3]) + y_off

                # Map classes
                if "cut" in cls_name or "boundary" in cls_name:
                    raw_cuts.append((gx1, gy1, gx2, gy2, conf))
                elif "panel" in cls_name or "frame" in cls_name or "page" in cls_name:
                    raw_panels.append((gx1, gy1, gx2, gy2))
                elif "bubble" in cls_name or "text" in cls_name or "balloon" in cls_name:
                    raw_bubbles.append((gx1, gy1, gx2, gy2))
                elif "face" in cls_name:
                    raw_faces.append((gx1, gy1, gx2, gy2))
                    raw_characters.append((gx1, gy1, gx2, gy2))
                elif "body" in cls_name:
                    raw_bodies.append((gx1, gy1, gx2, gy2))
                    raw_characters.append((gx1, gy1, gx2, gy2))
                elif "person" in cls_name or "character" in cls_name:
                    raw_bodies.append((gx1, gy1, gx2, gy2))
                    raw_characters.append((gx1, gy1, gx2, gy2))
                elif not cls.is_finetuned() and cls_name in ("person", "clock", "book"):
                    if cls_name == "person":
                        raw_bodies.append((gx1, gy1, gx2, gy2))
                        raw_characters.append((gx1, gy1, gx2, gy2))

        # Merge overlapping bboxes from adjacent tiles
        panels = cls._merge_bboxes(raw_panels)
        bubbles = cls._merge_bboxes(raw_bubbles)
        characters = cls._merge_bboxes(raw_characters)
        faces = cls._merge_bboxes(raw_faces)
        bodies = cls._merge_bboxes(raw_bodies)

        # Character regions and speech bubble regions form strict forbidden cut spans
        # Expanded safety margins (+-25px for characters, +-15px for bubbles) protect limbs, weapons, and tails
        forbidden_spans = []
        for _, cy1, _, cy2 in characters:
            if cy2 - cy1 > 25:
                forbidden_spans.append((max(0, cy1 - 25), min(h, cy2 + 25)))

        for _, by1, _, by2 in bubbles:
            if by2 - by1 > 15:
                forbidden_spans.append((max(0, by1 - 15), min(h, by2 + 15)))

        # Merge contiguous forbidden spans
        merged_forbidden = []
        if forbidden_spans:
            forbidden_spans.sort(key=lambda s: s[0])
            curr_s, curr_e = forbidden_spans[0]
            for ns, ne in forbidden_spans[1:]:
                if ns <= curr_e + 10:
                    curr_e = max(curr_e, ne)
                else:
                    merged_forbidden.append((curr_s, curr_e))
                    curr_s, curr_e = ns, ne
            merged_forbidden.append((curr_s, curr_e))

        t1 = time.time()
        elapsed_ms = round((t1 - t0) * 1000, 2)

        return {
            "panels": panels,
            "bubbles": bubbles,
            "characters": characters,
            "faces": faces,
            "bodies": bodies,
            "cut_boundaries": raw_cuts,
            "forbidden_spans": merged_forbidden,
            "inference_time_ms": elapsed_ms,
            "device": device
        }

    @staticmethod
    def _merge_bboxes(boxes: List[Tuple[int, int, int, int]], iou_thresh: float = 0.5) -> List[Tuple[int, int, int, int]]:
        if not boxes:
            return []

        boxes_sorted = sorted(boxes, key=lambda b: (b[1], b[0]))
        merged: List[Tuple[int, int, int, int]] = []

        for b in boxes_sorted:
            bx1, by1, bx2, by2 = b
            matched = False
            for i, (mx1, my1, mx2, my2) in enumerate(merged):
                ix1 = max(bx1, mx1)
                iy1 = max(by1, my1)
                ix2 = min(bx2, mx2)
                iy2 = min(by2, my2)

                iw = max(0, ix2 - ix1)
                ih = max(0, iy2 - iy1)
                inter_area = iw * ih

                area_b = (bx2 - bx1) * (by2 - by1)
                area_m = (mx2 - mx1) * (my2 - my1)
                union_area = area_b + area_m - inter_area

                if union_area > 0 and (inter_area / union_area) > iou_thresh:
                    merged[i] = (min(bx1, mx1), min(by1, my1), max(bx2, mx2), max(by2, my2))
                    matched = True
                    break

            if not matched:
                merged.append(b)

        return merged

    @classmethod
    def analyze_boundary_context(
        cls,
        canvas_bgr: np.ndarray,
        candidate_y: int,
        window: int = 200,
        conf_threshold: float = 0.20
    ) -> Dict[str, Any]:
        """
        Targeted Vision AI analysis over a small localized context window
        around candidate_y: [candidate_y - window, candidate_y + window].
        Prevents sending or repeatedly inferencing across the entire giant canvas.
        Returns:
            {
                "is_character_crossing": bool,
                "is_object_crossing": bool,
                "is_action_crossing": bool,
                "local_characters": List[Tuple[int, int, int, int]],
                "local_objects": List[Tuple[int, int, int, int]],
                "micro_gutter_y": Optional[int],
                "context_y_start": int,
                "context_y_end": int,
            }
        """
        h, w = canvas_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return {
                "is_character_crossing": False,
                "is_object_crossing": False,
                "is_action_crossing": False,
                "local_characters": [],
                "local_objects": [],
                "micro_gutter_y": None,
                "context_y_start": 0,
                "context_y_end": 0,
            }

        y_start = max(0, int(candidate_y - window))
        y_end = min(h, int(candidate_y + window))
        rel_y = int(candidate_y - y_start)

        context_img = canvas_bgr[y_start:y_end, :]
        ctx_h, ctx_w = context_img.shape[:2]

        model = cls.get_model()
        local_characters: List[Tuple[int, int, int, int]] = []
        local_objects: List[Tuple[int, int, int, int]] = []
        is_char_cross = False
        is_obj_cross = False

        if model is not None and ctx_h >= 40 and ctx_w >= 40:
            try:
                results = model(context_img, device=cls._device, conf=conf_threshold, verbose=False)
                if results and len(results) > 0 and results[0].boxes is not None:
                    boxes = results[0].boxes
                    for box in boxes:
                        xyxy = box.xyxy[0].cpu().numpy()
                        cls_id = int(box.cls[0].cpu().numpy())
                        cls_name = model.names.get(cls_id, "").lower()

                        bx1 = int(xyxy[0])
                        by1 = int(xyxy[1])
                        bx2 = int(xyxy[2])
                        by2 = int(xyxy[3])

                        # Global coordinates
                        g_box = (bx1, by1 + y_start, bx2, by2 + y_start)

                        if any(k in cls_name for k in ("person", "character", "face", "head", "monster")):
                            local_characters.append(g_box)
                            if by1 <= rel_y <= by2:
                                is_char_cross = True
                        elif any(k in cls_name for k in ("weapon", "sword", "gun", "knife", "vehicle", "car", "boat", "umbrella")):
                            local_objects.append(g_box)
                            if by1 <= rel_y <= by2:
                                is_obj_cross = True
            except Exception as e:
                logger.debug(f"[ComicVisionAI] Local context inference warning: {e}")

        # Check for micro-gutter within +/- 15px
        micro_gutter_y = None
        if ctx_h > 10:
            gray_ctx = cv2.cvtColor(context_img, cv2.COLOR_BGR2GRAY)
            search_min = max(0, rel_y - 15)
            search_max = min(ctx_h, rel_y + 16)
            row_stds = np.std(gray_ctx[search_min:search_max, :], axis=1)
            if len(row_stds) > 0:
                min_idx = int(np.argmin(row_stds))
                if row_stds[min_idx] < 6.0:
                    micro_gutter_y = y_start + search_min + min_idx

        # Check for vertical action lines crossing candidate_y
        is_act_cross = False
        if 10 <= rel_y < ctx_h - 10:
            sub_band = context_img[rel_y - 10:rel_y + 10, :]
            gray_band = cv2.cvtColor(sub_band, cv2.COLOR_BGR2GRAY)
            sob_x = np.abs(cv2.Sobel(gray_band, cv2.CV_32F, 1, 0, ksize=3))
            sob_y = np.abs(cv2.Sobel(gray_band, cv2.CV_32F, 0, 1, ksize=3))
            # Action / speed lines have strong horizontal gradient and vertical continuity
            if np.mean(sob_x) > 28.0 and np.mean(sob_x) > 1.4 * np.mean(sob_y):
                is_act_cross = True

        return {
            "is_character_crossing": is_char_cross,
            "is_object_crossing": is_obj_cross,
            "is_action_crossing": is_act_cross,
            "local_characters": local_characters,
            "local_objects": local_objects,
            "micro_gutter_y": micro_gutter_y,
            "context_y_start": y_start,
            "context_y_end": y_end,
        }

