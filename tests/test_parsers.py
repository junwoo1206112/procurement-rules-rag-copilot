from pathlib import Path
import zipfile

import pytest

from app.parsers import UnsupportedDocumentError, parse_document


def test_legacy_hwp_is_explicitly_rejected(tmp_path: Path) -> None:
    path = tmp_path / "legacy.hwp"
    path.write_bytes(b"not a real hwp")
    with pytest.raises(UnsupportedDocumentError, match="구형 HWP"):
        parse_document(path)


def test_pdf_parser_preserves_page_metadata(tmp_path: Path) -> None:
    import fitz

    path = tmp_path / "source.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Public procurement eligibility")
    document.save(path)
    blocks = parse_document(path)
    assert blocks[0].page == 1
    assert "eligibility" in blocks[0].text
    assert blocks[0].parser == "pymupdf-block"


def test_hwpx_parser_reads_section_text(tmp_path: Path) -> None:
    path = tmp_path / "source.hwpx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Contents/section0.xml", "<section><p>제출 서류와 평가 기준을 확인합니다.</p></section>")
    blocks = parse_document(path)
    assert blocks[0].page == 1
    assert "제출 서류" in blocks[0].text
    assert blocks[0].parser == "hwpx-xml"


def test_html_parser_reads_public_rule_text(tmp_path: Path) -> None:
    path = tmp_path / "rule.html"
    path.write_text("<html><body><h1>조달 규정</h1><p>제1조 목적</p></body></html>", encoding="utf-8")
    blocks = parse_document(path)
    assert blocks[0].text == "# 조달 규정"
    assert "제1조" in blocks[1].text
    assert blocks[0].parser == "html-structure"
