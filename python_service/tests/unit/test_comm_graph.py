"""Unified communication graph: identity merging, edge aggregation, coverage.

The fixtures build two fully independent source databases (an ``android.db``
with contacts/calls/SMS/inline WeChat, and an import-style ``graph.db`` with
only the wechat_* tables) so dataset merging is exercised for real.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from httpserver.services.comm_graph.datasets import resolve_datasets
from httpserver.services.comm_graph.models import (
    DatasetRef,
    GraphFilters,
    normalize_phone,
)
from httpserver.services.comm_graph.timeline import build_timeline, edge_detail
from httpserver.services.comm_graph.service import CommGraphService


def epoch(day=1, hour=10):
    return int(datetime(2026, 3, day, hour, tzinfo=timezone.utc).timestamp())


def build_task_db(path):
    """android.db written by the analysis layer (phone + inline WeChat)."""
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE contacts(id INTEGER PRIMARY KEY, display_name TEXT, phone_number TEXT);
            CREATE TABLE call_logs(id INTEGER PRIMARY KEY, number TEXT, date INTEGER,
                duration INTEGER, type INTEGER, name TEXT, date_seconds INTEGER);
            CREATE TABLE sms_messages(id INTEGER PRIMARY KEY, address TEXT, person TEXT,
                date INTEGER, type INTEGER, body TEXT, date_seconds INTEGER);
            CREATE TABLE wechat_messages(id INTEGER PRIMARY KEY, sender TEXT, receiver TEXT,
                content TEXT, timestamp INTEGER, media_type TEXT, msg_type INTEGER,
                is_send INTEGER, chatroom_name TEXT, sender_nickname TEXT, talker TEXT);
            CREATE TABLE wechat_contacts(id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                nickname TEXT, remark TEXT, avatar_path TEXT, type INTEGER,
                chatroom_flag INTEGER DEFAULT 0, mobile TEXT);
            CREATE TABLE wechat_chatrooms(id INTEGER PRIMARY KEY, chatroom_name TEXT UNIQUE,
                owner TEXT, member_list TEXT, member_count INTEGER, create_time INTEGER);
            CREATE TABLE wechat_owner_info(id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                nickname TEXT, uin INTEGER, imei TEXT);
        """)
        db.execute("INSERT INTO contacts VALUES (1,'张三','138-0013-8000'),(2,'李四','13900139000')")
        db.execute("INSERT INTO call_logs VALUES "
                   "(1,'+8613800138000',0,65,1,'张三',?),(2,'13900139000',0,0,3,'李四',?)",
                   (epoch(1), epoch(2)))
        db.execute("INSERT INTO sms_messages VALUES "
                   "(1,'13800138000','张三',0,1,'晚点到',?),(2,'13900139000','李四',0,2,'收到',?)",
                   (epoch(3), epoch(4)))
        db.execute("INSERT INTO wechat_owner_info VALUES (1,'wxid_owner','本人',12345,'')")
        db.execute("INSERT INTO wechat_contacts VALUES "
                   "(1,'wxid_zhangsan','张三','张三','',1,0,'13800138000'),"
                   "(2,'wxid_lisi','李四','','',1,0,''),"
                   "(3,'wxid_silent','沉默者','','',1,0,'')")
        db.execute("INSERT INTO wechat_chatrooms VALUES "
                   "(1,'12345@chatroom','wxid_zhangsan','wxid_zhangsan,wxid_lisi,wxid_silent',3,0)")
        db.executemany(
            "INSERT INTO wechat_messages(sender, receiver, content, timestamp, is_send, "
            "chatroom_name, msg_type) VALUES (?,?,?,?,?,?,1)",
            [("wxid_owner", "wxid_zhangsan", "你好", epoch(5) * 1000, 1, ""),
             ("wxid_zhangsan", "wxid_owner", "在", epoch(6) * 1000, 0, ""),
             ("wxid_lisi", "12345@chatroom", "群消息", epoch(7) * 1000, 0, "12345@chatroom")])


def build_import_db(path):
    """graph.db produced by a WeChat import (wechat_* only)."""
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE wechat_messages(id INTEGER PRIMARY KEY, sender TEXT, receiver TEXT,
                content TEXT, timestamp INTEGER, media_type TEXT, msg_type INTEGER,
                is_send INTEGER, chatroom_name TEXT, sender_nickname TEXT, talker TEXT);
            CREATE TABLE wechat_contacts(id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                nickname TEXT, remark TEXT, avatar_path TEXT, type INTEGER,
                chatroom_flag INTEGER DEFAULT 0, mobile TEXT);
            CREATE TABLE wechat_chatrooms(id INTEGER PRIMARY KEY, chatroom_name TEXT UNIQUE,
                owner TEXT, member_list TEXT, member_count INTEGER, create_time INTEGER);
            CREATE TABLE wechat_owner_info(id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                nickname TEXT, uin INTEGER, imei TEXT);
        """)
        db.execute("INSERT INTO wechat_owner_info VALUES (1,'wxid_owner','本人',12345,'')")
        db.execute("INSERT INTO wechat_contacts VALUES (1,'wxid_zhangsan','张三','','',1,0,'')")
        db.execute("INSERT INTO wechat_contacts VALUES (2,'wxid_wangwu','王五','','',1,0,'')")
        db.executemany(
            "INSERT INTO wechat_messages(sender, receiver, content, timestamp, is_send, "
            "chatroom_name, msg_type) VALUES (?,?,?,?,?,?,1)",
            [("wxid_owner", "wxid_zhangsan", "另一份证据里的消息", epoch(8) * 1000, 1, ""),
             ("wxid_wangwu", "wxid_owner", "我是王五", epoch(9) * 1000, 0, "")])


@pytest.fixture
def sources(tmp_path):
    task_db = tmp_path / "android.db"
    import_db = tmp_path / "graph.db"
    build_task_db(task_db)
    build_import_db(import_db)
    return (
        DatasetRef(kind="task", id="T1", path=str(task_db), label="手机检材 case"),
        DatasetRef(kind="wechat_import", id="abcdef123456", path=str(import_db),
                   label="微信导入 abcdef12"),
    )


def graph(sources, **kwargs):
    service = CommGraphService(SimpleNamespace())
    return service.build_graph(list(sources), GraphFilters(**kwargs))


def node_by_label(result, label):
    matches = [n for n in result.nodes if n.label == label]
    assert len(matches) == 1, f"expected exactly one {label!r}, got {[n.label for n in result.nodes]}"
    return matches[0]


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_phone_normalization_strips_separators_and_country_code():
    assert normalize_phone("138-0013-8000") == "13800138000"
    assert normalize_phone("+86 138 0013 8000") == "13800138000"
    assert normalize_phone("008613800138000") == "13800138000"
    assert normalize_phone("10086") == "10086"
    assert normalize_phone("") == ""
    assert normalize_phone("abc") == ""


def test_cross_source_edges_merge_on_phone_identity(sources):
    result = graph(sources)
    zhang = node_by_label(result, "张三")
    # Call (1) + SMS (1) + two private WeChat messages across both datasets.
    assert zhang.call_count == 1
    assert zhang.sms_count == 1
    assert zhang.message_count >= 2
    assert "task:T1" in zhang.datasets
    assert "wechat_import:abcdef123456" in zhang.datasets


def test_same_name_different_identity_is_not_auto_merged(tmp_path):
    db = tmp_path / "android.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE contacts(id INTEGER PRIMARY KEY, display_name TEXT, phone_number TEXT);
            CREATE TABLE call_logs(id INTEGER PRIMARY KEY, number TEXT, date INTEGER,
                duration INTEGER, type INTEGER, name TEXT, date_seconds INTEGER);
            CREATE TABLE sms_messages(id INTEGER PRIMARY KEY, address TEXT, person TEXT,
                date INTEGER, type INTEGER, body TEXT, date_seconds INTEGER);
        """)
        # Two distinct numbers share one display name.
        conn.execute("INSERT INTO contacts VALUES (1,'王五','13700000001'),(2,'王五','13700000002')")
    ref = DatasetRef(kind="task", id="T2", path=str(db), label="t")
    result = graph([ref])
    same_name = [n for n in result.nodes if n.label == "王五"]
    assert len(same_name) == 2, "same name must not be merged automatically"
    assert any(c["reason"] == "same_display_name_different_identities"
               for c in result.candidates)
    assert all(c["auto_merged"] is False for c in result.candidates)


def test_owner_hub_exists_without_wechat_owner_record(sources):
    """MIUI/Meiya datasets have no wechat_owner_info; calls still need a hub."""
    task_ref = sources[0]
    with sqlite3.connect(task_ref.path) as conn:
        conn.execute("DELETE FROM wechat_owner_info")
    result = graph([task_ref])
    owners = [n for n in result.nodes if n.is_owner]
    assert len(owners) == 1
    # Calls and SMS must still be connected to that hub.
    assert result.coverage["calls_read"] == 2
    assert any(edge.relation == "call" for edge in result.edges)
    assert result.coverage["owner_unknown_datasets"] == 1


def test_group_members_include_silent_participants(sources):
    result = graph(sources)
    groups = [n for n in result.nodes if n.kind == "group"]
    assert groups, "chatroom must become a node"
    member_edges = [e for e in result.edges if e.relation == "group_member"]
    labels = {n.id: n.label for n in result.nodes}
    members = {labels[e.source] for e in member_edges}
    assert "沉默者" in members, "a member who never spoke must still be linked"


# ---------------------------------------------------------------------------
# Edges / limits / coverage
# ---------------------------------------------------------------------------


def test_union_merges_same_pair_and_keeps_dataset_on_split_view(sources):
    merged = graph(sources, include_union=True)
    zhang = node_by_label(merged, "张三")
    im_edges = [e for e in merged.edges if e.relation == "im_private"
                and zhang.id in (e.source, e.target)]
    assert len(im_edges) == 1, "union view must collapse the pair into one edge"
    assert im_edges[0].dataset == "union"
    assert len(im_edges[0].record_refs) >= 2

    split = graph(sources, include_union=False)
    split_edges = [e for e in split.edges if e.relation == "im_private"]
    # Directed edges: each dataset contributes one edge per direction.
    assert len(split_edges) == 4
    assert {e.dataset for e in split_edges} == {"task:T1", "wechat_import:abcdef123456"}
    assert {e.direction for e in split_edges} == {"sent", "received"}


def test_time_filter_drops_out_of_range_edges(sources):
    result = graph(sources, start_time=epoch(5), end_time=epoch(6))
    assert all(edge.relation.startswith("im_") for edge in result.edges
               if edge.first_time is not None)
    assert result.coverage["calls_read"] == 2  # scanned, not necessarily shown
    assert not any(edge.relation == "call" for edge in result.edges)


def test_node_limit_reports_truncation_instead_of_hiding_it(sources):
    result = graph(sources, max_nodes=2)
    assert result.coverage["nodes_shown"] == 2
    assert result.coverage["nodes_truncated"] == result.coverage["nodes_total"] - 2


def test_unreadable_dataset_is_disclosed(tmp_path):
    missing = DatasetRef(kind="task", id="T3", path=str(tmp_path / "gone.db"), label="x")
    service = CommGraphService(SimpleNamespace())
    result = service.build_graph([missing], GraphFilters())
    assert result.coverage["datasets_unavailable"] == 1
    assert result.datasets == []


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def test_timeline_merges_sources_chronologically(sources):
    result = build_timeline(list(sources), limit=100)
    stamps = [record["timestamp"] for record in result["records"]]
    assert stamps == sorted(stamps)
    datasets = {record["dataset"] for record in result["records"]}
    assert datasets == {"task:T1", "wechat_import:abcdef123456"}
    assert result["coverage"]["dedup_rule"] == "dataset+record_ref:v1"


def test_timeline_filters_by_kind_and_range(sources):
    only_sms = build_timeline(list(sources), kinds={"sms"}, limit=100)
    assert {record["kind"] for record in only_sms["records"]} == {"sms"}

    window = build_timeline(list(sources), start_time=epoch(3), end_time=epoch(4), limit=100)
    assert all(epoch(3) <= record["timestamp"] <= epoch(4)
               for record in window["records"])


def test_timeline_states_truncation(sources):
    result = build_timeline(list(sources), limit=2)
    assert result["coverage"]["records_returned"] == 2
    assert result["coverage"]["records_truncated"] == result["coverage"]["records_total"] - 2


def test_edge_detail_returns_only_matching_records(sources):
    result = graph(sources)
    zhang = node_by_label(result, "张三")
    owner = next(n for n in result.nodes if n.is_owner)
    detail = edge_detail(list(sources), source=owner.id, target=zhang.id,
                         relation="im_private")
    assert detail["total"] >= 2
    assert all(record["kind"] == "im_private" for record in detail["records"])


# ---------------------------------------------------------------------------
# Dataset resolution
# ---------------------------------------------------------------------------


def test_resolve_uses_task_android_db(tmp_path):
    db = tmp_path / "android.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE contacts(id INTEGER, display_name TEXT, phone_number TEXT)")
    task = {"id": "T9", "image_path": "/cases/case.bin", "output_files_db": str(db)}
    refs, unavailable = resolve_datasets(task)
    assert unavailable == []
    # resolve_android_db looks for the sibling android.db of output_files_db.
    assert refs and refs[0].id == "T9"


def test_resolve_rejects_bad_import_id(tmp_path):
    task = {"id": "T9", "output_files_db": str(tmp_path / "files.db")}
    with pytest.raises(ValueError):
        resolve_datasets(task, wechat_imports=["../../etc"])
