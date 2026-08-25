from __future__ import annotations

import json
from pathlib import Path

from app.schemas import DocumentManifest


class ManifestRegistry:
    def __init__(self, records: list[DocumentManifest]):
        self.records = {record.document_id: record for record in records}

    @classmethod
    def from_json(cls, path: Path) -> "ManifestRegistry":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls([DocumentManifest.model_validate(item) for item in payload])

    def eligible(self) -> list[DocumentManifest]:
        return [record for record in self.records.values() if record.eligible_for_indexing]

    def excluded(self) -> list[DocumentManifest]:
        return [record for record in self.records.values() if not record.eligible_for_indexing]

    def require_eligible(self, document_id: str) -> DocumentManifest:
        record = self.records[document_id]
        if not record.eligible_for_indexing:
            raise PermissionError(record.exclusion_reason or "색인 대상이 아닌 문서입니다.")
        return record
