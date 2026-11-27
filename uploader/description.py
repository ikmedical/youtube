"""영상과 같은 이름의 설명 파일(.docx / Google 문서 / .txt)을 찾아 텍스트로 읽는다."""
from __future__ import annotations

import io
import os
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
GDOC_MIME = "application/vnd.google-apps.document"
TXT_MIME = "text/plain"
DESCRIPTION_MIMES = (DOCX_MIME, GDOC_MIME, TXT_MIME)
# 같은 이름이 여러 개면 이 순서로 우선
PRIORITY = {DOCX_MIME: 0, GDOC_MIME: 1, TXT_MIME: 2}

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def norm_stem(name: str, mime_type: str = "") -> str:
    """비교용 이름: 확장자 제거, 유니코드 정규화(맥 한글 NFD 대비), 대소문자/앞뒤 공백 무시."""
    stem = name if mime_type == GDOC_MIME else os.path.splitext(name)[0]
    return unicodedata.normalize("NFC", stem).strip().casefold()


def docx_to_text(data: bytes) -> str:
    """python-docx 없이 word/document.xml 에서 문단 텍스트만 뽑는다."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{_W}body")
    lines: list[str] = []
    for p in (body.iter(f"{_W}p") if body is not None else []):
        parts: list[str] = []
        for el in p.iter():
            if el.tag == f"{_W}t" and el.text:
                parts.append(el.text)
            elif el.tag == f"{_W}tab":
                parts.append("\t")
            elif el.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
        lines.append("".join(parts))
    return "\n".join(lines)


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    # 앞뒤 빈 줄 제거, 연속 빈 줄은 하나로
    out: list[str] = []
    for line in text.split("\n"):
        line = line.rstrip()
        if not line and (not out or not out[-1]):
            continue
        out.append(line)
    return "\n".join(out).strip()
