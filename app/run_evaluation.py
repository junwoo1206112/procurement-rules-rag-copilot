from __future__ import annotations

import json
import argparse
import platform
from pathlib import Path

from app.answering import OllamaAnswerer
from app.evaluation import corpus_sha256, evaluate, load_evaluation_set
from app.live_evaluation import render_live_report, run_live_evaluation, write_live_evaluation
from app.schemas import DocumentChunk

MEASUREMENT_VERSION = "v4.0"


def render_report(root: Path, version: str, corpus_hash: str, chunks: list[DocumentChunk], questions: list, reports: list[dict[str, object]], latency_mode: str) -> None:
    lines = [
        "# 검색·답변 품질 평가 리포트", "", f"- 데이터셋 버전: `{version}`", f"- 코퍼스 SHA-256: `{corpus_hash}`",
        f"- 코퍼스: 법령·용역 공고·공개 첨부자료, {len(chunks)}개 청크", f"- 질의: {len(questions)}개",
        f"- 실행 환경: Python {platform.python_version()} / {platform.platform()}", f"- 지연시간 측정: {latency_mode}",
        "", "| 구성 | Recall@5 | MRR | nDCG | Citation P/R | 선택 근거 Recall | 보류율 | p50/p95 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for report in reports:
        lines.append(
            f"| {report['mode']} | {report['recall_at_5']:.4f} | {report['mrr']:.4f} | {report['ndcg']:.4f} | "
            f"{report['citation_precision']:.4f}/{report['citation_recall']:.4f} | {report['selected_evidence_recall']:.4f} | "
            f"{report['unanswerable_hold_rate']:.4f} | {report['p50_latency_ms']:.3f}/{report['p95_latency_ms']:.3f} |"
        )
    lines.extend(["", "## 답변 상태", "", "| 구성 | 측정 방식 | grounded | grounded_demo | insufficient_evidence |", "| --- | --- | ---: | ---: | ---: |"])
    for report in reports:
        counts = report["answer_status_counts"]
        rates = report["answer_status_rates"]
        lines.append(
            f"| {report['mode']} | {report['answer_status_measurement']} | "
            f"{counts['grounded']} ({rates['grounded']:.4f}) | {counts['grounded_demo']} ({rates['grounded_demo']:.4f}) | "
            f"{counts['insufficient_evidence']} ({rates['insufficient_evidence']:.4f}) |"
        )
    lines.extend(["", "## 실패 사례", ""])
    for report in reports:
        examples = report.get("selection_failure_examples", [])
        lines.append(f"- `{report['mode']}`: " + (", ".join(f"[{item['question_id']}](../data/evaluation-set.json)" for item in examples) if examples else "선택 근거 실패 없음"))
    default_report = next((report for report in reports if report["mode"] == "lexical_hybrid"), None)
    lines.extend(["", "## 해석과 한계", ""])
    if default_report:
        lines.append(f"- CPU 데모 기본값은 `lexical_hybrid`이며, 이 실행의 Recall@5는 `{default_report['recall_at_5']:.4f}`입니다. 다른 구성은 같은 조건의 품질·지연시간을 비교한 뒤에만 기본값으로 채택할 수 있습니다.")
    lines.extend([
        "- `deterministic_evidence_contract`의 `grounded`는 실제 LLM 문장 품질이 아니라 선택 근거·인용 검증이 가능한 상태를 뜻한다. 실제 Ollama 생성 결과는 `--live-llm`으로 별도 JSON·리포트에 기록하며, 두 지표를 합산하지 않는다.",
        "- `tf_cosine`은 토큰 기반 cosine 기준선이며 실제 임베딩 Dense 검색이 아니다.",
        "- 정답 라벨은 수집된 조항의 문서·조항 메타데이터에서 생성한 검색 회귀 테스트용이다. 법률 해석 정확도를 측정하지 않는다.",
        "- 임베딩 모델의 최초 로드·코퍼스 색인 비용은 표의 단건 검색 지연시간에 포함하지 않는다.",
    ])
    (root / "docs" / "evaluation-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-embedding", action="store_true")
    parser.add_argument("--mode", choices=("tf_cosine", "hybrid", "hybrid_rerank", "embedding", "lexical_hybrid"), help="한 구성만 실행해 결과를 체크포인트에 저장합니다.")
    parser.add_argument("--single-query-latency", action="store_true", help="배치가 아닌 단건 검색의 p50/p95 지연시간을 측정합니다.")
    parser.add_argument("--answer-status-mode", choices=("deterministic", "ollama"), default="deterministic", help="답변 상태를 결정론적 근거 계약 또는 실제 Ollama로 측정합니다.")
    parser.add_argument("--live-llm", action="store_true", help="실제 Ollama 생성·인용 결과를 별도 산출물로 평가합니다.")
    parser.add_argument("--live-limit", type=int, help="실제 LLM 평가에 포함할 앞쪽 질의 수입니다.")
    parser.add_argument("--live-question-id", action="append", default=[], help="실제 LLM 평가에 포함할 질문 ID입니다. 여러 번 지정할 수 있습니다.")
    parser.add_argument("--live-resume", action="store_true", help="동일한 코퍼스·모델·검색 구성의 기존 실제 LLM 평가 결과를 이어 실행합니다.")
    parser.add_argument("--live-overwrite", action="store_true", help="기존 실제 LLM 평가 결과를 명시적으로 덮어씁니다.")
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    chunks = [DocumentChunk.model_validate(item) for name in ("collected-chunks.json", "g2b-service-chunks.json", "g2b-rfp-chunks.json") for item in json.loads((root / "data" / name).read_text(encoding="utf-8"))]
    version, questions = load_evaluation_set(root / "data" / "evaluation-set.json", chunks)
    corpus_hash = corpus_sha256(chunks)
    if args.live_llm:
        selected_questions = questions
        if args.live_question_id:
            requested = set(args.live_question_id)
            selected_questions = [item for item in questions if item.question_id in requested]
            missing = requested - {item.question_id for item in selected_questions}
            if missing:
                parser.error(f"평가 세트에 없는 질문 ID입니다: {', '.join(sorted(missing))}")
        if args.live_limit is not None:
            if args.live_limit < 1:
                parser.error("--live-limit은 1 이상이어야 합니다.")
            selected_questions = selected_questions[:args.live_limit]
        if not selected_questions:
            parser.error("실제 LLM 평가에 포함할 질의가 없습니다.")
        output_path = root / "data" / "live-llm-evaluation-results.json"
        live_mode = args.mode or "lexical_hybrid"
        existing_records = None
        if output_path.exists() and not args.live_overwrite:
            if not args.live_resume:
                parser.error("기존 실제 LLM 평가 결과가 있습니다. 이어 실행하려면 --live-resume, 새로 실행하려면 --live-overwrite를 사용하세요.")
            previous = json.loads(output_path.read_text(encoding="utf-8"))
            previous_metadata = previous.get("metadata", {})
            expected_metadata = {"dataset_version": version, "corpus_sha256": corpus_hash, "retrieval_mode": live_mode, "model": OllamaAnswerer().model}
            mismatched = [key for key, value in expected_metadata.items() if previous_metadata.get(key) != value]
            if mismatched:
                parser.error(f"기존 결과의 재현 조건이 달라 이어 실행할 수 없습니다: {', '.join(mismatched)}. --live-overwrite를 사용하세요.")
            existing_records = previous.get("records", [])
        live_result = run_live_evaluation(
            chunks, selected_questions, mode=live_mode, dataset_version=version, existing_records=existing_records,
            on_progress=lambda partial: write_live_evaluation(output_path, partial),
        )
        write_live_evaluation(output_path, live_result)
        render_live_report(root / "docs" / "live-llm-evaluation-report.md", live_result)
        print(json.dumps(live_result["summary"], ensure_ascii=False, indent=2))
        return
    modes = (args.mode,) if args.mode else ("lexical_hybrid", "tf_cosine", "hybrid", "hybrid_rerank") + (("embedding",) if args.include_embedding else ())
    answerer = OllamaAnswerer() if args.answer_status_mode == "ollama" else None
    resolver = (lambda question, hits: answerer.answer(question, hits).status) if answerer else None
    reports = [evaluate(chunks, questions, mode=mode, batch_queries=not args.single_query_latency, answer_status_resolver=resolver) for mode in modes]
    checkpoint_path = root / "data" / "evaluation-results.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {}
    if checkpoint.get("dataset_version") != version or checkpoint.get("measurement_version") != MEASUREMENT_VERSION or checkpoint.get("corpus_sha256") != corpus_hash:
        checkpoint = {"dataset_version": version, "measurement_version": MEASUREMENT_VERSION, "corpus_sha256": corpus_hash, "answer_status_mode": args.answer_status_mode, "reports": {}}
    checkpoint["reports"].update({report["mode"]: report for report in reports})
    checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
    required_modes = ("lexical_hybrid", "tf_cosine", "hybrid", "hybrid_rerank")
    if not all(mode in checkpoint["reports"] for mode in required_modes):
        print(json.dumps({"saved_modes": sorted(checkpoint["reports"]), "waiting_for": [mode for mode in required_modes if mode not in checkpoint["reports"]]}, ensure_ascii=False))
        return
    report_modes = required_modes + (("embedding",) if "embedding" in checkpoint["reports"] else ())
    reports = [checkpoint["reports"][mode] for mode in report_modes]
    latency_mode = "단건 검색" if args.single_query_latency else "배치 평가(질문당 평균)"
    render_report(root, version, corpus_hash, chunks, questions, reports, latency_mode)
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
