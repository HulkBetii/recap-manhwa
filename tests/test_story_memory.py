import os
import json
import pytest
from story_memory import StoryMemory
from app import generate_gemini_prompt
import markets


def test_story_memory_save_and_load(tmp_path):
    download_dir = str(tmp_path / "task_download")
    mem = StoryMemory(comic_title="Test Comic", language="vi")

    mock_recap = [
        {"speech": "Mở đầu thảm họa kinh hoàng.", "images": [{"page": 1, "priority": 1.0}]},
        {"speech": "Giữa trận chiến, anh chàng tìm thấy thanh gươm thần.", "images": [{"page": 5, "priority": 1.0}]},
        {"speech": "Cựu binh giơ cao vũ khí sẵn sàng càn quét con đường máu.", "images": [{"page": 10, "priority": 1.0}]},
    ]

    mem.add_episode_recap(1, mock_recap, language="vi")
    assert mem.save(download_dir) is True

    loaded_mem = StoryMemory.load(download_dir)
    assert loaded_mem.comic_title == "Test Comic"
    assert "1" in loaded_mem.episodes
    assert loaded_mem.episodes["1"]["closing_cliffhanger"] == "Cựu binh giơ cao vũ khí sẵn sàng càn quét con đường máu."
    assert "thanh gươm thần" in loaded_mem.episodes["1"]["summary"]


def test_extract_cliffhanger_and_summary():
    recap_data = [
        {"speech": "Phân đoạn một: mở đầu."},
        {"speech": "Phân đoạn hai: diễn biến."},
        {"speech": "Phân đoạn ba: cao trào."},
        {"speech": "Phân đoạn bốn: nút thắt nghẹt thở!"},
    ]

    cliff = StoryMemory.extract_cliffhanger(recap_data)
    assert cliff == "Phân đoạn bốn: nút thắt nghẹt thở!"

    summary = StoryMemory.extract_chapter_summary(recap_data, max_sentences=3)
    assert "Phân đoạn một" in summary
    assert "Phân đoạn ba" in summary


def test_get_previous_context_chaining(tmp_path):
    download_dir = str(tmp_path / "task_chain")
    mem = StoryMemory(comic_title="Veteran", language="vi")

    # Episode 1 has no previous context
    assert mem.get_previous_context(1) is None

    # Add Episode 1 recap
    mem.add_episode_recap(1, [
        {"speech": "Bắt đầu trận chiến đẫm máu."},
        {"speech": "Anh chàng tiêu diệt trùm cuối."},
        {"speech": "Một bóng đen khổng lồ bất ngờ xuất hiện trên bầu trời!"},
    ])

    # Episode 2 retrieves Episode 1 context
    ctx_ep2 = mem.get_previous_context(2)
    assert ctx_ep2 is not None
    assert ctx_ep2["previous_episode"] == 1
    assert "bóng đen khổng lồ" in ctx_ep2["closing_cliffhanger"]
    assert "tiêu diệt trùm cuối" in ctx_ep2["summary"]


def test_generate_gemini_prompt_with_previous_context_english():
    prev_ctx = {
        "previous_episode": 1,
        "closing_cliffhanger": "He activated the ancient portal, unaware of the beasts waiting inside.",
        "summary": "The hunter defeated the goblin boss and claimed the dungeon core.",
        "macro_context": "Chapter 1: The dungeon opened in Seoul.",
    }

    prompt = generate_gemini_prompt("Solo Leveling", 2, 30, target_language="en", previous_context=prev_ctx)
    assert "EPISODE CONTINUATION & BINGE-WATCHING NARRATIVE CONTINUITY" in prompt
    assert "PREVIOUS CHAPTER CONTEXT (ROLLING STORY MEMORY)" in prompt
    assert "He activated the ancient portal" in prompt
    assert "BINGE TRANSITION RULE FOR LINE 1" in prompt
    assert "in media res" in prompt


def test_generate_gemini_prompt_with_previous_context_vietnamese():
    prev_ctx = {
        "previous_episode": 1,
        "closing_cliffhanger": "Thanh niên nhà ta rút gậy bóng chày chuẩn bị xông lên.",
        "summary": "Tận thế bắt đầu từ bào tử lạ, cậu dặn gia đình trữ lương thực.",
        "macro_context": "",
    }

    prompt = generate_gemini_prompt("Veteran", 2, 25, target_language="vi", previous_context=prev_ctx)
    assert "PREVIOUS CHAPTER CONTEXT" in prompt
    assert "Thanh niên nhà ta rút gậy bóng chày" in prompt
    assert "BINGE TRANSITION RULE FOR LINE 1" in prompt


def test_us_apocalypse_prompt_with_previous_context():
    market = markets.get_market("us_apocalypse")
    prev_ctx = {
        "previous_episode": 1,
        "closing_cliffhanger": "The siren wailed as millions of subterranean worms breached the surface.",
        "summary": "Paran locked down his doomsday shelter with unlimited supplies.",
        "macro_context": "",
    }

    prompt = market.get_gemini_prompt("Veteran of the Apocalypse", ep=2, total_pages=30, previous_context=prev_ctx)
    assert "EPISODE CONTINUATION (BINGE-WATCHING PACING & ROLLING STORY MEMORY)" in prompt
    assert "subterranean worms" in prompt
    assert "BINGE TRANSITION RULE FOR LINE 1" in prompt
    assert "Start immediately in media res" in prompt


def test_rolling_macro_context_sliding_window():
    mem = StoryMemory(comic_title="Epic Webtoon", language="vi")

    for ep in range(1, 10):
        mem.add_episode_recap(ep, [
            {"speech": f"Tập {ep} mở đầu gay cấn."},
            {"speech": f"Tập {ep} cao trào với boss."},
            {"speech": f"Tập {ep} cliffhanger nghẹt thở!"},
        ])

    ctx_ep9 = mem.get_previous_context(9)
    assert ctx_ep9["previous_episode"] == 8
    assert "Tập 8 cliffhanger nghẹt thở!" in ctx_ep9["closing_cliffhanger"]
    # Sliding window should only include recent chapters (e.g. 7) not chapter 1
    assert "Tập 7:" in ctx_ep9["macro_context"]
    assert "Tập 1:" not in ctx_ep9["macro_context"]


def test_fallback_to_disk_when_memory_not_in_instance(tmp_path):
    download_dir = str(tmp_path / "disk_fallback")
    ep1_dir = os.path.join(download_dir, "episode_1")
    os.makedirs(ep1_dir, exist_ok=True)

    disk_recap = [
        {"speech": "Cậu vừa thức tỉnh năng lực SSS."},
        {"speech": "Đối thủ quỳ gối xin tha nhưng vô ích."},
        {"speech": "Hắn kích hoạt viên ngọc ma thuật rồi biến mất."},
    ]
    with open(os.path.join(ep1_dir, "recap.json"), "w", encoding="utf-8") as f:
        json.dump(disk_recap, f, ensure_ascii=False)

    # Empty memory instance
    fresh_mem = StoryMemory(comic_title="Isekai", language="vi")
    ctx = fresh_mem.get_previous_context(2, download_dir=download_dir)

    assert ctx is not None
    assert ctx["previous_episode"] == 1
    assert "Hắn kích hoạt viên ngọc ma thuật" in ctx["closing_cliffhanger"]
