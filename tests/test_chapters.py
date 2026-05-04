from app.chapters import normalize_chapters


def test_normalize_basic_sidecar_shape() -> None:
    raw = [
        {
            "index": 0,
            "start_ms_in_show": 0,
            "end_ms_in_show": 1454362,
            "title": "00:05:45 - 00:30:00 [show1]",
        },
        {
            "index": 1,
            "start_ms_in_show": 1454362,
            "end_ms_in_show": 3211415,
            "title": "00:30:00 - 00:59:17 [show2]",
        },
    ]
    assert normalize_chapters(raw) == [
        {"title": "00:05:45 - 00:30:00 [show1]", "start": 0, "end": 1454362},
        {"title": "00:30:00 - 00:59:17 [show2]", "start": 1454362, "end": 3211415},
    ]


def test_normalize_missing_title_uses_empty_string() -> None:
    raw = [{"start_ms_in_show": 1000, "end_ms_in_show": 2000}]
    assert normalize_chapters(raw) == [{"title": "", "start": 1000, "end": 2000}]


def test_normalize_non_string_title_becomes_empty() -> None:
    raw = [{"start_ms_in_show": 1000, "end_ms_in_show": 2000, "title": 42}]
    assert normalize_chapters(raw) == [{"title": "", "start": 1000, "end": 2000}]


def test_normalize_skips_chapters_without_times() -> None:
    raw = [
        {"start_ms_in_show": 1000, "end_ms_in_show": 2000, "title": "ok"},
        {"title": "missing times"},
        {"start_ms_in_show": 3000},
    ]
    assert normalize_chapters(raw) == [{"title": "ok", "start": 1000, "end": 2000}]


def test_normalize_handles_non_dict_entries() -> None:
    raw = ["not a dict", 42, None, {"start_ms_in_show": 1000, "end_ms_in_show": 2000}]
    assert normalize_chapters(raw) == [{"title": "", "start": 1000, "end": 2000}]


def test_normalize_skips_non_int_ms() -> None:
    raw = [
        {"start_ms_in_show": "1000", "end_ms_in_show": 2000, "title": "string start"},
        {"start_ms_in_show": 1000, "end_ms_in_show": 2.5, "title": "float end"},
        {"start_ms_in_show": 1000, "end_ms_in_show": 2000, "title": "ok"},
    ]
    assert normalize_chapters(raw) == [{"title": "ok", "start": 1000, "end": 2000}]


def test_normalize_skips_invalid_ranges() -> None:
    raw = [
        {"start_ms_in_show": -1, "end_ms_in_show": 1000, "title": "neg start"},
        {"start_ms_in_show": 0, "end_ms_in_show": -1, "title": "neg end"},
        {"start_ms_in_show": 1000, "end_ms_in_show": 1000, "title": "zero length"},
        {"start_ms_in_show": 2000, "end_ms_in_show": 1500, "title": "end before start"},
        {"start_ms_in_show": 1000, "end_ms_in_show": 2000, "title": "ok"},
    ]
    assert normalize_chapters(raw) == [{"title": "ok", "start": 1000, "end": 2000}]


def test_normalize_empty_input() -> None:
    assert normalize_chapters([]) == []
