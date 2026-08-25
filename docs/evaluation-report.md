# 검색·답변 품질 평가 리포트

- 데이터셋 버전: `2026-08-20-v3`
- 코퍼스 SHA-256: `35540f23efd8375ff2b9ad5bdade402ebd1b182eabf029faa25ed1e7e5f7509e`
- 코퍼스: 법령·용역 공고·공개 첨부자료, 2289개 청크
- 질의: 72개
- 실행 환경: Python 3.12.10 / Windows-11-10.0.26200-SP0
- 지연시간 측정: 단건 검색

| 구성 | Recall@5 | MRR | nDCG | Citation P/R | 선택 근거 Recall | 보류율 | p50/p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| lexical_hybrid | 0.5362 | 0.3365 | 0.3708 | 0.2271/0.2319 | 0.2319 | 1.0000 | 123.761/164.516 |
| tf_cosine | 0.5362 | 0.3732 | 0.3903 | 0.1981/0.2029 | 0.2029 | 1.0000 | 123.460/162.562 |
| hybrid | 0.7391 | 0.5734 | 0.5930 | 0.2754/0.2428 | 0.2754 | 1.0000 | 40.543/44.354 |
| hybrid_rerank | 0.6377 | 0.4092 | 0.4569 | 0.2271/0.2319 | 0.2319 | 1.0000 | 42.110/49.732 |
| embedding | 0.7536 | 0.6679 | 0.6782 | 0.3043/0.2705 | 0.3043 | 1.0000 | 134.536/214.835 |

## 답변 상태

| 구성 | 측정 방식 | grounded | grounded_demo | insufficient_evidence |
| --- | --- | ---: | ---: | ---: |
| lexical_hybrid | deterministic_evidence_contract | 69 (0.9583) | 0 (0.0000) | 3 (0.0417) |
| tf_cosine | deterministic_evidence_contract | 69 (0.9583) | 0 (0.0000) | 3 (0.0417) |
| hybrid | deterministic_evidence_contract | 69 (0.9583) | 0 (0.0000) | 3 (0.0417) |
| hybrid_rerank | deterministic_evidence_contract | 69 (0.9583) | 0 (0.0000) | 3 (0.0417) |
| embedding | deterministic_evidence_contract | 69 (0.9583) | 0 (0.0000) | 3 (0.0417) |

## 실패 사례

- `lexical_hybrid`: [evidence-003](../data/evaluation-set.json), [evidence-004](../data/evaluation-set.json), [evidence-005](../data/evaluation-set.json), [evidence-006](../data/evaluation-set.json), [evidence-007](../data/evaluation-set.json)
- `tf_cosine`: [evidence-001](../data/evaluation-set.json), [evidence-003](../data/evaluation-set.json), [evidence-004](../data/evaluation-set.json), [evidence-005](../data/evaluation-set.json), [evidence-006](../data/evaluation-set.json)
- `hybrid`: [evidence-001](../data/evaluation-set.json), [evidence-003](../data/evaluation-set.json), [evidence-004](../data/evaluation-set.json), [evidence-005](../data/evaluation-set.json), [evidence-006](../data/evaluation-set.json)
- `hybrid_rerank`: [evidence-003](../data/evaluation-set.json), [evidence-004](../data/evaluation-set.json), [evidence-005](../data/evaluation-set.json), [evidence-006](../data/evaluation-set.json), [evidence-007](../data/evaluation-set.json)
- `embedding`: [evidence-001](../data/evaluation-set.json), [evidence-002](../data/evaluation-set.json), [evidence-003](../data/evaluation-set.json), [evidence-004](../data/evaluation-set.json), [evidence-005](../data/evaluation-set.json)

## 해석과 한계

- CPU 데모 기본값은 `lexical_hybrid`이며, 이 실행의 Recall@5는 `0.5362`입니다. 다른 구성은 같은 조건의 품질·지연시간을 비교한 뒤에만 기본값으로 채택할 수 있습니다.
- `deterministic_evidence_contract`의 `grounded`는 실제 LLM 문장 품질이 아니라 선택 근거·인용 검증이 가능한 상태를 뜻한다. 실제 Ollama 생성 결과는 `--live-llm`으로 별도 JSON·리포트에 기록하며, 두 지표를 합산하지 않는다.
- `tf_cosine`은 토큰 기반 cosine 기준선이며 실제 임베딩 Dense 검색이 아니다.
- 정답 라벨은 수집된 조항의 문서·조항 메타데이터에서 생성한 검색 회귀 테스트용이다. 법률 해석 정확도를 측정하지 않는다.
- 임베딩 모델의 최초 로드·코퍼스 색인 비용은 표의 단건 검색 지연시간에 포함하지 않는다.
