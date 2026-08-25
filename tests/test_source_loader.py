from datetime import UTC, datetime
import json

import pytest

from app.schemas import AccessStatus, DocumentKind, DocumentManifest
from app.chunking import build_chunks
from app.source_loader import ARTICLE_PREFIX, ARTICLE_SUFFIX, fetch_verified_admin_rule_json, fetch_verified_html, reject_pii_blocks, verify_rfp_attachment


class _Response:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit: int) -> bytes:
        return self.payload


def _manifest(url: str = "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=1") -> DocumentManifest:
    return DocumentManifest(
        document_id="source-rule-001", title="조달청 계약 규정", source_url=url, issuing_organization="조달청",
        collected_at=datetime.now(UTC), document_kind=DocumentKind.HTML, access_status=AccessStatus.CONFIRMED_PUBLIC,
        usage_terms_checked=True, usage_basis="저작권법 제7조 제2호",
    )


def test_verified_html_returns_hash_and_structured_blocks() -> None:
    payload = "<h1>조달청 계약 규정</h1><p>제1조 목적</p>".encode("utf-8")
    receipt = fetch_verified_html(_manifest(), opener=lambda *_args, **_kwargs: _Response(payload))
    assert len(receipt.sha256) == 64
    assert receipt.blocks[0].text.startswith("#")


def test_untrusted_source_is_rejected_before_network_access() -> None:
    with pytest.raises(ValueError, match="허용되지 않은"):
        fetch_verified_html(_manifest("https://example.com/rule.html"), opener=lambda *_args, **_kwargs: None)


def test_title_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="제목"):
        fetch_verified_html(_manifest(), opener=lambda *_args, **_kwargs: _Response(b"<h1>\xeb\x8b\xa4\xeb\xa5\xb8 \xeb\xac\xb8\xec\x84\x9c</h1>"))


def test_admin_rule_json_keeps_article_section(monkeypatch) -> None:
    monkeypatch.setattr("app.source_loader._law_api_oc", lambda: "test-oc")
    payload = json.dumps({
        "name": _manifest().title,
        "body": f"{ARTICLE_PREFIX}1{ARTICLE_SUFFIX}(\ubaa9\uc801) first article body contains enough source text for chunking validation. "
                f"{ARTICLE_PREFIX}2{ARTICLE_SUFFIX}(\uc801\uc6a9\ubc94\uc704) second article body contains enough source text for chunking validation.",
    }, ensure_ascii=False).encode("utf-8")
    receipt = fetch_verified_admin_rule_json(_manifest(), opener=lambda *_args, **_kwargs: _Response(payload))
    chunks = build_chunks(_manifest(), receipt.blocks)
    assert [chunk.section for chunk in chunks] == ["\uc81c1\uc870(\ubaa9\uc801)", "\uc81c2\uc870(\uc801\uc6a9\ubc94\uc704)"]


def test_rfp_attachment_rejects_untrusted_url_and_pii() -> None:
    with pytest.raises(ValueError, match="공식"):
        verify_rfp_attachment("https://example.com/rfp.pdf", "공개 확인", opener=lambda *_args, **_kwargs: None)
    with pytest.raises(ValueError, match="개인정보"):
        verify_rfp_attachment("https://www.g2b.go.kr/files/rfp.pdf", "공개 확인", opener=lambda *_args, **_kwargs: _Response(b"010-1234-5678"))


def test_rfp_parsed_text_with_email_is_rejected() -> None:
    from app.parsers import ParsedBlock
    with pytest.raises(ValueError, match="개인정보"):
        reject_pii_blocks([ParsedBlock(1, "contact@example.com", "text", "fixture", 1.0)])
