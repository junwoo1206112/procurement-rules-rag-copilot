from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.evaluation import corpus_sha256
from app.schemas import DocumentChunk


def main() -> None:
    root = Path(__file__).parents[1]
    chunks = [DocumentChunk.model_validate(item) for name in ("collected-chunks.json", "g2b-service-chunks.json", "g2b-rfp-chunks.json") for item in json.loads((root / "data" / name).read_text(encoding="utf-8"))]
    def question_type(chunk: DocumentChunk) -> str:
        if "입찰참가자격" in chunk.document_title:
            return "참가자격"
        return {"일정": "일정", "계약·평가": "평가기준", "평가기준": "평가기준", "제출서류": "제출서류", "참가자격": "참가자격", "공고 개요": "공고 정보"}.get(chunk.section or "", "조항 조회")

    def first_by_document(candidates: list[DocumentChunk], limit: int) -> list[DocumentChunk]:
        selected: dict[str, DocumentChunk] = {}
        for chunk in candidates:
            if chunk.document_id not in selected:
                selected[chunk.document_id] = chunk
            if len(selected) == limit:
                break
        return list(selected.values())

    laws = first_by_document([chunk for chunk in chunks if chunk.document_id.startswith("pps-") and chunk.section], 30)
    notices = [
        *first_by_document([chunk for chunk in chunks if chunk.document_id.startswith("g2b-service-") and chunk.section == "공고 개요"], 10),
        *first_by_document([chunk for chunk in chunks if chunk.document_id.startswith("g2b-service-") and chunk.section == "일정"], 10),
        *first_by_document([chunk for chunk in chunks if chunk.document_id.startswith("g2b-service-") and chunk.section == "계약·평가"], 10),
    ]
    rfp = first_by_document([chunk for chunk in chunks if chunk.document_id.startswith("g2b-rfp-") and chunk.section], 10)
    selected = laws + notices + rfp
    questions = [{"question_id": f"evidence-{index:03d}", "question": f"{chunk.document_title}의 {chunk.section} 내용을 찾아줘", "question_type": question_type(chunk), "expected_chunk_ids": [candidate.chunk_id for candidate in chunks if candidate.document_id == chunk.document_id and candidate.section == chunk.section], "split_document_id": chunk.document_id, "answerable": True} for index, chunk in enumerate(selected, 1)]
    comparison = first_by_document([chunk for chunk in chunks if chunk.document_id.startswith("g2b-service-") and chunk.section == "공고 개요"], 2)
    questions.append({"question_id": f"evidence-{len(questions) + 1:03d}", "question": f"{comparison[0].document_title}와 {comparison[1].document_title}의 공고 기관을 비교해줘", "question_type": "문서 비교", "expected_chunk_ids": [chunk.chunk_id for chunk in comparison], "split_document_id": "comparison-g2b-notices", "answerable": True})
    questions.extend({"question_id": f"unanswerable-{index:03d}", "question": question, "question_type": "답변 불가", "expected_chunk_ids": [], "split_document_id": "unanswerable", "answerable": False} for index, question in enumerate(["초전도해파리쿠키의중력값은?", "제피로스항공항의구름색은?", "아르카디아화성기지의온도는?"], 1))
    output = {"dataset_version": "2026-08-20-v3", "created_at": datetime.now(UTC).isoformat(), "corpus_sha256": corpus_sha256(chunks), "questions": questions}
    (root / "data" / "evaluation-set.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"questions": len(questions), "answerable": len(questions) - 3}, ensure_ascii=False))


if __name__ == "__main__":
    main()
