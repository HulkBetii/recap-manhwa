import os
import sys
from pathlib import Path
import pytest

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
