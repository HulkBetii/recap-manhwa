import pytest

from series_status import (
    ReleaseStatus,
    detect_release_status,
    latest_episode_from_hrefs,
    load_release_status,
    save_release_status,
)


@pytest.mark.parametrize("info, state", [
    ("UP\nEVERY SUNDAY", "ongoing"),            # webtoons .day_info (verified live, Veteran 2026-10-03)
    ("COMPLETED", "completed"),                  # webtoons .day_info (verified live, Sweet Home)
    ("채용택 ∙ 글 한가람 ∙ 그림 월요웹툰 ∙ 15세 이용가", "ongoing"),  # Naver meta block (verified live)
    ("작가 ∙ 완결 ∙ 15세 이용가", "completed"),
    ("작가 ∙ 휴재 ∙ 토요웹툰", "hiatus"),          # a paused Naver series keeps its weekday label
    ("Status: Ongoing", "ongoing"),
    ("Status Releasing", "ongoing"),
    ("Status Completed", "completed"),
    ("Status: Hiatus", "hiatus"),
    ("完結", "completed"),
    ("連載中", "ongoing"),
])
def test_info_area_markers(info, state):
    assert detect_release_status([info]).state == state


def test_unclear_text_is_unknown():
    assert detect_release_status(["Action ∙ 4.9 rating"], "Read the latest chapters now!").state == "unknown"


def test_page_text_needs_a_status_label():
    # Recommendation blocks mention other series' states; only a labelled field counts on the whole page.
    assert detect_release_status([], "Completed series you may like: ...").state == "unknown"
    assert detect_release_status([], "Genre Action\nStatus\nOngoing\nType Manhwa").state == "ongoing"


def test_page_text_uses_first_status_label():
    page = "Status Hiatus ... Recommended: Status Completed"
    assert detect_release_status([], page).state == "hiatus"


def test_info_area_wins_over_page_text():
    assert detect_release_status(["COMPLETED"], "Status Ongoing").state == "completed"


def test_latest_episode_from_hrefs():
    hrefs = [
        "https://www.webtoons.com/en/action/x/episode-33/viewer?title_no=9675&episode_no=33",
        "https://www.webtoons.com/en/action/x/episode-32/viewer?title_no=9675&episode_no=32",
        "/webtoon/detail?titleId=758037&no=120",
        None, "/about",
    ]
    assert latest_episode_from_hrefs(hrefs) == 120
    assert latest_episode_from_hrefs(["/about", None]) is None


def test_running_series_trusts_newest_first_list_page():
    assert detect_release_status(["UP EVERY SUNDAY"], listed_latest=33).latest_episode == 33
    assert detect_release_status(["작가 ∙ 휴재 ∙ 토요웹툰"], listed_latest=88).latest_episode == 88


def test_completed_series_ignores_oldest_first_list_page():
    # Live 2026-10-03: Naver "여신강림" lists episodes 1-19 on page 1 of a 261-episode completed series.
    status = detect_release_status(["야옹이 ∙ 글/그림 261화 완결 ∙ 12세 이용가"], listed_latest=19)
    assert status.state == "completed" and status.latest_episode == 261
    # webtoons only says "COMPLETED": the total is unknown, so no ending can be claimed.
    assert detect_release_status(["COMPLETED"], listed_latest=15).latest_episode is None


def test_full_chapter_list_is_trusted_for_any_state():
    assert detect_release_status([], "Status Completed", listed_latest=5, full_list_latest=120).latest_episode == 120


def test_save_and_load_roundtrip(tmp_path):
    save_release_status(str(tmp_path), ReleaseStatus(state="ongoing", latest_episode=33, evidence="UP EVERY SUNDAY"))
    loaded = load_release_status(str(tmp_path))
    assert loaded.state == "ongoing" and loaded.latest_episode == 33


def test_load_prefers_artifacts_and_defaults_to_unknown(tmp_path):
    save_release_status(str(tmp_path), ReleaseStatus(state="ongoing"))
    assert load_release_status(str(tmp_path), {"release_status": {"state": "completed"}}).state == "completed"
    assert load_release_status(str(tmp_path / "missing")).state == "unknown"
    (tmp_path / "release_status.json").write_text("{broken", encoding="utf-8")
    assert load_release_status(str(tmp_path)).state == "unknown"


@pytest.mark.parametrize("info", ["次回更新は10/23(金曜)予定です。", "最新話更新：隔週金曜", "最新話更新：不定期"])
def test_magapoke_update_lines_mean_ongoing(info):
    # Live 2026-10-03: pocket.shonenmagazine.com/title/01152 (.p-episode__update-txt / .p-episode__new_update).
    assert detect_release_status([info]).state == "ongoing"
