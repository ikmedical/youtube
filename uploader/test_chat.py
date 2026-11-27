"""Google Chat 웹훅과 멘션(태그)이 잘 되는지 테스트 메시지를 보낸다."""
from __future__ import annotations

import logging
import os
import sys

from .chat import Chat


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    url = os.environ.get("GOOGLE_CHAT_WEBHOOK_URL", "").strip()
    if not url:
        raise SystemExit("GOOGLE_CHAT_WEBHOOK_URL 이 비어 있습니다.")
    chat = Chat(url)
    if not chat.mentions:
        chat.send("🔔 Drive→YouTube 알림 테스트입니다. (CHAT_MENTIONS 가 비어 있어 태그 없음)")
    else:
        chat.send("🔔 Drive→YouTube 알림 테스트입니다. 실패·조치 필요 알림에서는 이렇게 태그됩니다. 위 사람들이 파란색으로 태그되어 알림이 갔는지 확인해 주세요.", mention=True)
    logging.info("전송한 멘션: %s", " ".join(chat.mentions) or "(없음)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
