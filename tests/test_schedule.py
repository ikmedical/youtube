from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from uploader.schedule import slot_key, next_free_slot, next_publish_at, parse_schedule, to_rfc3339_utc

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


def test_next_free_slot():
    now = at("2026-11-27T14:00")
    assert next_free_slot(S, KST, set(), now) == at("2026-11-30T08:00")
    assert next_free_slot(S, KST, {"2026-11-30 08:00", "2026-12-07 08:00"}, now) == at("2026-12-14T08:00")
    assert next_free_slot(S, KST, {"2026-12-07 08:00"}, now) == at("2026-11-30T08:00")
    # 월요일이라도 08:00 이 아닌 예약은 '찬 주'가 아님
    assert next_free_slot(S, KST, {"2026-11-30 18:00"}, now) == at("2026-11-30T08:00")


def test_slot_key():
    assert slot_key("2026-11-30 08:00", KST) == "2026-11-30 08:00"
    assert slot_key("2026-11-29T23:00:00Z", KST) == "2026-11-30 08:00"
    assert slot_key("", KST) is None and slot_key("garbage", KST) is None


def test_natural_key():
    from uploader.main import natural_key
    assert sorted(["10강.mp4", "2강.mp4", "1강.mp4"], key=natural_key) == ["1강.mp4", "2강.mp4", "10강.mp4"]
