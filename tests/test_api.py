from fastapi.testclient import TestClient

from app.main import app, store
from app.source_loader import SourceReceipt


def test_index_then_answer(manifest, blocks) -> None:
    store.manifests.clear()
    store.chunks.clear()
    client = TestClient(app)
    indexed = client.post("/api/index", json={"manifest": manifest.model_dump(mode="json"), "blocks": [block.__dict__ for block in blocks]})
    assert indexed.status_code == 200
    answered = client.post("/api/ask", json={"question": "\uc81c\uc548\uc11c"})
    assert answered.status_code == 200
    assert answered.json()["status"] in {"grounded", "grounded_demo"}
    assert answered.json()["citations"]


def test_load_curated_indexes_verified_source(monkeypatch, blocks, tmp_path) -> None:
    from app import main
    from datetime import UTC, datetime

    store.manifests.clear()
    store.chunks.clear()
    monkeypatch.setattr(main, "COLLECTED_CHUNKS", tmp_path / "missing.json")
    monkeypatch.setattr(main, "fetch_verified_admin_rule_json", lambda manifest: SourceReceipt(manifest.document_id, datetime.now(UTC), "a" * 64, blocks))
    response = TestClient(app).post("/api/load-curated?limit=1")
    assert response.status_code == 200
    assert len(response.json()["loaded"]) == 1
    assert response.json()["loaded"][0]["sha256"] == "a" * 64


def test_load_collected_corpus_on_startup_path(monkeypatch, manifest, blocks, tmp_path) -> None:
    from app import main
    import json
    from app.chunking import build_chunks

    cache = tmp_path / "collected-chunks.json"
    cache.write_text(json.dumps([item.model_dump(mode="json") for item in build_chunks(manifest, blocks)], ensure_ascii=False), encoding="utf-8")
    store.manifests.clear()
    store.chunks.clear()
    monkeypatch.setattr(main, "COLLECTED_CHUNKS", cache)
    class _Registry:
        def eligible(self): return [manifest]
    monkeypatch.setattr(main.ManifestRegistry, "from_json", lambda _path: _Registry())
    assert main.load_collected_corpus() == {"documents": 1, "chunks": 3}
    assert len(store.chunks) == 3
