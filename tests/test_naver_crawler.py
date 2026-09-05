import urllib.parse
import re
import pytest
from fastapi.testclient import TestClient
from app import app, sanitize_title, download_image_sync


def test_naver_url_parsing_and_normalization():
    # 1. List URL with titleId
    url_list = "https://comic.naver.com/webtoon/list?titleId=836848"
    parsed = urllib.parse.urlparse(url_list)
    assert "comic.naver.com" in parsed.netloc.lower()
    query = urllib.parse.parse_qs(parsed.query)
    title_id = query.get("titleId", [""])[0] or query.get("title_no", [""])[0]
    assert title_id == "836848"

    # 2. Detail URL normalization
    url_detail = "https://comic.naver.com/webtoon/detail?titleId=836848&no=5&week=tue"
    parsed_detail = urllib.parse.urlparse(url_detail)
    query_detail = urllib.parse.parse_qs(parsed_detail.query)
    detail_title_id = query_detail.get("titleId", [""])[0] or query_detail.get("title_no", [""])[0]
    assert detail_title_id == "836848"
    assert "/webtoon/detail" in parsed_detail.path

    # Normalization logic
    normalized_url = f"https://comic.naver.com/webtoon/list?titleId={detail_title_id}"
    assert normalized_url == "https://comic.naver.com/webtoon/list?titleId=836848"


def test_naver_korean_title_sanitization():
    title = "44교시 생존수업"
    sanitized = sanitize_title(title)
    assert sanitized == "44교시_생존수업"

    title_with_suffix = "44교시 생존수업 : 네이버 웹툰"
    cleaned = title_with_suffix.split(" : 네이버")[0].strip()
    assert cleaned == "44교시 생존수업"
    assert sanitize_title(cleaned) == "44교시_생존수업"


def test_naver_image_url_filtering():
    raw_images = [
        "https://image-comic.pstatic.net/staticImages/webtoon/common/agerate/age_15_white.jpg",
        "https://image-comic.pstatic.net/webtoon/836848/1/20250827215220_e881e0a0b457cdf436a3ad3885cfabe9_IMAG01_1.jpg",
        "https://image-comic.pstatic.net/webtoon/836848/1/20250827215220_e881e0a0b457cdf436a3ad3885cfabe9_IMAG01_2.jpg",
        "",
        None,
        "https://ssl.pstatic.net/static/comic/images/migration/common/blank.gif"
    ]

    filtered = [
        src for src in raw_images
        if src and "webtoon" in src and "agerate" not in src
    ]

    assert len(filtered) == 2
    assert "IMAG01_1.jpg" in filtered[0]
    assert "IMAG01_2.jpg" in filtered[1]
    assert not any("agerate" in url for url in filtered)


def test_naver_download_image_sync_referer(monkeypatch, tmp_path):
    captured_request = {}

    def mock_urlopen(req, timeout=20):
        captured_request["url"] = req.full_url
        captured_request["headers"] = dict(req.headers)
        class MockResponse:
            def read(self):
                return b"fake_jpeg_content"
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
        return MockResponse()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    test_url = "https://image-comic.pstatic.net/webtoon/836848/1/test.jpg"
    dest_path = str(tmp_path / "test.jpg")
    download_image_sync(test_url, dest_path)

    assert "Referer" in captured_request["headers"]
    assert captured_request["headers"]["Referer"] == "https://comic.naver.com/"


def test_crawl_request_naver_market_auto_assignment():
    with TestClient(app, base_url="http://127.0.0.1") as client:
        # Establish authenticated session
        init_res = client.get("/")
        assert init_res.status_code == 200

        payload = {
            "url": "https://comic.naver.com/webtoon/detail?titleId=836848&no=1",
            "from_episode": 1,
            "to_episode": 1,
            "language": "en",  # Default en should be auto-switched to ko with korea_apocalypse
            "market_id": None
        }

        res = client.post("/api/crawl", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        task_id = data["task_id"]

        from app import workflow_manager
        task = workflow_manager.repository.load(task_id)
        assert task is not None
        assert task.comic_url == "https://comic.naver.com/webtoon/list?titleId=836848"
        assert task.comic_title == "Naver_836848"
        assert task.payload.get("market_id") == "korea_apocalypse"
        assert task.payload.get("language") == "ko"
