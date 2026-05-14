from datetime import date

from app.show_metadata import ShowMetadata, ShowMetadataError, extract_show_metadata


def _full_meta() -> dict[str, object]:
    return {
        "show": {
            "name": "管理新思維",
            "date": "2026-04-05",
            "start": "14:00",
            "end": "16:00",
        }
    }


def test_happy_path() -> None:
    result = extract_show_metadata(_full_meta())
    assert result == ShowMetadata(
        name="管理新思維",
        aired_on=date(2026, 4, 5),
        time_slot="1400_1600",
    )


def test_missing_show_returns_error() -> None:
    assert extract_show_metadata({}) is ShowMetadataError.MISSING_SHOW_OBJECT


def test_show_not_dict() -> None:
    assert extract_show_metadata({"show": "nope"}) is ShowMetadataError.MISSING_SHOW_OBJECT


def test_missing_name_returns_error() -> None:
    assert extract_show_metadata({"show": {"date": "2026-04-05"}}) is ShowMetadataError.MISSING_NAME


def test_empty_name_returns_error() -> None:
    assert (
        extract_show_metadata({"show": {"name": "", "date": "2026-04-05"}})
        is ShowMetadataError.MISSING_NAME
    )


def test_name_not_string() -> None:
    assert (
        extract_show_metadata({"show": {"name": 123, "date": "2026-04-05"}})
        is ShowMetadataError.MISSING_NAME
    )


def test_missing_date_returns_missing_date_enum() -> None:
    assert extract_show_metadata({"show": {"name": "X"}}) is ShowMetadataError.MISSING_DATE


def test_invalid_date_format() -> None:
    assert (
        extract_show_metadata({"show": {"name": "X", "date": "2026/04/05"}})
        is ShowMetadataError.INVALID_DATE
    )
    assert (
        extract_show_metadata({"show": {"name": "X", "date": "04-05-2026"}})
        is ShowMetadataError.INVALID_DATE
    )


def test_invalid_calendar_date() -> None:
    assert (
        extract_show_metadata({"show": {"name": "X", "date": "2026-02-30"}})
        is ShowMetadataError.INVALID_DATE
    )


def test_missing_start_end_returns_null_time_slot() -> None:
    result = extract_show_metadata({"show": {"name": "X", "date": "2026-04-05"}})
    assert isinstance(result, ShowMetadata)
    assert result.time_slot is None


def test_partial_time_only_start() -> None:
    result = extract_show_metadata({"show": {"name": "X", "date": "2026-04-05", "start": "14:00"}})
    assert isinstance(result, ShowMetadata)
    assert result.time_slot is None


def test_malformed_time_format() -> None:
    for start, end in [("6:00", "10:00"), ("0600", "1000"), ("14:0", "16:00")]:
        result = extract_show_metadata(
            {"show": {"name": "X", "date": "2026-04-05", "start": start, "end": end}}
        )
        assert isinstance(result, ShowMetadata)
        assert result.time_slot is None


def test_time_not_string() -> None:
    result = extract_show_metadata(
        {"show": {"name": "X", "date": "2026-04-05", "start": 1400, "end": 1600}}
    )
    assert isinstance(result, ShowMetadata)
    assert result.time_slot is None


def test_midnight_boundary() -> None:
    result = extract_show_metadata(
        {"show": {"name": "X", "date": "2026-04-05", "start": "00:00", "end": "02:00"}}
    )
    assert isinstance(result, ShowMetadata)
    assert result.time_slot == "0000_0200"
