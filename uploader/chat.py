"""Google Chat 수신 웹훅 알림."""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)


class Chat:
    def __init__(self, webhook_url: str | None):
        self.url = webhook_url

    def send(self, text: str) -> None:
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
