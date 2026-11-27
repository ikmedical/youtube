"""업로드 관리 시트를 공유 드라이브에 새로 만든다 (최초 1회).

필요 환경변수: DRIVE_SERVICE_ACCOUNT_JSON 또는 (DRIVE_REFRESH_TOKEN + GOOGLE_CLIENT_ID/SECRET)
선택: SHEET_PARENT_FOLDER_ID (없으면 DRIVE_FOLDER_ID), SHEET_NAME, SHEET_TAB, GOOGLE_CHAT_WEBHOOK_URL
"""
from __future__ import annotations

import logging
import os
import sys

from .chat import Chat
from .config import Config
from .drive import Drive
from .google_auth import drive_credentials
from .sheet import Sheet


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.from_env()
    creds = drive_credentials(cfg)
    parent = os.environ.get("SHEET_PARENT_FOLDER_ID", "").strip() or cfg.drive_folder_id
    name = os.environ.get("SHEET_NAME", "").strip() or "YouTube 업로드 관리"

    if cfg.sheet_id:
        sheet_id = cfg.sheet_id
        logging.info("SHEET_ID 가 이미 설정되어 있어 새로 만들지 않고 헤더/서식만 맞춥니다.")
    else:
        sheet_id = Drive(creds).create_spreadsheet(name, parent)
        logging.info("시트를 만들었습니다: %s", sheet_id)

    sheet = Sheet(creds, sheet_id, cfg.sheet_tab)
    sheet.ensure_ready()
    sheet.format_tab()
    # 새로 만든 파일의 기본 탭(Sheet1/시트1)은 그대로 둔다.

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    print(f"\nSHEET_ID={sheet_id}\n{url}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### 업로드 관리 시트\n\n- SHEET_ID: `{sheet_id}`\n- {url}\n\n"
                     "이 값을 저장소 Settings → Secrets and variables → Actions 의 `SHEET_ID` 에 저장하세요.\n")
    Chat(cfg.chat_webhook_url).send(f"📄 업로드 관리 시트 준비 완료\nSHEET_ID: {sheet_id}\n{url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
