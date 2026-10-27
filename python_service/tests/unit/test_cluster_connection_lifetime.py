"""Cluster loops must release SQLite handles without relying on cyclic GC."""
import gc
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from httpserver.services.case_analysis import cluster_budget, cluster_jobs, schema
from httpserver.services.case_analysis.cluster_analyzer import _connect_events
from httpserver.services.model_budget import ModelBudgetError
from httpserver.config import Settings
from httpserver.services.case_analysis.cluster_analyzer import _prepare_cluster_candidates
from httpserver.services.case_analysis import cluster_revision


def test_events_connection_commits_rolls_back_and_closes(tmp_path):
    path = str(tmp_path / 'events.db')
    with _connect_events(path) as conn:
        conn.execute('CREATE TABLE values_test(value TEXT)')
        conn.execute('INSERT INTO values_test VALUES (?)', ('已提交',))
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute('SELECT 1')
    with pytest.raises(RuntimeError):
        with _connect_events(path) as failed:
            failed.execute('INSERT INTO values_test VALUES (?)', ('应回滚',))
            raise RuntimeError('rollback')
    with pytest.raises(sqlite3.ProgrammingError):
        failed.execute('SELECT 1')
    with _connect_events(path) as check:
        assert [row[0] for row in check.execute('SELECT * FROM values_test')] == ['已提交']
        assert check.execute("SELECT CAST(x'ff' AS TEXT)").fetchone()[0] == '\ufffd'


@pytest.mark.skipif(not Path('/proc/self/fd').exists(), reason='Linux FD regression')
def test_cluster_budget_and_polling_do_not_leak_without_gc(tmp_path):
    path = str(tmp_path / 'events.db')
    schema.ensure_cluster_analysis_schema(path)
    cluster_budget.create(path, 'plan', 120, 100000)
    job, _ = cluster_jobs.create(path, 'task')
    gc.collect()
    before = len(os.listdir('/proc/self/fd'))
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        for i in range(120):
            with cluster_budget.bind(path, 'plan', str(i)):
                cluster_budget.reserve(10, 10)
            cluster_jobs.update(path, job['job_id'], detail=str(i))
            assert cluster_jobs.read(path, job['job_id'])['detail'] == str(i)
            assert schema.read_bucket_epoch_offset(path) == 0
            with _connect_events(path) as db:
                assert db.execute('SELECT 1').fetchone()[0] == 1
        with pytest.raises(ModelBudgetError):
            with cluster_budget.bind(path, 'plan', 'overflow'):
                cluster_budget.reserve(10, 10)
        cluster_jobs.request_cancel(path, job['job_id'])
        assert cluster_jobs.read(path, job['job_id'])['status'] == 'cancel_requested'
        assert len(os.listdir('/proc/self/fd')) <= before + 2
        with closing(sqlite3.connect(path)) as db:
            assert db.execute('SELECT used_calls FROM cluster_model_budget').fetchone()[0] == 120
            assert db.execute('SELECT COUNT(*) FROM cluster_model_ledger').fetchone()[0] == 120
    finally:
        if was_enabled:
            gc.enable()


def test_large_cluster_freshness_uses_one_select_and_preserves_budget_identity(tmp_path, monkeypatch):
    path = str(tmp_path / 'events.db')
    schema.ensure_cluster_analysis_schema(path)
    config = Settings()
    clusters = [{'bucket_epoch_offset': 0, 'bucket_seconds': 60, 'time_window': i,
                 'event_type': 'CREATED', 'parent_directory': '/test/', 'members_hash': str(i)}
                for i in range(2000)]
    statements = []
    original = sqlite3.connect
    def traced(*args, **kwargs):
        conn = original(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(sqlite3, 'connect', traced)
    pending, fresh = _prepare_cluster_candidates(path, 'task', clusters, config, '', 60, 0, 200)
    assert len(pending) == 2000 and fresh == 0
    assert len([s for s in statements if s.lstrip().upper().startswith('SELECT')]) == 1
    expected = cluster_revision.digest({'task_id': 'task', 'context': cluster_revision.context_hash(config, ''),
        'calls': 2000, 'tokens': 2000 * config.llm_context_length, 'window': 60, 'offset': 0,
        'clusters': sorted((c['event_type'], c['time_window'], c['parent_directory'], c['members_hash']) for c in clusters)})
    assert all(c['budget_plan_id'] == expected for c in pending)
    with cluster_budget.bind(path, expected, 'source'):
        cluster_budget.reserve(10, 10)
    _prepare_cluster_candidates(path, 'task', clusters, config, '', 60, 0, 200)
    with closing(original(path)) as db:
        assert db.execute('SELECT used_calls FROM cluster_model_budget').fetchone()[0] == 1
