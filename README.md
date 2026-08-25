# Procurement Rules RAG Copilot

국가법령정보센터의 조달 관련 행정규칙에서 참가 자격, 계약·평가 기준을 찾아 **원문 문서·조항·원문 링크**와 함께 답하는 로컬 우선 RAG 포트폴리오입니다.

> 조달 관련 공공 원문을 조항 단위로 검색하고, 출처 인용·안전 보류·실제 LLM 품질 평가를 제공하는 근거 중심 RAG Copilot입니다.

**포트폴리오 초점:** 답변을 무조건 생성하는 것보다, 근거가 없거나 인용 검증에 실패했을 때 안전하게 보류하고 실제 실패 사례까지 측정·공개하는 RAG 품질 검증 과정에 있습니다.

## 핵심 증거

- 공개 접근·이용 조건 확인 여부, 저작권법 제7조 이용 근거와 원문 URL을 문서 메타데이터로 보존합니다.
- PDF/HWPX 파싱, 구조·표 보존 청킹, 메타데이터 필터 검색을 제공합니다.
- 수집 CLI가 검증한 로컬 청크를 서버 시작 시 자동 색인해, 빈 인덱스 데모를 방지합니다.
- CPU 데모의 기본 검색은 즉시 재현 가능한 `lexical_hybrid`(TF-cosine+BM25)입니다. 실제 `hybrid`(임베딩+BM25)와 Dense는 로컬 임베딩 모델·캐시가 준비된 환경에서 비교하며, 휴리스틱 reranker는 기본 경로에서 제외했습니다.
- 근거가 부족하거나 인용 검증에 실패하면 답변을 보류합니다.
- 로컬 Ollama 경로와 Docker Compose 재현 구성을 제공합니다.
- Docker Compose E2E에서 컨테이너 시작 후 67개 문서·2,289개 청크가 자동 색인되고, 로컬 Ollama의 인용형 답변을 확인했습니다.

## 실행

Python 3.12 이상에서 다음을 실행합니다.

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q -p no:cacheprovider
python -m uvicorn app.main:app --reload
```

브라우저에서 `http://127.0.0.1:8000`을 엽니다. 서버는 `data/collected-chunks.json`이 있으면 검증된 조항 청크를 자동으로 색인합니다. 처음 수집할 때는 프로젝트 루트의 `.env`에 발급받은 OC를 `LAW_API_OC=...` 형식으로 저장한 뒤 다음을 실행합니다.

```powershell
python -m app.collect_corpus --offset 0 --limit 5
```

30건 전체는 `--offset`을 5씩 늘려 실행합니다. 원문은 법령 HTML처럼 페이지 번호가 없으므로, 이 코퍼스의 인용은 **페이지 대신 조항**을 표시합니다.

> **v4.0 측정 기준:** CPU 데모 기본값은 외부 임베딩 모델 다운로드 없이 바로 재현되는 `lexical_hybrid`입니다. 같은 72문항 단건 평가에서 실제 `hybrid`의 검색 Recall@5는 `0.7391`, Dense 단독은 `0.7536`으로 높았지만, 최초 모델 로드·코퍼스 벡터화 비용은 p50/p95에 포함하지 않습니다. 따라서 모델·캐시가 준비된 환경의 결과만으로 Docker CPU 기본 경로를 변경하지 않습니다.

## Docker와 Ollama

Docker Desktop이 설치된 환경에서는 다음을 실행합니다.

```powershell
docker compose up --build
docker compose exec ollama ollama pull qwen2.5:3b
```

Compose 이미지는 CPU 전용 PyTorch와 검증된 코퍼스 스냅샷만 포함합니다. 첫 실행 후 `http://127.0.0.1:8000/health`에서 문서·청크 수를 확인할 수 있습니다.

Compose 실행 전 프로젝트 루트의 `.env`에 `LAW_API_OC`, `G2B_SERVICE_KEY`를 저장합니다. `.env`는 절대 커밋하지 않습니다. Docker Desktop이 설치된 환경에서만 아래 흐름을 완료로 처리합니다.

```powershell
python -m app.collect_corpus --offset 0 --limit 5
python -m app.g2b_collector --limit 30
docker compose up --build
```

CPU 환경에서는 첫 응답이 느릴 수 있습니다. GPU 환경은 로컬 모델 추론에 권장되지만, 특정 성능 수치를 주장하지 않습니다. Ollama 모델이 아직 준비되지 않았거나 claim 검증에 실패하면, 관련 근거가 있는 경우에만 `grounded_demo` 상태의 검증된 원문 발췌를 반환합니다. 검색 근거 자체가 없으면 모델을 호출하지 않고 `insufficient_evidence`와 빈 인용 목록으로 보류합니다.

## 데이터·한계

현재 포트폴리오 수치는 **v4.0 단건 평가 결과**를 기준으로 합니다. 구성별 수치·선택 근거 Recall·실패 사례는 [`docs/evaluation-report.md`](docs/evaluation-report.md)와 `data/evaluation-results.json`을 우선합니다.

- 원문 문서는 저장소에 포함하지 않습니다. `data/procurement-rules-manifest.json`에는 국가법령정보센터의 조달청 행정규칙 30건과 저작권법 제7조 이용 근거를 등록했습니다. 개별 입찰 첨부물처럼 이용 조건을 확인하지 못한 문서는 `data/excluded-sources.json`에 제외 사유와 함께 기록했습니다.
- 현재 테스트 fixture는 파이프라인 검증용 합성 문서이며 실제 공고 성능을 의미하지 않습니다.
- 고정 평가 세트와 실제 측정값·실패 사례는 [`docs/evaluation-report.md`](docs/evaluation-report.md)에 기록합니다. v4.0 단건 측정에서 `lexical_hybrid` / `hybrid` / Dense의 Recall@5는 각각 `0.5362` / `0.7391` / `0.7536`입니다. p50/p95는 측정 조건에 민감하므로, 최초 모델 로드·코퍼스 벡터화 비용이 제외된 상세 수치와 한계를 리포트에서 함께 확인합니다.
- 법률·계약·입찰 결정을 대신하지 않으며, 최신 공고 여부는 원문에서 재확인해야 합니다.

## 품질 평가 재실행

임베딩 모델을 한 번 로컬에 준비한 환경에서는 외부 업데이트 확인 없이 아래처럼 같은 단건 조건으로 재측정할 수 있습니다.

```powershell
$env:HF_HUB_OFFLINE="1"
python -m app.run_evaluation --include-embedding --single-query-latency
```

기본 상태 평가는 `deterministic_evidence_contract`로, 선택된 근거가 인용형 답변의 조건을 충족하는지만 검증합니다. `--answer-status-mode ollama`는 기존 상태 비율 비교용이며, 생성문·인용 적합성까지 남기는 실제 품질 평가는 아래의 `--live-llm` 경로를 사용합니다.

## 실제 LLM 생성·인용 평가

실제 생성문 품질은 결정론적 근거 계약과 별도로 기록합니다. Docker/Ollama가 준비된 상태에서 대표 질의부터 다음처럼 실행합니다.

```powershell
docker compose exec api python -m app.run_evaluation --live-llm --live-limit 8
```

실행 결과는 `data/live-llm-evaluation-results.json`, 검토용 리포트는 `docs/live-llm-evaluation-report.md`에 저장됩니다. 이 결과에는 모델명·프롬프트 해시·코퍼스 해시·인용 정답 근거 일치·안전 보류·실행 실패 수가 포함됩니다. 기존 결과를 이어 실행할 때만 `--live-resume`을 사용하며, 새 결과로 바꾸려면 `--live-overwrite`를 명시합니다.

`grounded` 상태나 인용 정답 근거 일치는 생성문 의미와 법률 해석의 정확성 자체를 보장하지 않습니다. 인용 불일치, `grounded_demo`, 문서 비교 질의는 리포트의 우선 검토 사례에서 사람이 확인합니다.

## 명세와 진행 방식

- OpenSpec 변경 명세: `openspec/changes/build-procurement-rag-portfolio/`
- 재사용 가능한 전문가 인터뷰 템플릿: `전문가_대화형_프로젝트_인터뷰_OpenSpec_템플릿.md`
