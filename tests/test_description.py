import io
import unicodedata
import zipfile
from zoneinfo import ZoneInfo

from uploader.description import DOCX_MIME, GDOC_MIME, clean, docx_to_text, norm_stem
from uploader.drive import DriveFile
from uploader.main import render
from uploader.youtube import safe_description

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(body_xml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{body_xml}</w:body></w:document>')
    return buf.getvalue()


def test_docx_to_text():
    data = make_docx(
        "<w:p><w:r><w:t>첫 줄 </w:t></w:r><w:r><w:t>이어짐</w:t></w:r></w:p>"
        "<w:p/><w:p/>"
        "<w:p><w:r><w:t>A</w:t><w:tab/><w:t>B</w:t><w:br/><w:t>C</w:t></w:r></w:p>"
    )
    assert clean(docx_to_text(data)) == "첫 줄 이어짐\n\nA\tB\nC"


def test_norm_stem():
    nfd = unicodedata.normalize("NFD", "강의 01")
    assert norm_stem(nfd + ".MP4") == norm_stem("강의 01.docx", DOCX_MIME) == norm_stem("강의 01", GDOC_MIME)


def test_render_description():
    f = DriveFile("i", "a.mp4", "video/mp4", 1, "2026-11-27T00:00:00Z", "", [])
    tz = ZoneInfo("Asia/Seoul")
    assert render("{description}", f, tz, "내용 {stem} 그대로") == "내용 {stem} 그대로"
    assert render("{description}\\n\\n#{stem}", f, tz, "") == "#a"


def test_description_byte_limit():
    d = safe_description("가" * 3000)
    assert len(d.encode("utf-8")) <= 5000 and len(d) == 1666
