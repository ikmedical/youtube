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
    w = row("waiting")
    w.set("next_try_date", "2026-11-28")
    assert decide(w, 3, "2026-11-27")[0] is False
    assert decide(w, 3, "2026-11-28")[0] is True


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


def test_parse_mentions():
    from uploader.chat import parse_mentions
    assert parse_mentions("123, users/456\na@b.com all") == [
        "<users/123>", "<users/456>", "<users/a@b.com>", "<users/all>"]
    assert parse_mentions("") == []


def test_fit_thumbnail():
    import io
    import os as _os

    from PIL import Image

    from uploader.thumbnail import MAX_BYTES, fit_thumbnail

    small = b"x" * 100
    assert fit_thumbnail(small, "image/png") == (small, "image/png")
    img = Image.frombytes("RGB", (2400, 1600), _os.urandom(2400 * 1600 * 3))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    assert buf.tell() > MAX_BYTES
    data, mime = fit_thumbnail(buf.getvalue(), "image/png")
    assert mime == "image/jpeg" and len(data) <= MAX_BYTES
