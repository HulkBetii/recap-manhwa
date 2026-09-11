import os
import json
import pytest
from app import generate_gemini_prompt
from markets.us_apocalypse.prompt import get_us_apocalypse_prompt
from story_memory import StoryMemory


def test_us_apocalypse_prompt_ep1_has_name_anchoring_and_gender_adaptive():
    prompt = get_us_apocalypse_prompt("Veteran of the Apocalypse", ep=1, total_pages=30)
    # Check Name Anchoring in Episode 1
    assert "PROTAGONIST NAME IDENTIFICATION & ANCHORING" in prompt
    assert "MUST explicitly introduce the protagonist by their actual name" in prompt
    # Check Contextual Anchoring (Organic Flow)
    assert "CONTEXTUAL PROTAGONIST ANCHORING (ORGANIC FLOW & ZERO FORMULAIC REPETITION)" in prompt
    assert "ONLY 4 CRITICAL CONTEXTUAL ANCHORS" in prompt
    assert "Opening Hook (0-15s)" in prompt
    assert "Scene & Time Transitions" in prompt
    assert "Multi-Character Disambiguation" in prompt
    assert "Climax Milestone" in prompt
    assert "THE 80% NARRATIVE FREEDOM" in prompt
    # Check Anti-AI Cliché Filter
    assert "ANTI-AI CLICHÉ FILTER (BAN FORMULAIC AI STEREOTYPES)" in prompt
    assert "SENTENCE VARIETY & CADENCE" in prompt
    # Check Gender-Adaptive Matrix
    assert "GENDER-ADAPTIVE PRONOUN MATRIX (ZERO MISGENDERING MANDATE)" in prompt
    assert "If Male MC" in prompt
    assert "If Female MC" in prompt
    assert "our girl" in prompt
    assert "our boy" in prompt
    # Check Zero Misgendering
    assert "ZERO MISGENDERING" in prompt
    assert "If the protagonist is FEMALE, NEVER use 'he', 'him', 'boy', or 'dude'" in prompt
    # Check Side Character Shield
    assert "SIDE CHARACTER ISOLATION SHIELD" in prompt


def test_vietnamese_prompt_has_name_anchoring_and_gender_adaptive():
    prompt_vi = generate_gemini_prompt("Veteran of the Apocalypse", 1, 30, target_language="vi")
    # Check Name Anchoring in VN Ep 1
    assert "PROTAGONIST NAME IDENTIFICATION & ANCHORING" in prompt_vi
    # Check VN Contextual Anchoring
    assert "ĐỊNH DANH THEO NGỮ CẢNH & KỂ CHUYỆN HỮU CƠ (CONTEXTUAL PROTAGONIST ANCHORING)" in prompt_vi
    assert "CHỈ GỌI TÊN RIÊNG Ở 4 VỊ TRÍ THẬT SỰ CẦN THIẾT" in prompt_vi
    assert "CHỦ NGỮ ẨN" in prompt_vi
    # Check VN Anti-AI Clichés
    assert "BỘ LỌC CHỐNG VĂN MẪU AI (ANTI-AI CLICHÉ FILTER)" in prompt_vi
    assert "TIẾT CHẾ DANH XƯNG CÁ TÍNH" in prompt_vi
    # Check VN Gender-Adaptive
    assert "MA TRẬN ĐẠI TỪ THÍCH ỨNG GIỚI TÍNH (ZERO MISGENDERING MANDATE)" in prompt_vi
    assert "NẾU LÀ NAM CHÍNH" in prompt_vi
    assert "NẾU LÀ NỮ CHÍNH" in prompt_vi
    assert "CẤM TIỆT việc gọi Nữ chính là 'anh chàng', 'thanh niên', 'ông bạn'" in prompt_vi
    # Check VN Side Character Shield
    assert "RÀO CẢN ĐỊNH DANH NHÂN VẬT PHỤ (SIDE CHARACTER ISOLATION SHIELD)" in prompt_vi


def test_story_memory_protagonist_name_and_gender_persistence(tmp_path):
    download_dir = str(tmp_path / "mem_test")
    mem = StoryMemory(comic_title="Villainess", language="vi", protagonist_name="Penelope", protagonist_gender="female")

    assert mem.protagonist_name == "Penelope"
    assert mem.protagonist_gender == "female"
    mem.save(download_dir)

    loaded = StoryMemory.load(download_dir)
    assert loaded.protagonist_name == "Penelope"
    assert loaded.protagonist_gender == "female"


def test_story_memory_infer_protagonist_name_and_gender():
    # 1. From glossary female
    glossary = {"protagonist": "Penelope", "gender": "female"}
    inferred_name = StoryMemory.infer_protagonist_name([], glossary=glossary)
    inferred_gender = StoryMemory.infer_protagonist_gender(glossary=glossary)
    assert inferred_name == "Penelope"
    assert inferred_gender == "female"

    # 2. From recap speech with titles
    recap_with_titles = [
        {"speech": "Khi Tổng thống Jang Wontaek bất ngờ ban bố tình trạng khẩn cấp toàn quốc, Seongho Kang nhận ra cơn ác mộng ngày tận thế sắp thành hiện thực."},
        {"speech": "Seongho Kang đứng lặng trong căn phòng nhỏ, vuốt ve chú chó cưng và tự nhủ bản thân phải sinh tồn như một cựu binh tận thế."},
        {"speech": "Seongho quan sát hai gã đồng đội thích đâm đầu lấy thịt đè người và hào phóng nhường hẳn một phút chạy trước."}
    ]
    inferred_title_name = StoryMemory.infer_protagonist_name(recap_with_titles)
    assert inferred_title_name == "Seongho Kang"

    # 3. From recap speech female
    recap_female = [
        {"speech": "Penelope wakes up in the body of the hated villainess."},
        {"speech": "Cô nàng nhà ta mỉm cười sắc sảo trước đám quý tộc hợm hĩnh."},
        {"speech": "She raises her wine glass and outsmarts her brothers."},
    ]
    inferred_speech_gender = StoryMemory.infer_protagonist_gender(recap_data=recap_female)
    assert inferred_speech_gender == "female"


def test_story_memory_female_protagonist_propagation_to_subsequent_episodes():
    mem = StoryMemory(comic_title="Villainess Reverse", language="vi")
    recap_ep1 = [
        {"speech": "Penelope has returned to turn the tables on everyone."},
        {"speech": "Cô nàng nhà ta lạnh lùng đối đầu với hoàng tử."},
    ]
    mem.add_episode_recap(1, recap_ep1, language="vi", protagonist_name="Penelope", protagonist_gender="female")
    assert mem.protagonist_name == "Penelope"
    assert mem.protagonist_gender == "female"

    ctx_ep2 = mem.get_previous_context(2)
    assert ctx_ep2 is not None
    assert ctx_ep2["protagonist_name"] == "Penelope"
    assert ctx_ep2["protagonist_gender"] == "female"

    # Test prompt generation for Episode 2 with female protagonist
    prompt_ep2_us = get_us_apocalypse_prompt("Villainess Reverse", ep=2, total_pages=25, previous_context=ctx_ep2)
    assert 'Protagonist Name Anchor: "Penelope"' in prompt_ep2_us
    assert "Protagonist Gender: FEMALE" in prompt_ep2_us
    assert "our girl" in prompt_ep2_us

    prompt_ep2_app = generate_gemini_prompt("Villainess Reverse", 2, 25, target_language="vi", previous_context=ctx_ep2)
    assert 'Protagonist Name Anchor: "Penelope"' in prompt_ep2_app
    assert "Protagonist Gender: FEMALE" in prompt_ep2_app
    assert "cô/nàng/cô ấy" in prompt_ep2_app
