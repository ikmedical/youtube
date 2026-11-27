"""업로드 관리 시트(Google Sheets) 읽기/쓰기.

시트 한 행 = 드라이브 파일 하나. drive_file_id 로 중복 업로드를 막는다.

status 값
  uploading : 업로드 진행 중 (실행이 중간에 죽으면 이 상태로 남음 → 자동 재시도 안 함, 직접 확인 필요)
  success   : 업로드 완료 → 다시 올리지 않음
  failed    : 실패 → attempts < MAX_ATTEMPTS 이면 다음 실행에서 재시도
  queued    : 할당량 초과 등으로 미뤄짐 → 다음 실행에서 재시도 (시도 횟수에 포함 안 함)
  skip      : 사람이 직접 입력하면 해당 파일을 업로드하지 않음
  waiting   : 같은 이름의 설명 파일이 없어 대기 중 → next_try_date 날짜에 다시 확인
"""
from __future__ import annotations

from dataclasses import dataclass, field

from googleapiclient.discovery import build

HEADERS = [
    "drive_file_id",
    "file_name",
    "size_mb",
    "drive_created",
    "status",
    "youtube_video_id",
    "youtube_url",
    "title",
    "attempts",
    "started_at",
    "finished_at",
    "error",
    "playlist_id",
    "description_file",
    "next_try_date",
]
COL = {name: i for i, name in enumerate(HEADERS)}
LAST_COL = chr(ord("A") + len(HEADERS) - 1)  # 'L'

RETRYABLE = {"failed", "queued"}
DONE = {"success", "skip"}


@dataclass
class Row:
    row_number: int  # 시트 상의 1-based 행 번호
    values: list[str] = field(default_factory=list)

    def get(self, name: str) -> str:
        i = COL[name]
        return self.values[i] if i < len(self.values) else ""

    def set(self, name: str, value) -> None:
        i = COL[name]
        while len(self.values) <= i:
            self.values.append("")
        self.values[i] = "" if value is None else str(value)

    @property
    def status(self) -> str:
        return self.get("status").strip().lower()

    @property
    def attempts(self) -> int:
        try:
            return int(self.get("attempts") or 0)
        except ValueError:
            return 0


def decide(row: Row | None, max_attempts: int, today: str = "") -> tuple[bool, str]:
    """(업로드할지, 이유). today 는 YYYY-MM-DD"""
    if row is None:
        return True, "new"
    st = row.status
    if st in DONE:
        return False, st
    if st == "uploading":
        return False, "uploading (이전 실행이 중단됨 - 유튜브 확인 후 status 를 success/failed 로 바꿔주세요)"
    if st == "waiting":
        nxt = row.get("next_try_date").strip()
        if not nxt or not today or today >= nxt:
            return True, "waiting → 설명 파일 다시 확인"
        return False, f"waiting (설명 파일 없음, {nxt}에 다시 확인)"
    if st == "queued":
        return True, "queued"
    if st == "failed":
        if row.attempts < max_attempts:
            return True, f"retry {row.attempts + 1}/{max_attempts}"
        return False, f"failed (최대 {max_attempts}회 시도 초과)"
    # 알 수 없는/빈 status: 사람이 비워둔 경우 재시도
    return True, f"status='{st}'"


class Sheet:
    def __init__(self, creds, spreadsheet_id: str, tab: str = "uploads"):
        self.svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self.id = spreadsheet_id
        self.tab = tab

    # ---------- 초기화 ----------
    def ensure_ready(self) -> None:
        meta = self.svc.spreadsheets().get(spreadsheetId=self.id, fields="sheets.properties").execute()
        titles = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}
        if self.tab not in titles:
            resp = (
                self.svc.spreadsheets()
                .batchUpdate(
                    spreadsheetId=self.id,
                    body={"requests": [{"addSheet": {"properties": {"title": self.tab}}}]},
                )
                .execute()
            )
            sheet_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
            self._format(sheet_id)
        first = (
            self.svc.spreadsheets()
            .values()
            .get(spreadsheetId=self.id, range=f"'{self.tab}'!A1:{LAST_COL}1")
            .execute()
            .get("values", [[]])
        )
        if not first or first[0][: len(HEADERS)] != HEADERS:
            self._write(1, HEADERS)

    def _format(self, sheet_id: int) -> None:
        requests = [
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount",
                }
            },
            {
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "backgroundColor": {"red": 0.9, "green": 0.93, "blue": 0.98},
                        }
                    },
                    "fields": "userEnteredFormat(textFormat,backgroundColor)",
                }
            },
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": COL["status"],
                        "endColumnIndex": COL["status"] + 1,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [
                                {"userEnteredValue": v}
                                for v in ("uploading", "success", "failed", "queued", "skip", "waiting")
                            ],
                        },
                        "showCustomUi": True,
                        "strict": False,
                    },
                }
            },
        ]
        self.svc.spreadsheets().batchUpdate(spreadsheetId=self.id, body={"requests": requests}).execute()

    def format_tab(self) -> None:
        meta = self.svc.spreadsheets().get(spreadsheetId=self.id, fields="sheets.properties").execute()
        for s in meta.get("sheets", []):
            if s["properties"]["title"] == self.tab:
                self._format(s["properties"]["sheetId"])

    # ---------- 읽기/쓰기 ----------
    def load(self) -> dict[str, Row]:
        values = (
            self.svc.spreadsheets()
            .values()
            .get(spreadsheetId=self.id, range=f"'{self.tab}'!A2:{LAST_COL}")
            .execute()
            .get("values", [])
        )
        rows: dict[str, Row] = {}
        self._next_row = 2
        for i, vals in enumerate(values):
            rn = i + 2
            self._next_row = rn + 1
            if vals and vals[0].strip():
                rows[vals[0].strip()] = Row(rn, list(vals))
        return rows

    def _write(self, row_number: int, values: list[str]) -> None:
        self.svc.spreadsheets().values().update(
            spreadsheetId=self.id,
            range=f"'{self.tab}'!A{row_number}:{LAST_COL}{row_number}",
            valueInputOption="RAW",
            body={"values": [values]},
        ).execute()

    def new_row(self) -> Row:
        rn = getattr(self, "_next_row", None)
        if rn is None:
            self.load()
            rn = self._next_row
        self._next_row = rn + 1
        return Row(rn, [""] * len(HEADERS))

    def save(self, row: Row) -> None:
        vals = (row.values + [""] * len(HEADERS))[: len(HEADERS)]
        self._write(row.row_number, vals)
