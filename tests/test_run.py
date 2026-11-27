"""외부 API 없이 _run 흐름(중복 방지, 실패/할당량 처리)을 검증."""
from zoneinfo import ZoneInfo

import uploader.main as m
from uploader.config import Config
from uploader.drive import DriveFile
from uploader.sheet import HEADERS, Row
from uploader.youtube import QuotaExceeded


class FakeSheet:
    store: dict[int, list[str]] = {}

    def __init__(self, *a, **k):
        pass

    def ensure_ready(self):
        pass

    def load(self):
        rows = {}
        for rn, vals in FakeSheet.store.items():
            rows[vals[0]] = Row(rn, list(vals))
        self._next_row = max(FakeSheet.store, default=1) + 1
        return rows

    def new_row(self):
        rn = self._next_row
        self._next_row += 1
        return Row(rn, [""] * len(HEADERS))

    def save(self, row):
        FakeSheet.store[row.row_number] = list(row.values)


def vid(i):
    return DriveFile(f"f{i}", f"v{i}.mp4", "video/mp4", 1, f"2026-01-0{i}T00:00:00Z", "2026-01-01T00:00:00Z", ["p"])


class FakeDrive:
    files = [vid(1), vid(2), vid(3)]

    def __init__(self, *a):
        pass

    def list_videos(self, *a):
        return list(self.files)

    is_stable = staticmethod(lambda f, n: True)

    def download(self, fid, path):
        open(path, "wb").close()

    def move(self, *a):
        pass

    def read_text(self, doc):
        return "  설명 본문\r\n\r\n\r\n둘째 줄  "


class FakeYT:
    behaviour = {}

    def __init__(self, *a):
        pass

    def upload(self, path, mime, title, *a):
        b = FakeYT.behaviour.get(title)
        if b == "fail":
            raise RuntimeError("boom")
        if b == "quota":
            raise QuotaExceeded("403 quotaExceeded")
        return "YT_" + title

    added = []

    def add_to_playlist(self, video_id, playlist_id):
        FakeYT.added.append((video_id, playlist_id))


class FakeChat:
    msgs = []

    def send(self, t):
        FakeChat.msgs.append(t)


def setup(monkeypatch):
    monkeypatch.setattr(m, "Sheet", FakeSheet)
    monkeypatch.setattr(m, "Drive", FakeDrive)
    monkeypatch.setattr(m, "YouTube", FakeYT)
    monkeypatch.setattr(m, "drive_credentials", lambda c: None)
    monkeypatch.setattr(m, "youtube_credentials", lambda c: None)
    FakeSheet.store = {}
    FakeChat.msgs = []


def cfg(monkeypatch, **env):
    base = dict(DRIVE_FOLDER_ID="p", SHEET_ID="s", DRIVE_REFRESH_TOKEN="x", MAX_UPLOADS_PER_RUN="5",
                REQUIRE_DESCRIPTION_FILE="false")
    base.update(env)
    for k, v in base.items():
        monkeypatch.setenv(k, v)
    return Config.from_env()


def status_map():
    return {v[0]: (v[HEADERS.index("status")], v[HEADERS.index("attempts")]) for v in FakeSheet.store.values()}


def test_flow(monkeypatch):
    setup(monkeypatch)
    c = cfg(monkeypatch)
    tz = ZoneInfo("Asia/Seoul")
    FakeYT.behaviour = {"v2": "fail", "v3": "quota"}
    m._run(c, FakeChat(), tz)
    assert status_map() == {"f1": ("success", "1"), "f2": ("failed", "1"), "f3": ("queued", "0")}

    # 두 번째 실행: f1 은 다시 올리지 않고, f2 재시도, f3 이어서
    FakeYT.behaviour = {}
    m._run(c, FakeChat(), tz)
    assert status_map() == {"f1": ("success", "1"), "f2": ("success", "2"), "f3": ("success", "1")}
    assert len(FakeSheet.store) == 3  # 중복 행 없음

    # 세 번째 실행: 아무것도 안 올림
    before = len(FakeChat.msgs)
    m._run(c, FakeChat(), tz)
    assert len(FakeChat.msgs) == before


def test_max_per_run(monkeypatch):
    setup(monkeypatch)
    c = cfg(monkeypatch, MAX_UPLOADS_PER_RUN="2")
    FakeYT.behaviour = {}
    m._run(c, FakeChat(), ZoneInfo("Asia/Seoul"))
    assert len(FakeSheet.store) == 2


def test_playlist(monkeypatch):
    setup(monkeypatch)
    FakeYT.behaviour = {}
    FakeYT.added = []
    files = [vid(1), vid(2)]
    files[1].folder_name = "강의"
    monkeypatch.setattr(FakeDrive, "files", files)
    c = cfg(monkeypatch, YT_PLAYLIST_ID="https://www.youtube.com/playlist?list=PLdefault&si=x",
            YT_PLAYLIST_MAP="강의=PLlecture; 기타=PLetc")
    m._run(c, FakeChat(), ZoneInfo("Asia/Seoul"))
    assert FakeYT.added == [("YT_v1", "PLdefault"), ("YT_v2", "PLlecture")]
    assert {v[0]: v[HEADERS.index("playlist_id")] for v in FakeSheet.store.values()} == {
        "f1": "PLdefault", "f2": "PLlecture"}


def test_description_file(monkeypatch):
    setup(monkeypatch)
    FakeYT.behaviour = {}
    got = {}
    orig = FakeYT.upload

    def spy(self, path, mime, title, description, *a):
        got[title] = description
        return orig(self, path, mime, title, description, *a)

    monkeypatch.setattr(FakeYT, "upload", spy)
    files = [vid(1), vid(2), vid(3)]
    files[0].description_file = {"id": "d1", "name": "v1.docx", "mimeType": "x", "parents": ["p"]}
    monkeypatch.setattr(FakeDrive, "files", files)
    tz = ZoneInfo("Asia/Seoul")
    today = m.datetime.now(tz).date()
    tomorrow = (today + m.timedelta(days=1)).isoformat()

    # 설명 파일이 없으면 보류 + 알림, 다음날 다시 확인
    monkeypatch.delenv("REQUIRE_DESCRIPTION_FILE", raising=False)
    assert Config.from_env().require_description_file is True  # 기본값
    c = cfg(monkeypatch, REQUIRE_DESCRIPTION_FILE="true")
    m._run(c, FakeChat(), tz)
    assert got == {"v1": "설명 본문\n\n둘째 줄"}
    st = {v[0]: (v[HEADERS.index("status")], v[HEADERS.index("next_try_date")]) for v in FakeSheet.store.values()}
    assert st == {"f1": ("success", ""), "f2": ("waiting", tomorrow), "f3": ("waiting", tomorrow)}
    assert sum("보류" in t for t in FakeChat.msgs) == 1

    # 같은 날 다시 실행: 파일이 생겨도 다음날까지 기다리고, 알림도 다시 안 보냄
    files[1].description_file = {"id": "d2", "name": "v2.docx", "mimeType": "x", "parents": ["p"]}
    n = len(FakeChat.msgs)
    m._run(c, FakeChat(), tz)
    assert "v2" not in got and len(FakeChat.msgs) == n

    # 다음날: v2 는 업로드, v3 는 여전히 없으므로 다시 알림 후 하루 더 대기
    for vals in FakeSheet.store.values():
        if vals[HEADERS.index("status")] == "waiting":
            vals[HEADERS.index("next_try_date")] = today.isoformat()
    m._run(c, FakeChat(), tz)
    st = {v[0]: (v[HEADERS.index("status")], v[HEADERS.index("next_try_date")]) for v in FakeSheet.store.values()}
    assert st["f2"] == ("success", "") and st["f3"] == ("waiting", tomorrow)
    assert sum("보류" in t for t in FakeChat.msgs) == 2
    assert len(FakeSheet.store) == 3

    # 옵션 끄면 설명 없이 바로 업로드
    c = cfg(monkeypatch, REQUIRE_DESCRIPTION_FILE="false")
    for vals in FakeSheet.store.values():
        if vals[0] == "f3":
            vals[HEADERS.index("next_try_date")] = today.isoformat()
    m._run(c, FakeChat(), tz)
    assert got["v3"] == ""
