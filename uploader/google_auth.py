"""Google 자격증명 생성.

- YouTube: 채널 소유 계정의 OAuth refresh token (서비스 계정은 YouTube 업로드 불가)
- Drive/Sheets: 공유 드라이브 계정. 서비스 계정 JSON 또는 그 계정의 OAuth refresh token
"""
from __future__ import annotations

import json

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials

from .config import Config

TOKEN_URI = "https://oauth2.googleapis.com/token"

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _user_creds(cfg: Config, refresh_token: str, scopes: list[str]) -> Credentials:
    if not (cfg.google_client_id and cfg.google_client_secret):
        raise SystemExit("[auth] GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET 가 필요합니다.")
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=cfg.google_client_id,
        client_secret=cfg.google_client_secret,
        scopes=scopes,
    )


def youtube_credentials(cfg: Config) -> Credentials:
    if not cfg.youtube_refresh_token:
        raise SystemExit("[auth] YT_REFRESH_TOKEN 이 필요합니다.")
    return _user_creds(cfg, cfg.youtube_refresh_token, YOUTUBE_SCOPES)


def drive_credentials(cfg: Config):
    if cfg.drive_service_account_json:
        info = json.loads(cfg.drive_service_account_json)
        return service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
    if cfg.drive_refresh_token:
        return _user_creds(cfg, cfg.drive_refresh_token, DRIVE_SCOPES)
    raise SystemExit("[auth] DRIVE_SERVICE_ACCOUNT_JSON 또는 DRIVE_REFRESH_TOKEN 이 필요합니다.")
