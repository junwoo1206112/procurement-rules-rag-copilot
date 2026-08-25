from app.chunking import build_chunks


def test_table_is_stored_as_independent_chunk(manifest, blocks) -> None:
    chunks = build_chunks(manifest, blocks)
    table_chunks = [chunk for chunk in chunks if chunk.content_type == "table"]
    assert len(table_chunks) == 1
    assert "기술평가" in table_chunks[0].content
    assert table_chunks[0].page == 3


def test_chunk_has_source_metadata(manifest, blocks) -> None:
    chunk = build_chunks(manifest, blocks)[0]
    assert chunk.document_id == manifest.document_id
    assert str(chunk.source_url) == str(manifest.source_url)
