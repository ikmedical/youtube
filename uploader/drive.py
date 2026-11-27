"""공유 드라이브에서 영상 목록 조회 / 다운로드 / 이동."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

log = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"
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

    def list_videos(self, folder_id: str, include_subfolders: bool = False,
                    exclude_folder_ids: set[str] | None = None) -> list[DriveFile]:
        exclude = exclude_folder_ids or set()
        folders: list[tuple[str, str]] = [(folder_id, "")]
        videos: list[DriveFile] = []
        while folders:
            fid, fname = folders.pop(0)
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

    def move(self, f: DriveFile, target_folder_id: str) -> None:
        self.svc.files().update(
            fileId=f.id,
            addParents=target_folder_id,
            removeParents=",".join(f.parents),
            supportsAllDrives=True,
            fields="id, parents",
        ).execute()

    def create_spreadsheet(self, name: str, parent_folder_id: str | None) -> str:
        body = {"name": name, "mimeType": "application/vnd.google-apps.spreadsheet"}
        if parent_folder_id:
            body["parents"] = [parent_folder_id]
        created = self.svc.files().create(body=body, fields="id", supportsAllDrives=True).execute()
        return created["id"]
