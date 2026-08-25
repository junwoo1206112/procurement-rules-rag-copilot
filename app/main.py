from __future__ import annotations

import json
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.answering import OllamaAnswerer
from app.chunking import build_chunks
from app.ingestion import ManifestRegistry
from app.parsers import ParsedBlock
from app.retrieval import HybridRetriever
from app.schemas import AnswerResponse, DocumentChunk, DocumentManifest, SearchRequest
from app.store import InMemoryDocumentStore
from app.source_loader import fetch_verified_admin_rule_json

app = FastAPI(title="Procurement RAG Copilot", version="0.1.0")
store = InMemoryDocumentStore()
STATIC_DIR = Path(__file__).parent / "static"
CURATED_MANIFEST = Path(__file__).parents[1] / "data" / "procurement-rules-manifest.json"
COLLECTED_CHUNKS = Path(__file__).parents[1] / "data" / "collected-chunks.json"
G2B_MANIFEST = Path(__file__).parents[1] / "data" / "g2b-service-manifest.json"
G2B_CHUNKS = Path(__file__).parents[1] / "data" / "g2b-service-chunks.json"
RFP_MANIFEST = Path(__file__).parents[1] / "data" / "g2b-rfp-manifest.json"
RFP_CHUNKS = Path(__file__).parents[1] / "data" / "g2b-rfp-chunks.json"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class IndexRequest(BaseModel):
    manifest: DocumentManifest
    blocks: list[ParsedBlock]


def load_collected_corpus(limit: int = 50) -> dict[str, int]:
    """Load only locally verified collector output; never accept browser-provided chunks."""
    if not COLLECTED_CHUNKS.exists():
        return {"documents": 0, "chunks": 0}
    registry = ManifestRegistry.from_json(CURATED_MANIFEST)
    allowed = {item.document_id: item for item in registry.eligible()[:limit]}
    grouped: dict[str, list] = {}
    for raw in json.loads(COLLECTED_CHUNKS.read_text(encoding="utf-8")):
        chunk = DocumentChunk.model_validate(raw)
        if chunk.document_id in allowed:
            grouped.setdefault(chunk.document_id, []).append(chunk)
    for document_id, chunks in grouped.items():
        store.add(allowed[document_id], chunks)
    return {"documents": len(grouped), "chunks": sum(len(chunks) for chunks in grouped.values())}


def load_g2b_corpus() -> dict[str, int]:
    if not G2B_MANIFEST.exists() or not G2B_CHUNKS.exists(): return {"documents": 0, "chunks": 0}
    manifests = {m.document_id: m for m in [DocumentManifest.model_validate(raw) for raw in json.loads(G2B_MANIFEST.read_text(encoding="utf-8"))]}
    grouped: dict[str, list[DocumentChunk]] = {}
    for raw in json.loads(G2B_CHUNKS.read_text(encoding="utf-8")):
        chunk = DocumentChunk.model_validate(raw); grouped.setdefault(chunk.document_id, []).append(chunk)
    for document_id, chunks in grouped.items(): store.add(manifests[document_id], chunks)
    return {"documents": len(grouped), "chunks": sum(map(len, grouped.values()))}


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "indexed_documents": len(store.manifests), "indexed_chunks": len(store.chunks)}


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/index")
def index_document(request: IndexRequest) -> dict[str, object]:
    if not request.manifest.eligible_for_indexing:
        raise HTTPException(status_code=422, detail=request.manifest.exclusion_reason or "공개 접근과 이용 조건을 확인한 문서만 색인할 수 있습니다.")
    chunks = build_chunks(request.manifest, request.blocks)
    store.add(request.manifest, chunks)
    return {"document_id": request.manifest.document_id, "chunk_count": len(chunks)}


@app.post("/api/load-curated")
def load_curated(limit: int = 30) -> dict[str, object]:
    if not 1 <= limit <= 50:
        raise HTTPException(status_code=422, detail="limit은 1~50 사이여야 합니다.")
    cached = load_collected_corpus(limit)
    if cached["documents"]:
        return {"loaded": [{"document_id": document_id, "chunk_count": len([chunk for chunk in store.chunks if chunk.document_id == document_id]), "source": "verified-cache"} for document_id in list(store.manifests)[:limit]], "failed": []}
    registry = ManifestRegistry.from_json(CURATED_MANIFEST)
    loaded, failed = [], []
    for manifest in registry.eligible()[:limit]:
        try:
            receipt = fetch_verified_admin_rule_json(manifest)
            chunks = build_chunks(manifest, receipt.blocks)
            store.add(manifest, chunks)
            loaded.append({"document_id": manifest.document_id, "chunk_count": len(chunks), "sha256": receipt.sha256, "collected_at": receipt.collected_at.isoformat()})
        except (OSError, UnicodeError, ValueError) as exc:
            failed.append({"document_id": manifest.document_id, "reason": str(exc)})
    return {"loaded": loaded, "failed": failed}


load_collected_corpus()
load_g2b_corpus()
if RFP_MANIFEST.exists() and RFP_CHUNKS.exists():
    G2B_MANIFEST, G2B_CHUNKS = RFP_MANIFEST, RFP_CHUNKS
    load_g2b_corpus()


@app.post("/api/ask", response_model=AnswerResponse)
def ask(request: SearchRequest) -> AnswerResponse:
    hits = HybridRetriever(store.chunks).search(request.question, request.filters, request.top_k, mode=os.getenv("RETRIEVAL_MODE", "lexical_hybrid"))
    return OllamaAnswerer().answer(request.question, hits)
