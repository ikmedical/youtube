from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from uploader.drive import Drive, DriveFile
from uploader.main import render
from uploader.sheet import HEADERS, Row, decide
from uploader.youtube import safe_title


def row(status, attempts=0):
    r = Row(2, [""] * len(HEADERS))
    r.set("status", status)
    r.set("attempts", attempts)
    return r


def f(name="영상 01.mp4", modified=None):
    return DriveFile("id1", name, "video/mp4", 10, "2026-11-27T00:00:00Z",
                     modified or "2026-11-27T00:00:00Z", ["p"])


def test_decide():
    assert decide(None, 3)[0] is True
    assert decide(row("success"), 3)[0] is False
    assert decide(row("skip"), 3)[0] is False
    assert decide(row("uploading", 1), 3)[0] is False
    assert decide(row("queued", 0), 3)[0] is True
    assert decide(row("failed", 2), 3)[0] is True
    assert decide(row("failed", 3), 3)[0] is False
    assert decide(row("", 0), 3)[0] is True


def test_render_and_title():
    tz = ZoneInfo("Asia/Seoul")
    assert render("{stem}", f(), tz) == "영상 01"
    assert render("{stem} ({created_date})\\n{unknown}", f(), tz) == "영상 01 (2026-11-27)\n{unknown}"
    assert safe_title("a<b>" + "x" * 200).startswith("ab") and len(safe_title("x" * 200)) == 100


def test_is_stable():
    now = datetime(2026, 11, 27, 1, 0, tzinfo=timezone.utc)
    recent = (now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z")
    assert Drive.is_stable(f(), 10, now) is True
    assert Drive.is_stable(f(modified=recent), 10, now) is False
