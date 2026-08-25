from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Protocol

from app.answering import AnswerExecutionTrace, OllamaAnswerer
from app.evaluation import EvaluationQuestion, corpus_sha256
from app.retrieval import HybridRetriever
from app.schemas import AnswerResponse, DocumentChunk, SearchFilters


class TracedAnswerer(Protocol):
    model: str

    def answer_with_trace(self, question: str, hits: list) -> tuple[AnswerResponse, AnswerExecutionTrace]: ...


@dataclass(frozen=True)
class LiveEvaluationRecord:
    question_id: str
    question: str
    question_type: str
    answerable: bool
    answer_status: str
    answer_text: str | None
    selected_chunk_ids: list[str]
    citation_chunk_ids: list[str]
    expected_chunk_ids: list[str]
    citation_matches_expected: bool | None
    hold_is_appropriate: bool | None
    manual_review_required: bool
    execution_status: str


def _safe_answer_text(response: AnswerResponse) -> str | None:
    """원문 발췌(grounded_demo)의 코퍼스 본문을 live 결과에 중복 저장하지 않는다."""
    return response.answer if response.status == "grounded" else None


def record_live_answer(question: EvaluationQuestion, response: AnswerResponse, trace: AnswerExecutionTrace) -> LiveEvaluationRecord:
    citations = [citation.chunk_id for citation in response.citations]
    expected = sorted(question.expected_chunk_ids)
    citation_matches = bool(set(citations) & question.expected_chunk_ids) if question.answerable else None
    hold_is_appropriate = (response.status == "insufficient_evidence" and not citations) if not question.answerable else None
    review_required = (
        response.status == "grounded_demo"
        or question.question_type == "문서 비교"
        or (question.answerable and not citation_matches)
    )
    return LiveEvaluationRecord(
        question_id=question.question_id,
        question=question.question,
        question_type=question.question_type,
        answerable=question.answerable,
        answer_status=response.status,
        answer_text=_safe_answer_text(response),
        selected_chunk_ids=trace.selected_chunk_ids,
        citation_chunk_ids=citations,
        expected_chunk_ids=expected,
        citation_matches_expected=citation_matches,
        hold_is_appropriate=hold_is_appropriate,
        manual_review_required=review_required,
        execution_status=trace.execution_status,
    )


def summarize_live_records(records: list[LiveEvaluationRecord]) -> dict[str, int | float]:
    execution_failures = [item for item in records if item.execution_status in {"model_unavailable", "timeout", "runner_error"}]
    completed = [item for item in records if item not in execution_failures]
    answerable_completed = [item for item in completed if item.answerable]
    unanswerable_completed = [item for item in completed if not item.answerable]
    citation_matches = sum(item.citation_matches_expected is True for item in answerable_completed)
    appropriate_holds = sum(item.hold_is_appropriate is True for item in unanswerable_completed)
    return {
        "question_count": len(records),
        "completed_execution_count": len(completed),
        "execution_failure_count": len(execution_failures),
        "answerable_completed_count": len(answerable_completed),
        "unanswerable_completed_count": len(unanswerable_completed),
        "citation_expected_match_count": citation_matches,
        "citation_expected_match_rate": round(citation_matches / max(len(answerable_completed), 1), 4),
        "appropriate_hold_count": appropriate_holds,
        "appropriate_hold_rate": round(appropriate_holds / max(len(unanswerable_completed), 1), 4),
        "grounded_demo_count": sum(item.answer_status == "grounded_demo" for item in completed),
        "manual_review_required_count": sum(item.manual_review_required for item in completed),
    }


def run_live_evaluation(
    chunks: list[DocumentChunk], questions: list[EvaluationQuestion], *, mode: str = "lexical_hybrid",
    answerer: TracedAnswerer | None = None, dataset_version: str = "unknown",
    existing_records: list[dict[str, object]] | None = None,
    on_progress: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    active_answerer = answerer or OllamaAnswerer()
    retriever = HybridRetriever(chunks)
    records = [LiveEvaluationRecord(**item) for item in (existing_records or [])]
    completed_ids = {item.question_id for item in records}
    metadata = {
        "measurement_type": "live_llm_grounding_review",
        "dataset_version": dataset_version,
        "corpus_sha256": corpus_sha256(chunks),
        "model": active_answerer.model,
        "executed_at": datetime.now(UTC).isoformat(),
        "retrieval_mode": mode,
    }

    def result() -> dict[str, object]:
        return {"metadata": metadata, "summary": summarize_live_records(records), "records": [asdict(item) for item in records]}

    for item in questions:
        if item.question_id in completed_ids:
            continue
        hits = retriever.search(item.question, SearchFilters(), top_k=5, mode=mode)
        try:
            response, trace = active_answerer.answer_with_trace(item.question, hits)
            records.append(record_live_answer(item, response, trace))
        except (OSError, TimeoutError, ValueError, TypeError) as exc:
            records.append(LiveEvaluationRecord(
                question_id=item.question_id, question=item.question, question_type=item.question_type,
                answerable=item.answerable, answer_status="execution_failure", answer_text=None,
                selected_chunk_ids=[], citation_chunk_ids=[], expected_chunk_ids=sorted(item.expected_chunk_ids),
                citation_matches_expected=None, hold_is_appropriate=None, manual_review_required=False,
                execution_status="timeout" if isinstance(exc, TimeoutError) else "runner_error",
            ))
        completed_ids.add(item.question_id)
        if on_progress:
            on_progress(result())
    return result()


def write_live_evaluation(path: Path, result: dict[str, object]) -> None:
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_live_report(path: Path, result: dict[str, object]) -> None:
    metadata = result["metadata"]
    summary = result["summary"]
    records = result["records"]
    lines = [
        "# 실제 LLM 근거·인용 평가 리포트", "",
        f"- 측정 유형: `{metadata['measurement_type']}`",
        f"- 데이터셋 버전: `{metadata['dataset_version']}`",
        f"- 코퍼스 SHA-256: `{metadata['corpus_sha256']}`",
        f"- 모델: `{metadata['model']}`",
        f"- 실행 시각(UTC): `{metadata['executed_at']}`",
        f"- 검색 구성: `{metadata['retrieval_mode']}`", "",
        "## 실행·자동 검토 집계", "",
        "| 항목 | 값 | 분모 |", "| --- | ---: | ---: |",
        f"| 전체 질의 | {summary['question_count']} | 전체 |",
        f"| 완료 실행 | {summary['completed_execution_count']} | 전체 |",
        f"| 인프라 실패 | {summary['execution_failure_count']} | 전체 |",
        f"| 인용 정답 근거 일치 | {summary['citation_expected_match_count']} ({summary['citation_expected_match_rate']:.4f}) | 완료된 답변 가능 질의 {summary['answerable_completed_count']} |",
        f"| 안전 보류 적절 | {summary['appropriate_hold_count']} ({summary['appropriate_hold_rate']:.4f}) | 완료된 답변 불가 질의 {summary['unanswerable_completed_count']} |",
        f"| grounded_demo | {summary['grounded_demo_count']} | 완료 실행 |",
        f"| 사람 검토 필요 | {summary['manual_review_required_count']} | 완료 실행 |", "",
        "## 우선 검토 사례", "",
    ]
    review_records = [item for item in records if item["manual_review_required"]]
    if review_records:
        for item in review_records:
            lines.append(
                f"- `{item['question_id']}` ({item['question_type']}): status={item['answer_status']}, "
                f"execution={item['execution_status']}, citation_expected_match={item['citation_matches_expected']}"
            )
    else:
        lines.append("- 자동 기준에서 우선 검토 대상으로 분류된 사례가 없습니다.")
    lines.extend([
        "", "## 해석 한계", "",
        "- 이 리포트의 인용 정답 근거 일치는 반환 citation ID와 고정 평가 라벨의 교집합을 보는 자동 지표입니다.",
        "- 생성 문장이 근거를 정확히 요약했는지와 법률 해석의 정확성은 자동 판정하지 않으며, 우선 검토 사례에서 사람이 확인해야 합니다.",
        "- 모델·인프라 실패는 생성 품질 성공률의 분모에서 제외하고 별도로 기록합니다.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
