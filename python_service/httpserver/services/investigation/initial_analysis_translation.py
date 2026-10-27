"""Chinese reading overlay for immutable Initial Analysis snapshots.

The source snapshot and files.db are never modified; translations are keyed
by the exact source digest and stored in a separate cache. Inference uses a
local Argos model and never sends evidence text to a network service.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

from .offline_translation import OfflineArgosTranslator, OfflineTranslationError

PROMPT_VERSION = "initial-analysis-zh:offline-v1"


class TranslationUnavailable(Exception):
    """Translation failed; callers should retain the original snapshot text."""


def needs_chinese_translation(text: str) -> bool:
    latin = sum(char.isascii() and char.isalpha() for char in text)
    han = sum("\u4e00" <= char <= "\u9fff" for char in text)
    return latin >= 40 and latin > han * 1.5


class InitialAnalysisTranslationCache:
    def __init__(self, db_path: Path, translator: OfflineArgosTranslator):
        self.db_path = Path(db_path)
        self.translator = translator
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    def _lookup(self, task_id: str, evidence_key: str, source_hash: str) -> tuple[str, str] | None:
        if not self.db_path.is_file():
            return None
        uri = f"file:{quote(str(self.db_path.resolve()), safe='/')}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=10) as conn:
            conn.execute("PRAGMA query_only=ON")
            row = conn.execute(
                "SELECT translated_text, model FROM initial_analysis_translations "
                "WHERE task_id=? AND evidence_key=? AND source_hash=? AND prompt_version=?",
                (task_id, evidence_key, source_hash, PROMPT_VERSION),
            ).fetchone()
        return (row[0], row[1]) if row else None

    def _store(self, task_id: str, evidence_key: str, source_hash: str, text: str, model: str) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS initial_analysis_translations (
                task_id TEXT NOT NULL,
                evidence_key TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (task_id, evidence_key, source_hash, prompt_version)
            )""")
            conn.execute(
                "INSERT OR REPLACE INTO initial_analysis_translations "
                "(task_id,evidence_key,source_hash,prompt_version,translated_text,model,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (task_id, evidence_key, source_hash, PROMPT_VERSION, text, model, int(time.time())),
            )

    def purge_task(self, task_id: str) -> int:
        """Drop every cached translation for a deleted task.

        The cache is keyed by task id and holds derived text only, so it is
        safe to regenerate; leaving it behind just accumulates rows no task
        can ever read again.
        """
        if not self.db_path.is_file():
            return 0
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='initial_analysis_translations'"
            ).fetchone()
            if not has_table:
                return 0
            cursor = conn.execute(
                "DELETE FROM initial_analysis_translations WHERE task_id=?", (task_id,)
            )
            conn.commit()
            return cursor.rowcount

    async def translate(
        self,
        task_id: str,
        evidence_key: str,
        source_text: str,
        *,
        evidence_name: str = "",
    ) -> dict:
        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        if not needs_chinese_translation(source_text):
            return {
                "text": source_text, "translated": False,
                "cached": False, "source_hash": source_hash, "model": None,
            }

        key = (task_id, evidence_key, source_hash)
        async with self._locks.setdefault(key, asyncio.Lock()):
            cached = await asyncio.to_thread(self._lookup, *key)
            if cached:
                return {
                    "text": cached[0], "translated": True,
                    "cached": True, "source_hash": source_hash, "model": cached[1],
                }
            try:
                translated, model = await asyncio.to_thread(self.translator.translate, source_text)
            except OfflineTranslationError as exc:
                raise TranslationUnavailable(str(exc)) from exc
            if len(re.findall(r"[\u4e00-\u9fff]", translated)) < 10:
                raise TranslationUnavailable("model did not return Chinese text")
            if evidence_name and evidence_name in source_text and evidence_name not in translated:
                raise TranslationUnavailable("translation changed the evidence filename")
            await asyncio.to_thread(self._store, *key, translated, model)
            return {
                "text": translated, "translated": True,
                "cached": False, "source_hash": source_hash, "model": model,
            }
