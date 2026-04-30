from app.chapters import normalize_chapters


def test_normalize_basic_ffprobe_shape() -> None:
    raw = [
        {
            "id": 0,
            "time_base": "1/1000",
            "start": 0,
            "start_time": "0.000000",
            "end": 7200000,
            "end_time": "7200.000000",
            "tags": {"title": "Intro"},
        },
        {
            "id": 1,
            "time_base": "1/1000",
            "start": 7200000,
            "start_time": "7200.000000",
            "end": 14400000,
            "end_time": "14400.500000",
            "tags": {"title": "Main"},
        },
    ]
    assert normalize_chapters(raw) == [
        {"title": "Intro", "start": 0, "end": 7200000},
        {"title": "Main", "start": 7200000, "end": 14400500},
    ]


def test_normalize_missing_title_uses_empty_string() -> None:
    raw = [{"start_time": "1.0", "end_time": "2.0"}]
    assert normalize_chapters(raw) == [{"title": "", "start": 1000, "end": 2000}]


def test_normalize_skips_chapters_without_times() -> None:
    raw = [
        {"start_time": "1.0", "end_time": "2.0", "tags": {"title": "ok"}},
        {"tags": {"title": "missing times"}},
        {"start_time": "3.0"},
    ]
    assert normalize_chapters(raw) == [{"title": "ok", "start": 1000, "end": 2000}]


def test_normalize_handles_non_dict_entries() -> None:
    raw = ["not a dict", 42, None, {"start_time": "1.0", "end_time": "2.0"}]
    assert normalize_chapters(raw) == [{"title": "", "start": 1000, "end": 2000}]


def test_normalize_rounds_subms() -> None:
    # 1.2345s → 1234.5ms → rounds to even → 1234
    raw = [{"start_time": "1.2345", "end_time": "2.6789"}]
    result = normalize_chapters(raw)
    assert result[0]["start"] == round(1.2345 * 1000)
    assert result[0]["end"] == round(2.6789 * 1000)


def test_normalize_invalid_time_strings_skipped() -> None:
    raw = [
        {"start_time": "not a number", "end_time": "2.0"},
        {"start_time": "1.0", "end_time": "2.0"},
    ]
    assert normalize_chapters(raw) == [{"title": "", "start": 1000, "end": 2000}]


def test_normalize_empty_input() -> None:
    assert normalize_chapters([]) == []
