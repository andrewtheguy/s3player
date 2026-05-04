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
        start = c.get("start_ms_in_show")
        end = c.get("end_ms_in_show")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if start < 0 or end < 0 or end <= start:
            continue
        title_raw = c.get("title")
        title = title_raw if isinstance(title_raw, str) else ""
        out.append({"title": title, "start": start, "end": end})
    return out
