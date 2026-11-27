"""환경변수(= GitHub Actions secrets / variables)에서 설정을 읽는다."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, "").strip()
    if not value:
        if required:
            raise SystemExit(f"[config] 필수 환경변수 {name} 가 비어 있습니다.")
        return default
    return value


def _int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def _bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "y", "on")


@dataclass
class Config:
    # --- OAuth 클라이언트 (Google Cloud 프로젝트의 "데스크톱 앱" OAuth 클라이언트) ---
    google_client_id: str | None
    google_client_secret: str | None

    # --- YouTube 채널 계정 ---
    youtube_refresh_token: str | None

    # --- 공유 드라이브 계정 (둘 중 하나) ---
    drive_service_account_json: str | None
    drive_refresh_token: str | None

    # --- 대상 ---
    drive_folder_id: str | None
    sheet_id: str | None
    sheet_tab: str
    chat_webhook_url: str | None

    # --- 동작 옵션 ---
    privacy_status: str
    category_id: str
    made_for_kids: bool
    title_template: str
    description_template: str
    tags: list[str]
    max_uploads_per_run: int
    max_attempts: int
    min_file_age_minutes: int
    after_upload: str  # keep | move
    done_folder_id: str | None
    include_subfolders: bool
    dry_run: bool
    timezone: str

    @classmethod
    def from_env(cls) -> "Config":
        tags_raw = _env("YT_TAGS", "") or ""
        return cls(
            google_client_id=_env("GOOGLE_CLIENT_ID"),
            google_client_secret=_env("GOOGLE_CLIENT_SECRET"),
            youtube_refresh_token=_env("YT_REFRESH_TOKEN"),
            drive_service_account_json=_env("DRIVE_SERVICE_ACCOUNT_JSON"),
            drive_refresh_token=_env("DRIVE_REFRESH_TOKEN"),
            drive_folder_id=_env("DRIVE_FOLDER_ID"),
            sheet_id=_env("SHEET_ID"),
            sheet_tab=_env("SHEET_TAB", "uploads") or "uploads",
            chat_webhook_url=_env("GOOGLE_CHAT_WEBHOOK_URL"),
            privacy_status=(_env("YT_PRIVACY_STATUS", "private") or "private").lower(),
            category_id=_env("YT_CATEGORY_ID", "22") or "22",
            made_for_kids=_bool("YT_MADE_FOR_KIDS", False),
            title_template=_env("YT_TITLE_TEMPLATE", "{stem}") or "{stem}",
            description_template=_env("YT_DESCRIPTION_TEMPLATE", "") or "",
            tags=[t.strip() for t in tags_raw.split(",") if t.strip()],
            max_uploads_per_run=_int("MAX_UPLOADS_PER_RUN", 3),
            max_attempts=_int("MAX_ATTEMPTS", 3),
            min_file_age_minutes=_int("MIN_FILE_AGE_MINUTES", 10),
            after_upload=(_env("AFTER_UPLOAD", "keep") or "keep").lower(),
            done_folder_id=_env("DONE_FOLDER_ID"),
            include_subfolders=_bool("INCLUDE_SUBFOLDERS", False),
            dry_run=_bool("DRY_RUN", False),
            timezone=_env("TIMEZONE", "Asia/Seoul") or "Asia/Seoul",
        )

    def validate_for_run(self) -> None:
        missing = []
        if not self.drive_folder_id:
            missing.append("DRIVE_FOLDER_ID")
        if not self.sheet_id:
            missing.append("SHEET_ID")
        if not self.dry_run:
            for name, val in (
                ("GOOGLE_CLIENT_ID", self.google_client_id),
                ("GOOGLE_CLIENT_SECRET", self.google_client_secret),
                ("YT_REFRESH_TOKEN", self.youtube_refresh_token),
            ):
                if not val:
                    missing.append(name)
        if not (self.drive_service_account_json or self.drive_refresh_token):
            missing.append("DRIVE_SERVICE_ACCOUNT_JSON 또는 DRIVE_REFRESH_TOKEN")
        if self.privacy_status not in ("private", "unlisted", "public"):
            raise SystemExit("[config] YT_PRIVACY_STATUS 는 private / unlisted / public 중 하나여야 합니다.")
        if self.after_upload not in ("keep", "move"):
            raise SystemExit("[config] AFTER_UPLOAD 는 keep 또는 move 여야 합니다.")
        if self.after_upload == "move" and not self.done_folder_id:
            missing.append("DONE_FOLDER_ID (AFTER_UPLOAD=move 일 때)")
        if missing:
            raise SystemExit("[config] 다음 값이 비어 있습니다: " + ", ".join(missing))
