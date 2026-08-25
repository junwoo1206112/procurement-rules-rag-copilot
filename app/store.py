from __future__ import annotations

from app.schemas import DocumentChunk, DocumentManifest


class InMemoryDocumentStore:
    def __init__(self) -> None:
        self.manifests: dict[str, DocumentManifest] = {}
        self.chunks: list[DocumentChunk] = []

    def add(self, manifest: DocumentManifest, chunks: list[DocumentChunk]) -> None:
        if not manifest.eligible_for_indexing:
            raise PermissionError(manifest.exclusion_reason or "색인 대상이 아닌 문서입니다.")
        self.manifests[manifest.document_id] = manifest
        self.chunks = [item for item in self.chunks if item.document_id != manifest.document_id] + chunks
