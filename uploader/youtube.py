"""YouTube 업로드."""
from __future__ import annotations

import logging
import random
import time

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload

log = logging.getLogger(__name__)

RETRIABLE_STATUS = {500, 502, 503, 504}
QUOTA_REASONS = {"quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded", "rateLimitExceeded"}


class QuotaExceeded(Exception):
    """오늘 더 이상 업로드할 수 없음 → 이번 실행 중단."""


def error_reason(err: HttpError) -> str:
    try:
        details = err.error_details or []
        if details and isinstance(details, list) and isinstance(details[0], dict):
            return details[0].get("reason", "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def safe_title(title: str) -> str:
    # YouTube 제목: 최대 100자, '<' '>' 불가
    t = title.replace("<", "").replace(">", "").strip()
    return (t or "untitled")[:100]


def safe_description(desc: str) -> str:
    # YouTube 설명: 최대 5000 바이트(UTF-8, 한글 1자 = 3바이트), '<' '>' 불가
    d = desc.replace("<", "").replace(">", "")
    b = d.encode("utf-8")
    if len(b) <= 5000:
        return d
    return b[:5000].decode("utf-8", errors="ignore")


class YouTube:
    def __init__(self, creds):
        self.svc = build("youtube", "v3", credentials=creds, cache_discovery=False)

    def upload(self, path: str, mime_type: str, title: str, description: str, tags: list[str],
               category_id: str, privacy_status: str, made_for_kids: bool,
               publish_at: str | None = None) -> str:
        body = {
            "snippet": {
                "title": safe_title(title),
                "description": safe_description(description),
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": made_for_kids,
            },
        }
        if tags:
            body["snippet"]["tags"] = tags
        if publish_at:
            # 예약 공개: 비공개로 올리고 publishAt 시각에 YouTube 가 공개로 전환
            body["status"]["privacyStatus"] = "private"
            body["status"]["publishAt"] = publish_at
        media = MediaFileUpload(path, mimetype=mime_type or "video/*", chunksize=16 * 1024 * 1024, resumable=True)
        req = self.svc.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        retry = 0
        last = -1
        while response is None:
            try:
                status, response = req.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    if pct // 10 != last // 10:
                        log.info("  업로드 %d%%", pct)
                        last = pct
            except HttpError as e:
                reason = error_reason(e)
                if e.resp.status in (403, 429) and reason in QUOTA_REASONS:
                    raise QuotaExceeded(f"{e.resp.status} {reason}") from e
                if e.resp.status in RETRIABLE_STATUS and retry < 8:
                    retry += 1
                    wait = min(60, 2 ** retry) + random.random()
                    log.warning("  일시 오류 %s, %.0f초 후 재시도 (%d)", e.resp.status, wait, retry)
                    time.sleep(wait)
                    continue
                raise
            except (ConnectionError, TimeoutError, OSError) as e:
                if retry < 8:
                    retry += 1
                    wait = min(60, 2 ** retry) + random.random()
                    log.warning("  네트워크 오류 %s, %.0f초 후 재시도 (%d)", e, wait, retry)
                    time.sleep(wait)
                    continue
                raise
        if "id" not in response:
            raise RuntimeError(f"업로드 응답에 video id 가 없습니다: {response}")
        return response["id"]

    def add_to_playlist(self, video_id: str, playlist_id: str) -> None:
        """재생목록 맨 뒤에 추가 (할당량 50 units)."""
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        }
        for attempt in range(4):
            try:
                self.svc.playlistItems().insert(part="snippet", body=body).execute()
                return
            except HttpError as e:
                # 업로드 직후엔 영상이 아직 처리 중이라 실패할 수 있어 잠시 후 재시도
                if attempt < 3 and e.resp.status in (404, 409, 500, 503):
                    time.sleep(5 * (attempt + 1))
                    continue
                raise

    def scheduled_publish_times(self, max_items: int = 300) -> list[str]:
        """채널에 이미 공개 예약(publishAt)이 걸린 영상들의 예약 시각(RFC3339) 목록."""
        ch = self.svc.channels().list(part="contentDetails", mine=True).execute()
        items = ch.get("items", [])
        if not items:
            return []
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        ids: list[str] = []
        token = None
        while len(ids) < max_items:
            resp = self.svc.playlistItems().list(
                part="contentDetails", playlistId=uploads, maxResults=50, pageToken=token
            ).execute()
            ids += [it["contentDetails"]["videoId"] for it in resp.get("items", [])]
            token = resp.get("nextPageToken")
            if not token:
                break
        out: list[str] = []
        for i in range(0, len(ids), 50):
            resp = self.svc.videos().list(part="status", id=",".join(ids[i:i + 50])).execute()
            for v in resp.get("items", []):
                pa = v.get("status", {}).get("publishAt")
                if pa:
                    out.append(pa)
        return out

    def playlists_by_title(self) -> dict[str, str]:
        """내 채널 재생목록 {정규화된 제목: id}"""
        from .description import norm_title

        out: dict[str, str] = {}
        token = None
        while True:
            resp = self.svc.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=token).execute()
            for p in resp.get("items", []):
                out.setdefault(norm_title(p["snippet"]["title"]), p["id"])
            token = resp.get("nextPageToken")
            if not token:
                return out

    def set_thumbnail(self, video_id: str, data: bytes, mime_type: str) -> None:
        media = MediaInMemoryUpload(data, mimetype=mime_type, resumable=False)
        self.svc.thumbnails().set(videoId=video_id, media_body=media).execute()
