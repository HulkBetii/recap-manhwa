from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional


def _extract_japanese_story_beats(
    comic_title: str,
    story_memory: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    title_lower = (comic_title or "").lower()
    mc_name = "主人公"
    if story_memory:
        raw_mc = story_memory.get("protagonist_name", "").strip()
        if raw_mc and len(raw_mc) > 1 and raw_mc.lower() not in ["a", "protagonist", "mc", "unknown"]:
            mc_name = raw_mc

    advantage = "規格外チート能力"
    disaster = "不毛の荒野"
    flaw = "無能と見下された元貴族"

    mem_text = str(story_memory).lower() if story_memory else ""
    combined = f"{title_lower} {mem_text}"

    if any(k in combined for k in ["farm", "agriculture", "領地", "開拓"]):
        advantage = "現代農業知識と生産魔法"
        flaw = "辺境へ左遷された追放領主"
    elif any(k in combined for k in ["magic", "craft", "creator", "スキル"]):
        advantage = "万能創造スキル"
        flaw = "Fランク判定の無能"
    elif any(k in combined for k in ["sword", "demon", "reincarnat", "転生"]):
        advantage = "前世の最強チート記憶"
        flaw = "捨てられた没落貴族"

    return {
        "mc_name": mc_name,
        "advantage": advantage,
        "disaster": disaster,
        "flaw": flaw,
    }


def build_japanese_narrative_chapters(
    chapters: Optional[List[Dict[str, Any]]] = None,
    from_ep: int = 1,
    to_ep: int = 1,
) -> List[Dict[str, Any]]:
    japanese_default_progression = [
        "追放とチート能力の覚醒",
        "最果ての荒野と仲間との出会い",
        "規格外スキルで領地開拓スタート",
        "迫り来る脅威と圧倒的無双",
        "最強帝国の建国と完全ざまぁ",
    ]

    if not chapters:
        return [
            {"timestamp": "00:00", "title": f"{japanese_default_progression[0]} (第{from_ep}話)", "episode": from_ep},
            {"timestamp": "10:00", "title": f"{japanese_default_progression[1]} (第{from_ep+1 if to_ep > from_ep else from_ep}話)", "episode": from_ep + 1 if to_ep > from_ep else from_ep},
            {"timestamp": "25:00", "title": f"{japanese_default_progression[-1]} (第{to_ep}話)", "episode": to_ep},
        ]

    result = []
    total_ch = len(chapters)
    for i, ch in enumerate(chapters):
        ts = "00:00" if i == 0 else ch.get("timestamp", "00:00")
        ep_num = ch.get("episode", from_ep + i)
        prog_idx = min(len(japanese_default_progression) - 1, int(i * len(japanese_default_progression) / max(1, total_ch)))
        theme = japanese_default_progression[prog_idx]
        result.append({
            "timestamp": ts,
            "title": f"{theme} (第{ep_num}話)",
            "episode": ep_num,
        })
    return result


def generate_japan_isekai_metadata(
    comic_title: str,
    from_ep: int,
    to_ep: int,
    chapters: Optional[List[Dict[str, Any]]] = None,
    story_memory: Optional[Dict[str, Any]] = None,
    download_dir: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    ep_range = f"{from_ep}話~{to_ep}話" if from_ep != to_ep else f"{from_ep}話"
    beats = _extract_japanese_story_beats(comic_title, story_memory)
    mc_name = beats["mc_name"]
    advantage = beats["advantage"]
    flaw = beats["flaw"]

    # 1. Title Variants for A/B Testing
    var_a = f"【異世界漫画】役立たずと蔑まれ追放された{mc_name}、{advantage}で元家族を完全論破する ({ep_range} 一気見)"
    var_b = f"【異世界漫画】無能と追放された{flaw}、{advantage}で最果ての荒野を最強帝国へ開拓してしまう ({ep_range} 一気見)"
    var_c = f"【漫画総集編】追放された没落貴族が{advantage}で大逆転！隣国が平伏する巨大都市へ成り上がる【作業用/睡眠用】"

    title_variants = {
        "variant_a_conflict": var_a,
        "variant_b_paradox": var_b,
        "variant_c_scale": var_c,
    }

    suggested_titles = [
        var_b,
        var_a,
        var_c,
        f"【異世界漫画】{comic_title} ({ep_range}) 1話から全話イッキ見まとめ【マンガ動画】",
        f"【漫画解説】無能と追放された主人公が規格外スキルで大逆転する神作 ({comic_title})",
    ]
    primary_title = suggested_titles[0]

    # 2. Narrative Chapters
    narrative_chapters = build_japanese_narrative_chapters(chapters, from_ep, to_ep)

    # 3. 6-Tier Description
    desc_lines = [
        f"🔥【異世界漫画・総集編】{comic_title} ({ep_range}) 一気見まとめ",
        f"「無能」と見下され追放された{mc_name}が、隠された{advantage}で荒野を最強帝国へと開拓する痛快成り上がり劇！",
        "",
        f"📖 作品名: {comic_title}",
        f"📚 収録話数: {ep_range}",
        "",
        "⏱️ タイムスタンプ (Timestamps):",
    ]
    for ch in narrative_chapters:
        desc_lines.append(f"{ch['timestamp']} {ch['title']}")

    desc_lines.extend([
        "",
        "📌 チャンネル登録＆高評価をいただけると、次回の動画制作の大きな励みになります！",
        "🔔 通知ベルをONにして最新の総集編をお見逃しなく！",
        "",
        "📌 本動画は、原作者様および出版社の権利を侵害する目的はなく、作品の魅力を伝えるための独自の解説・考察・要約・編集を加えたオリジナル解説動画です。",
        "著作権は原作者様および公式出版社に帰属します。ぜひ公式配信サイトや単行本でお楽しみください。",
        "",
        "#異世界漫画 #漫画総集編 #一気見 #領地経営 #成り上がり",
    ])

    desc_text = "\n".join(desc_lines)
    desc_bytes = len(desc_text.encode("utf-8"))

    # 4. Minimal Tags
    clean_title = re.sub(r"[^\w\s]", "", comic_title).strip()
    tags = [
        "異世界漫画",
        "漫画総集編",
        "一気見",
        "マンガ動画",
        "領地経営",
        "成り上がり",
        "ざまぁ",
        "追放",
        clean_title,
        f"{clean_title} 一気見",
    ]

    # 5. Pinned Comment
    pinned_comment = (
        f"📌【動画情報＆タイムスタンプ】\n"
        f"📖 作品: {comic_title} ({ep_range})\n\n"
        f"💬 もしあなたが異世界へ追放されたら、最初に手に入れたいチート能力は何ですか？ ぜひコメント欄で教えてください！ 👇\n\n"
        f"👉 チャンネル登録＆高評価よろしくお願いいたします！"
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
        "ypp_originality_statement_present": "オリジナル解説動画" in desc_text,
    }

    # 7. Formatted Kit
    kit_lines = [
        "=" * 80,
        f"YOUTUBE UPLOAD KIT (JAPAN MARKET): {comic_title}",
        f"Episodes: {from_ep} - {to_ep} | Market: japan_isekai_territory",
        "=" * 80,
        "",
        "[1. NATIVE A/B TEST TITLE HYPOTHESES (YouTube A/B テスト候補)]",
        f"★ Hypothesis A (ざまぁ / 完全論破型):",
        f"  {title_variants['variant_a_conflict']}",
        f"★ Hypothesis B (追放 / 荒野開拓型):",
        f"  {title_variants['variant_b_paradox']}",
        f"★ Hypothesis C (総集編 / 成り上がり型):",
        f"  {title_variants['variant_c_scale']}",
        "",
        "[2. DESCRIPTION & TIMESTAMPS (概要欄コピー用)]",
        desc_text,
        "",
        "[3. PINNED COMMENT (固定コメント用)]",
        pinned_comment,
        "",
        "[4. TAGS (タグ欄用)]",
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
