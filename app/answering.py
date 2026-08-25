from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass
from hashlib import sha256

from app.schemas import AnswerResponse, Citation, SearchHit

logger = logging.getLogger(__name__)

COMPARISON_TERMS = {"비교", "차이", "각각"}


@dataclass(frozen=True)
class AnswerEvidenceSelection:
    """생성 모델에 전달할, 질문과 직접 연결된 검색 근거다."""

    hits: list[SearchHit]
    reason: str | None = None


@dataclass(frozen=True)
class AnswerExecutionTrace:
    """평가 전용 실행 흔적이다. API 응답에 비밀값이나 프롬프트 원문을 노출하지 않는다."""

    selected_chunk_ids: list[str]
    prompt_sha256: str | None
    execution_status: str


class CitationValidationError(ValueError):
    pass


def citations_for(hits: list[SearchHit]) -> list[Citation]:
    citations = [Citation(
        chunk_id=hit.chunk.chunk_id, document_title=hit.chunk.document_title, section=hit.chunk.section,
        page=hit.chunk.page, source_url=hit.chunk.source_url,
    ) for hit in hits]
    validate_citations(citations, hits)
    return citations


def citations_for_ids(citation_ids: list[str], hits: list[SearchHit]) -> list[Citation]:
    by_id = {hit.chunk.chunk_id: hit for hit in hits}
    selected = [by_id[chunk_id] for chunk_id in citation_ids if chunk_id in by_id]
    citations = citations_for(selected)
    if len(citations) != len(set(citation_ids)):
        raise CitationValidationError("존재하지 않는 인용 ID입니다.")
    return citations


def validate_citations(citations: list[Citation], hits: list[SearchHit]) -> None:
    valid = {hit.chunk.chunk_id: hit.chunk for hit in hits}
    for citation in citations:
        chunk = valid.get(citation.chunk_id)
        if not chunk or citation.page != chunk.page or str(citation.source_url) != str(chunk.source_url):
            raise CitationValidationError(f"검증되지 않은 인용입니다: {citation.chunk_id}")


def validate_claims(payload: object, hits: list[SearchHit]) -> list[tuple[str, list[str]]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("claims"), list) or not payload["claims"]:
        raise CitationValidationError("claim 구조가 없습니다.")
    available = {hit.chunk.chunk_id: hit for hit in hits}
    validated: list[tuple[str, list[str]]] = []
    for claim in payload["claims"]:
        if not isinstance(claim, dict) or not isinstance(claim.get("text"), str) or not isinstance(claim.get("citation_ids"), list):
            raise CitationValidationError("claim 형식이 올바르지 않습니다.")
        text = claim["text"].strip()
        citation_ids = list(dict.fromkeys(item for item in claim["citation_ids"] if isinstance(item, str)))
        if not text or not citation_ids or any(item not in available for item in citation_ids):
            raise CitationValidationError("claim 인용 ID가 유효하지 않습니다.")
        claim_terms = {term for term in _terms(text) if len(term) > 1}
        evidence_terms = set().union(*(_terms(available[item].chunk.content) for item in citation_ids))
        has_lexical_evidence = any(claim_term in evidence_term or evidence_term in claim_term for claim_term in claim_terms for evidence_term in evidence_terms)
        if not claim_terms or not has_lexical_evidence:
            raise CitationValidationError("claim이 인용 근거와 어휘적으로 연결되지 않습니다.")
        validated.append((text, citation_ids))
    return validated


def _terms(value: str) -> set[str]:
    import re
    return set(re.findall(r"[가-힣A-Za-z0-9]+", value.lower()))


def has_minimum_evidence(question: str, hits: list[SearchHit]) -> bool:
    """Dense 유사도만으로는 답변하지 않고, 검색 근거에 실제 BM25 일치가 있어야 한다."""
    return bool(hits) and hits[0].bm25_score > 0


def _overlap_count(question_terms: set[str], candidate_terms: set[str]) -> int:
    return sum(any(term in candidate or candidate in term for candidate in candidate_terms) for term in question_terms)


def _metadata_match(question: str, hit: SearchHit) -> bool:
    if hit.chunk.notice_number and hit.chunk.notice_number.lower() in question.lower():
        return True
    question_terms = {term for term in _terms(question) if len(term) >= 4}
    title_terms = {term for term in _terms(hit.chunk.document_title) if len(term) >= 4}
    # 기관명·"세부"처럼 여러 문서에 흔한 짧은 단어가 직접 일치로
    # 승격되는 것을 막고, 문서 제목의 고유어가 질문에 있을 때만 우선한다.
    return bool(question_terms and title_terms and _overlap_count(question_terms, title_terms))


def select_answer_evidence(question: str, hits: list[SearchHit]) -> AnswerEvidenceSelection:
    """검색 결과 중 claim으로 인용 가능한 직접 근거만 선택한다.

    일반 질의는 가장 관련 높은 하나를 전달해 모델 문맥 혼선을 줄인다.
    비교 의도 질의는 관련 문서마다 하나씩 남겨 복수 근거를 보존한다.
    """
    question_terms = {term for term in _terms(question) if len(term) > 1}
    candidates: list[tuple[tuple[float, float, float], SearchHit]] = []
    for hit in hits:
        content_terms = {term for term in _terms(hit.chunk.content) if len(term) > 1}
        metadata_terms = {term for term in _terms(" ".join(filter(None, [hit.chunk.document_title, hit.chunk.section, hit.chunk.notice_number]))) if len(term) > 1}
        content_matches = _overlap_count(question_terms, content_terms)
        metadata_matches = _overlap_count(question_terms, metadata_terms)
        direct = _metadata_match(question, hit)
        # 최소 하나의 실제 본문 또는 메타데이터 일치와 BM25 양수 없이는 생성하지 않는다.
        if hit.bm25_score <= 0 or not (direct or content_matches):
            continue
        candidates.append(((float(direct), float(content_matches), float(metadata_matches) + hit.hybrid_score), hit))
    if not candidates:
        return AnswerEvidenceSelection([], "no_evidence")

    candidates.sort(key=lambda item: item[0], reverse=True)
    is_comparison = any(term in question for term in COMPARISON_TERMS)
    if not is_comparison:
        return AnswerEvidenceSelection([candidates[0][1]])

    selected: list[SearchHit] = []
    seen_documents: set[str] = set()
    for _, hit in candidates:
        if hit.chunk.document_id in seen_documents:
            continue
        selected.append(hit)
        seen_documents.add(hit.chunk.document_id)
        if len(selected) == 3:
            break
    return AnswerEvidenceSelection(selected)


class OllamaAnswerer:
    def __init__(self, endpoint: str | None = None, model: str | None = None):
        self.endpoint = endpoint or os.getenv("OLLAMA_URL", "http://ollama:11434")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

    def build_prompt(self, question: str, evidence_hits: list[SearchHit]) -> str:
        context = "\n\n".join(f"[chunk_id={hit.chunk.chunk_id}] {hit.chunk.content}" for hit in evidence_hits)
        return (
            "당신은 공공 조달 문서 도우미입니다. 제공된 근거 밖의 사실을 말하지 마세요. "
            "JSON만 반환하세요: {\"claims\":[{\"text\":\"근거에 있는 짧은 주장\",\"citation_ids\":[\"chunk_id\"]}]}. "
            "모든 claim은 하나 이상의 제공 chunk_id를 참조해야 하며, 근거가 부족하면 {\"claims\":[]}를 반환하세요.\n\n"
            "질문의 핵심 단어 또는 문서명이 명시적으로 일치하는 근거가 하나라도 있으면 claims를 비우지 말고, "
            "그 chunk_id를 인용한 짧은 claim을 반드시 하나 반환하세요. 관련 없는 근거는 인용하지 마세요.\n\n"
            f"질문: {question}\n\n근거:\n{context}"
        )

    def answer_with_trace(self, question: str, hits: list[SearchHit]) -> tuple[AnswerResponse, AnswerExecutionTrace]:
        selection = select_answer_evidence(question, hits)
        selected_chunk_ids = [hit.chunk.chunk_id for hit in selection.hits]
        if not selection.hits:
            logger.info("답변 보류: reason=%s", selection.reason)
            response = AnswerResponse(status="insufficient_evidence", answer="확인 가능한 근거를 찾지 못했습니다. 원문 문서 또는 검색 조건을 확인해 주세요.", citations=[], retrieval=hits)
            return response, AnswerExecutionTrace(selected_chunk_ids, None, "not_called_no_evidence")

        evidence_hits = selection.hits
        prompt = self.build_prompt(question, evidence_hits)
        prompt_sha256 = sha256(prompt.encode("utf-8")).hexdigest()
        try:
            body = json.dumps({
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            }).encode("utf-8")
            request = urllib.request.Request(f"{self.endpoint}/api/generate", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(json.loads(response.read())["response"])
            claims = validate_claims(payload, evidence_hits)
            citation_ids = list(dict.fromkeys(item for _, ids in claims for item in ids))
            citations = citations_for_ids(citation_ids, evidence_hits)
            index = {citation.chunk_id: number + 1 for number, citation in enumerate(citations)}
            answer = "\n".join(f"- {text} " + " ".join(f"[{index[item]}]" for item in ids) for text, ids in claims)
            return AnswerResponse(status="grounded", answer=answer, citations=citations, retrieval=hits, model_used=self.model), AnswerExecutionTrace(selected_chunk_ids, prompt_sha256, "completed")
        except (OSError, TimeoutError, json.JSONDecodeError, CitationValidationError, KeyError, TypeError) as exc:
            reason = "claim_validation_failed" if isinstance(exc, CitationValidationError) else "model_unavailable"
            logger.warning("Ollama 답변을 검증된 발췌로 보류했습니다: reason=%s error=%s", reason, exc)
            excerpts = "\n".join(f"- {hit.chunk.content[:260]}" for hit in evidence_hits[:3])
            execution_status = "timeout" if isinstance(exc, TimeoutError) else "invalid_model_payload" if isinstance(exc, (json.JSONDecodeError, CitationValidationError, KeyError, TypeError)) else "model_unavailable"
            response = AnswerResponse(status="grounded_demo", answer=f"검증된 원문 발췌입니다.\n{excerpts}", citations=citations_for(evidence_hits[:3]), retrieval=hits, model_used=None)
            return response, AnswerExecutionTrace(selected_chunk_ids, prompt_sha256, execution_status)

    def answer(self, question: str, hits: list[SearchHit]) -> AnswerResponse:
        response, _ = self.answer_with_trace(question, hits)
        return response
