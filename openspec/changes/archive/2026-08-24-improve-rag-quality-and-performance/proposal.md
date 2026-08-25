## Why

현재 시스템은 근거가 불충분할 때 안전하게 보류하고 Docker 환경에서도 재현되지만, 여러 후보가 함께 검색되면 로컬 모델이 빈 claim을 반환해 원문 발췌 모드로 전환되는 비율이 높다. 또한 실제 Dense+BM25 Hybrid는 TF 기준선보다 높지만 Dense 단독보다 낮아, 품질과 CPU 응답 시간을 함께 개선할 검증 가능한 튜닝이 필요하다.

## What Changes

- 질문과 직접 일치하는 근거를 우선 선별해 로컬 모델에 전달하고, 생성·보류·원문 발췌 전환 사유를 구분해 반환한다.
- 고정 평가 세트에서 검색 구성과 답변 상태별 통과율을 다시 측정하고, 기준선 대비 개선·실패 사례·단건 지연시간을 같은 조건으로 보고한다.
- CPU 데모는 안전한 보류 정책을 유지하며, 검증되지 않은 생성 답변이나 임의 성능 수치를 추가하지 않는다.

## Capabilities

### New Capabilities

- `quality-aware-rag-answering`: 검색 근거의 관련성을 바탕으로 생성 문맥을 구성하고, 검증 가능한 생성 답변과 안전한 보류를 구분한다.
- `retrieval-quality-optimization`: 고정 평가 세트에서 검색·답변 품질과 단건 성능을 비교해 개선 근거를 기록한다.

### Modified Capabilities

- 없음. 기존 변경의 delta spec은 아직 메인 OpenSpec spec으로 동기화되지 않았으므로, 이번 변경은 독립된 관찰 가능 품질 계약을 정의한다.

## Impact

- `app/retrieval.py`, `app/answering.py`, `app/evaluation.py`, 평가 데이터·리포트와 웹 UI의 답변 상태 표시가 영향을 받는다.
- API는 기존 인용·보류 응답 구조를 유지하되, 검색·생성 단계의 상태 정보를 더 명확히 제공할 수 있다.
- CPU 데모, Docker Compose, 로컬 Ollama 모델을 같은 실행 기준으로 재검증한다.
