"""Additive tables owned by InvestigationRepository, with immutable run artifacts."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from ..investigation.repository import InvestigationRepository
from ..evidence.exceptions import EvidenceStoreError
from .models import digest

DDL = (
    """CREATE TABLE IF NOT EXISTS graph_analysis_runs (
        run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, base_run_id TEXT,
        operation TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','completed','failed','cancelled')),
        owner_epoch TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT,
        phase TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, input_json TEXT NOT NULL,
        input_hash TEXT NOT NULL, result_json TEXT, result_hash TEXT, error TEXT)""",
    "CREATE INDEX IF NOT EXISTS graph_analysis_task ON graph_analysis_runs(task_id,created_at,run_id)",
    """CREATE UNIQUE INDEX IF NOT EXISTS graph_analysis_active ON graph_analysis_runs(task_id)
        WHERE status='running'""",
    """CREATE TRIGGER IF NOT EXISTS graph_analysis_input_immutable BEFORE UPDATE ON graph_analysis_runs
        WHEN NEW.run_id != OLD.run_id OR NEW.task_id != OLD.task_id OR NEW.input_json != OLD.input_json
        OR NEW.input_hash != OLD.input_hash OR NEW.actor != OLD.actor OR NEW.owner_epoch != OLD.owner_epoch
        OR NEW.operation != OLD.operation OR NEW.created_at != OLD.created_at
        OR NEW.base_run_id IS NOT OLD.base_run_id
        BEGIN SELECT RAISE(ABORT,'graph analysis input is immutable'); END""",
    """CREATE TRIGGER IF NOT EXISTS graph_analysis_terminal_immutable BEFORE UPDATE ON graph_analysis_runs
        WHEN OLD.status != 'running'
        BEGIN SELECT RAISE(ABORT,'graph analysis terminal is immutable'); END""",
)


def install(conn):
    for sql in DDL:
        conn.execute(sql)


def now():
    return datetime.now(timezone.utc).isoformat()


class RunConflict(ValueError):
    pass


class PeopleGraphStore:
    def __init__(self, path, task_id):
        self.path, self.task_id = Path(path), task_id

    def prepare(self):
        repo = InvestigationRepository(self.path, self.task_id)
        repo.prepare_graph_analysis_storage()

    def _connect(self, write=False):
        conn = sqlite3.connect(f"file:{quote(str(self.path.resolve()), safe='/')}?mode={'rw' if write else 'ro'}",
                               uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        if not write:
            conn.execute("PRAGMA query_only=ON")
        return conn

    def _exists(self, conn):
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='graph_analysis_runs'").fetchone()

    @staticmethod
    def _decode(row, with_result=False):
        value = dict(row)
        frozen = json.loads(value.pop("input_json"))
        if digest(frozen) != value["input_hash"]:
            raise EvidenceStoreError("graph input integrity check failed")
        value["input"] = frozen
        raw = value.pop("result_json")
        if raw is not None and with_result:
            result = json.loads(raw)
            if digest(result) != value["result_hash"]:
                raise EvidenceStoreError("graph result integrity check failed")
            value["result"] = result
        return value

    def list(self, operations=None):
        if not self.path.is_file():
            return []
        with closing(self._connect()) as conn:
            if not self._exists(conn):
                return []
            clause = " AND operation IN (" + ",".join("?" for _ in operations) + ")" if operations else ""
            rows = conn.execute("SELECT run_id,task_id,base_run_id,operation,status,owner_epoch,actor,created_at,"
                                "completed_at,phase,progress,input_json,input_hash,NULL AS result_json,result_hash,error "
                                "FROM graph_analysis_runs WHERE task_id=?" + clause + " ORDER BY created_at DESC,run_id DESC LIMIT 100",
                                (self.task_id, *(operations or ()))).fetchall()
            return [self._decode(row) for row in rows]

    def get(self, run_id, with_result=True):
        if not self.path.is_file():
            return None
        with closing(self._connect()) as conn:
            if not self._exists(conn):
                return None
            row = conn.execute("SELECT * FROM graph_analysis_runs WHERE task_id=? AND run_id=?",
                               (self.task_id, run_id)).fetchone()
            return self._decode(row, with_result) if row else None

    def admit(self, frozen, actor, epoch, operation, base_run_id=None):
        self.prepare()
        run_id = "pg_" + uuid.uuid4().hex
        with closing(self._connect(True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE graph_analysis_runs SET status='failed', error='服务重启中断了本轮分析',completed_at=? "
                         "WHERE task_id=? AND status='running' AND owner_epoch!=?", (now(), self.task_id, epoch))
            try:
                conn.execute("INSERT INTO graph_analysis_runs(run_id,task_id,base_run_id,operation,status,owner_epoch,actor,"
                             "created_at,phase,input_json,input_hash) VALUES (?,?,?,?,'running',?,?,?,'queued',?,?)",
                             (run_id, self.task_id, base_run_id, operation, epoch, actor, now(),
                              json.dumps(frozen, ensure_ascii=False), digest(frozen)))
            except sqlite3.IntegrityError as exc:
                raise RunConflict("当前任务已有图谱分析在运行") from exc
        return self.get(run_id)

    def progress(self, run_id, phase, progress):
        with closing(self._connect(True)) as conn, conn:
            conn.execute("UPDATE graph_analysis_runs SET phase=?,progress=? WHERE task_id=? AND run_id=? AND status='running'",
                         (phase, progress, self.task_id, run_id))

    def finish(self, run_id, result=None, error=None, cancelled=False):
        status = "cancelled" if cancelled else "failed" if error else "completed"
        with closing(self._connect(True)) as conn, conn:
            conn.execute("UPDATE graph_analysis_runs SET status=?,completed_at=?,phase=?,progress=?,result_json=?,result_hash=?,error=? "
                         "WHERE task_id=? AND run_id=? AND status='running'",
                         (status, now(), status, 100 if status == "completed" else 0,
                          json.dumps(result, ensure_ascii=False) if result is not None else None,
                          digest(result) if result is not None else None, error, self.task_id, run_id))
