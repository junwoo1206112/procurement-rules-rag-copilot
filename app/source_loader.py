from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from app.parsers import ParsedBlock, parse_html_text
from app.schemas import DocumentManifest

ALLOWED_HOSTS = {"law.go.kr", "www.law.go.kr"}
RFP_ALLOWED_HOSTS = {"g2b.go.kr", "www.g2b.go.kr"}
RFP_SUFFIXES = {".pdf", ".hwpx"}
ARTICLE_PREFIX = "\uc81c"
ARTICLE_SUFFIX = "\uc870"
ARTICLE_PATTERN = re.compile(rf"({ARTICLE_PREFIX}\s*\d+\s*{ARTICLE_SUFFIX}(?:\uc758\s*\d+)?(?:\s*\([^)]{{1,80}}\))?)")


@dataclass(frozen=True)
class SourceReceipt:
    document_id: str
    collected_at: datetime
    sha256: str
    blocks: list[ParsedBlock]


def verify_rfp_attachment(url: str, usage_basis: str, opener=urlopen) -> tuple[str, bytes]:
    """Gate RFP attachments before parsing/indexing; caller must record the receipt."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in RFP_ALLOWED_HOSTS:
        raise ValueError("RFP 첨부자료는 공식 나라장터 HTTPS 도메인만 허용합니다.")
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in RFP_SUFFIXES and not parsed.path.endswith("downloadFile.do"):
        raise ValueError("RFP 첨부자료는 PDF 또는 HWPX만 허용합니다.")
    if not usage_basis.strip():
        raise ValueError("RFP 첨부자료의 이용 근거가 필요합니다.")
    with opener(Request(url, headers={"User-Agent": "ProcurementRulesRAG/0.1"}), timeout=20) as response:
        disposition = response.headers.get("Content-Disposition", "")
        filename_match = re.search(r"filename\*?=(?:UTF-8''|\")?([^;\"]+)", disposition, re.I)
        response_suffix = Path(filename_match.group(1)).suffix.lower() if filename_match else suffix
        if response_suffix not in RFP_SUFFIXES:
            raise ValueError("응답 파일 형식이 PDF 또는 HWPX인지 확인할 수 없습니다.")
        payload = response.read(10_000_001)
    if len(payload) > 10_000_000:
        raise ValueError("RFP 첨부자료 크기가 허용 한도를 초과했습니다.")
    preview = payload.decode("utf-8", errors="ignore")
    if re.search(r"\b\d{6}[-\s]?\d{7}\b|\b01[0-9][-\s]?\d{3,4}[-\s]?\d{4}\b", preview):
        raise ValueError("개인정보 패턴이 감지되어 RFP 첨부자료를 제외했습니다.")
    return hashlib.sha256(payload).hexdigest(), payload


def reject_pii_blocks(blocks: list[ParsedBlock]) -> None:
    """Run after PDF/HWPX parsing because binary previews cannot reveal all text."""
    text = "\n".join(block.text for block in blocks)
    if re.search(r"\b\d{6}[-\s]?\d{7}\b|\b01[0-9][-\s]?\d{3,4}[-\s]?\d{4}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
        raise ValueError("파싱된 RFP 본문에서 개인정보 패턴이 감지되었습니다.")


def fetch_verified_html(manifest: DocumentManifest, opener=urlopen) -> SourceReceipt:
    parsed = urlparse(str(manifest.source_url))
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("허용되지 않은 원문 도메인입니다.")
    request = Request(str(manifest.source_url), headers={"User-Agent": "ProcurementRulesRAG/0.1"})
    with opener(request, timeout=15) as response:
        payload = response.read(5_000_001)
    if len(payload) > 5_000_000:
        raise ValueError("원문 크기가 허용 한도를 초과했습니다.")
    text = payload.decode("utf-8", errors="replace")
    if _normalized(manifest.title) not in _normalized(text):
        raise ValueError("원문 제목이 매니페스트와 일치하지 않습니다.")
    return SourceReceipt(
        document_id=manifest.document_id,
        collected_at=datetime.now(UTC),
        sha256=hashlib.sha256(payload).hexdigest(),
        blocks=parse_html_text(text),
    )


def fetch_verified_admin_rule_json(manifest: DocumentManifest, opener=urlopen) -> SourceReceipt:
    """Fetch the official administrative-rule body API using local LAW_API_OC."""
    oc = _law_api_oc()
    sequence = _sequence_from_url(str(manifest.source_url))
    query = urlencode({"OC": oc, "target": "admrul", "ID": sequence, "type": "JSON"})
    request = Request(f"https://www.law.go.kr/DRF/lawService.do?{query}", headers={"User-Agent": "ProcurementRulesRAG/0.1"})
    with opener(request, timeout=20) as response:
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError("원문 크기가 허용 한도를 초과했습니다.")
    payload = json.loads(raw.decode("utf-8"))
    text = json.dumps(payload, ensure_ascii=False)
    if _normalized(manifest.title) not in _normalized(text) or f"{ARTICLE_PREFIX}1{ARTICLE_SUFFIX}" not in text:
        raise ValueError("공식 API 본문 검증에 실패했습니다.")
    articles = re.split(rf"(?=(?:{ARTICLE_PREFIX}\s*\d+\s*{ARTICLE_SUFFIX}))", _strings(payload))
    blocks = [
        ParsedBlock(None, item.strip(), "text", "law-api-json", 0.99, _article_section(item))
        for item in articles
        if len(item.strip()) > 30
    ]
    if not any(block.section for block in blocks):
        raise ValueError("공식 API 조항 구조를 찾지 못했습니다.")
    return SourceReceipt(manifest.document_id, datetime.now(UTC), hashlib.sha256(raw).hexdigest(), blocks)


def _law_api_oc() -> str:
    value = os.getenv("LAW_API_OC")
    if value:
        return value
    env_path = Path(__file__).parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("LAW_API_OC="):
                return line.split("=", 1)[1].strip()
    raise ValueError("LAW_API_OC 환경변수가 필요합니다.")


def _sequence_from_url(url: str) -> str:
    match = re.search(r"admRulSeq=(\d+)", url)
    if not match:
        raise ValueError("행정규칙 일련번호를 찾을 수 없습니다.")
    return match.group(1)


def _strings(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(_strings(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_strings(item) for item in value)
    return value if isinstance(value, str) else ""


def _article_section(value: str) -> str | None:
    """Keep the legal article label as citation provenance when API fields are flattened."""
    match = ARTICLE_PATTERN.search(value)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else None


def _normalized(value: str) -> str:
    return "".join(value.split()).lower()
