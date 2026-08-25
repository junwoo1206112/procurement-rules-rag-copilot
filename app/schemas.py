from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator


class DocumentKind(StrEnum):
    PDF = "pdf"
    HWPX = "hwpx"
    HWP = "hwp"
    HTML = "html"


class AccessStatus(StrEnum):
    CONFIRMED_PUBLIC = "confirmed_public"
    UNKNOWN = "unknown"
    RESTRICTED = "restricted"


class DocumentManifest(BaseModel):
    document_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,80}$")
    title: str = Field(min_length=3, max_length=300)
    source_url: AnyHttpUrl
    issuing_organization: str = Field(min_length=2, max_length=120)
    collected_at: datetime
    document_kind: DocumentKind
    access_status: AccessStatus
    usage_terms_checked: bool
    usage_basis: str | None = Field(default=None, max_length=500)
    notice_number: str | None = None
    published_at: datetime | None = None
    exclusion_reason: str | None = None

    @field_validator("source_url")
    @classmethod
    def source_must_use_https(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("원문 URL은 HTTPS여야 합니다.")
        return value

    @model_validator(mode="after")
    def validate_eligibility(self) -> "DocumentManifest":
        if self.access_status == AccessStatus.CONFIRMED_PUBLIC and not self.usage_terms_checked:
            raise ValueError("공개 문서는 이용 조건 확인 결과가 필요합니다.")
        if self.access_status == AccessStatus.CONFIRMED_PUBLIC and not self.usage_basis:
            raise ValueError("공개 문서는 이용 가능 근거를 기록해야 합니다.")
        if self.access_status != AccessStatus.CONFIRMED_PUBLIC and not self.exclusion_reason:
            raise ValueError("제외 문서는 exclusion_reason이 필요합니다.")
        return self

    @property
    def eligible_for_indexing(self) -> bool:
        return self.access_status == AccessStatus.CONFIRMED_PUBLIC and self.usage_terms_checked


class DocumentChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    page: int | None = None
    section: str | None = None
    content: str
    content_type: str = "text"
    parser: str
    confidence: float = Field(ge=0, le=1)
    source_url: AnyHttpUrl
    issuing_organization: str
    notice_number: str | None = None
    document_kind: DocumentKind | None = None


class SearchFilters(BaseModel):
    issuing_organization: str | None = None
    notice_number: str | None = None
    document_kind: DocumentKind | None = None


class SearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=800)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = Field(default=5, ge=1, le=10)


class Citation(BaseModel):
    chunk_id: str
    document_title: str
    section: str | None
    page: int | None
    source_url: AnyHttpUrl


class SearchHit(BaseModel):
    chunk: DocumentChunk
    dense_score: float
    bm25_score: float
    rerank_score: float
    hybrid_score: float


class AnswerResponse(BaseModel):
    status: str
    answer: str
    citations: list[Citation]
    retrieval: list[SearchHit]
    model_used: str | None = None
