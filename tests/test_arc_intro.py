import os
import pytest
from arc_intro_engine import (
    ArcClimaxMiner,
    InMediasResHookGenerator,
    DynamicHookDirector,
    HookArchetype,
    FastIntroPrepender
)

def test_in_medias_res_hook_generator_en():
    hook = InMediasResHookGenerator.generate_hook_script(
        comic_title="Test Apocalypse",
        protagonist_name="Hunter Park",
        climax_episode=100,
        language="en"
    )
    assert "Hunter Park" in hook
    assert "mutant" in hook
    assert "right here" in hook
    assert len(hook.split()) >= 30, "Hook script should have adequate storytelling length"


def test_in_medias_res_hook_generator_vi():
    hook = InMediasResHookGenerator.generate_hook_script(
        comic_title="Chiến Binh Tận Thế",
        protagonist_name="Kang Seongho",
        climax_episode=50,
        language="vi"
    )
    assert "Kang Seongho" in hook
    assert "quái thú" in hook
    assert "tận thế" in hook
    assert len(hook.split()) >= 30


def test_custom_hook_override():
    custom = "This is a completely custom high-retention opening hook line."
    hook = InMediasResHookGenerator.generate_hook_script(
        comic_title="Any",
        protagonist_name="Any",
        climax_episode=10,
        custom_hook=custom
    )
    assert hook == custom


def test_srt_time_shifting(tmp_path):
    intro_srt = tmp_path / "intro.srt"
    intro_srt.write_text(
        "1\n00:00:00,000 --> 00:00:05,000\nThis is the intro hook.\n\n"
        "2\n00:00:05,100 --> 00:00:10,000\nFacing the final boss.\n",
        encoding="utf-8"
    )

    main_srt = tmp_path / "main.srt"
    main_srt.write_text(
        "1\n00:00:00,500 --> 00:00:04,500\nEpisode 1 starts here.\n\n"
        "2\n00:00:05,000 --> 00:00:08,000\nHe gathers supplies.\n",
        encoding="utf-8"
    )

    out_srt = tmp_path / "combined.srt"
    # Create fake videos so prepend_intro can run or mock video part
    intro_vid = tmp_path / "intro.mp4"
    intro_vid.write_bytes(b"dummy")
    main_vid = tmp_path / "main.mp4"
    main_vid.write_bytes(b"dummy")
    out_vid = tmp_path / "out.mp4"

    # We can test the srt shifting logic directly through FastIntroPrepender or helper
    # Mock subprocess.run for ffmpeg copy
    import subprocess
    orig_run = subprocess.run
    def mock_run(cmd, *args, **kwargs):
        temp_target = cmd[-1]
        with open(temp_target, "wb") as f:
            f.write(b"combined_video_dummy")
        class Res:
            returncode = 0
        return Res()

    subprocess.run = mock_run
    try:
        ok = FastIntroPrepender.prepend_intro(
            intro_video_path=str(intro_vid),
            intro_srt_path=str(intro_srt),
            intro_duration=10.0,
            target_video_path=str(main_vid),
            target_srt_path=str(main_srt),
            output_video_path=str(out_vid),
            output_srt_path=str(out_srt)
        )
        assert ok is True
        content = out_srt.read_text(encoding="utf-8")
        assert "This is the intro hook." in content
        assert "Episode 1 starts here." in content
        # Check that main subtitle start time is shifted by exactly 10.0s (00:00:00,500 -> 00:00:10,500)
        assert "00:00:10,500 --> 00:00:14,500" in content
        assert "00:00:15,000 --> 00:00:18,000" in content
    finally:
        subprocess.run = orig_run


def test_archetype_detection():
    # 1. Vengeance
    assert DynamicHookDirector.detect_archetype(
        climax_text="Hắn tìm đến những kẻ đã phản bội năm xưa để phục thù máu."
    ) == HookArchetype.VENGEANCE_RETRIBUTION

    # 2. Ticking bomb
    assert DynamicHookDirector.detect_archetype(
        climax_text="Thời gian đếm ngược chỉ còn 10 giây trước khi thế giới diệt vong."
    ) == HookArchetype.TICKING_BOMB_CRISIS

    # 3. Absurd high concept
    assert DynamicHookDirector.detect_archetype(
        climax_text="Lợi dụng lỗi hệ thống và độc quyền nguồn cung để thao túng thị trường."
    ) == HookArchetype.ABSURD_HIGH_CONCEPT

    # 4. Paradox
    assert DynamicHookDirector.detect_archetype(
        climax_text="Một nghịch lý bí ẩn không thể giải thích được diễn ra trong căn hầm."
    ) == HookArchetype.OPEN_LOOP_PARADOX

    # 5. Default Flex
    assert DynamicHookDirector.detect_archetype(
        climax_text="Nhát chém kinh hoàng quét sạch bầy quái vật."
    ) == HookArchetype.OUTRAGEOUS_FLEX


@pytest.mark.parametrize("arch", [
    HookArchetype.OUTRAGEOUS_FLEX,
    HookArchetype.ABSURD_HIGH_CONCEPT,
    HookArchetype.VENGEANCE_RETRIBUTION,
    HookArchetype.TICKING_BOMB_CRISIS,
    HookArchetype.OPEN_LOOP_PARADOX
])
def test_all_five_archetypes_open_loop_and_length(arch):
    # Test Vietnamese
    script_vi = DynamicHookDirector.get_archetype_template(
        archetype=arch,
        protagonist_name="Kang Seongho",
        language="vi"
    )
    words_vi = script_vi.split()
    assert 30 <= len(words_vi) <= 55, f"VI script length {len(words_vi)} out of 30-55 range for {arch}"
    assert script_vi.strip().endswith("?"), f"VI script for {arch} must end with an Open Loop question: {script_vi}"

    # Test English
    script_en = DynamicHookDirector.get_archetype_template(
        archetype=arch,
        protagonist_name="Hunter Park",
        language="en"
    )
    words_en = script_en.split()
    assert 30 <= len(words_en) <= 55, f"EN script length {len(words_en)} out of 30-55 range for {arch}"
    assert script_en.strip().endswith("?"), f"EN script for {arch} must end with an Open Loop question: {script_en}"


@pytest.mark.asyncio
async def test_dynamic_retention_hook_async():
    res = await DynamicHookDirector.generate_dynamic_retention_hook(
        comic_title="The Greatest Estate Developer",
        protagonist_name="Lloyd",
        climax_episode=100,
        climax_text="Hệ thống ban thưởng cho kẻ trục lợi bá đạo nhất thiên hạ.",
        language="vi"
    )
    assert res["archetype"] == HookArchetype.ABSURD_HIGH_CONCEPT.value
    assert "Lloyd" in res["hook_script"]
    assert res["hook_script"].endswith("?")
    assert 30 <= res["word_count"] <= 55


def test_select_top_climax_images_white_ratio_filtering(tmp_path):
    import numpy as np
    from PIL import Image

    ep_dir = tmp_path / "episode_10" / "images"
    ep_dir.mkdir(parents=True)

    # 1. Image with rich saturated action colors (0% white)
    img_action_arr = np.random.randint(50, 180, (600, 600, 3), dtype=np.uint8)
    img_action_arr[:, :, 0] = np.random.randint(180, 240, (600, 600), dtype=np.uint8)
    Image.fromarray(img_action_arr).save(str(ep_dir / "001_action.jpg"))

    # 2. Image with text bubble / speech box (25% white) on textured image
    img_white_arr = np.random.randint(50, 180, (600, 600, 3), dtype=np.uint8)
    img_white_arr[:150, :] = 255  # 25% pure white text box
    Image.fromarray(img_white_arr).save(str(ep_dir / "002_white_box.jpg"))

    top = ArcClimaxMiner.select_top_climax_images(str(tmp_path), climax_episode=10, num_images=2, min_point_threshold=0)
    assert len(top) == 2
    # The action image should be ranked #1 because 002_white_box is penalized by white_ratio * 40
    assert top[0]["filename"] == "001_action.jpg"
    assert top[0]["composite"] > top[1]["composite"]
    assert top[1]["white_ratio"] > 0.20



