from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Iterator
from zoneinfo import ZoneInfo

# Cho phép lệch tối đa 10 phút (bot bị trễ hoặc vừa khởi động lại) vẫn gửi nhắc.
GRACE = dt.timedelta(minutes=10)
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_times(text: str) -> str | None:
    """'8:00, 20:30' -> '08:00,20:30'. Trả về None nếu không hợp lệ."""
    out: list[str] = []
    for part in re.split(r"[,\s]+", text.strip()):
        if not part:
            continue
        m = _TIME_RE.match(part)
        if not m:
            return None
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return None
        out.append(f"{h:02d}:{mi:02d}")
    if not out or len(out) > 6:
        return None
    return ",".join(sorted(set(out)))


def due_slots(
    tz_name: str, reminders: Iterable[tuple[str, str, bool]], now_utc: dt.datetime
) -> Iterator[tuple[str, str]]:
    """Với mỗi (kind, times, enabled) tới giờ, trả về (kind, slot_id)."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Ho_Chi_Minh")
    local = now_utc.astimezone(tz)
    for kind, times, enabled in reminders:
        if not enabled:
            continue
        for t in times.split(","):
            h, mi = (int(x) for x in t.split(":"))
            slot_dt = local.replace(hour=h, minute=mi, second=0, microsecond=0)
            if slot_dt <= local < slot_dt + GRACE:
                yield kind, f"{local.date().isoformat()} {t}"
