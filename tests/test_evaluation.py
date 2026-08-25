from app.chunking import build_chunks
import pytest

from app.evaluation import EvaluationQuestion, evaluate, validate_evaluation_questions
from app.run_evaluation import render_report
from app.retrieval import HybridRetriever


def test_evaluation_reports_retrieval_metrics(manifest, blocks) -> None:
    chunks = build_chunks(manifest, blocks)
    report = evaluate(chunks, [EvaluationQuestion("q-1", "제출 서류", {chunks[1].chunk_id}, manifest.document_id)], mode="lexical_hybrid")
    assert report["recall_at_5"] == 1.0
    assert report["mrr"] > 0
    assert report["p50_latency_ms"] >= 0


def test_evaluation_compares_named_retrieval_modes(monkeypatch, manifest, blocks) -> None:
    chunks = build_chunks(manifest, blocks)
    question = EvaluationQuestion("q-1", "\uc81c\uc548\uc11c", {chunks[1].chunk_id}, manifest.document_id)

    def fake_embedding_scores(self, question, candidates, query_embedding=None):
        return {index: 1.0 for index in candidates}

    monkeypatch.setattr(HybridRetriever, "_embedding_scores", fake_embedding_scores)
    reports = [evaluate(chunks, [question], mode=mode, batch_queries=False) for mode in ("tf_cosine", "lexical_hybrid", "hybrid_rerank", "embedding")]
    assert [report["mode"] for report in reports] == ["tf_cosine", "lexical_hybrid", "hybrid_rerank", "embedding"]
    assert all("citation_precision" in report and "p95_latency_ms" in report and "answer_status_counts" in report for report in reports)


def test_evaluation_records_answer_statuses_and_selected_evidence(manifest, blocks) -> None:
    chunks = build_chunks(manifest, blocks)
    questions = [
        EvaluationQuestion("q-1", "\uc81c\ucd9c \uc11c\ub958", {chunks[1].chunk_id}, manifest.document_id, question_type="\uc81c\ucd9c\uc11c\ub958"),
        EvaluationQuestion("q-2", "\uc5c6\ub294 \uc870\uac74", set(), manifest.document_id, answerable=False, question_type="\ub2f5\ubcc0 \ubd88\uac00"),
    ]
    report = evaluate(chunks, questions, mode="lexical_hybrid", batch_queries=False)
    assert report["answer_status_measurement"] == "deterministic_evidence_contract"
    assert sum(report["answer_status_counts"].values()) == len(questions)
    assert report["selected_evidence_recall"] >= 0


def test_rendered_report_uses_result_fields(tmp_path, manifest, blocks) -> None:
    (tmp_path / "docs").mkdir()
    chunks = build_chunks(manifest, blocks)
    question = EvaluationQuestion("q-1", "\uc81c\ucd9c \uc11c\ub958", {chunks[1].chunk_id}, manifest.document_id, question_type="\uc81c\ucd9c\uc11c\ub958")
    report = evaluate(chunks, [question], mode="lexical_hybrid", batch_queries=False)
    render_report(tmp_path, "test-v1", "test-hash", chunks, [question], [report], "\ub2e8\uac74 \uac80\uc0c9")
    contents = (tmp_path / "docs" / "evaluation-report.md").read_text(encoding="utf-8")
    assert "test-v1" in contents
    assert "test-hash" in contents
    assert "deterministic_evidence_contract" in contents


def test_evaluation_set_rejects_missing_required_question_types() -> None:
    with pytest.raises(ValueError, match="필수 질의 유형"):
        validate_evaluation_questions([EvaluationQuestion("q-1", "제출", {"chunk-1"}, "document-1", question_type="제출서류")])
