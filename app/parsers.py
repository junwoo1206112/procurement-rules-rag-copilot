from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True)
class ParsedBlock:
    page: int | None
    text: str
    content_type: str
    parser: str
    confidence: float
    section: str | None = None


class UnsupportedDocumentError(ValueError):
    pass


def parse_document(path: Path) -> list[ParsedBlock]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix == ".hwpx":
        return parse_hwpx(path)
    if suffix in {".html", ".htm"}:
        return parse_html(path)
    if suffix == ".hwp":
        raise UnsupportedDocumentError("구형 HWP는 지원하지 않습니다. HWPX 또는 PDF로 변환해 주세요.")
    raise UnsupportedDocumentError(f"지원하지 않는 문서 형식입니다: {suffix}")


def parse_pdf(path: Path) -> list[ParsedBlock]:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF 설치가 필요합니다.") from exc

    blocks: list[ParsedBlock] = []
    with fitz.open(path) as document:
        for page_number, page in enumerate(document, start=1):
            for raw_block in page.get_text("blocks", sort=True):
                text = raw_block[4].strip()
                if not text:
                    continue
                blocks.append(
                    ParsedBlock(
                        page=page_number,
                        text=text,
                        content_type="table" if _looks_like_table(text) else "text",
                        parser="pymupdf-block",
                        confidence=0.98,
                    )
                )
    return blocks


def parse_hwpx(path: Path) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    with zipfile.ZipFile(path) as archive:
        section_names = sorted(name for name in archive.namelist() if name.startswith("Contents/section") and name.endswith(".xml"))
        if not section_names:
            raise UnsupportedDocumentError("HWPX 본문 섹션을 찾을 수 없습니다.")
        for page_number, section_name in enumerate(section_names, start=1):
            root = ElementTree.fromstring(archive.read(section_name))
            for node in root.iter():
                text = " ".join(part.strip() for part in node.itertext() if part.strip())
                if text and len(text) > 10:
                    blocks.append(ParsedBlock(page_number, text, "text", "hwpx-xml", 0.9))
                    break
    return blocks


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def parse_html(path: Path) -> list[ParsedBlock]:
    return parse_html_text(path.read_text(encoding="utf-8"))


class _StructuredHTMLExtractor(HTMLParser):
    heading_tags = {"h1", "h2", "h3", "h4", "h5", "h6"}
    block_tags = heading_tags | {"p", "li", "td", "th", "tr", "div"}

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[ParsedBlock] = []
        self._tag: str | None = None
        self._parts: list[str] = []
        self._in_table = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
        if tag in self.block_tags:
            self._flush()
            self._tag = tag

    def handle_endtag(self, tag: str) -> None:
        if tag in self.block_tags:
            self._flush()
        if tag == "table":
            self._in_table = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self._parts.append(text)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = " ".join(self._parts).strip()
        if text:
            if self._tag in self.heading_tags:
                text = f"# {text}"
            self.blocks.append(ParsedBlock(None, text, "table" if self._in_table else "text", "html-structure", 0.92))
        self._tag, self._parts = None, []


def parse_html_text(value: str) -> list[ParsedBlock]:
    parser = _StructuredHTMLExtractor()
    parser.feed(value)
    parser.close()
    if not parser.blocks:
        raise UnsupportedDocumentError("HTML 본문 텍스트를 찾을 수 없습니다.")
    return parser.blocks


def _looks_like_table(text: str) -> bool:
    return "|" in text or len(re.findall(r"\s{3,}", text)) >= 3
