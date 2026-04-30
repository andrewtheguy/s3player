from datetime import date

from app.parse_key import parse_episode_key


def test_happy_path_radio1() -> None:
    parsed = parse_episode_key("shows/rthk/radio1/2026/03/22/20260322_0000_0200_我得你都得.m4a")
    assert parsed is not None
    assert parsed.show == "我得你都得"
    assert parsed.aired_on == date(2026, 3, 22)
    assert parsed.time_slot == "0000_0200"


def test_happy_path_radio2() -> None:
    parsed = parse_episode_key("shows/rthk/radio2/2026/03/28/20260328_0000_0200_音樂說.m4a")
    assert parsed is not None
    assert parsed.show == "音樂說"
    assert parsed.aired_on == date(2026, 3, 28)
    assert parsed.time_slot == "0000_0200"


def test_show_name_contains_underscore() -> None:
    parsed = parse_episode_key("20250101_0800_1000_my_show_name.m4a")
    assert parsed is not None
    assert parsed.show == "my_show_name"
    assert parsed.time_slot == "0800_1000"


def test_basename_only_no_path_prefix() -> None:
    parsed = parse_episode_key("20260101_2200_2400_深夜節目.m4a")
    assert parsed is not None
    assert parsed.aired_on == date(2026, 1, 1)


def test_wrong_extension_returns_none() -> None:
    assert parse_episode_key("shows/rthk/radio1/20260322_0000_0200_show.mp3") is None


def test_missing_time_slot_returns_none() -> None:
    assert parse_episode_key("shows/rthk/radio1/20260322_show.m4a") is None


def test_invalid_date_returns_none() -> None:
    assert parse_episode_key("99999999_0000_0200_show.m4a") is None
    assert parse_episode_key("20260230_0000_0200_show.m4a") is None


def test_garbage_returns_none() -> None:
    assert parse_episode_key("") is None
    assert parse_episode_key("not-an-audio-file") is None
    assert parse_episode_key("shows/rthk/radio1/") is None
