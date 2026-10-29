#!/usr/bin/env python3
"""End-to-end: one case with a phone acquisition *and* a WeChat import.

This is the scenario the second requirement is about — a big relationship graph
built from contacts/SMS/calls plus WeChat contacts and chats. The two sources
live in separate databases (a task ``android.db`` and an import ``graph.db``);
the unified layer merges them only where a strong identity key says they are
the same person.

Asserted here:

  * the phone number stored on a WeChat contact joins the WeChat identity to
    the dialler/SMS identity (one node, one set of edges);
  * a second dataset adds messages without duplicating the person;
  * same display name on different numbers stays two nodes, listed as a
    candidate merge;
  * the timeline merges both datasets and keeps per-dataset provenance;
  * no source database is modified.
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python_service"))

from httpserver.services.comm_graph.models import DatasetRef, GraphFilters  # noqa: E402
from httpserver.services.comm_graph.service import CommGraphService  # noqa: E402
from httpserver.services.comm_graph.timeline import build_timeline, edge_detail  # noqa: E402


def epoch(day: int, hour: int = 10) -> int:
    return int(datetime(2026, 4, day, hour, tzinfo=timezone.utc).timestamp())


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_task_db(path: Path) -> None:
    """android.db: dialler + SMS + inline WeChat, as the analysis stage writes it."""
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE contacts(id INTEGER PRIMARY KEY, display_name TEXT,
                phone_number TEXT);
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
        con.execute("INSERT INTO contacts VALUES (1,'张三','138-0013-8000'),"
                    "(2,'李四','13900139000'),(3,'王五','13700000001')")
        con.execute("INSERT INTO call_logs VALUES "
                    "(1,'+8613800138000',0,125,1,'张三',?),"
                    "(2,'13800138000',0,0,3,'张三',?),"
                    "(3,'13900139000',0,45,2,'李四',?)",
                    (epoch(1), epoch(2), epoch(3)))
        con.execute("INSERT INTO sms_messages VALUES "
                    "(1,'13800138000','张三',0,1,'钱准备好了吗',?),"
                    "(2,'13900139000','李四',0,2,'收到',?)",
                    (epoch(4), epoch(5)))
        con.execute("INSERT INTO wechat_owner_info VALUES "
                    "(1,'wxid_owner','本人',10001,'')")
        con.execute("INSERT INTO wechat_contacts VALUES "
                    "(1,'wxid_zhangsan','张三','张总','',1,0,'13800138000'),"
                    "(2,'wxid_lisi','李四','','',1,0,''),"
                    "(3,'wxid_wangwu_a','王五','','',1,0,'13700000001'),"
                    "(4,'wxid_silent','沉默者','','',1,0,'')")
        con.execute("INSERT INTO wechat_chatrooms VALUES "
                    "(1,'10001@chatroom','wxid_zhangsan',"
                    "'wxid_zhangsan,wxid_lisi,wxid_silent',3,0)")
        con.executemany(
            "INSERT INTO wechat_messages(sender, receiver, content, timestamp, "
            "is_send, chatroom_name, msg_type) VALUES (?,?,?,?,?,?,1)",
            [("wxid_owner", "wxid_zhangsan", "在吗", epoch(6) * 1000, 1, ""),
             ("wxid_zhangsan", "wxid_owner", "在", epoch(7) * 1000, 0, ""),
             ("wxid_lisi", "10001@chatroom", "群消息", epoch(8) * 1000, 0,
              "10001@chatroom")])


def build_import_db(path: Path) -> None:
    """graph.db from a WeChat import: only the wechat_* tables."""
    with sqlite3.connect(path) as con:
        con.executescript("""
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
        con.execute("INSERT INTO wechat_owner_info VALUES "
                    "(1,'wxid_owner','本人',10001,'')")
        con.execute("INSERT INTO wechat_contacts VALUES "
                    "(1,'wxid_zhangsan','张三','','',1,0,''),"
                    "(2,'wxid_zhaoliu','赵六','','',1,0,''),"
                    "(3,'wxid_wangwu_b','王五','','',1,0,'13700000002')")
        con.executemany(
            "INSERT INTO wechat_messages(sender, receiver, content, timestamp, "
            "is_send, chatroom_name, msg_type) VALUES (?,?,?,?,?,?,1)",
            [("wxid_owner", "wxid_zhangsan", "换个地方说", epoch(9) * 1000, 1, ""),
             ("wxid_owner", "wxid_zhaoliu", "文件已发", epoch(10) * 1000, 1, "")])


def build(refs, **filters):
    return CommGraphService(None).build_graph(list(refs), GraphFilters(**filters))


def node_by_label(node_list, label):
    return [node for node in node_list if node.label == label]


def node_by_identity(node_list, kind, value):
    return [node for node in node_list if value in node.identities.get(kind, [])]


def main() -> int:
    with __import__("tempfile").TemporaryDirectory(prefix="comm-e2e-") as temp:
        root = Path(temp)
        task_db = root / "android.db"
        import_db = root / "graph.db"
        build_task_db(task_db)
        build_import_db(import_db)
        digests = {path: file_digest(path) for path in (task_db, import_db)}

        task_ref = DatasetRef(kind="task", id="case-phone", path=str(task_db),
                              label="手机检材")
        import_ref = DatasetRef(kind="wechat_import", id="abcdef123456",
                                path=str(import_db), label="微信导入")
        refs = [task_ref, import_ref]

        # ---- identity merging ------------------------------------------------
        merged = build(refs)
        # The WeChat contact carries the dialler number, so the wxid and the
        # phone must collapse into one node. The display label is the contact
        # remark ("张总"), which is why the lookup is by identity.
        zhang = node_by_identity(merged.nodes, "phone", "13800138000")
        check(len(zhang) == 1,
              f"the WeChat contact's stored number must merge both identities; "
              f"got {len(zhang)} nodes")
        zhang = zhang[0]
        check("phone" in zhang.identities and "wxid" in zhang.identities,
              f"merged node lost an identity: {zhang.identities}")
        check("wxid_zhangsan" in zhang.identities["wxid"],
              f"wrong WeChat identity merged: {zhang.identities}")
        check(zhang.label == "张总",
              f"the contact remark is the most specific label, got {zhang.label!r}")
        check(zhang.call_count == 2, f"expected 2 calls for 张三, got {zhang.call_count}")
        check(zhang.sms_count == 1, f"expected 1 SMS for 张三, got {zhang.sms_count}")
        check(zhang.message_count >= 3,
              f"messages from both datasets must land on one node, got {zhang.message_count}")
        check({"task:case-phone", "wechat_import:abcdef123456"} <= set(zhang.datasets),
              f"merged node is missing a dataset: {zhang.datasets}")

        # A WeChat contact with no stored number keeps its own identity: there
        # is no evidence linking it to the dialler contact of the same name.
        lisi_phone = node_by_identity(merged.nodes, "phone", "13900139000")
        lisi_wxid = node_by_identity(merged.nodes, "wxid", "wxid_lisi")
        check(len(lisi_phone) == 1 and len(lisi_wxid) == 1,
              "a number-less WeChat identity must stay separate")
        check(lisi_phone[0].id != lisi_wxid[0].id,
              "name-only matching must never merge identities")
        check(any(candidate["name"] == "李四" and candidate["auto_merged"] is False
                  for candidate in merged.candidates),
              "the same-name pair must surface as a merge candidate")

        # ---- same name, different numbers: never auto-merged -----------------
        wangwu = node_by_label(merged.nodes, "王五")
        check(len(wangwu) == 2,
              f"two different numbers sharing a name must stay apart, got {len(wangwu)}")
        check(any(candidate["name"] == "王五" and candidate["auto_merged"] is False
                  for candidate in merged.candidates),
              "the same-name pair must be listed as a candidate, not merged")

        # ---- silent group member is still present ---------------------------
        group_nodes = [node for node in merged.nodes if node.kind == "group"]
        check(len(group_nodes) == 1, "the chatroom must be a node")
        member_edges = [edge for edge in merged.edges if edge.relation == "group_member"]
        labels = {node.id: node.label for node in merged.nodes}
        members = {labels[edge.source] for edge in member_edges}
        check("沉默者" in members, f"a silent member must be linked, got {members}")

        # ---- one owner hub across datasets ----------------------------------
        owners = [node for node in merged.nodes if node.is_owner]
        check(len(owners) == 1,
              f"both datasets share the same wxid owner, expected 1 hub, got {len(owners)}")

        # ---- edges keep their dataset on the split view ---------------------
        split = build(refs, include_union=False)
        im_edges = [edge for edge in split.edges if edge.relation == "im_private"]
        check({edge.dataset for edge in im_edges} ==
              {"task:case-phone", "wechat_import:abcdef123456"},
              "split view must keep each dataset's own edges")
        union_edges = [edge for edge in merged.edges
                       if edge.relation == "im_private"
                       and edge.dataset == "union"]
        check(bool(union_edges), "union view must collapse cross-dataset pairs")

        # ---- time filter ----------------------------------------------------
        window = build(refs, start_time=epoch(9))
        check(all(edge.last_time is None or edge.last_time >= epoch(9)
                  for edge in window.edges),
              "time filter must drop edges that ended before the window")
        check(window.coverage["messages_read"] == merged.coverage["messages_read"],
              "coverage reports what was scanned, not what the filter kept")

        # ---- timeline -------------------------------------------------------
        timeline = build_timeline(refs, limit=200)
        datasets = {record["dataset"] for record in timeline["records"]}
        check(datasets == {"task:case-phone", "wechat_import:abcdef123456"},
              f"timeline must keep both datasets, got {datasets}")
        stamps = [record["timestamp"] for record in timeline["records"]]
        check(stamps == sorted(stamps), "timeline must be chronological")
        check(all(record["record_ref"] for record in timeline["records"]),
              "every timeline row needs a record reference")
        check(timeline["coverage"]["dedup_rule"] == "dataset+record_ref:v1",
              "dedup rule must be declared")

        # ---- edge drill-down resolves through the same identity rules -------
        owner = owners[0]
        detail = edge_detail(refs, source=owner.id, target=zhang.id,
                             relation="im_private")
        check(detail["total"] >= 3,
              f"drill-down must find the pair's records in both datasets, "
              f"got {detail['total']}")
        check({record["dataset"] for record in detail["records"]} ==
              {"task:case-phone", "wechat_import:abcdef123456"},
              "drill-down must span both datasets")

        # ---- no source database was modified --------------------------------
        for path, before in digests.items():
            check(file_digest(path) == before,
                  f"read-only violation: {path.name} changed")

    print("CROSS-DATASET COMM E2E: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
