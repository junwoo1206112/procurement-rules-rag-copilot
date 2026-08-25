# 실제 LLM 근거·인용 평가 리포트

- 측정 유형: `live_llm_grounding_review`
- 데이터셋 버전: `2026-08-20-v3`
- 코퍼스 SHA-256: `35540f23efd8375ff2b9ad5bdade402ebd1b182eabf029faa25ed1e7e5f7509e`
- 모델: `qwen2.5:3b`
- 실행 시각(UTC): `2026-08-24T10:41:39.478033+00:00`
- 검색 구성: `lexical_hybrid`

## 실행·자동 검토 집계

| 항목 | 값 | 분모 |
| --- | ---: | ---: |
| 전체 질의 | 8 | 전체 |
| 완료 실행 | 8 | 전체 |
| 인프라 실패 | 0 | 전체 |
| 인용 정답 근거 일치 | 3 (0.4286) | 완료된 답변 가능 질의 7 |
| 안전 보류 적절 | 1 (1.0000) | 완료된 답변 불가 질의 1 |
| grounded_demo | 4 | 완료 실행 |
| 사람 검토 필요 | 6 | 완료 실행 |

## 우선 검토 사례

- `evidence-001` (조항 조회): status=grounded_demo, execution=invalid_model_payload, citation_expected_match=True
- `evidence-016` (참가자격): status=grounded_demo, execution=invalid_model_payload, citation_expected_match=False
- `evidence-041` (일정): status=grounded, execution=completed, citation_expected_match=False
- `evidence-051` (평가기준): status=grounded, execution=completed, citation_expected_match=False
- `evidence-062` (제출서류): status=grounded_demo, execution=invalid_model_payload, citation_expected_match=False
- `evidence-069` (문서 비교): status=grounded_demo, execution=invalid_model_payload, citation_expected_match=True

## 해석 한계

- 이 리포트의 인용 정답 근거 일치는 반환 citation ID와 고정 평가 라벨의 교집합을 보는 자동 지표입니다.
- 생성 문장이 근거를 정확히 요약했는지와 법률 해석의 정확성은 자동 판정하지 않으며, 우선 검토 사례에서 사람이 확인해야 합니다.
- 모델·인프라 실패는 생성 품질 성공률의 분모에서 제외하고 별도로 기록합니다.
