# -*- coding: utf-8 -*-
"""
Chapter Resolver & Integrity Guard Module.
Ngăn chặn tuyệt đối tình trạng sai lệch hoặc nhầm lẫn số tập (Chapter Mismatch).

Cung cấp các cơ chế:
1. Trích xuất số tập (numeric chapter number) từ mọi định dạng slug, URL, title.
2. Ánh xạ số tập chính xác dựa trên giá trị số học (Value-based Numeric Matching),
   TUYỆT ĐỐI KHÔNG dùng index mảng (slugs[ep-1]).
3. Chốt chặn toàn vẹn (Chapter Integrity Guard Assertion) phát hiện và dừng ngay lập tức
   nếu URL / slug có số tập lệch pha với requested_ep.
"""

import re
import urllib.parse
from typing import Optional, Sequence


def extract_chapter_number(text: str) -> Optional[float]:
    """
    Trích xuất số tập chính xác từ slug, URL, hoặc title.
    Hỗ trợ các định dạng:
    - 'chapter-2', 'chap-2', 'ch-2', 'ep-2', 'episode-2', 'c-2', 'p-2'
    - 'chapter-2.5', 'ch-2_5', 'chap-2-5'
    - URL: 'https://mgread.io/manga/title/chapter-2/'
    - Số đứng độc lập trong slug: '2', '2.5'
    - Query parameters: '?no=2', '?episode_no=2', '?ch=2'
    """
    if not text:
        return None

    # Nếu là URL, trích xuất query param hoặc path cuối
    if "://" in text:
        parsed = urllib.parse.urlparse(text)
        qs = urllib.parse.parse_qs(parsed.query)
        for q_key in ["no", "episode_no", "ch", "chapter", "ep"]:
            if q_key in qs and qs[q_key]:
                try:
                    return float(qs[q_key][0])
                except ValueError:
                    pass
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        if path_parts:
            last_part = path_parts[-1]
            num = extract_chapter_number(last_part)
            if num is not None:
                return num
            if len(path_parts) >= 2 and path_parts[-1].lower() in ["viewer", "read"]:
                num = extract_chapter_number(path_parts[-2])
                if num is not None:
                    return num

    # 1. Regex ưu tiên có tiền tố rõ ràng (chapter, chap, ch, episode, ep, c, p)
    m = re.search(r"(?:chapter|chap|ch|episode|ep|c|p)[\s\-_]*(\d+(?:[\._\-]\d+)?)", text, re.IGNORECASE)
    if m:
        val_str = m.group(1).replace("_", ".").replace("-", ".")
        try:
            return float(val_str)
        except ValueError:
            pass

    # 2. Toàn bộ chuỗi là số (ví dụ slug = "2" hoặc "2.5")
    clean_text = text.strip()
    try:
        return float(clean_text)
    except ValueError:
        pass

    # 3. Tìm số độc lập dạng word boundary
    m = re.search(r"\b(\d+(?:\.\d+)?)\b", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    return None


def resolve_numeric_chapter_slug(
    slugs: Optional[Sequence[str]],
    ep: int,
    fallback_pattern: str = "chapter-{ep}"
) -> str:
    """
    Tìm slug có số tập khớp chính xác với ep (ví dụ ep=2 -> 'chapter-2' hoặc '2').
    TUYỆT ĐỐI KHÔNG sử dụng index mảng slugs[ep - 1] vì danh sách chapter trên web
    có thể bị phân trang (chỉ hiện 25 chap mới nhất), đảo ngược thứ tự, hoặc chứa chapter ngoại truyện.
    
    Nếu không tìm thấy slug khớp số trong danh sách, trả về slug chuẩn hóa theo fallback_pattern.
    """
    if slugs:
        for s in slugs:
            num = extract_chapter_number(s)
            if num is not None and abs(num - ep) < 0.01:
                return s

    # Fallback chuẩn xác theo quy luật domain
    return fallback_pattern.format(ep=ep)


def assert_and_guard_chapter_url(
    requested_ep: int,
    viewer_url: str,
    chapter_slug: Optional[str] = None
) -> str:
    """
    Chốt chặn bảo vệ toàn vẹn số tập (Chapter Integrity Guard).
    Kiểm tra xem URL và slug có đúng số tập requested_ep hay không.
    Nếu phát hiện lệch số (ví dụ ep=2 nhưng URL là chapter-610),
    lập tức raise ValueError để dừng khẩn cấp, ngăn chặn tuyệt đối việc tải sai nội dung truyện!
    """
    detected_num = None
    if chapter_slug:
        detected_num = extract_chapter_number(chapter_slug)
    if detected_num is None:
        detected_num = extract_chapter_number(viewer_url)

    if detected_num is not None:
        if abs(detected_num - requested_ep) > 0.01:
            err_msg = (
                f"[CRITICAL CHAPTER INTEGRITY ERROR] Requested episode {requested_ep}, "
                f"but resolved URL/slug points to chapter {detected_num}! "
                f"Target URL: '{viewer_url}', Slug: '{chapter_slug}'. "
                f"Pipeline aborted immediately to prevent downloading wrong chapter!"
            )
            raise ValueError(err_msg)
    return viewer_url


KNOWN_WEBTOON_TITLE_MAP = {
    # Naver Webtoon TitleId / Korean Title Mappings
    "814742": "Zombie Revelation 82-08",
    "좀비묵시록 82-08": "Zombie Revelation 82-08",
    "좀비묵시록": "Zombie Revelation",
    "나 혼자만 레벨업": "Solo Leveling",
    "전지적 독자 시점": "Omniscient Reader's Viewpoint",
    "멸망 이후의 세계": "The World After the Fall",
    "화산귀환": "Return of the Blossoming Blade",
    "나노 마신": "Nano Machine",
    "신과함께 돌아온 기사왕님": "The Knight King Who Returned with a God",
    "재벌집 막내아들": "Reborn Rich",
    "싸움독학": "Viral Hit",
    "외모지상주의": "Lookism",
    "퀘스트지상주의": "Quest Supremacy",
    "김부장": "Manager Kim",
    "촉법소년": "Juvenile Offender",
    "인생존망": "My Life as a Loser",
    "신의 탑": "Tower of God",
    "갓 오브 하이스쿨": "The God of High School",
    "노블레스": "Noblesse",
    "호랑이형님": "Tiger Brother",
    "입학용병": "Mercenary Enrollment",
    "템빨": "Overgeared",
    "두 번 사는 랭커": "Second Life Ranker",
    "SSS급 죽어야 사는 헌터": "SSS-Class Revival Hunter",
    "만렙뉴비": "Solo Max-Level Newbie",
    "도굴왕": "Tomb Raider King",
    "튜토리얼 탑의 고인물": "The Advanced Player of the Tutorial Tower",
    "비선실세 레이디가 되었습니다": "I Became the Male Lead's Adopted Daughter",
    "마이크 없이 살아남자": "Surviving The Apocalypse",
}


def resolve_english_comic_title(title: str, url: str = "") -> str:
    """
    Tự động chuẩn hóa và tìm tên chuẩn tiếng Anh cho truyện tranh,
    đặc biệt khi nguồn đầu vào là tiếng Hàn (Naver, Kakao), tiếng Nhật hoặc tiếng Trung.
    """
    if not title and not url:
        return "Manhwa Recap"

    # 1. Tra cứu theo titleId từ URL Naver nếu có
    if url and "comic.naver.com" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        t_id = qs.get("titleId", [""])[0] or qs.get("title_no", [""])[0]
        if t_id and t_id in KNOWN_WEBTOON_TITLE_MAP:
            return KNOWN_WEBTOON_TITLE_MAP[t_id]

    clean_title = (title or "").strip()

    # 2. Tra cứu trực tiếp từ bảng mapping
    if clean_title in KNOWN_WEBTOON_TITLE_MAP:
        return KNOWN_WEBTOON_TITLE_MAP[clean_title]

    # Tra cứu case-insensitive & partial match
    for k_name, en_name in KNOWN_WEBTOON_TITLE_MAP.items():
        if k_name.lower() == clean_title.lower() or (len(k_name) > 3 and k_name in clean_title):
            return en_name

    # 3. Kiểm tra xem tiêu đề có chứa ký tự tiếng Hàn (Hangul) hay không
    has_hangul = bool(re.search(r"[\uac00-\ud7a3]", clean_title))
    has_cjk = bool(re.search(r"[\u3040-\u30ff\u4e00-\u9faf]", clean_title))

    if not has_hangul and not has_cjk:
        # Đã là tiếng Anh hoặc chữ Latin chuẩn
        return clean_title

    # 4. Nếu là tiếng Hàn/CJK và chưa có trong mapping:
    # Thử trích xuất từ URL slug nếu URL chứa slug tiếng Anh
    if url:
        parsed = urllib.parse.urlparse(url)
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        for part in path_parts:
            if part not in ["webtoon", "list", "detail", "manga", "series", "title", "viewer", "read"]:
                slug_clean = part.replace("-", " ").replace("_", " ").title()
                if not re.search(r"[\uac00-\ud7a3\u3040-\u30ff\u4e00-\u9faf]", slug_clean) and len(slug_clean) > 2:
                    return slug_clean

    return clean_title

