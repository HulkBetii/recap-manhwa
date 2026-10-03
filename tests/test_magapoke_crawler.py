import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from magapoke_crawler import (
    is_magapoke_url,
    parse_magapoke_url,
    load_magapoke_cookies,
)

def test_is_magapoke_url():
    valid_urls = [
        "https://pocket.shonenmagazine.com/title/01152/episode/308806",
        "https://pocket.shonenmagazine.com/title/01152",
        "https://pocket.shonenmagazine.com/episode/308806",
        "http://pocket.shonenmagazine.com/title/1234",
    ]
    for url in valid_urls:
        assert is_magapoke_url(url) is True

    invalid_urls = [
        "https://comic.naver.com/webtoon/list?titleId=836848",
        "https://comix.to/title/123",
        "https://google.com",
        "",
        None,
    ]
    for url in invalid_urls:
        assert is_magapoke_url(url) is False

def test_parse_magapoke_url():
    ep_url = "https://pocket.shonenmagazine.com/title/01152/episode/308806"
    parsed = parse_magapoke_url(ep_url)
    assert parsed["title_id"] == "01152"
    assert parsed["episode_id"] == "308806"

    title_url = "https://pocket.shonenmagazine.com/title/01152"
    parsed_title = parse_magapoke_url(title_url)
    assert parsed_title["title_id"] == "01152"
    assert parsed_title["episode_id"] is None

    direct_ep_url = "https://pocket.shonenmagazine.com/episode/308806"
    parsed_ep = parse_magapoke_url(direct_ep_url)
    assert parsed_ep["title_id"] is None
    assert parsed_ep["episode_id"] == "308806"

def test_load_magapoke_cookies():
    cookies = load_magapoke_cookies()
    assert isinstance(cookies, list)
    if cookies:
        cookie_names = [c["name"] for c in cookies]
        assert "uwt" in cookie_names or "_ga" in cookie_names


def test_cookies_from_env_path_are_converted(tmp_path, monkeypatch):
    import json as _json
    path = tmp_path / "magapoke.json"
    path.write_text(_json.dumps([{"name": "uwt", "value": "v", "domain": ".pocket.shonenmagazine.com",
                                  "sameSite": "no_restriction", "secure": True}]), encoding="utf-8")
    monkeypatch.setenv("MAGAPOKE_COOKIE_PATH", str(path))
    cookies = load_magapoke_cookies()
    assert cookies == [{"name": "uwt", "value": "v", "domain": ".pocket.shonenmagazine.com", "path": "/", "secure": True}]


def test_broken_cookie_file_is_skipped(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text("{broken", encoding="utf-8")
    monkeypatch.setenv("MAGAPOKE_COOKIE_PATH", str(path))
    assert isinstance(load_magapoke_cookies(), list)


def test_no_personal_cookie_path_in_source():
    import magapoke_crawler
    source = Path(magapoke_crawler.__file__).read_text(encoding="utf-8")
    assert "HulkBeoti" not in source


def test_episode_url_pads_numeric_title_ids():
    """The episode list API returns title_id 1152; /title/1152/episode/... has no viewer."""
    from magapoke_crawler import magapoke_episode_url
    assert magapoke_episode_url(1152, 308806) == "https://pocket.shonenmagazine.com/title/01152/episode/308806"
    assert magapoke_episode_url("01152", "308807") == "https://pocket.shonenmagazine.com/title/01152/episode/308807"
