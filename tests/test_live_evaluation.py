import json
import sys

from app.answering import AnswerExecutionTrace, citations_for
from app.chunking import build_chunks
from app.evaluation import EvaluationQuestion
from app.live_evaluation import (
    LiveEvaluationRecord,
    record_live_answer,
    render_live_report,
    run_live_evaluation,
    summarize_live_records,
    write_live_evaluation,
)
from app.retrieval import HybridRetriever
from app.schemas import AnswerResponse, SearchFilters


class FakeAnswerer:
    model = "fake-local-model"

    def answer_with_trace(self, question, hits):
        if "없는" in question:
            return (
                AnswerResponse(status="insufficient_evidence", answer="근거 없음", citations=[], retrieval=hits),
                AnswerExecutionTrace([], None, "not_called_no_evidence"),
            )
        selected = [hits[0]]
        return (
            AnswerResponse(status="grounded", answer="근거 기반 답변", citations=citations_for(selected), retrieval=hits, model_used=self.model),
            AnswerExecutionTrace([hits[0].chunk.chunk_id], "prompt-hash", "completed"),
        )


class FailingAnswerer:
    model = "fake-local-model"

    def answer_with_trace(self, question, hits):
        raise OSError("ollama unavailable")


def test_live_record_does_not_store_grounded_demo_source_text(manifest, blocks) -> None:
    hit = HybridRetriever(build_chunks(manifest, blocks)).search("제출 서류", SearchFilters())[0]
    response = AnswerResponse(status="grounded_demo", answer="검증된 원문 발췌입니다. 매우 긴 원문", citations=citations_for([hit]), retrieval=[hit])
    question = EvaluationQuestion("q-1", "제출 서류", {hit.chunk.chunk_id}, manifest.document_id, question_type="제출서류")
    record = record_live_answer(question, response, AnswerExecutionTrace([hit.chunk.chunk_id], "prompt-hash", "invalid_model_payload"))
    assert record.answer_text is None
    assert record.manual_review_required is True


def test_live_record_flags_grounded_answer_with_wrong_expected_citation(manifest, blocks) -> None:
    hit = HybridRetriever(build_chunks(manifest, blocks)).search("제출 서류", SearchFilters())[0]
    response = AnswerResponse(status="grounded", answer="근거 기반 답변", citations=citations_for([hit]), retrieval=[hit])
    question = EvaluationQuestion("q-1", "제출 서류", {"different-expected-chunk"}, manifest.document_id, question_type="제출서류")
    record = record_live_answer(question, response, AnswerExecutionTrace([hit.chunk.chunk_id], "prompt-hash", "completed"))
    assert record.citation_matches_expected is False
    assert record.manual_review_required is True


def test_live_summary_excludes_infrastructure_failures_from_quality_denominators() -> None:
    records = [
        LiveEvaluationRecord("ok", "질문", "제출서류", True, "grounded", "답", ["a"], ["a"], ["a"], True, None, False, "completed"),
        LiveEvaluationRecord("down", "질문", "제출서류", True, "grounded_demo", None, ["a"], ["a"], ["a"], True, None, True, "model_unavailable"),
        LiveEvaluationRecord("hold", "없는 질문", "답변 불가", False, "insufficient_evidence", None, [], [], [], None, True, False, "not_called_no_evidence"),
    ]
    summary = summarize_live_records(records)
    assert summary["completed_execution_count"] == 2
    assert summary["execution_failure_count"] == 1
    assert summary["citation_expected_match_rate"] == 1.0
    assert summary["appropriate_hold_rate"] == 1.0


def test_live_evaluation_writes_separate_reviewable_artifacts(tmp_path, manifest, blocks) -> None:
    chunks = build_chunks(manifest, blocks)
    questions = [
        EvaluationQuestion("q-1", "제출 서류", {chunks[1].chunk_id}, manifest.document_id, question_type="제출서류"),
        EvaluationQuestion("q-2", "없는 조건", set(), manifest.document_id, answerable=False, question_type="답변 불가"),
    ]
    result = run_live_evaluation(chunks, questions, answerer=FakeAnswerer(), dataset_version="test-v1")
    json_path = tmp_path / "live-results.json"
    report_path = tmp_path / "live-report.md"
    write_live_evaluation(json_path, result)
    render_live_report(report_path, result)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["measurement_type"] == "live_llm_grounding_review"
    assert payload["metadata"]["dataset_version"] == "test-v1"
    assert "SERVICE_KEY" not in json_path.read_text(encoding="utf-8")
    report = report_path.read_text(encoding="utf-8")
    assert "인용 정답 근거 일치" in report
    assert "법률 해석의 정확성은 자동 판정하지 않으며" in report


def test_live_evaluation_checkpoints_and_resumes_without_replaying_records(manifest, blocks) -> None:
    chunks = build_chunks(manifest, blocks)
    questions = [
        EvaluationQuestion("q-1", "제출 서류", {chunks[1].chunk_id}, manifest.document_id, question_type="제출서류"),
        EvaluationQuestion("q-2", "없는 조건", set(), manifest.document_id, answerable=False, question_type="답변 불가"),
    ]
    checkpoints = []
    first = run_live_evaluation(chunks, questions[:1], answerer=FakeAnswerer(), dataset_version="test-v1", on_progress=checkpoints.append)
    resumed = run_live_evaluation(chunks, questions, answerer=FakeAnswerer(), dataset_version="test-v1", existing_records=first["records"], on_progress=checkpoints.append)
    assert [item["question_id"] for item in resumed["records"]] == ["q-1", "q-2"]
    assert len(checkpoints) == 2


def test_live_evaluation_separates_runner_failure_from_quality_metrics(manifest, blocks) -> None:
    chunks = build_chunks(manifest, blocks)
    question = EvaluationQuestion("q-1", "제출 서류", {chunks[1].chunk_id}, manifest.document_id, question_type="제출서류")
    result = run_live_evaluation(chunks, [question], answerer=FailingAnswerer(), dataset_version="test-v1")
    assert result["summary"]["execution_failure_count"] == 1
    assert result["summary"]["answerable_completed_count"] == 0
    assert result["records"][0]["execution_status"] == "runner_error"


def test_live_cli_uses_separate_checkpoint_without_changing_deterministic_results(tmp_path, monkeypatch) -> None:
    import app.run_evaluation as runner

    source_root = __import__("pathlib").Path(runner.__file__).parents[1]
    project_root = tmp_path / "project"
    (project_root / "app").mkdir(parents=True)
    (project_root / "data").mkdir()
    (project_root / "docs").mkdir()
    sample_chunk = json.loads((source_root / "data" / "g2b-rfp-chunks.json").read_text(encoding="utf-8"))[0]
    for filename in ("collected-chunks.json", "g2b-service-chunks.json", "g2b-rfp-chunks.json"):
        (project_root / "data" / filename).write_text(json.dumps([sample_chunk], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "load_evaluation_set",
        lambda _path, chunks: (
            "test-v1",
            [EvaluationQuestion("q-1", "제출 서류", {chunks[0].chunk_id}, chunks[0].document_id, question_type="제출서류")],
        ),
    )
    deterministic_path = project_root / "data" / "evaluation-results.json"
    deterministic_path.write_text('{"deterministic": true}\n', encoding="utf-8")
    monkeypatch.setattr(runner, "__file__", str(project_root / "app" / "run_evaluation.py"))
    monkeypatch.setattr(runner, "run_live_evaluation", lambda chunks, questions, **kwargs: run_live_evaluation(chunks, questions, answerer=FakeAnswerer(), dataset_version=kwargs["dataset_version"]))
    monkeypatch.setattr(sys, "argv", ["run_evaluation.py", "--live-llm", "--live-limit", "1"])

    runner.main()

    assert deterministic_path.read_text(encoding="utf-8") == '{"deterministic": true}\n'
    assert (project_root / "data" / "live-llm-evaluation-results.json").exists()
    assert (project_root / "docs" / "live-llm-evaluation-report.md").exists()
