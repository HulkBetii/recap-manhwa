from __future__ import annotations

import os
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from PIL import Image, ImageDraw, ImageFont


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MODERATION_MODEL_VERSION = "grounding-dino-base+sam-vit-base:v1"
MODERATION_PROMPT_VERSION = "sensitive-comic-regions:v1"
MODERATION_PROMPT = (
    "breast. buttocks. genitalia. nude body. male chest. exposed torso. "
    "underwear. bikini. speech bubble. comic text. written words."
)
SAFETY_MARKERS = (
    "safety policy",
    "safety policies",
    "safety guideline",
    "safety guidelines",
    "content policy",
    "content policies",
    "explicit content",
    "sexually explicit",
    "sexual content",
    "graphic nudity",
    "nội dung nhạy cảm",
    "chính sách an toàn",
)
JUNK_TEXT_KEYWORDS = (
    "chapter",
    "chap",
    "tập",
    "chương",
    "prologue",
    "epilogue",
    "credit",
    "credits",
    "translated",
    "translator",
    "translation",
    "scanlation",
    "scans",
    "discord",
    "donate",
    "patreon",
    "team",
    "group",
    "tác giả",
    "họa sĩ",
    "nhóm dịch",
    "raw",
    "edit",
    "typeset",
    "proofread",
    "cleaning",
)


def list_image_files(directory: str | Path) -> list[str]:
    root = Path(directory)
    if not root.is_dir():
        return []
    return sorted(
        item.name
        for item in root.iterdir()
        if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES
    )


def is_blank_or_solid_page(
    img_bgr: Any,
    bg_val: int | None = None,
    tol: int = 15,
    ratio_threshold: float = 0.992,
) -> tuple[bool, str]:
    import cv2
    import numpy as np

    if img_bgr is None or (hasattr(img_bgr, "size") and img_bgr.size == 0):
        return True, "empty_image"
    h, w = img_bgr.shape[:2]
    if h < 20 or w < 20:
        return True, "dimension_too_small"

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    if bg_val is None:
        border_pixels = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
        bg_val = int(np.median(border_pixels))

    diff = np.abs(gray.astype(np.int32) - bg_val)
    bg_ratio = float(np.mean(diff <= tol))
    if bg_ratio >= ratio_threshold:
        return True, "solid_background"

    canny = cv2.Canny(gray, 50, 150)
    edge_ratio = float(np.mean(canny > 0))
    if edge_ratio < 0.0005:
        return True, "low_edge_density"

    variance = float(np.var(gray))
    if variance < 12.0:
        return True, "low_variance"

    return False, "valid"


def is_junk_or_title_page(
    img_bgr: Any,
    bg_val: int | None = None,
    tol: int = 15,
    ocr_texts: list[str] | None = None,
) -> tuple[bool, str]:
    """
    Detects whether a comic slice is a title card, chapter banner, credits, or non-story junk.
    """
    import cv2
    import numpy as np

    is_blank, reason = is_blank_or_solid_page(img_bgr, bg_val=bg_val, tol=tol)
    if is_blank:
        return True, reason

    h, w = img_bgr.shape[:2]
    if h < 100 or w < 100:
        return True, "too_small"

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    if bg_val is None:
        border_pixels = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
        bg_val = int(np.median(border_pixels))

    diff = np.abs(gray.astype(np.int32) - bg_val)
    bg_ratio = float(np.mean(diff <= tol))

    # 1. OCR text check if provided
    if ocr_texts:
        joined_text = " ".join(t.lower() for t in ocr_texts if t).strip()
        for kw in JUNK_TEXT_KEYWORDS:
            if kw in joined_text:
                canny = cv2.Canny(gray, 50, 150)
                edge_ratio = float(np.mean(canny > 0))
                if edge_ratio < 0.05:
                    return True, f"junk_keyword_{kw}"

    # 2. Sparse title banner detection (88%+ uniform background with minimal sparse text)
    if bg_ratio >= 0.88:
        canny = cv2.Canny(gray, 50, 150)
        edge_ratio = float(np.mean(canny > 0))
        if edge_ratio < 0.025:
            return True, "sparse_title_banner"

    return False, "valid_story_panel"


def selected_page_numbers(segments: Iterable[dict[str, Any]], *, max_page: int) -> list[int]:
    if max_page < 1:
        raise ValueError("max_page must be positive")
    pages: set[int] = set()
    for segment in segments:
        for image in segment.get("images", []):
            page = image.get("page") if isinstance(image, dict) else None
            if not isinstance(page, int) or isinstance(page, bool):
                raise ValueError("selected image page must be an integer")
            if page < 1 or page > max_page:
                raise ValueError(f"page {page} exceeds available page count {max_page}")
            pages.add(page)
    if not pages:
        raise ValueError("recap does not select any image pages")
    return sorted(pages)


def selected_file_names(image_files: list[str], pages: Iterable[int]) -> list[str]:
    return [image_files[page - 1] for page in pages]


def is_safety_refusal(value: str) -> bool:
    normalized = value.casefold()
    return any(marker in normalized for marker in SAFETY_MARKERS)


def should_use_safety_fallback(*, safe_mode: bool, attempt: int, response: str) -> bool:
    return safe_mode and attempt == 1 and is_safety_refusal(response)


def create_numbered_pdf(image_dir: str | Path, pdf_path: str | Path, quality: int) -> None:
    source = Path(image_dir)
    destination = Path(pdf_path)
    image_files = list_image_files(source)
    if not image_files:
        raise FileNotFoundError("no images available for PDF generation")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.tmp.pdf")
    converted: list[Image.Image] = []
    try:
        for index, file_name in enumerate(image_files, 1):
            with Image.open(source / file_name) as image:
                page = image.convert("RGB")
                page.load()
            if page.width > 700:
                resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
                page = page.resize((700, int(page.height * (700 / page.width))), resampling)

            draw = ImageDraw.Draw(page)
            label = f"Page: {index}"
            try:
                font = ImageFont.truetype("arial.ttf", 36)
            except Exception:
                font = ImageFont.load_default()
            bounds = draw.textbbox((0, 0), label, font=font)
            text_width = bounds[2] - bounds[0]
            text_height = bounds[3] - bounds[1]
            padding = 10
            left = (page.width - text_width - padding * 2) // 2
            top = 20
            draw.rectangle(
                [left, top, left + text_width + padding * 2, top + text_height + padding * 2],
                fill=(0, 0, 0),
            )
            draw.text((left + padding, top + padding), label, fill=(255, 255, 255), font=font)
            converted.append(page)

        converted[0].save(
            temp_path,
            "PDF",
            save_all=True,
            append_images=converted[1:],
            quality=quality,
            optimize=True,
        )
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()
        for image in converted:
            image.close()


def _replace_directory(temp_dir: Path, destination: Path) -> None:
    backup = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.bak")
    had_destination = destination.exists()
    if had_destination:
        os.replace(destination, backup)
    try:
        os.replace(temp_dir, destination)
    except Exception:
        if had_destination and backup.exists():
            os.replace(backup, destination)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


async def prepare_moderated_directory(
    source_dir: str | Path,
    destination_dir: str | Path,
    *,
    sanitizer: Callable[..., Awaitable[list[str]]] | None,
    selected_files: Iterable[str] | None,
    sanitizer_kwargs: dict[str, Any] | None = None,
) -> list[str]:
    source = Path(source_dir)
    destination = Path(destination_dir)
    image_files = list_image_files(source)
    if not image_files:
        raise FileNotFoundError("no source images available for moderation")

    selected = None if selected_files is None else sorted(set(selected_files))
    if selected is not None:
        missing = sorted(set(selected) - set(image_files))
        if missing:
            raise ValueError(f"selected moderation files are missing: {missing}")

    temp_dir = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.tmp")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        for file_name in image_files:
            shutil.copy2(source / file_name, temp_dir / file_name)

        results: list[str] = []
        if sanitizer is not None:
            kwargs = dict(sanitizer_kwargs or {})
            results = await sanitizer(
                ep_dir=str(temp_dir),
                selected_files=selected,
                strict=True,
                **kwargs,
            )
            expected = len(image_files) if selected is None else len(selected)
            if len(results) != expected:
                raise RuntimeError("moderation did not process every requested image")

        _replace_directory(temp_dir, destination)
        return results
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


async def prepare_safe_pdf_bundle(
    source_dir: str | Path,
    destination_dir: str | Path,
    *,
    pdf_name: str,
    pdf_quality: int,
    sanitizer: Callable[..., Awaitable[list[str]]],
    sanitizer_kwargs: dict[str, Any] | None = None,
) -> Path:
    source = Path(source_dir)
    destination = Path(destination_dir)
    image_files = list_image_files(source)
    if not image_files:
        raise FileNotFoundError("no source images available for safe PDF fallback")

    temp_dir = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.tmp")
    images_dir = temp_dir / "images"
    try:
        images_dir.mkdir(parents=True, exist_ok=False)
        for file_name in image_files:
            shutil.copy2(source / file_name, images_dir / file_name)

        kwargs = dict(sanitizer_kwargs or {})
        results = await sanitizer(
            ep_dir=str(images_dir),
            selected_files=None,
            strict=True,
            **kwargs,
        )
        if len(results) != len(image_files):
            raise RuntimeError("safe PDF moderation did not process every chapter image")

        create_numbered_pdf(images_dir, temp_dir / pdf_name, pdf_quality)
        (temp_dir / "used.json").write_text(
            json.dumps({"fallback": "gemini_safety_refusal"}, ensure_ascii=True),
            encoding="utf-8",
        )
        _replace_directory(temp_dir, destination)
        return destination / pdf_name
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
