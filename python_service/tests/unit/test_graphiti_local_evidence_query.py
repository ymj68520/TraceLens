"""The local KG must be anchored to an exact task-owned file-path entity."""

from unittest.mock import AsyncMock

import pytest

from httpserver.services.graphiti_parts._query import GraphitiQueryMixin


@pytest.mark.asyncio
async def test_local_query_uses_exact_path_and_task_scoped_neighbours():
    query = GraphitiQueryMixin()
    query._run_read_query = AsyncMock(side_effect=[
        [{"id": "path", "name": "/case/a.txt", "labels": ["Entity"], "summary": "file"}],
        [{"id": "owner", "name": "Administrator", "labels": ["Entity"],
          "summary": "user", "source": "path", "target": "owner", "relation": "OWNED_BY"}],
    ])

    nodes, links = await query.get_local_graph_data("task-a", "/case/a.txt", 10)

    assert [node["name"] for node in nodes] == ["/case/a.txt", "Administrator"]
    assert links == [{"source": "path", "target": "owner", "label": "OWNED_BY"}]
    first, second = query._run_read_query.call_args_list
    assert first.args[1] == {"gid": "task-a", "path": "/case/a.txt"}
    assert "seed:Entity {name: $path}" in first.args[0]
    assert second.args[1]["gid"] == "task-a"
    assert "r.group_id = $gid" in second.args[0]
    assert "[:MENTIONS]->(neighbor)" in second.args[0]


@pytest.mark.asyncio
async def test_no_exact_file_path_has_no_graph_or_basename_fallback():
    query = GraphitiQueryMixin()
    query._run_read_query = AsyncMock(return_value=[])

    assert await query.get_local_graph_data("task-a", "/other/a.txt", 10) == ([], [])
    query._run_read_query.assert_awaited_once()
