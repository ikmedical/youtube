"""Google Chat 수신 웹훅 알림."""
from __future__ import annotations

import logging
import os
import re

import requests

log = logging.getLogger(__name__)


def parse_mentions(raw: str) -> list[str]:
    """CHAT_MENTIONS 값을 Google Chat 멘션 태그 목록으로.

    항목은 쉼표/공백/줄바꿈으로 구분. 다음 형식을 받는다.
      123456789012345678901      → <users/123456789012345678901>  (숫자 사용자 ID, 가장 확실)
      users/123456789012345678901 → 그대로
      name@example.com           → <users/name@example.com>       (이메일, 웹훅에선 안 될 수 있음)
      all                        → <users/all>                    (스페이스 전체)
    """
    tags: list[str] = []
    for item in re.split(r"[,\s;]+", raw or ""):
        item = item.strip()
        if not item:
            continue
        if item.startswith("users/"):
            item = item[len("users/"):]
        tags.append(f"<users/{item}>")
    return tags


class Chat:
    def __init__(self, webhook_url: str | None, mentions: str | None = None):
        self.url = webhook_url
        raw = os.environ.get("CHAT_MENTIONS", "") if mentions is None else mentions
        self.mentions = parse_mentions(raw)

    def send(self, text: str, mention: bool = False) -> None:
        """mention=True 일 때만 CHAT_MENTIONS 사람들을 태그 (실패·조치 필요 알림용)."""
        if mention and self.mentions:
            text = " ".join(self.mentions) + "\n" + text
        if not self.url:
            log.info("[chat 미설정] %s", text)
            return
        try:
            r = requests.post(
                self.url,
                json={"text": text[:4000]},
                headers={"Content-Type": "application/json; charset=UTF-8"},
                timeout=20,
            )
            if r.status_code >= 300:
                log.warning("Google Chat 전송 실패 %s: %s", r.status_code, r.text[:300])
        except requests.RequestException as e:
            log.warning("Google Chat 전송 실패: %s", e)
