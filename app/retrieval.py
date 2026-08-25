from __future__ import annotations

import math
import re
from hashlib import sha256
from functools import lru_cache
from collections import Counter
from pathlib import Path

from app.schemas import DocumentChunk, SearchFilters, SearchHit


def tokenize(value: str) -> list[str]:
    return re.findall(r"[가-힣A-Za-z0-9]+", value.lower())


class HybridRetriever:
    """토큰 기반 Hybrid 검색과 선택 가능한 실제 임베딩 검색을 제공한다."""

    def __init__(self, chunks: list[DocumentChunk]):
        self.chunks = chunks
        self.documents = [tokenize(chunk.document_title + " " + (chunk.section or "") + " " + chunk.content) for chunk in chunks]
        self.content_documents = [tokenize(chunk.content) for chunk in chunks]
        self.doc_frequency: Counter[str] = Counter(token for tokens in self.documents for token in set(tokens))
        self.average_length = sum(map(len, self.documents)) / max(len(self.documents), 1)
        self._document_embeddings = None
        self._embedding_fingerprint = sha256(("embedding-v2-600-256\n" + "\n".join(f"{chunk.chunk_id}:{chunk.content}" for chunk in chunks)).encode("utf-8")).hexdigest()

    def search(self, question: str, filters: SearchFilters, top_k: int = 5, mode: str = "lexical_hybrid", _query_embedding=None) -> list[SearchHit]:
        if mode not in {"tf_cosine", "embedding", "lexical_hybrid", "hybrid", "hybrid_rerank"}:
            raise ValueError("지원하지 않는 검색 평가 모드입니다.")
        query = tokenize(question)
        candidates = [index for index, chunk in enumerate(self.chunks) if self._matches(chunk, filters)]
        if not candidates:
            return []
        dense = self._embedding_scores(question, candidates, _query_embedding) if mode in {"embedding", "hybrid", "hybrid_rerank"} else {index: self._dense_score(query, self.documents[index]) for index in candidates}
        bm25 = {index: self._bm25_score(query, self.documents[index]) for index in candidates}
        dense_max = max(dense.values(), default=1) or 1
        bm25_max = max(bm25.values(), default=1) or 1
        semantic_hybrid = mode in {"hybrid", "hybrid_rerank"}
        hits = [
            SearchHit(
                chunk=self.chunks[index], dense_score=round(dense[index], 5), bm25_score=round(bm25[index], 5),
                rerank_score=0, hybrid_score=round(
                    0.8 * dense[index] / dense_max + 0.2 * bm25[index] / bm25_max
                    if semantic_hybrid else 0.25 * dense[index] / dense_max + 0.25 * bm25[index] / bm25_max + 0.50 * self._content_match_score(query, self.content_documents[index]),
                    5,
                ),
            )
            for index in candidates
        ]
        if mode == "tf_cosine":
            return sorted(hits, key=lambda item: item.dense_score, reverse=True)[:top_k]
        if mode == "embedding":
            return sorted(hits, key=lambda item: item.dense_score, reverse=True)[:top_k]
        hits.sort(key=lambda item: item.hybrid_score, reverse=True)
        return hits[:top_k] if mode in {"hybrid", "lexical_hybrid"} else self._rerank(question, hits[:20])[:top_k]

    def _content_match_score(self, query: list[str], document: list[str]) -> float:
        meaningful = [term for term in query if len(term) > 1]
        return sum(any(term in candidate or candidate in term for candidate in document) for term in meaningful) / max(len(meaningful), 1)

    def _matches(self, chunk: DocumentChunk, filters: SearchFilters) -> bool:
        return (
            (not filters.issuing_organization or chunk.issuing_organization == filters.issuing_organization)
            and (not filters.notice_number or chunk.notice_number == filters.notice_number)
            and (not filters.document_kind or chunk.document_kind == filters.document_kind)
        )

    def _dense_score(self, query: list[str], document: list[str]) -> float:
        if not query or not document:
            return 0
        query_counts, document_counts = Counter(query), Counter(document)
        dot = sum(query_counts[token] * document_counts[token] for token in query_counts)
        return dot / math.sqrt(sum(value * value for value in query_counts.values()) * sum(value * value for value in document_counts.values()))

    def search_many(self, questions: list[str], filters: SearchFilters, top_k: int = 5, mode: str = "lexical_hybrid") -> list[list[SearchHit]]:
        if mode not in {"embedding", "hybrid", "hybrid_rerank"}:
            return [self.search(question, filters, top_k, mode) for question in questions]
        model = _embedding_model()
        if self._document_embeddings is None:
            self._document_embeddings = self._load_or_create_embedding_cache(model)
        vectors = model.encode(["query: " + question for question in questions], normalize_embeddings=True, show_progress_bar=False, batch_size=32)
        return [self.search(question, filters, top_k, mode, _query_embedding=vector) for question, vector in zip(questions, vectors)]

    def _embedding_scores(self, question: str, candidates: list[int], query_embedding=None) -> dict[int, float]:
        model = _embedding_model()
        if self._document_embeddings is None:
            self._document_embeddings = self._load_or_create_embedding_cache(model)
        query = query_embedding if query_embedding is not None else model.encode(["query: " + question], normalize_embeddings=True, show_progress_bar=False)[0]
        return {index: float(query @ self._document_embeddings[index]) for index in candidates}

    def _load_or_create_embedding_cache(self, model):
        import numpy as np

        cache_path = Path(__file__).parents[1] / "data" / f"embedding-cache-{self._embedding_fingerprint[:16]}.npz"
        if cache_path.exists():
            with np.load(cache_path, allow_pickle=False) as cached:
                if str(cached["fingerprint"]) == self._embedding_fingerprint and len(cached["vectors"]) == len(self.chunks):
                    return cached["vectors"]
        passages = [("passage: " + chunk.document_title + " " + (chunk.section or "") + " " + chunk.content)[:600] for chunk in self.chunks]
        vectors = model.encode(passages, normalize_embeddings=True, show_progress_bar=False, batch_size=32)
        temporary = cache_path.with_name(f"{cache_path.stem}.tmp.npz")
        np.savez_compressed(temporary, fingerprint=self._embedding_fingerprint, vectors=vectors)
        temporary.replace(cache_path)
        return vectors
    def _bm25_score(self, query: list[str], document: list[str]) -> float:
        k1, b, total_documents = 1.5, 0.75, max(len(self.documents), 1)
        counts = Counter(document)
        score = 0.0
        for term in set(query):
            frequency = counts[term]
            if not frequency:
                continue
            idf = math.log(1 + (total_documents - self.doc_frequency[term] + 0.5) / (self.doc_frequency[term] + 0.5))
            score += idf * frequency * (k1 + 1) / (frequency + k1 * (1 - b + b * len(document) / max(self.average_length, 1)))
        return score

    def _rerank(self, question: str, hits: list[SearchHit]) -> list[SearchHit]:
        query_terms = set(tokenize(question))
        reranked: list[SearchHit] = []
        for hit in hits:
            content_terms = set(tokenize(hit.chunk.content))
            title_terms = set(tokenize(hit.chunk.document_title + " " + (hit.chunk.section or "")))
            exact_bonus = 0.2 if hit.chunk.notice_number and hit.chunk.notice_number in question else 0
            # 한국어 조사·활용형은 공백 토큰이 일치하지 않아도 의미상 관련될 수 있다.
            # 예: "제출" ↔ "제출합니다". 제목 일치보다 본문 일치에 더 큰 가중치를 준다.
            content_matches = sum(any(term in candidate or candidate in term for candidate in content_terms) for term in query_terms)
            title_matches = sum(any(term in candidate or candidate in term for candidate in title_terms) for term in query_terms)
            score = content_matches / max(len(query_terms), 1) + 0.3 * title_matches / max(len(query_terms), 1) + exact_bonus
            reranked.append(hit.model_copy(update={"rerank_score": round(score, 5), "hybrid_score": round(0.4 * hit.hybrid_score + 0.6 * score, 5)}))
        return sorted(reranked, key=lambda item: item.hybrid_score, reverse=True)


@lru_cache(maxsize=1)
def _embedding_model():
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("intfloat/multilingual-e5-small")
    model.max_seq_length = 256
    return model
