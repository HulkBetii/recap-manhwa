import pytest
import math
from app import generate_gemini_prompt, _parse_gemini_image_specs, parse_gemini_recap_text
from recap_schema import parse_recap_data


def test_generate_gemini_prompt_contains_visual_grounding_rules():
    prompt = generate_gemini_prompt("Solo Leveling", 1, 30, "vi")
    assert "DIRECT VISUAL MATCHING" in prompt or "Direct Alignment" in prompt
    assert "Multi-Panel" in prompt
    assert "Solo Leveling" in prompt
    assert "Total provided pages: 30" in prompt


def test_parse_gemini_image_specs():
    # 1. Single page string
    s1 = _parse_gemini_image_specs("14")
    assert s1 == [{"page": 14, "priority": 1.0}]

    # 2. Single page with brackets
    s2 = _parse_gemini_image_specs("[14]")
    assert s2 == [{"page": 14, "priority": 1.0}]

    # 3. Two pages comma-separated (equal split)
    s3 = _parse_gemini_image_specs("[14, 15]")
    assert len(s3) == 2
    assert s3[0]["page"] == 14 and s3[0]["priority"] == 0.5
    assert s3[1]["page"] == 15 and s3[1]["priority"] == 0.5

    # 4. Two pages with percentage weights
    s4 = _parse_gemini_image_specs("[14:40%, 15:60%]")
    assert len(s4) == 2
    assert s4[0]["page"] == 14 and s4[0]["priority"] == 0.4
    assert s4[1]["page"] == 15 and s4[1]["priority"] == 0.6

    # 5. Two pages with float weights
    s5 = _parse_gemini_image_specs("[14:0.35, 15:0.65]")
    assert len(s5) == 2
    assert s5[0]["page"] == 14 and s5[0]["priority"] == 0.35
    assert s5[1]["page"] == 15 and s5[1]["priority"] == 0.65


def test_parse_gemini_recap_text_multi_panel():
    response = """
5 - Jin-woo bất ngờ nhận được nhiệm vụ bí ẩn từ hệ thống.#
[12, 13] - Trong lúc quái vật lao đến, anh né đòn rồi chém đứt cánh tay nó.#
[20:30%, 21:70%] - Sau khi kết liễu boss, anh nhận được thanh kiếm huyền thoại.#
"""
    parsed = parse_gemini_recap_text(response)
    assert len(parsed) == 3

    # Segment 1: Single image
    assert parsed[0]["speech"] == "Jin-woo bất ngờ nhận được nhiệm vụ bí ẩn từ hệ thống."
    assert parsed[0]["images"] == [{"page": 5, "priority": 1.0}]

    # Segment 2: Multi image equal split
    assert parsed[1]["speech"] == "Trong lúc quái vật lao đến, anh né đòn rồi chém đứt cánh tay nó."
    assert len(parsed[1]["images"]) == 2
    assert parsed[1]["images"][0] == {"page": 12, "priority": 0.5}
    assert parsed[1]["images"][1] == {"page": 13, "priority": 0.5}

    # Segment 3: Multi image percentage split
    assert len(parsed[2]["images"]) == 2
    assert parsed[2]["images"][0] == {"page": 20, "priority": 0.3}
    assert parsed[2]["images"][1] == {"page": 21, "priority": 0.7}

    # Segment 4: Triple image equal split
    s_triple = _parse_gemini_image_specs("[14, 15, 16]")
    assert len(s_triple) == 3
    assert [img["page"] for img in s_triple] == [14, 15, 16]
    assert math.isclose(sum(img["priority"] for img in s_triple), 1.0, abs_tol=0.01)

    # Validate against schema
    validated = parse_recap_data(parsed, max_page=30)
    assert len(validated) == 3


def test_generate_gemini_prompt_us_recap_culture_and_retention_hook():
    prompt_ep1_en = generate_gemini_prompt("Solo Leveling", 1, 45, "en")
    assert "EPISODE 1 HIGH-RETENTION HOOK" in prompt_ep1_en
    assert "0–5s GOLDEN RULE" in prompt_ep1_en
    assert "US MANHWA/WEBTOON CULTURE RULES" in prompt_ep1_en
    assert "Awakened abilities" in prompt_ep1_en or "Status Window" in prompt_ep1_en
    assert "YOUTUBE MONETIZATION & ADVERTISER-FRIENDLY SAFETY" in prompt_ep1_en
    assert "eliminated" in prompt_ep1_en and "dispatched" in prompt_ep1_en

    prompt_ep2_en = generate_gemini_prompt("Solo Leveling", 2, 45, "en")
    assert "EPISODE CONTINUATION" in prompt_ep2_en
    assert "in media res" in prompt_ep2_en


def test_parse_gemini_recap_text_drops_truncated_fragments():
    raw_response = """
1 - Đây là câu mở đầu hoàn chỉnh với đầy đủ thông tin chi tiết.#
2 - Quá ngắn.#
3 - Từng đứng mũi chịu s#
4 - Căn hầm trú ẩn được gia cố vững chắc trước đợt tấn công đầu tiên của quái vật.#
"""
    parsed = parse_gemini_recap_text(raw_response)
    assert len(parsed) == 2
    assert parsed[0]["speech"] == "Đây là câu mở đầu hoàn chỉnh với đầy đủ thông tin chi tiết."
    assert parsed[0]["images"][0]["page"] == 1
    assert parsed[1]["speech"] == "Căn hầm trú ẩn được gia cố vững chắc trước đợt tấn công đầu tiên của quái vật."
    assert parsed[1]["images"][0]["page"] == 4


def test_recap_segment_schema_enforces_min_length():
    from recap_schema import RecapSegment, RecapImage
    from pydantic import ValidationError

    # Should raise error for < 15 chars
    with pytest.raises(ValidationError):
        RecapSegment(
            speech="Quá ngắn.",
            images=[RecapImage(page=1, priority=1.0)]
        )

    # Valid segment
    valid_seg = RecapSegment(
        speech="Đây là câu recap hợp lệ với độ dài đầy đủ tiêu chuẩn.",
        images=[RecapImage(page=1, priority=1.0)]
    )
    assert valid_seg.speech.startswith("Đây là câu recap")


def test_generate_gemini_prompt_contains_hero_subject_alignment_rules():
    # Check Vietnamese prompt
    prompt_vi = generate_gemini_prompt("Ultimate Shut-in", 1, 40, "vi")
    assert "HERO SUBJECT ALIGNMENT" in prompt_vi or "Hero Subject Alignment" in prompt_vi
    assert "WEIGHTED MULTI-PANEL" in prompt_vi or "Weighted Multi-Panel" in prompt_vi
    assert "KHÔNG" in prompt_vi and "50/50" in prompt_vi

    # Check English prompt
    prompt_en = generate_gemini_prompt("Ultimate Shut-in", 1, 40, "en")
    assert "HERO SUBJECT ALIGNMENT" in prompt_en or "Hero Subject Alignment" in prompt_en
    assert "WEIGHTED MULTI-PANEL" in prompt_en or "Weighted Multi-Panel" in prompt_en
    assert "50/50" in prompt_en


def test_parse_gemini_image_specs_weighted_priority():
    # Test 75% / 25% hero panel split
    specs = _parse_gemini_image_specs("[39:75%, 40:25%]")
    assert len(specs) == 2
    assert specs[0]["page"] == 39
    assert math.isclose(specs[0]["priority"], 0.75, abs_tol=1e-3)
    assert specs[1]["page"] == 40
    assert math.isclose(specs[1]["priority"], 0.25, abs_tol=1e-3)


def test_master_prompt_bilingual_five_golden_rules_and_contrast():
    # 1. English Master Prompt
    prompt_en = generate_gemini_prompt("Solo Leveling", 1, 40, "en")
    assert "5 GOLDEN RULES FOR US RECAP STORYTELLING" in prompt_en
    assert "PERSONALITY FIRST" in prompt_en
    assert "RHYTHM VARIATION" in prompt_en
    assert "CONTRAST JUXTAPOSITION" in prompt_en
    assert "SHOW DON'T TELL" in prompt_en
    assert "AUDIENCE PULSE CHECK" in prompt_en
    assert "STYLE REFERENCE — BEFORE vs AFTER" in prompt_en
    assert "ANTI-AI CLICHÉ FILTER" in prompt_en
    assert "HERO SUBJECT ALIGNMENT" in prompt_en or "DIRECT VISUAL MATCHING" in prompt_en

    # 2. Vietnamese Master Prompt
    prompt_vi = generate_gemini_prompt("Solo Leveling", 1, 40, "vi")
    assert "5 QUY TẮC VÀNG CHO GIỌNG KỂ TIẾNG VIỆT" in prompt_vi
    assert "CÓ GÓC NHÌN, CÓ Ý KIẾN" in prompt_vi
    assert "BIẾN TẤU NHỊP CÂU" in prompt_vi
    assert "ĐỐI LẬP TƯƠNG PHẢN" in prompt_vi
    assert "MÔ TẢ CỤ THỂ, KHÔNG GIẢI THÍCH" in prompt_vi
    assert "GIỮ CHÂN KHÁN GIẢ" in prompt_vi
    assert "PHONG CÁCH THAM CHIẾU — TRƯỚC VÀ SAU" in prompt_vi
    assert "BỘ LỌC CHỐNG VĂN MẪU AI" in prompt_vi
    assert "KHỚP ĐÚNG CHỦ THỂ HÌNH ẢNH" in prompt_vi or "DIRECT VISUAL MATCHING" in prompt_vi


def test_english_master_prompt_has_couch_companion_and_action_slang():
    prompt_en = generate_gemini_prompt("Omniscient Reader", 1, 35, "en")
    assert "ACTION SLANG & HIGH-VELOCITY ACTIVE VERBS LEXICON" in prompt_en
    assert "drops him cold" in prompt_en
    assert "folds him in half" in prompt_en
    assert "sends him straight to the lobby" in prompt_en
    assert "hands them a massive L" in prompt_en
    assert "Couch Companion Persona" in prompt_en
    assert "Get this" in prompt_en or "Look at that" in prompt_en
    assert "Outside / Rivals?" in prompt_en

