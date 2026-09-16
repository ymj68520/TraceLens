"""KG hardening Phase B (SPEC docs/specs/kg-ingestion-hardening.md §A2/§A3).

Read-path contract pins:
- one shared pooled Neo4j driver (no per-request drivers),
- every read query bounded by a hard timeout,
- /status counts are index-direct on group_id,
- list_task_graphs is served from a 5 s cache.
"""

import asyncio
import sys
import time
import unittest.mock as mock
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from httpserver.services.graphiti_service import GraphitiService


class FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)
        self.consumed = False

    def __aiter__(self):
        return self._agen()

    async def _agen(self):
        for row in self._rows:
            yield row

    async def consume(self):
        self.consumed = True


class FakeSession:
    def __init__(self, driver):
        self._driver = driver

    async def __aenter__(self):
        self._driver.sessions_opened += 1
        return self

    async def __aexit__(self, *exc):
        return False

    async def run(self, query, **params):
        self._driver.queries.append((query, params))
        if self._driver.hang_forever:
            await asyncio.sleep(3600)
        return FakeResult(self._driver.rows_by_query.get(query, [{"cnt": 0}]))


class FakeDriver:
    def __init__(self, rows_by_query=None, hang_forever=False):
        self.rows_by_query = rows_by_query or {}
        self.hang_forever = hang_forever
        self.sessions_opened = 0
        self.queries = []
        self.closed = False

    def session(self):
        return FakeSession(self)

    async def close(self):
        self.closed = True


def _service(driver_factory):
    """GraphitiService with mocked settings and a stubbed driver factory."""
    svc = GraphitiService.__new__(GraphitiService)
    svc.settings = mock.Mock()
    svc.settings.neo4j_uri = "neo4j://127.0.0.1:7687"
    svc.settings.neo4j_user = "neo4j"
    svc.settings.neo4j_password = "x"
    svc.neo4j_connect_timeout = 5.0
    svc.neo4j_query_timeout = 5.0
    type(svc.settings).neo4j_connect_timeout = mock.PropertyMock(return_value=5.0)
    type(svc.settings).neo4j_query_timeout = mock.PropertyMock(return_value=5.0)
    svc._initialized = False
    svc._graphiti = None
    svc._jobs = {}
    svc._task_graphs = {}
    svc._neo_driver = None
    svc._task_graphs_cache = None
    svc._task_graphs_cache_at = 0.0
    svc._driver_factory = driver_factory
    return svc


def _patch_driver(svc, driver):
    """Patch the lazy neo4j import inside _get_shared_driver."""
    return mock.patch(
        "neo4j.AsyncGraphDatabase.driver",
        side_effect=lambda *a, **k: driver,
    )


class TestSharedDriver:
    @pytest.mark.asyncio
    async def test_driver_created_once_and_reused(self):
        driver = FakeDriver(rows_by_query={
            "MATCH (n:Entity {group_id: $gid}) RETURN count(n) AS cnt": [{"cnt": 7}],
            "MATCH ()-[r:RELATES_TO {group_id: $gid}]->() RETURN count(r) AS cnt": [{"cnt": 4}],
        })
        svc = _service(None)
        with _patch_driver(svc, driver) as factory:
            c1 = await svc._query_neo4j_counts("task-1")
            c2 = await svc._query_neo4j_counts("task-1")

        assert c1 == (7, 4)
        assert c2 == (7, 4)
        assert factory.call_count == 1  # pooled, not per-request

    @pytest.mark.asyncio
    async def test_counts_are_index_direct(self):
        driver = FakeDriver()
        svc = _service(None)
        with _patch_driver(svc, driver):
            await svc._query_neo4j_counts("task-1")

        entity_q, rel_q = [q for q, _ in driver.queries]
        assert "Entity {group_id: $gid}" in entity_q
        assert "MENTIONS" not in entity_q
        assert "RELATES_TO {group_id: $gid}" in rel_q

    @pytest.mark.asyncio
    async def test_shutdown_closes_shared_driver(self):
        driver = FakeDriver()
        svc = _service(None)
        with _patch_driver(svc, driver):
            await svc._check_neo4j_connection()
            await svc.shutdown()
        assert driver.closed is True
        assert svc._neo_driver is None


class TestReadTimeout:
    @pytest.mark.asyncio
    async def test_hung_query_fails_fast(self):
        driver = FakeDriver(hang_forever=True)
        svc = _service(None)
        with _patch_driver(svc, driver):
            with pytest.raises(asyncio.TimeoutError):
                await svc._run_read_query("RETURN 1", timeout=0.05)

    @pytest.mark.asyncio
    async def test_connection_check_degrades_to_false(self):
        driver = FakeDriver(hang_forever=True)
        svc = _service(None)
        with _patch_driver(svc, driver):
            assert await svc._check_neo4j_connection() is False


class TestTaskGraphsCache:
    @pytest.mark.asyncio
    async def test_second_call_within_ttl_hits_cache(self):
        driver = FakeDriver(rows_by_query={
            "MATCH (e:Episodic) WHERE e.group_id IS NOT NULL "
            "RETURN DISTINCT e.group_id AS gid LIMIT 1000": [
                {"gid": "a"}, {"gid": "b"},
            ],
        })
        svc = _service(None)
        with _patch_driver(svc, driver):
            first = await svc.list_task_graphs()
            second = await svc.list_task_graphs()

        assert first == ["a", "b"]
        assert second == ["a", "b"]
        assert len(driver.queries) == 1  # cached

    @pytest.mark.asyncio
    async def test_delete_invalidates_cache(self):
        driver = FakeDriver(rows_by_query={
            "MATCH (e:Episodic) WHERE e.group_id IS NOT NULL "
            "RETURN DISTINCT e.group_id AS gid LIMIT 1000": [{"gid": "a"}],
        })
        svc = _service(None)
        with _patch_driver(svc, driver):
            await svc.list_task_graphs()
            await svc.delete_task_graph("a")
            await svc.list_task_graphs()

        list_query = (
            "MATCH (e:Episodic) WHERE e.group_id IS NOT NULL "
            "RETURN DISTINCT e.group_id AS gid LIMIT 1000"
        )
        assert sum(1 for q, _ in driver.queries if q == list_query) == 2

    @pytest.mark.asyncio
    async def test_ttl_expiry_requeries(self):
        driver = FakeDriver(rows_by_query={
            "MATCH (e:Episodic) WHERE e.group_id IS NOT NULL "
            "RETURN DISTINCT e.group_id AS gid LIMIT 1000": [{"gid": "a"}],
        })
        svc = _service(None)
        with _patch_driver(svc, driver):
            await svc.list_task_graphs()
            svc._task_graphs_cache_at -= 6.0  # age past the 5 s TTL
            await svc.list_task_graphs()

        assert len(driver.queries) == 2
