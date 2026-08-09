"""Regression tests for the WeChat graph FastAPI routes.

These guard against the route-split bug where ``_resolve_android_db_path``,
``_get_service`` and ``_now_iso`` were referenced by name inside the endpoint
modules (``wechat_graph_endpoints/_graph.py`` and ``_data.py``) but never
imported — producing a ``NameError`` and a HTTP 500 on every request.

The tests assert two things:

1. The three helpers are bound in each endpoint module's namespace (static
   import check — the direct regression for the ``NameError``).
2. A live request to ``/api/wechat/graph`` for an unknown task returns 404
   (database-not-found), NOT 500. A 500 here would mean the handler blew up
   before/inside the resolver — i.e. the ``NameError`` is back.
"""

import pytest


def test_endpoint_modules_have_helpers_bound():
    """The route-split must import the shared helpers into each module."""
    from httpserver.routes.wechat_graph_endpoints import _data, _graph

    for module in (_graph, _data):
        for name in ("_resolve_android_db_path", "_get_service", "_now_iso"):
            assert hasattr(module, name), (
                f"{module.__name__} is missing {name}; every /api/wechat/* "
                "request would raise NameError -> HTTP 500"
            )


def test_graph_endpoint_returns_404_not_500_for_unknown_task(test_client):
    """Unknown task -> 404 from the db resolver, never a 500 from a NameError.

    A 500 (or a NameError surfacing as 500) means the endpoint module failed
    to import the shared helpers — the original regression.
    """
    response = test_client.get("/api/wechat/graph", params={"task_id": "does-not-exist"})
    assert response.status_code != 500, (
        "WeChat graph endpoint returned 500 — likely the route-split NameError "
        f"regression. Body: {response.text}"
    )
    assert response.status_code == 404
