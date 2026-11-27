"""썸네일 이미지 준비: YouTube 제한(2MB, jpg/png)에 맞게 필요하면 줄인다."""
from __future__ import annotations

import io

MAX_BYTES = 2 * 1024 * 1024


def fit_thumbnail(data: bytes, mime_type: str) -> tuple[bytes, str]:
    """2MB 이하면 그대로, 넘으면 1280x720 이내 JPEG 로 다시 압축."""
    if len(data) <= MAX_BYTES:
        return data, mime_type
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    img.thumbnail((1920, 1080))
    for size in ((1920, 1080), (1280, 720)):
        img.thumbnail(size)
        for quality in (90, 85, 80, 70, 60, 50):
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality, optimize=True)
            if buf.tell() <= MAX_BYTES:
                return buf.getvalue(), "image/jpeg"
    raise ValueError("썸네일을 2MB 이하로 줄이지 못했습니다.")
