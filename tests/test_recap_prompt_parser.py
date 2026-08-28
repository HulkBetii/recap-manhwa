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

