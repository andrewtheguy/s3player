import re
from dataclasses import dataclass
from datetime import date, datetime

_BASENAME_RE = re.compile(r"^(?P<date>\d{8})_(?P<start>\d{4})_(?P<end>\d{4})_(?P<show>.+)\.m4a$")


@dataclass(frozen=True)
class ParsedEpisode:
    show: str
    aired_on: date
    time_slot: str


def parse_episode_key(s3_key: str) -> ParsedEpisode | None:
    basename = s3_key.rsplit("/", 1)[-1]
    m = _BASENAME_RE.match(basename)
    if m is None:
        return None
    try:
        aired_on = datetime.strptime(m["date"], "%Y%m%d").date()
    except ValueError:
        return None
    return ParsedEpisode(
        show=m["show"],
        aired_on=aired_on,
        time_slot=f"{m['start']}_{m['end']}",
    )
