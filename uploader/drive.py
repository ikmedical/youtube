"""공유 드라이브에서 영상 목록 조회 / 다운로드 / 이동."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from .description import DESCRIPTION_MIMES, GDOC_MIME, PRIORITY, TXT_MIME, docx_to_text, norm_stem

log = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"
IMAGE_PRIORITY = {"image/jpeg": 0, "image/png": 1}
FIELDS = "nextPageToken, files(id, name, mimeType, size, createdTime, modifiedTime, parents, md5Checksum)"


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int
    created_time: str
    modified_time: str
    parents: list[str]
    folder_name: str = ""  # 하위 폴더 이름 (최상위 폴더면 빈 값)
    description_file: dict | None = None  # 같은 이름의 설명 파일 {id, name, mimeType, parents}
    thumbnail_file: dict | None = None  # 같은 이름의 이미지 파일 (jpg/png)

    @property
    def modified_dt(self) -> datetime:
        return datetime.fromisoformat(self.modified_time.replace("Z", "+00:00"))


class Drive:
    def __init__(self, creds):
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    def _list_children(self, folder_id: str, extra_q: str) -> list[dict]:
        q = f"'{folder_id}' in parents and trashed = false and ({extra_q})"
        out: list[dict] = []
        token = None
        while True:
            resp = (
                self.svc.files()
                .list(
                    q=q,
                    fields=FIELDS,
                    pageSize=200,
                    pageToken=token,
                    orderBy="createdTime",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            out.extend(resp.get("files", []))
            token = resp.get("nextPageToken")
            if not token:
                return out

    def folder_info(self, folder_id: str) -> dict:
        """폴더 접근 확인. 권한이 없거나 ID 가 틀리면 알기 쉬운 오류로 바꾼다."""
        from googleapiclient.errors import HttpError

        try:
            return self.svc.files().get(
                fileId=folder_id, fields="id, name, mimeType, driveId", supportsAllDrives=True
            ).execute()
        except HttpError as e:
            if e.resp.status in (403, 404):
                raise RuntimeError(
                    f"드라이브 폴더({folder_id})를 찾을 수 없거나 접근 권한이 없습니다. "
                    "DRIVE_FOLDER_ID 와, 토큰을 발급한 계정이 그 공유 드라이브 멤버인지 확인하세요."
                ) from e
            raise

    def describe_children(self, folder_id: str, limit: int = 10) -> str:
        """영상이 0개일 때 원인 파악용: 폴더 안에 무엇이 있는지 요약."""
        items = self._list_children(folder_id, "mimeType != 'x'")
        folders = [f["name"] for f in items if f["mimeType"] == FOLDER_MIME]
        others = [f"{f['name']} ({f['mimeType']})" for f in items if f["mimeType"] != FOLDER_MIME]
        return (f"폴더 안 항목 {len(items)}개 - 하위 폴더 {len(folders)}개: {folders[:limit]}, "
                f"기타 파일 {len(others)}개: {others[:limit]}")

    def list_videos(self, folder_id: str, include_subfolders: bool = False,
                    exclude_folder_ids: set[str] | None = None) -> list[DriveFile]:
        exclude = exclude_folder_ids or set()
        folders: list[tuple[str, str]] = [(folder_id, "")]
        videos: list[DriveFile] = []
        mime_q = " or ".join(f"mimeType = '{m}'" for m in DESCRIPTION_MIMES)
        img_q = " or ".join(f"mimeType = '{m}'" for m in IMAGE_PRIORITY)
        while folders:
            fid, fname = folders.pop(0)
            docs: dict[str, dict] = {}
            for d in self._list_children(fid, mime_q):
                key = norm_stem(d["name"], d["mimeType"])
                if key not in docs or PRIORITY[d["mimeType"]] < PRIORITY[docs[key]["mimeType"]]:
                    docs[key] = d
            thumbs: dict[str, dict] = {}
            for t in self._list_children(fid, img_q):
                key = norm_stem(t["name"])
                if key not in thumbs or IMAGE_PRIORITY[t["mimeType"]] < IMAGE_PRIORITY[thumbs[key]["mimeType"]]:
                    thumbs[key] = t
            for f in self._list_children(fid, "mimeType contains 'video/'"):
                videos.append(
                    DriveFile(
                        id=f["id"],
                        name=f["name"],
                        mime_type=f["mimeType"],
                        size=int(f.get("size", 0)),
                        created_time=f.get("createdTime", ""),
                        modified_time=f.get("modifiedTime", ""),
                        parents=f.get("parents", []),
                        folder_name=fname,
                        description_file=docs.get(norm_stem(f["name"])),
                        thumbnail_file=thumbs.get(norm_stem(f["name"])),
                    )
                )
            if include_subfolders:
                for sub in self._list_children(fid, f"mimeType = '{FOLDER_MIME}'"):
                    if sub["id"] not in exclude:
                        folders.append((sub["id"], sub["name"]))
        videos.sort(key=lambda v: v.created_time)
        return videos

    @staticmethod
    def is_stable(f: DriveFile, min_age_minutes: int, now: datetime | None = None) -> bool:
        """업로드(동기화) 중인 파일을 피하기 위해 최근 수정된 파일은 건너뛴다."""
        if min_age_minutes <= 0 or not f.modified_time:
            return True
        now = now or datetime.now(timezone.utc)
        return now - f.modified_dt >= timedelta(minutes=min_age_minutes)

    def download(self, file_id: str, dest_path: str, chunk_mb: int = 32) -> None:
        req = self.svc.files().get_media(fileId=file_id, supportsAllDrives=True)
        with io.FileIO(dest_path, "wb") as fh:
            dl = MediaIoBaseDownload(fh, req, chunksize=chunk_mb * 1024 * 1024)
            done = False
            last = -1
            while not done:
                status, done = dl.next_chunk(num_retries=5)
                if status:
                    pct = int(status.progress() * 100)
                    if pct // 10 != last // 10:
                        log.info("  다운로드 %d%%", pct)
                        last = pct

    def download_bytes(self, file_id: str) -> bytes:
        return self.svc.files().get_media(fileId=file_id, supportsAllDrives=True).execute()

    def read_text(self, doc: dict) -> str:
        """설명 파일 내용을 텍스트로 읽는다."""
        if doc["mimeType"] == GDOC_MIME:
            data = self.svc.files().export(fileId=doc["id"], mimeType="text/plain").execute()
            return data.decode("utf-8-sig") if isinstance(data, bytes) else str(data)
        data = self.svc.files().get_media(fileId=doc["id"], supportsAllDrives=True).execute()
        if doc["mimeType"] == TXT_MIME:
            return data.decode("utf-8-sig", errors="replace")
        return docx_to_text(data)

    def move(self, f: DriveFile | dict, target_folder_id: str) -> None:
        file_id = f.id if isinstance(f, DriveFile) else f["id"]
        parents = f.parents if isinstance(f, DriveFile) else f.get("parents", [])
        self.svc.files().update(
            fileId=file_id,
            addParents=target_folder_id,
            removeParents=",".join(parents),
            supportsAllDrives=True,
            fields="id, parents",
        ).execute()

    def create_spreadsheet(self, name: str, parent_folder_id: str | None) -> str:
        body = {"name": name, "mimeType": "application/vnd.google-apps.spreadsheet"}
        if parent_folder_id:
            body["parents"] = [parent_folder_id]
        created = self.svc.files().create(body=body, fields="id", supportsAllDrives=True).execute()
        return created["id"]
