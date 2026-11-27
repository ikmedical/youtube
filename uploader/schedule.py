"""공개 예약 시각 계산. 예: 'MON 08:00' → 다음 월요일 08:00 (TIMEZONE 기준)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6,
        "월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}


def parse_schedule(raw: str | None) -> tuple[int, int, int] | None:
    """'MON 08:00' → (0, 8, 0). 빈 값/none/off → None."""
    if not raw or raw.strip().lower() in ("none", "off", "false", "no"):
        return None
    parts = raw.strip().split()
    if len(parts) != 2:
        raise SystemExit(f"[config] YT_PUBLISH_SCHEDULE 형식 오류: '{raw}' (예: MON 08:00)")
    day = DAYS.get(parts[0].upper()[:3]) if parts[0].upper()[:3] in DAYS else DAYS.get(parts[0][:1])
    hh, _, mm = parts[1].partition(":")
    if day is None or not hh.isdigit() or not (mm or "0").isdigit():
        raise SystemExit(f"[config] YT_PUBLISH_SCHEDULE 형식 오류: '{raw}' (예: MON 08:00)")
    return day, int(hh), int(mm or 0)


def next_publish_at(sched: tuple[int, int, int], tz: ZoneInfo, now: datetime | None = None,
                    min_lead: timedelta = timedelta(hours=1)) -> datetime:
    """now + min_lead 이후의 가장 가까운 지정 요일·시각."""
    day, hh, mm = sched
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    earliest = now + min_lead
    cand = earliest.replace(hour=hh, minute=mm, second=0, microsecond=0)
    cand += timedelta(days=(day - cand.weekday()) % 7)
    if cand < earliest:
        cand += timedelta(days=7)
    return cand


def to_rfc3339_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
