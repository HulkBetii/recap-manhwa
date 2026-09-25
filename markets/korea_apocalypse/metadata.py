from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional


def _extract_korean_story_beats(
    comic_title: str,
    story_memory: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    title_lower = (comic_title or "").lower()
    mc_name = "생존자"
    if story_memory:
        raw_mc = story_memory.get("protagonist_name", "").strip()
        if raw_mc and len(raw_mc) > 1 and raw_mc.lower() not in ["a", "protagonist", "mc", "unknown"]:
            mc_name = raw_mc

    disaster = "아포칼립스"
    advantage = "치트 시스템"
    flaw = "F급 최약체"

    mem_text = str(story_memory).lower() if story_memory else ""
    combined = f"{title_lower} {mem_text}"

    if any(k in combined for k in ["zombie", "좀비", "괴물", "infected", "82-08"]):
        disaster = "좀비 바이러스"
        advantage = "무한 벙커와 보급품"
        flaw = "평범한 회사원"
    elif any(k in combined for k in ["freeze", "빙하기", "frost", "cold"]):
        disaster = "영하 60도 극한 빙하기"
        advantage = "무한 차원 창고"
        flaw = "버림받은 쉘터 난민"
    elif any(k in combined for k in ["tower", "탑", "floor", "regress"]):
        disaster = "멸망의 탑"
        advantage = "회귀 거부 치트"
        flaw = "최하층 도전자"
    elif any(k in combined for k in ["hunter", "게이트", "dungeon", "헌터"]):
        disaster = "SSS급 던전 브레이크"
        advantage = "버그급 고유 스킬"
        flaw = "만년 F급 짐꾼"

    return {
        "mc_name": mc_name,
        "disaster": disaster,
        "advantage": advantage,
        "flaw": flaw,
    }


def build_korean_narrative_chapters(
    chapters: Optional[List[Dict[str, Any]]] = None,
    from_ep: int = 1,
    to_ep: int = 1,
) -> List[Dict[str, Any]]:
    korean_default_progression = [
        "재앙의 시작과 각성",
        "생존자 구출과 첫 번째 위기",
        "지하 벙커 방어전과 사이다 복수",
        "돌연변이 군단의 침공",
        "파멸의 여명과 최강의 군주",
    ]

    if not chapters:
        return [
            {"timestamp": "00:00", "title": f"{korean_default_progression[0]} (제{from_ep}화)", "episode": from_ep},
            {"timestamp": "10:00", "title": f"{korean_default_progression[1]} (제{from_ep+1 if to_ep > from_ep else from_ep}화)", "episode": from_ep + 1 if to_ep > from_ep else from_ep},
            {"timestamp": "25:00", "title": f"{korean_default_progression[-1]} (제{to_ep}화)", "episode": to_ep},
        ]

    result = []
    total_ch = len(chapters)
    for i, ch in enumerate(chapters):
        ts = "00:00" if i == 0 else ch.get("timestamp", "00:00")
        ep_num = ch.get("episode", from_ep + i)
        prog_idx = min(len(korean_default_progression) - 1, int(i * len(korean_default_progression) / max(1, total_ch)))
        theme = korean_default_progression[prog_idx]
        result.append({
            "timestamp": ts,
            "title": f"{theme} (제{ep_num}화)",
            "episode": ep_num,
        })
    return result


def generate_korea_apocalypse_metadata(
    comic_title: str,
    from_ep: int,
    to_ep: int,
    chapters: Optional[List[Dict[str, Any]]] = None,
    story_memory: Optional[Dict[str, Any]] = None,
    download_dir: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    ep_range = f"{from_ep}화~{to_ep}화" if from_ep != to_ep else f"{from_ep}화"
    beats = _extract_korean_story_beats(comic_title, story_memory)
    mc_name = beats["mc_name"]
    disaster = beats["disaster"]
    advantage = beats["advantage"]
    flaw = beats["flaw"]

    # 1. Title Variants for A/B Testing
    var_a = f"[아포칼립스 웹툰] {flaw} 취급받던 생존자, {advantage} 각성하고 배신자들 참교육 ({ep_range} 몰아보기)"
    var_b = f"[웹툰 몰아보기] 세상은 {disaster}로 멸망했는데 나 혼자만 {advantage} 독점함 ({ep_range} 몰아보기)"
    var_c = f"[웹툰 몰아보기] 바닥부터 시작해 {disaster} 세계관 최강자가 된 생존자 ({ep_range} 전편 몰아보기)"

    title_variants = {
        "variant_a_conflict": var_a,
        "variant_b_paradox": var_b,
        "variant_c_scale": var_c,
    }

    suggested_titles = [
        var_b,
        var_a,
        var_c,
        f"[웹툰 추천] {disaster} 속에서 나 혼자만 {advantage} 각성했다 ({comic_title} {ep_range})",
        f"[웹툰 몰아보기] {comic_title} ({ep_range}) 전편 1화부터 전편 연속 몰아보기",
    ]
    primary_title = suggested_titles[0]

    # 2. Narrative Chapters
    narrative_chapters = build_korean_narrative_chapters(chapters, from_ep, to_ep)

    # 3. 6-Tier Description
    desc_lines = [
        f"🔥 [웹툰 몰아보기] {comic_title} ({ep_range}) 전편 몰아보기",
        f"{disaster} 속에서 {flaw}였던 {mc_name}이(가) {advantage}을(를) 각성하고 펼치는 처절하고 통쾌한 사이다 생존기!",
        "",
        f"📖 작품명: {comic_title}",
        f"📚 에피소드: {ep_range}",
        "",
        "⏱️ 챕터 타임라인 (Chapters):",
    ]
    for ch in narrative_chapters:
        desc_lines.append(f"{ch['timestamp']} {ch['title']}")

    desc_lines.extend([
        "",
        "👍 채널 구독과 좋아요, 알림 설정은 다음 영상 제작에 큰 힘이 됩니다!",
        "",
        "📌 본 영상은 원작 웹툰의 줄거리 해설, 비평, 교육 및 리뷰를 목적으로 제작된 오리지널 2차 창작 영상입니다.",
        "원작의 저작권은 작가 및 공식 출판사에 있습니다. 공식 플랫폼에서 원작을 감상해주세요.",
        "",
        "#웹툰몰아보기 #아포칼립스웹툰 #생존웹툰 #사이다웹툰 #웹툰추천",
    ])

    desc_text = "\n".join(desc_lines)
    desc_bytes = len(desc_text.encode("utf-8"))

    # 4. Minimal Tags
    clean_title = re.sub(r"[^\w\s]", "", comic_title).strip()
    tags = [
        "웹툰몰아보기",
        "아포칼립스웹툰",
        "생존웹툰",
        "사이다웹툰",
        "웹툰추천",
        clean_title,
        f"{clean_title} 몰아보기",
    ]

    # 5. Pinned Comment
    pinned_comment = (
        f"📌 [웹툰 몰아보기 정보 & 타임라인]\n"
        f"📖 작품: {comic_title} ({ep_range})\n\n"
        f"💬 아포칼립스 상황에서 여러분이라면 가장 먼저 챙길 생존 물품은 무엇인가요? 댓글로 남겨주세요! 👇\n\n"
        f"👉 구독과 좋아요 누르고 다음 사이다 몰아보기를 놓치지 마세요!"
    )

    # 6. Compliance Flags
    compliance_flags = {
        "title_length_chars": len(primary_title),
        "title_length_ok": len(primary_title) <= 100,
        "description_utf8_bytes": desc_bytes,
        "description_bytes_ok": desc_bytes <= 5000,
        "tag_count": len(tags),
        "tag_count_ok": 5 <= len(tags) <= 15,
        "hashtag_count": 5,
        "hashtag_count_ok": True,
        "first_chapter_is_zero": bool(narrative_chapters and narrative_chapters[0]["timestamp"] in ("00:00", "0:00")),
        "ypp_originality_statement_present": "오리지널 2차 창작" in desc_text,
    }

    # 7. Formatted Kit
    kit_lines = [
        "=" * 80,
        f"YOUTUBE UPLOAD KIT (KOREA MARKET): {comic_title}",
        f"Episodes: {from_ep} - {to_ep} | Market: korea_apocalypse",
        "=" * 80,
        "",
        "[1. NATIVE A/B TEST TITLE HYPOTHESES (YouTube A/B 테스트용)]",
        f"★ Hypothesis A (사이다 / 참교육 갈등형):",
        f"  {title_variants['variant_a_conflict']}",
        f"★ Hypothesis B (독점 / 자원 역설형):",
        f"  {title_variants['variant_b_paradox']}",
        f"★ Hypothesis C (성장 / 세계관 최강형):",
        f"  {title_variants['variant_c_scale']}",
        "",
        "[2. DESCRIPTION & TIMESTAMPS (유튜브 더보기 설명란)]",
        desc_text,
        "",
        "[3. PINNED COMMENT (고정 댓글)]",
        pinned_comment,
        "",
        "[4. TAGS (유튜브 스튜디오 태그)]",
        ", ".join(tags),
        "",
        "=" * 80,
    ]

    return {
        "title": primary_title,
        "title_options": suggested_titles,
        "title_variants": title_variants,
        "description": desc_text,
        "pinned_comment": pinned_comment,
        "tags": tags,
        "narrative_chapters": narrative_chapters,
        "thumbnail_concepts": [],
        "compliance_flags": compliance_flags,
        "formatted_kit": "\n".join(kit_lines),
    }
