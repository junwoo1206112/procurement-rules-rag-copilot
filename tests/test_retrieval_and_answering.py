import json

import pytest

from app.answering import CitationValidationError, OllamaAnswerer, citations_for, has_minimum_evidence, select_answer_evidence, validate_claims
from app.chunking import build_chunks
from app.retrieval import HybridRetriever
from app.schemas import DocumentKind, SearchFilters, SearchHit


def test_notice_number_and_filter_return_relevant_chunk(manifest, blocks) -> None:
    chunks = build_chunks(manifest, blocks)
    hits = HybridRetriever(chunks).search("2026-001 제출 서류는 무엇인가요?", SearchFilters(notice_number="2026-001"))
    assert hits
    assert "제안서" in hits[0].chunk.content


def test_document_kind_filter_returns_matching_chunks(manifest, blocks) -> None:
    chunks = build_chunks(manifest, blocks)
    hits = HybridRetriever(chunks).search("제안서", SearchFilters(document_kind=DocumentKind.PDF))
    assert hits


def test_insufficient_evidence_is_not_generated(manifest, blocks) -> None:
    response = OllamaAnswerer(endpoint="http://127.0.0.1:1").answer("존재하지 않는 해외 조달 조건은?", [])
    assert response.status == "insufficient_evidence"
    assert response.citations == []


def test_unrelated_hits_do_not_call_model(monkeypatch, manifest, blocks) -> None:
    chunk = build_chunks(manifest, blocks)[0]
    unrelated_hit = SearchHit(chunk=chunk, dense_score=0.8, bm25_score=0, rerank_score=0, hybrid_score=0.8)
    monkeypatch.setattr("app.answering.urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("모델을 호출하면 안 됩니다."))
    response = OllamaAnswerer().answer("존재하지 않는 해외 조달 조건은?", [unrelated_hit])
    assert response.status == "insufficient_evidence"
    assert response.citations == []


def test_unrelated_question_needs_lexical_evidence(manifest, blocks) -> None:
    retriever = HybridRetriever(build_chunks(manifest, blocks))
    assert not has_minimum_evidence("화성 기지 중력값은?", retriever.search("화성 기지 중력값은?", SearchFilters()))
    assert has_minimum_evidence("제안서 사업자등록증", retriever.search("제안서 사업자등록증", SearchFilters()))


def test_citations_match_retrieved_chunks(manifest, blocks) -> None:
    hits = HybridRetriever(build_chunks(manifest, blocks)).search("참가 자격", SearchFilters())
    citations = citations_for(hits)
    assert citations[0].chunk_id == hits[0].chunk.chunk_id
    assert citations[0].page == hits[0].chunk.page


def test_claim_without_valid_evidence_is_rejected(manifest, blocks) -> None:
    hits = HybridRetriever(build_chunks(manifest, blocks)).search("참가 자격", SearchFilters())
    with pytest.raises(CitationValidationError, match="어휘적으로"):
        validate_claims({"claims": [{"text": "화성 이주 조건", "citation_ids": [hits[0].chunk.chunk_id]}]}, hits)


def test_claim_with_retrieved_evidence_returns_only_referenced_citation(manifest, blocks) -> None:
    hits = HybridRetriever(build_chunks(manifest, blocks)).search("참가 자격", SearchFilters())
    claim = {"claims": [{"text": "참가 자격을 확인합니다", "citation_ids": [hits[0].chunk.chunk_id]}]}
    assert validate_claims(claim, hits)[0][1] == [hits[0].chunk.chunk_id]


def test_answer_evidence_prefers_direct_section_match(manifest, blocks) -> None:
    chunks = build_chunks(manifest, blocks)
    correct = next(chunk for chunk in chunks if chunk.section == "제출 서류" and chunk.content_type == "text")
    distractor = next(chunk for chunk in chunks if chunk.section == "입찰 참가 자격")
    hits = [
        SearchHit(chunk=distractor, dense_score=0.9, bm25_score=1.2, rerank_score=0, hybrid_score=0.9),
        SearchHit(chunk=correct, dense_score=0.4, bm25_score=1.0, rerank_score=0, hybrid_score=0.4),
    ]
    selected = select_answer_evidence("제출 서류는 무엇인가요?", hits)
    assert [hit.chunk.chunk_id for hit in selected.hits] == [correct.chunk_id]


def test_answer_evidence_does_not_promote_generic_title_terms(manifest, blocks) -> None:
    correct = build_chunks(manifest, blocks)[0].model_copy(update={
        "chunk_id": "registration-team-1", "document_title": "조달등록팀 운영규정",
        "content": "조달청 조달등록팀의 세부 운영사항에 대하여 규정함을 목적으로 한다.",
    })
    distractor = correct.model_copy(update={
        "chunk_id": "competitive-dialogue-1", "document_id": "competitive-dialogue",
        "document_title": "조달청 경쟁적 대화에 의한 계약체결 세부기준",
        "content": "경쟁적 대화에 의한 계약체결 세부기준을 정한다.",
    })
    hits = [
        SearchHit(chunk=distractor, dense_score=0.9, bm25_score=1.3, rerank_score=0, hybrid_score=0.9),
        SearchHit(chunk=correct, dense_score=0.4, bm25_score=1.0, rerank_score=0, hybrid_score=0.4),
    ]
    selected = select_answer_evidence("조달청 조달등록팀의 세부 운영사항은 무엇을 규정하나요?", hits)
    assert [hit.chunk.chunk_id for hit in selected.hits] == [correct.chunk_id]


def test_answer_evidence_keeps_documents_for_comparison(manifest, blocks) -> None:
    first = build_chunks(manifest, blocks)[1]
    second = first.model_copy(update={"chunk_id": "other-document-1", "document_id": "other-document", "document_title": "다른 제안요청서", "content": "다른 제안요청서도 사업자등록증 사본을 제출합니다."})
    hits = [
        SearchHit(chunk=first, dense_score=0.7, bm25_score=1.0, rerank_score=0, hybrid_score=0.7),
        SearchHit(chunk=second, dense_score=0.6, bm25_score=1.0, rerank_score=0, hybrid_score=0.6),
    ]
    selected = select_answer_evidence("두 제안요청서의 사업자등록증 조건을 비교해줘", hits)
    assert {hit.chunk.document_id for hit in selected.hits} == {first.document_id, second.document_id}


def test_answerer_uses_selected_evidence_and_returns_grounded(monkeypatch, manifest, blocks) -> None:
    chunks = build_chunks(manifest, blocks)
    correct = next(chunk for chunk in chunks if chunk.section == "제출 서류" and chunk.content_type == "text")
    distractor = next(chunk for chunk in chunks if chunk.section == "입찰 참가 자격")
    hits = [
        SearchHit(chunk=distractor, dense_score=0.9, bm25_score=1.2, rerank_score=0, hybrid_score=0.9),
        SearchHit(chunk=correct, dense_score=0.4, bm25_score=1.0, rerank_score=0, hybrid_score=0.4),
    ]
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            payload = {"claims": [{"text": "제안서와 사업자등록증 사본을 제출합니다.", "citation_ids": [correct.chunk_id]}]}
            return json.dumps({"response": json.dumps(payload)}).encode()

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return Response()

    monkeypatch.setattr("app.answering.urllib.request.urlopen", fake_urlopen)
    response = OllamaAnswerer().answer("제출 서류는 무엇인가요?", hits)
    assert response.status == "grounded"
    assert response.citations[0].chunk_id == correct.chunk_id
    request_body = json.loads(captured["request"].data)
    assert correct.chunk_id in request_body["prompt"]
    assert distractor.chunk_id not in request_body["prompt"]


def test_invalid_model_claim_returns_selected_verified_excerpt(monkeypatch, manifest, blocks) -> None:
    chunks = build_chunks(manifest, blocks)
    correct = next(chunk for chunk in chunks if chunk.section == "제출 서류" and chunk.content_type == "text")
    hit = SearchHit(chunk=correct, dense_score=0.4, bm25_score=1.0, rerank_score=0, hybrid_score=0.4)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"response": json.dumps({"claims": []})}).encode()

    monkeypatch.setattr("app.answering.urllib.request.urlopen", lambda *args, **kwargs: Response())
    response = OllamaAnswerer().answer("제출 서류는 무엇인가요?", [hit])
    assert response.status == "grounded_demo"
    assert [citation.chunk_id for citation in response.citations] == [correct.chunk_id]
