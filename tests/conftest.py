from datetime import UTC, datetime

import pytest

from app.parsers import ParsedBlock
from app.schemas import AccessStatus, DocumentManifest, DocumentKind


@pytest.fixture
def manifest() -> DocumentManifest:
    return DocumentManifest(
        document_id="demo-notice-001", title="디지털 행정 서비스 구축 제안요청서", source_url="https://www.g2b.go.kr/",
            issuing_organization="조달청", collected_at=datetime(2026, 8, 20, tzinfo=UTC),
            document_kind=DocumentKind.PDF, access_status=AccessStatus.CONFIRMED_PUBLIC, usage_terms_checked=True,
            usage_basis="테스트용 합성 공개 문서",
            notice_number="2026-001",
    )


@pytest.fixture
def blocks() -> list[ParsedBlock]:
    return [
        ParsedBlock(1, "# 입찰 참가 자격", "text", "fixture", 1.0),
        ParsedBlock(1, "입찰 참가자는 소프트웨어 사업자 신고를 완료하고 최근 3년 이내 유사 사업 실적을 제출해야 합니다.", "text", "fixture", 1.0),
        ParsedBlock(2, "# 제출 서류", "text", "fixture", 1.0),
        ParsedBlock(2, "제안서, 가격입찰서, 사업자등록증 사본을 2026년 9월 1일 18시까지 제출합니다.", "text", "fixture", 1.0),
        ParsedBlock(3, "평가항목 | 배점\n기술평가 | 80\n가격평가 | 20", "table", "fixture", 1.0),
    ]
