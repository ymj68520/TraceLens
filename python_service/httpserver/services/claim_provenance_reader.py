"""Read-only historical Claim provenance access for report trace-back."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional


class ClaimProvenanceReader:
    """Read one task-scoped Event Claim without opening the write lifecycle."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(str(self.db_path))
        uri = f"file:{self.db_path.resolve()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _warnings(value: Any) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return [str(value)]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [str(parsed)]

    def get_claim(self, task_id: str, claim_id: str) -> Optional[Dict[str, Any]]:
        """Return the immutable Claim row and its task-scoped evidence links."""
        with self._connect() as connection:
            claim = connection.execute(
                "SELECT id, task_id, event_id, event_version_id, claim_text, "
                "claim_type, status, grounding_status, grounding_warnings, "
                "origin, confidence, created_at, accepted_at, rejected_at "
                "FROM event_claims WHERE task_id = ? AND id = ?",
                (task_id, claim_id),
            ).fetchone()
            if claim is None:
                return None

            links = connection.execute(
                "SELECT link.evidence_key, link.relation, link.rationale "
                "FROM event_claim_evidence AS link "
                "JOIN event_claims AS owner ON owner.id = link.claim_id "
                "WHERE owner.task_id = ? AND owner.id = ? "
                "ORDER BY link.evidence_key",
                (task_id, claim_id),
            ).fetchall()

        result = dict(claim)
        result["claim_id"] = result.pop("id")
        result["grounding_warnings"] = self._warnings(result.get("grounding_warnings"))
        result["evidence_links"] = [dict(link) for link in links]
        return result
