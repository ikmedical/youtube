from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from uploader.schedule import next_publish_at, parse_schedule, to_rfc3339_utc

KST = ZoneInfo("Asia/Seoul")
S = parse_schedule("MON 08:00")


def at(s):
    return datetime.fromisoformat(s).replace(tzinfo=KST)


def test_parse():
    assert S == (0, 8, 0)
    assert parse_schedule("월 8:30") == (0, 8, 30)
    assert parse_schedule("none") is None and parse_schedule("") is None
    with pytest.raises(SystemExit):
        parse_schedule("someday")


def test_next_monday():
    # 2026-11-27 은 금요일
    assert next_publish_at(S, KST, at("2026-11-27T14:00")) == at("2026-11-30T08:00")
    # 월요일 06:00 업로드 → 같은 날 08:00
    assert next_publish_at(S, KST, at("2026-11-30T06:00")) == at("2026-11-30T08:00")
    # 월요일 07:30 → 1시간 여유가 안 돼서 다음 주
    assert next_publish_at(S, KST, at("2026-11-30T07:30")) == at("2026-12-07T08:00")
    assert next_publish_at(S, KST, at("2026-11-30T09:00")) == at("2026-12-07T08:00")


def test_rfc3339():
    assert to_rfc3339_utc(at("2026-11-30T08:00")) == "2026-11-29T23:00:00.000Z"
