from __future__ import annotations

import json
import math
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Callable

from app.answering import select_answer_evidence
from app.retrieval import HybridRetriever
from app.schemas import DocumentChunk, SearchFilters


@dataclass(frozen=True)
class EvaluationQuestion:
    question_id: str
    question: str
    expected_chunk_ids: set[str]
    split_document_id: str
    answerable: bool = True
    question_type: str = "조항 조회"


REQUIRED_QUESTION_TYPES = {"참가자격", "일정", "제출서류", "평가기준", "문서 비교", "답변 불가"}


def validate_evaluation_questions(questions: list[EvaluationQuestion]) -> None:
    missing = REQUIRED_QUESTION_TYPES - {item.question_type for item in questions}
    if missing:
        raise ValueError(f"평가 세트에 필수 질의 유형이 없습니다: {', '.join(sorted(missing))}")
    if len({item.question_id for item in questions}) != len(questions):
        raise ValueError("평가 질의 ID는 중복될 수 없습니다.")
    for item in questions:
        if not item.split_document_id:
            raise ValueError("문서 또는 공고 단위 split_document_id가 필요합니다.")
        if item.answerable and not item.expected_chunk_ids:
            raise ValueError("답변 가능한 질의에는 정답 근거 청크가 필요합니다.")
        if item.question_type == "문서 비교" and len(item.expected_chunk_ids) < 2:
            raise ValueError("문서 비교 질의에는 두 개 이상의 정답 근거가 필요합니다.")


def corpus_sha256(chunks: list[DocumentChunk]) -> str:
    stable = [{"chunk_id": c.chunk_id, "content": c.content, "section": c.section} for c in chunks]
    return sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def load_evaluation_set(path: Path, chunks: list[DocumentChunk]) -> tuple[str, list[EvaluationQuestion]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["corpus_sha256"] != corpus_sha256(chunks):
        raise ValueError("평가 세트와 수집 코퍼스 버전이 다릅니다.")
    questions = [EvaluationQuestion(
        item["question_id"], item["question"], set(item["expected_chunk_ids"]), item["split_document_id"],
        item["answerable"], item["question_type"],
    ) for item in payload["questions"]]
    validate_evaluation_questions(questions)
    return payload["dataset_version"], questions


def _mrr(ids: list[str], expected: set[str]) -> float:
    return next((1 / index for index, item in enumerate(ids, 1) if item in expected), 0.0)


def _ndcg(ids: list[str], expected: set[str], k: int) -> float:
    dcg = sum(1 / math.log2(index + 2) for index, item in enumerate(ids[:k]) if item in expected)
    ideal = sum(1 / math.log2(index + 2) for index in range(min(len(expected), k)))
    return dcg / ideal if ideal else 1.0


AnswerStatusResolver = Callable[[str, list], str]


def _deterministic_answer_status(question: str, hits: list) -> str:
    """모델을 호출하지 않는 회귀 평가용 상태 판정이다.

    `grounded`는 실제 LLM 문장 품질이 아니라 선택된 근거가 인용형 답변을
    생성할 수 있는지 검증했다는 뜻이다. 실제 모델 평가는 resolver를 주입한다.
    """
    return "grounded" if select_answer_evidence(question, hits).hits else "insufficient_evidence"


def evaluate(
    chunks: list[DocumentChunk], questions: list[EvaluationQuestion], top_k: int = 5,
    mode: str = "hybrid_rerank", batch_queries: bool = True,
    answer_status_resolver: AnswerStatusResolver | None = None,
) -> dict[str, object]:
    retriever = HybridRetriever(chunks)
    recall: list[float] = []; mrr: list[float] = []; ndcg: list[float] = []; precision: list[float] = []; citation_recall: list[float] = []; latency: list[float] = []
    answerable = [item for item in questions if item.answerable]; held = 0; failures: list[dict[str, str]] = []
    selection_failures: list[dict[str, str]] = []
    answer_status_counts = {"grounded": 0, "grounded_demo": 0, "insufficient_evidence": 0}
    resolver = answer_status_resolver or _deterministic_answer_status
    if batch_queries:
        started = perf_counter()
        grouped_hits = retriever.search_many([item.question for item in questions], SearchFilters(), top_k, mode=mode)
        average_latency = (perf_counter() - started) * 1000 / max(len(questions), 1)
        timed_hits = [(item, hits, average_latency) for item, hits in zip(questions, grouped_hits)]
    else:
        timed_hits = []
        for item in questions:
            started = perf_counter()
            hits = retriever.search(item.question, SearchFilters(), top_k, mode=mode)
            timed_hits.append((item, hits, (perf_counter() - started) * 1000))
    for item, hits, elapsed in timed_hits:
        latency.append(elapsed)
        ids = [hit.chunk.chunk_id for hit in hits]
        selected = select_answer_evidence(item.question, hits)
        cited = [hit.chunk.chunk_id for hit in selected.hits]
        status = resolver(item.question, hits)
        if status not in answer_status_counts:
            raise ValueError(f"지원하지 않는 답변 상태입니다: {status}")
        answer_status_counts[status] += 1
        if not item.answerable:
            held += int(status == "insufficient_evidence"); continue
        retrieval_overlap = set(ids) & item.expected_chunk_ids
        citation_overlap = set(cited) & item.expected_chunk_ids
        recall.append(float(bool(retrieval_overlap))); mrr.append(_mrr(ids, item.expected_chunk_ids)); ndcg.append(_ndcg(ids, item.expected_chunk_ids, top_k))
        precision.append(len(citation_overlap) / len(cited) if cited else 0.0); citation_recall.append(len(citation_overlap) / len(item.expected_chunk_ids))
        if not retrieval_overlap:
            failures.append({"question_id": item.question_id, "question": item.question, "expected_document": item.split_document_id})
        if not citation_overlap:
            selection_failures.append({"question_id": item.question_id, "question": item.question, "expected_document": item.split_document_id})
    ordered = sorted(latency); p95 = ordered[min(len(ordered) - 1, math.ceil(len(ordered) * .95) - 1)] if ordered else 0
    average = lambda values: round(sum(values) / max(len(values), 1), 4)
    return {
        "mode": mode,
        "question_count": len(questions),
        "answerable_question_count": len(answerable),
        "unanswerable_question_count": len(questions) - len(answerable),
        f"recall_at_{top_k}": average(recall), "mrr": average(mrr), "ndcg": average(ndcg),
        "citation_precision": average(precision), "citation_recall": average(citation_recall),
        "selected_evidence_recall": average([
            float(bool({hit.chunk.chunk_id for hit in select_answer_evidence(item.question, hits).hits} & item.expected_chunk_ids))
            for item, hits, _ in timed_hits if item.answerable
        ]),
        "answer_status_measurement": "resolver" if answer_status_resolver else "deterministic_evidence_contract",
        "answer_status_counts": answer_status_counts,
        "answer_status_rates": {key: round(value / max(len(questions), 1), 4) for key, value in answer_status_counts.items()},
        "unanswerable_hold_rate": round(held / max(len(questions) - len(answerable), 1), 4),
        "p50_latency_ms": round(median(ordered), 3) if ordered else 0,
        "p95_latency_ms": round(p95, 3),
        "failure_examples": failures[:5],
        "selection_failure_examples": selection_failures[:5],
    }
