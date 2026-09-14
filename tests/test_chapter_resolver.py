# -*- coding: utf-8 -*-
import pytest
from chapter_resolver import (
    extract_chapter_number,
    resolve_numeric_chapter_slug,
    assert_and_guard_chapter_url,
)


def test_extract_chapter_number_various_formats():
    assert extract_chapter_number("chapter-2") == 2.0
    assert extract_chapter_number("chapter-2.5") == 2.5
    assert extract_chapter_number("chap-15") == 15.0
    assert extract_chapter_number("ch_42") == 42.0
    assert extract_chapter_number("ep-3") == 3.0
    assert extract_chapter_number("episode-7") == 7.0
    assert extract_chapter_number("c-99") == 99.0
    assert extract_chapter_number("p-100") == 100.0
    assert extract_chapter_number("2") == 2.0
    assert extract_chapter_number("2.5") == 2.5
    assert extract_chapter_number("") is None
    assert extract_chapter_number(None) is None


def test_extract_chapter_number_from_urls():
    # mgread format
    url1 = "https://mgread.io/manga/global-freeze-i-created-an-apocalypse-shelter/chapter-2/"
    assert extract_chapter_number(url1) == 2.0

    # asura format
    url2 = "https://asuracomic.net/comics/solo-leveling/chapter/150"
    assert extract_chapter_number(url2) == 150.0

    # toongod format
    url3 = "https://toongod.org/webtoon/magic-emperor/chapter-450/"
    assert extract_chapter_number(url3) == 450.0

    # naver query format
    url4 = "https://comic.naver.com/webtoon/detail?titleId=183559&no=600"
    assert extract_chapter_number(url4) == 600.0

    # naver viewer path
    url5 = "https://comic.naver.com/webtoon/ep-5/viewer?title_no=123&episode_no=5"
    assert extract_chapter_number(url5) == 5.0


def test_resolve_numeric_chapter_slug_with_pagination():
    """
    Test case kinh điển: Trang web manga chỉ render 25 chapter mới nhất (610-634)
    kèm 1 nút Read First Chapter (chapter-1).
    Khi ep = 2, tuyệt đối KHÔNG được bốc chapter-610 mà phải fallback về chapter-2!
    """
    slugs = ["chapter-1", "chapter-610", "chapter-611", "chapter-612"]
    
    # ep = 1 -> match exact chapter-1
    assert resolve_numeric_chapter_slug(slugs, 1) == "chapter-1"
    
    # ep = 2 -> không có trong mảng -> TUYỆT ĐỐI KHÔNG lấy slugs[1] (chapter-610)
    assert resolve_numeric_chapter_slug(slugs, 2) == "chapter-2"


def test_resolve_numeric_chapter_slug_with_reversed_order():
    """
    Test case danh sách chapter bị sắp xếp giảm dần (Mới nhất -> Cũ nhất).
    """
    slugs = ["chapter-10", "chapter-9", "chapter-8", "chapter-2", "chapter-1"]
    
    assert resolve_numeric_chapter_slug(slugs, 1) == "chapter-1"
    assert resolve_numeric_chapter_slug(slugs, 2) == "chapter-2"
    assert resolve_numeric_chapter_slug(slugs, 9) == "chapter-9"


def test_resolve_numeric_chapter_slug_with_spinoffs():
    """
    Test case danh sách chapter chứa chapter ngoại truyện / số lẻ (chapter-0, chapter-0.5).
    """
    slugs = ["chapter-0", "chapter-0.5", "chapter-1", "chapter-2"]
    
    # Code cũ lấy slugs[0] sẽ ra chapter-0 thay vì chapter-1!
    assert resolve_numeric_chapter_slug(slugs, 1) == "chapter-1"
    assert resolve_numeric_chapter_slug(slugs, 2) == "chapter-2"


def test_resolve_numeric_chapter_slug_asura_pattern():
    """
    Test case asura dùng số nguyên trần '{ep}'.
    """
    slugs = ["1", "2", "3", "4", "5"]
    assert resolve_numeric_chapter_slug(slugs, 3, fallback_pattern="{ep}") == "3"
    
    # Khi thiếu chapter 50
    assert resolve_numeric_chapter_slug(slugs, 50, fallback_pattern="{ep}") == "50"


def test_assert_and_guard_chapter_url():
    """
    Kiểm định tính năng chặn đứng tức thì khi phát hiện sai lệch số tập.
    """
    # Hợp lệ
    valid_url = "https://mgread.io/manga/title/chapter-2/"
    assert assert_and_guard_chapter_url(2, valid_url, "chapter-2") == valid_url

    # Sai lệch số tập: yêu cầu tập 2 nhưng URL là chapter-610
    invalid_url = "https://mgread.io/manga/title/chapter-610/"
    with pytest.raises(ValueError) as excinfo:
        assert_and_guard_chapter_url(2, invalid_url, "chapter-610")
    assert "CRITICAL CHAPTER INTEGRITY ERROR" in str(excinfo.value)
    assert "Requested episode 2" in str(excinfo.value)
    assert "610" in str(excinfo.value)
