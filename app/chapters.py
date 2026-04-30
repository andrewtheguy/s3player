from typing import Any, TypedDict


class Chapter(TypedDict):
    title: str
    start: int
    end: int


def normalize_chapters(raw: list[Any]) -> list[Chapter]:
    out: list[Chapter] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        start = _to_ms(c.get("start_time"))
        end = _to_ms(c.get("end_time"))
        if start is None or end is None:
            continue
        title = ""
        tags = c.get("tags")
        if isinstance(tags, dict):
            t = tags.get("title")
            if isinstance(t, str):
                title = t
        out.append({"title": title, "start": start, "end": end})
    return out


def _to_ms(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return round(float(value) * 1000)
    except (TypeError, ValueError):
        return None
