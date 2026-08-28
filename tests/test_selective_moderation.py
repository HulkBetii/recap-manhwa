import asyncio
import inspect

import pytest
from PIL import Image

from artifact_cache import validate_pdf_file
from moderation_utils import (
    is_safety_refusal,
    list_image_files,
    prepare_moderated_directory,
    prepare_safe_pdf_bundle,
    selected_file_names,
    selected_page_numbers,
    should_use_safety_fallback,
)
from workflow_stages_1 import Stage3_NSFWModeration, Stage4_PDFGeneration


def write_image(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 30), color).save(path)
    return path


def test_selected_pages_are_unique_and_keep_canonical_mapping(tmp_path):
    source = tmp_path / "images_pdf"
    destination = tmp_path / "images_blur"
    for page in range(1, 8):
        write_image(source / f"{page:03d}.jpg", (page, page, page))

    segments = [
        {"images": [{"page": 2}, {"page": 5}]},
        {"images": [{"page": 5}, {"page": 7}]},
    ]
    pages = selected_page_numbers(segments, max_page=7)
    selected = selected_file_names(list_image_files(source), pages)
    calls = []

    async def fake_sanitizer(*, ep_dir, selected_files, strict, **kwargs):
        calls.extend(selected_files)
        assert strict is True
        assert list_image_files(ep_dir) == list_image_files(source)
        return [f"{name}: safe" for name in selected_files]

    asyncio.run(prepare_moderated_directory(
        source,
        destination,
        sanitizer=fake_sanitizer,
        selected_files=selected,
    ))

    assert pages == [2, 5, 7]
    assert calls == ["002.jpg", "005.jpg", "007.jpg"]
    assert list_image_files(destination) == list_image_files(source)


def test_safe_mode_disabled_copies_images_without_sanitizer(tmp_path):
    source = tmp_path / "images_pdf"
    destination = tmp_path / "images_blur"
    for page in range(1, 4):
        write_image(source / f"{page:03d}.jpg", (page, 0, 0))

    asyncio.run(prepare_moderated_directory(
        source,
        destination,
        sanitizer=None,
        selected_files=["002.jpg"],
    ))

    assert list_image_files(destination) == ["001.jpg", "002.jpg", "003.jpg"]


def test_failed_moderation_does_not_replace_existing_directory(tmp_path):
    source = tmp_path / "images_pdf"
    destination = tmp_path / "images_blur"
    write_image(source / "001.jpg", (1, 2, 3))
    write_image(destination / "old.jpg", (9, 9, 9))
    old_bytes = (destination / "old.jpg").read_bytes()

    async def failing_sanitizer(**kwargs):
        raise RuntimeError("inference failed")

    with pytest.raises(RuntimeError, match="inference failed"):
        asyncio.run(prepare_moderated_directory(
            source,
            destination,
            sanitizer=failing_sanitizer,
            selected_files=["001.jpg"],
        ))

    assert list_image_files(destination) == ["old.jpg"]
    assert (destination / "old.jpg").read_bytes() == old_bytes


@pytest.mark.parametrize("segments", [[], [{"images": []}]])
def test_empty_selected_pages_are_rejected(segments):
    with pytest.raises(ValueError, match="does not select"):
        selected_page_numbers(segments, max_page=3)


def test_out_of_range_selected_page_is_rejected():
    with pytest.raises(ValueError, match="exceeds"):
        selected_page_numbers([{"images": [{"page": 4}]}], max_page=3)


@pytest.mark.parametrize(
    "message",
    [
        "I cannot help with explicit content because of the safety policy.",
        "Không thể xử lý nội dung nhạy cảm.",
    ],
)
def test_explicit_safety_refusal_is_detected(message):
    assert is_safety_refusal(message)


@pytest.mark.parametrize(
    "message",
    [
        "Response is empty",
        "Timeout waiting for Gemini",
        "Profile is not logged in",
        "Something went wrong while generating",
        "I cannot help with that request.",
    ],
)
def test_generic_gemini_errors_do_not_trigger_safety_fallback(message):
    assert not is_safety_refusal(message)


def test_disabled_safe_mode_never_uses_full_chapter_fallback():
    assert not should_use_safety_fallback(
        safe_mode=False,
        attempt=1,
        response="I cannot help because of the safety policy.",
    )
    assert not should_use_safety_fallback(
        safe_mode=True,
        attempt=2,
        response="I cannot help because of the safety policy.",
    )


def test_safe_pdf_fallback_is_atomic_and_does_not_mutate_canonical_images(tmp_path):
    source = tmp_path / "images_pdf"
    destination = tmp_path / "gemini_safe"
    write_image(source / "001.jpg", (10, 20, 30))
    write_image(source / "002.jpg", (40, 50, 60))
    original = {name: (source / name).read_bytes() for name in list_image_files(source)}
    calls = []

    async def fake_sanitizer(*, ep_dir, selected_files, strict, **kwargs):
        calls.append(selected_files)
        assert strict is True
        Image.new("RGB", (20, 30), (0, 0, 0)).save(f"{ep_dir}/001.jpg")
        return [f"{name}: safe" for name in list_image_files(ep_dir)]

    pdf_path = asyncio.run(prepare_safe_pdf_bundle(
        source,
        destination,
        pdf_name="chapter.pdf",
        pdf_quality=30,
        sanitizer=fake_sanitizer,
    ))

    assert calls == [None]
    assert validate_pdf_file(pdf_path)
    assert (destination / "used.json").is_file()
    assert {name: (source / name).read_bytes() for name in list_image_files(source)} == original


def test_stage_3_defers_moderation_and_stage_4_uses_raw_images_pdf():
    stage_3_source = inspect.getsource(Stage3_NSFWModeration.execute)
    stage_4_source = inspect.getsource(Stage4_PDFGeneration.execute)

    assert "sanitize_episode_images" not in stage_3_source
    assert "images_blur" not in stage_3_source
    assert '"images_pdf"' in stage_4_source
    assert '"images_blur"' not in stage_4_source
