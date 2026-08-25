from __future__ import annotations

from app.parsers import ParsedBlock
from app.schemas import DocumentChunk, DocumentManifest


def build_chunks(manifest: DocumentManifest, blocks: list[ParsedBlock], max_chars: int = 2600, overlap_chars: int = 320) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    section = "본문"
    buffer = ""
    buffer_page: int | None = None
    buffer_type = "text"

    def flush() -> None:
        nonlocal buffer
        if not buffer.strip():
            return
        index = len(chunks) + 1
        chunks.append(DocumentChunk(
            chunk_id=f"{manifest.document_id}-{index:04d}", document_id=manifest.document_id,
            document_title=manifest.title, page=buffer_page, section=section, content=buffer.strip(),
            content_type=buffer_type, parser="structure-chunker", confidence=0.95,
            source_url=manifest.source_url, issuing_organization=manifest.issuing_organization,
            notice_number=manifest.notice_number,
            document_kind=manifest.document_kind,
        ))
        buffer = buffer[-overlap_chars:] if buffer_type == "text" else ""

    for block in blocks:
        text = block.text.strip()
        if block.section and block.section != section:
            flush()
            buffer = ""
            section = block.section
            buffer_page, buffer_type = block.page, block.content_type
        if text.startswith("#") or (len(text) < 100 and text.endswith(("요", "기준", "방법", "사항"))):
            flush()
            # 겹침은 같은 섹션 안에서만 유지한다. 새 제목으로 넘어갈 때 이전 조항이
            # 섞이면 인용 위치와 검색 순위가 왜곡될 수 있다.
            buffer = ""
            section = text.lstrip("# ").strip()
            buffer_page, buffer_type = block.page, block.content_type
            continue
        if block.content_type == "table":
            flush()
            buffer, buffer_page, buffer_type = text, block.page, "table"
            flush()
            continue
        if not buffer:
            buffer_page, buffer_type = block.page, "text"
        if len(buffer) + len(text) + 1 > max_chars:
            flush()
            buffer_page = block.page
        buffer = f"{buffer}\n{text}".strip()
    flush()
    return chunks
