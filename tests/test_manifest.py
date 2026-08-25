from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import AccessStatus, DocumentManifest, DocumentKind
from app.ingestion import ManifestRegistry


def test_confirmed_public_document_requires_usage_terms() -> None:
    with pytest.raises(ValidationError):
        DocumentManifest(
            document_id="valid-doc-001", title="공개 규정", source_url="https://www.g2b.go.kr/", issuing_organization="조달청",
            collected_at=datetime.now(UTC), document_kind=DocumentKind.PDF, access_status=AccessStatus.CONFIRMED_PUBLIC,
            usage_terms_checked=False, usage_basis="저작권법 제7조",
        )


def test_confirmed_public_document_requires_usage_basis() -> None:
    with pytest.raises(ValidationError):
        DocumentManifest(
            document_id="valid-doc-002", title="공개 규정", source_url="https://www.law.go.kr/", issuing_organization="조달청",
            collected_at=datetime.now(UTC), document_kind=DocumentKind.HTML, access_status=AccessStatus.CONFIRMED_PUBLIC,
            usage_terms_checked=True,
        )


def test_unknown_document_requires_exclusion_reason() -> None:
    with pytest.raises(ValidationError):
        DocumentManifest(
            document_id="unknown-doc-001", title="확인 중 문서", source_url="https://www.g2b.go.kr/", issuing_organization="조달청",
            collected_at=datetime.now(UTC), document_kind=DocumentKind.PDF, access_status=AccessStatus.UNKNOWN,
            usage_terms_checked=False,
        )


def test_curated_procurement_rules_are_indexable_and_exclusions_remain_out() -> None:
    root = Path(__file__).resolve().parents[1]
    included = ManifestRegistry.from_json(root / "data" / "procurement-rules-manifest.json")
    excluded = ManifestRegistry.from_json(root / "data" / "excluded-sources.json")
    assert len(included.eligible()) == 30
    assert not included.excluded()
    assert not excluded.eligible()
    assert len(excluded.excluded()) == 2
