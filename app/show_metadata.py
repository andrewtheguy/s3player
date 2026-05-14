import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


@dataclass(frozen=True)
class ShowMetadata:
    name: str
    aired_on: date
    time_slot: str | None


class ShowMetadataError(Enum):
    MISSING_SHOW_OBJECT = "missing_show_object"
    MISSING_NAME = "missing_name"
    MISSING_DATE = "missing_date"
    INVALID_DATE = "invalid_date"


def _format_time_slot(start: Any, end: Any) -> str | None:
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    if not _TIME_RE.match(start) or not _TIME_RE.match(end):
        return None
    return f"{start.replace(':', '')}_{end.replace(':', '')}"


def extract_show_metadata(meta: dict[str, Any]) -> ShowMetadata | ShowMetadataError:
    show = meta.get("show")
    if not isinstance(show, dict):
        return ShowMetadataError.MISSING_SHOW_OBJECT

    name = show.get("name")
    if not isinstance(name, str) or not name:
        return ShowMetadataError.MISSING_NAME

    date_raw = show.get("date")
    if not isinstance(date_raw, str) or not date_raw:
        return ShowMetadataError.MISSING_DATE
    try:
        aired_on = datetime.strptime(date_raw, "%Y-%m-%d").date()
    except ValueError:
        return ShowMetadataError.INVALID_DATE

    return ShowMetadata(
        name=name,
        aired_on=aired_on,
        time_slot=_format_time_slot(show.get("start"), show.get("end")),
    )
