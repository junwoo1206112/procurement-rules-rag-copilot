# Procurement Rules RAG Copilot

국가법령정보센터의 조달 관련 행정규칙을 수집하고, 조항 단위의 근거와 원문 링크를 함께 제시하는 로컬 우선 RAG 포트폴리오 프로젝트입니다.

## 구성

- `app/`: FastAPI, 수집·파싱·검색·답변·평가 코드와 웹 UI
- `data/`: 수집 매니페스트, 제외 목록, 검증된 청크와 평가 결과
- `tests/`: 파싱·수집·검색·근거 선택·API 회귀 테스트
- `docs/`: 평가 리포트, 전문가 인터뷰 기록, 포트폴리오 발표 자료
- `openspec/`: 확정 명세와 완료된 변경 이력

## 검증된 완료 상태 (2026-08-24)

- 공식 원문에서 수집한 67개 문서, 2,289개 청크를 서버 시작 시 자동 색인한다.
- 수집 단계에서 허용 도메인·문서 제목·원문 SHA-256을 확인하고, 출처·이용 근거를 보존한다.
- 답변에는 선택된 근거만 인용한다. 근거가 없으면 모델을 호출하지 않고 `insufficient_evidence`로 보류하며, 생성 또는 인용 검증이 실패하면 `grounded_demo` 원문 발췌만 반환한다.
- 72문항 고정 평가와 구성별 검색·인용·선택 근거·지연시간 지표를 `docs/evaluation-report.md`에 기록한다.
- Docker Compose 실환경에서 API·Ollama를 실행하고, 자동 색인·인용 답변·근거 부족 보류를 확인했다.
- 회귀 테스트 44개가 통과했다. FastAPI 테스트 클라이언트의 라이브러리 사용 중단 경고 1건은 기능 실패가 아닌 추후 의존성 업데이트 항목이다.
- 실제 Ollama 생성 평가는 결정론적 검색 평가와 별도 산출물로 기록하며, 대표 8문항 결과와 한계는 `docs/live-llm-evaluation-report.md`에 공개한다.

## OpenSpec 이력

- 현행 명세: `openspec/specs/quality-aware-rag-answering/`, `openspec/specs/retrieval-quality-optimization/`
- 완료·보관 변경: `openspec/changes/archive/2026-08-24-improve-rag-quality-and-performance/`
- 전문가 교차 검증 기록: `프로젝트_전문가_인터뷰_기록.md`

## 재현 환경

프로젝트 루트의 `.env`에 발급받은 키를 보관한다. `.env`는 Git에 올리지 않는다.

```env
LAW_API_OC=발급받은_OC
G2B_SERVICE_KEY=나라장터_일반인증키
```

로컬 Python 실행, Docker 실행, 평가 재현 절차는 `README.md`를 기준으로 한다. 발표·지원용 요약은 `PORTFOLIO_CASE_STUDY.md`를 사용한다.
