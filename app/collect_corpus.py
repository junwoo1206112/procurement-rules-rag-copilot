from __future__ import annotations

import json
import argparse
from pathlib import Path

from app.chunking import build_chunks
from app.ingestion import ManifestRegistry
from app.source_loader import fetch_verified_admin_rule_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    records = ManifestRegistry.from_json(root / "data" / "procurement-rules-manifest.json").eligible()
    selected = records[args.offset:args.offset + args.limit]
    report_path = root / "data" / "collection-report.json"
    chunks_path = root / "data" / "collected-chunks.json"
    previous = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"successes": [], "failures": []}
    saved_chunks = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path.exists() else []
    completed = {item["document_id"] for item in previous["successes"]}
    successes, failures = [], []
    for manifest in selected:
        if manifest.document_id in completed and not args.refresh:
            continue
        try:
            receipt = fetch_verified_admin_rule_json(manifest)
            chunks = build_chunks(manifest, receipt.blocks)
            successes.append({"document_id": manifest.document_id, "chunk_count": len(chunks), "sha256": receipt.sha256})
            saved_chunks = [item for item in saved_chunks if item["document_id"] != manifest.document_id] + [item.model_dump(mode="json") for item in chunks]
        except Exception as exc:
            failures.append({"document_id": manifest.document_id, "error": type(exc).__name__})
    success_by_id = {item["document_id"]: item for item in previous["successes"]}
    success_by_id.update({item["document_id"]: item for item in successes})
    report = {"requested": len(records), "successes": list(success_by_id.values()), "failures": previous["failures"] + failures}
    report["total_chunks"] = sum(item["chunk_count"] for item in report["successes"])
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    chunks_path.write_text(json.dumps(saved_chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"batch_requested": len(selected), "success": len(successes), "failed": len(failures), "total_success": len(report["successes"]), "total_chunks": report["total_chunks"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
