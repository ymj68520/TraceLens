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


def test_graph_endpoint_heals_empty_import_graph_db(test_client, tmp_path, monkeypatch):
    """空 graph.db 残留的 wx_ 导入：图谱端点先自愈再应答，而非返回无边空图。

    演示导入缺陷回归：旧构建中断留下的空 graph.db 被路由当有效数据，
    GET /api/wechat/graph 返回 200 + 零边（联系人节点仍在，前端却显示
    「未发现聊天记录关系数据」）。读取路径现在应先重建 graph.db。
    """
    import sqlite3

    import httpserver.services.wechat_import_service as wis
    from httpserver.services.wechat_import_service import WeChatImportService
    from tests.unit.test_wechat_forensics_import import (
        IMEI, OWNER_WXID, UIN, _build_plain_db,
    )

    storage = tmp_path / "imports"
    storage.mkdir()
    monkeypatch.setattr(wis, "import_root", lambda: str(storage))

    plain = str(tmp_path / "plain.db")
    _build_plain_db(plain)
    svc = WeChatImportService()
    result = svc._create_import_sync(
        plain, "演示导入", "", None, None,
        {"uin": UIN, "imei": IMEI, "wxid": OWNER_WXID, "account_dir": "t"},
        "unit-test",
    )
    assert result["status"] == "ready", result
    graph_db = svc._graph_db_path(result["import_id"])

    # 复现旧缺陷现场：构建中断留下的空消息表（联系人仍在）
    con = sqlite3.connect(graph_db)
    con.execute("DELETE FROM wechat_messages")
    con.commit()
    con.close()

    response = test_client.get(
        "/api/wechat/graph", params={"task_id": f"wx_{result['import_id']}"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["edges"], (
        "graph endpoint answered an edgeless graph for an import that has "
        "messages — ensure_graph_db did not heal the empty graph.db"
    )
