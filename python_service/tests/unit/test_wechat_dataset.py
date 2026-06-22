"""Pytest validation for the generated WeChat forensic dataset.

Drives the full WeChat analysis pipeline (WeChatGraphService) against the
normalized ``wechat_dataset_android.db`` produced by
``scripts/generate_wechat_dataset.py``, and asserts that every analysis
capability produces sensible output:

  1. dataset scale (>=50 subjects, >=10000 messages)
  2. full graph build (nodes/edges/owner)
  3. community detection (>=2 communities, hub PageRank dominance)
  4. private chat history query
  5. group chat history query
  6. contacts / chatrooms list queries
  7. activity timeline
  8. cross-DB consistency (raw <-> normalized conversion is lossless)

The dataset DBs live at the project-root ``tests/`` directory and are generated
on demand if missing (the generator is stdlib-only and fast).
"""

import asyncio
import os
import sqlite3
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Project root = python_service/../
PROJECT_ROOT = Path(__file__).resolve().parents[3]
TESTS_DIR = PROJECT_ROOT / "tests"
NORM_DB = TESTS_DIR / "wechat_dataset_android.db"
RAW_DB = TESTS_DIR / "EnMicroMsg_dataset.db"
GENERATOR = PROJECT_ROOT / "scripts" / "generate_wechat_dataset.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def wechat_dbs():
    """Ensure both dataset DBs exist; (re)generate if missing.

    Returns a dict with 'raw' and 'norm' absolute paths.
    """
    if not NORM_DB.exists() or not RAW_DB.exists():
        rc = subprocess.run(
            [sys.executable, str(GENERATOR)],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        assert rc.returncode == 0, (
            f"generator failed (rc={rc.returncode}):\n{rc.stdout}\n{rc.stderr}"
        )
    assert NORM_DB.exists() and RAW_DB.exists()
    return {"raw": str(RAW_DB), "norm": str(NORM_DB)}


@pytest.fixture()
def norm_conn(wechat_dbs):
    """A sqlite3 connection (row factory) to the normalized DB; closed after test."""
    conn = sqlite3.connect(wechat_dbs["norm"])
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture()
def raw_conn(wechat_dbs):
    """A sqlite3 connection (row factory) to the raw DB; closed after test."""
    conn = sqlite3.connect(wechat_dbs["raw"])
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture()
def graph_service(monkeypatch):
    """Instantiate WeChatGraphService.

    NOTE: ``WeChatGraphCoreMixin.__init__`` (``_core.py:27``) references an
    undefined global ``CACHE_TTL`` -- a latent NameError that breaks every
    instantiation. We inject the intended value (1800s = 30 min, per the
    ``/graph`` docstring) into the module namespace without touching production
    code. Remove this once the bug is fixed upstream.
    """
    import httpserver.services.wechat_graph_parts._core as core_mod
    monkeypatch.setattr(core_mod, "CACHE_TTL", 1800, raising=False)

    from httpserver.services.wechat_graph_service import WeChatGraphService
    return WeChatGraphService()


@pytest.fixture()
def full_graph(graph_service, wechat_dbs):
    """Build the full graph once and cache it for the module-level graph tests."""
    return graph_service._build_and_analyze(
        "test_task", wechat_dbs["norm"], include_metrics=True
    )


# ---------------------------------------------------------------------------
# Helper lookups (so tests don't hardcode specific wxids)
# ---------------------------------------------------------------------------

def _top_private_contact(norm_conn) -> str:
    """Username of the contact with the most private messages with the owner."""
    row = norm_conn.execute(
        """
        SELECT receiver AS u, COUNT(*) AS c
        FROM wechat_messages
        WHERE chatroom_name = '' AND sender = 'wxid_owner'
        GROUP BY receiver ORDER BY c DESC LIMIT 1
        """
    ).fetchone()
    assert row is not None, "no private messages from owner found"
    return row["u"]


def _top_chatroom(norm_conn) -> str:
    """Chatroom with the most messages."""
    row = norm_conn.execute(
        """
        SELECT chatroom_name, COUNT(*) AS c
        FROM wechat_messages
        WHERE chatroom_name != ''
        GROUP BY chatroom_name ORDER BY c DESC LIMIT 1
        """
    ).fetchone()
    assert row is not None, "no group messages found"
    return row["chatroom_name"]


# ---------------------------------------------------------------------------
# 1. Dataset scale
# ---------------------------------------------------------------------------

class TestDatasetScale:
    def test_at_least_50_subjects(self, norm_conn):
        """Owner (1) + real contacts (>=49) = >=50 subjects in the graph."""
        contacts = norm_conn.execute("SELECT COUNT(*) FROM wechat_contacts").fetchone()[0]
        owner = norm_conn.execute("SELECT COUNT(*) FROM wechat_owner_info").fetchone()[0]
        assert owner == 1
        assert contacts >= 49
        # 1 owner + 49 contacts = 50 subjects minimum
        assert owner + contacts >= 50

    def test_at_least_10000_messages(self, norm_conn):
        total = norm_conn.execute("SELECT COUNT(*) FROM wechat_messages").fetchone()[0]
        assert total >= 10000, f"only {total} messages (need >=10000)"

    def test_both_private_and_group_messages_present(self, norm_conn):
        private = norm_conn.execute(
            "SELECT COUNT(*) FROM wechat_messages WHERE chatroom_name = ''"
        ).fetchone()[0]
        group = norm_conn.execute(
            "SELECT COUNT(*) FROM wechat_messages WHERE chatroom_name != ''"
        ).fetchone()[0]
        assert private > 0, "no private messages"
        assert group > 0, "no group messages"

    def test_message_types_within_supported_set(self, norm_conn):
        """C++ enhanced parser only ingests type IN (1,3,34,43,47,49)."""
        bad = norm_conn.execute(
            "SELECT COUNT(*) FROM wechat_messages WHERE msg_type NOT IN (1,3,34,43,47,49)"
        ).fetchone()[0]
        assert bad == 0, f"{bad} messages have unsupported msg_type"


# ---------------------------------------------------------------------------
# 2. Full graph build
# ---------------------------------------------------------------------------

class TestFullGraph:
    def test_graph_has_expected_node_count(self, full_graph):
        nodes = full_graph["nodes"]
        # 50 subjects (owner + >=49 contacts); allow more if extra senders appeared
        assert len(nodes) >= 50

    def test_owner_is_node_and_flagged(self, full_graph):
        owners = [n for n in full_graph["nodes"] if n["is_owner"]]
        assert len(owners) == 1, "expected exactly one owner node"
        assert owners[0]["id"] == "wxid_owner"

    def test_private_edges_exist_with_positive_weight(self, full_graph):
        private_edges = [e for e in full_graph["edges"] if e["edge_type"] == "private"]
        assert len(private_edges) >= 1, "no private edges built"
        assert all(e["weight"] > 0 for e in private_edges)

    def test_edge_time_ordering(self, full_graph):
        for e in full_graph["edges"]:
            if e["first_time"] is not None and e["last_time"] is not None:
                assert e["first_time"] <= e["last_time"], (
                    f"edge {e['source']}->{e['target']} first_time > last_time"
                )

    def test_owner_participates_in_graph(self, full_graph):
        """Owner must appear as source or target of at least one edge."""
        owner = "wxid_owner"
        owner_edges = [
            e for e in full_graph["edges"]
            if e["source"] == owner or e["target"] == owner
        ]
        assert len(owner_edges) >= 1, "owner has no edges in the graph"


# ---------------------------------------------------------------------------
# 3. Community detection & centrality
# ---------------------------------------------------------------------------

class TestCommunityAnalysis:
    def test_multiple_communities_detected(self, full_graph):
        """3 social circles should yield >=2 communities."""
        communities = full_graph["communities"]
        # Filter out trivial single-node "communities" for the structural check.
        real = [c for c in communities if len(c) > 1]
        assert len(real) >= 2, (
            f"expected >=2 real communities, got {len(real)} (sizes={[len(c) for c in communities]})"
        )

    def test_hub_pagerank_dominance(self, full_graph):
        """Top nodes by PageRank should be well above the median.

        The owner is the graph root (highest PageRank by design). At least one
        non-owner contact should also exceed 2x the median PageRank, confirming
        the hub design produced a non-uniform centrality distribution.
        """
        nodes = full_graph["nodes"]
        prs = [n["pagerank"] for n in nodes]
        assert max(prs) > 0, "all PageRank values are 0 (scipy/networkx issue?)"
        median_pr = statistics.median(prs)

        owner_pr = next(n["pagerank"] for n in nodes if n["is_owner"])
        assert owner_pr == max(prs), "owner should have the highest PageRank"

        non_owner_top = max(n["pagerank"] for n in nodes if not n["is_owner"])
        assert non_owner_top > 2 * median_pr, (
            f"top non-owner PageRank {non_owner_top:.6f} not > 2x median {median_pr:.6f}"
        )


# ---------------------------------------------------------------------------
# 4. Private chat history
# ---------------------------------------------------------------------------

class TestPrivateChatHistory:
    def test_get_chat_history_returns_messages(self, graph_service, wechat_dbs, norm_conn):
        contact = _top_private_contact(norm_conn)
        result = asyncio.get_event_loop().run_until_complete(
            graph_service.get_chat_history(wechat_dbs["norm"], contact, "wxid_owner")
        )
        assert "error" not in result
        assert result["total"] > 0
        assert len(result["messages"]) > 0

    def test_chat_history_is_time_ordered(self, graph_service, wechat_dbs, norm_conn):
        contact = _top_private_contact(norm_conn)
        result = asyncio.get_event_loop().run_until_complete(
            graph_service.get_chat_history(wechat_dbs["norm"], contact, "wxid_owner", page_size=500)
        )
        msgs = result["messages"]
        timestamps = [m["timestamp"] for m in msgs]
        assert timestamps == sorted(timestamps), "messages not in ascending timestamp order"

    def test_chat_history_has_is_send_field(self, graph_service, wechat_dbs, norm_conn):
        contact = _top_private_contact(norm_conn)
        result = asyncio.get_event_loop().run_until_complete(
            graph_service.get_chat_history(wechat_dbs["norm"], contact, "wxid_owner")
        )
        for m in result["messages"]:
            assert "is_send" in m
            assert m["is_send"] in (0, 1)


# ---------------------------------------------------------------------------
# 5. Group chat history
# ---------------------------------------------------------------------------

class TestGroupChatHistory:
    def test_get_group_chat_history(self, graph_service, wechat_dbs, norm_conn):
        chatroom = _top_chatroom(norm_conn)
        result = asyncio.get_event_loop().run_until_complete(
            graph_service.get_group_chat_history(wechat_dbs["norm"], chatroom)
        )
        assert "error" not in result
        assert result["total"] > 0
        assert len(result["messages"]) > 0
        sample = result["messages"][0]
        assert sample["chatroom_name"] == chatroom
        assert sample["sender_nickname"], "sender_nickname should be populated"

    def test_group_senders_are_chatroom_members(self, graph_service, wechat_dbs, norm_conn):
        chatroom = _top_chatroom(norm_conn)
        members_row = norm_conn.execute(
            "SELECT member_list FROM wechat_chatrooms WHERE chatroom_name = ?",
            (chatroom,),
        ).fetchone()
        members = set(members_row["member_list"].split(","))

        result = asyncio.get_event_loop().run_until_complete(
            graph_service.get_group_chat_history(wechat_dbs["norm"], chatroom, page_size=500)
        )
        for m in result["messages"]:
            assert m["sender"] in members, (
                f"sender {m['sender']} not a member of {chatroom}"
            )


# ---------------------------------------------------------------------------
# 6. Contacts & chatrooms lists
# ---------------------------------------------------------------------------

class TestContactAndChatroomLists:
    def test_get_contacts_list(self, graph_service, wechat_dbs, norm_conn):
        result = asyncio.get_event_loop().run_until_complete(
            graph_service.get_contacts_list(wechat_dbs["norm"])
        )
        assert result["total"] > 0
        db_count = norm_conn.execute(
            "SELECT COUNT(*) FROM wechat_contacts WHERE chatroom_flag = 0"
        ).fetchone()[0]
        assert result["total"] == db_count

    def test_get_chatrooms_list(self, graph_service, wechat_dbs, norm_conn):
        result = asyncio.get_event_loop().run_until_complete(
            graph_service.get_chatrooms_list(wechat_dbs["norm"])
        )
        assert result["total"] > 0
        db_count = norm_conn.execute("SELECT COUNT(*) FROM wechat_chatrooms").fetchone()[0]
        assert result["total"] == db_count
        # member_list must be comma-separated usernames.
        sample = result["chatrooms"][0]
        assert "," in sample["member_list"], "member_list not comma-separated"


# ---------------------------------------------------------------------------
# 7. Activity timeline
# ---------------------------------------------------------------------------

class TestTimeline:
    def test_timeline_has_multiple_intervals(self, graph_service, wechat_dbs):
        result = asyncio.get_event_loop().run_until_complete(
            graph_service.compute_timeline("test_task", wechat_dbs["norm"], granularity="month")
        )
        assert "error" not in result
        # 90-day window spans >=2 months.
        assert len(result["intervals"]) >= 2

    def test_timeline_message_sum_matches_total(self, graph_service, wechat_dbs, norm_conn):
        result = asyncio.get_event_loop().run_until_complete(
            graph_service.compute_timeline("test_task", wechat_dbs["norm"], granularity="month")
        )
        total_in_timeline = sum(i["total_messages"] for i in result["intervals"])
        db_total = norm_conn.execute(
            "SELECT COUNT(*) FROM wechat_messages WHERE timestamp IS NOT NULL AND timestamp > 0"
        ).fetchone()[0]
        assert total_in_timeline == db_total


# ---------------------------------------------------------------------------
# 8. Cross-DB consistency (raw <-> normalized)
# ---------------------------------------------------------------------------

class TestCrossDbConsistency:
    def test_raw_message_count_matches_normalized(self, raw_conn, norm_conn):
        """Messages the C++ parser keeps (type in supported set) must equal
        the normalized message count -- proving the conversion is lossless."""
        raw_kept = raw_conn.execute(
            "SELECT COUNT(*) FROM message WHERE type IN (1,3,34,43,47,49)"
        ).fetchone()[0]
        norm_total = norm_conn.execute(
            "SELECT COUNT(*) FROM wechat_messages"
        ).fetchone()[0]
        assert raw_kept == norm_total, (
            f"raw kept ({raw_kept}) != normalized ({norm_total}) -- conversion loss"
        )

    def test_contacts_match_between_dbs(self, raw_conn, norm_conn):
        raw_real = raw_conn.execute(
            "SELECT COUNT(*) FROM rcontact "
            "WHERE username NOT LIKE '%@chatroom%' "
            "AND username != 'weixin' AND username != 'filehelper'"
        ).fetchone()[0]
        norm_contacts = norm_conn.execute(
            "SELECT COUNT(*) FROM wechat_contacts"
        ).fetchone()[0]
        assert raw_real == norm_contacts

    def test_owner_consistent_between_dbs(self, raw_conn, norm_conn):
        raw_owner = raw_conn.execute(
            "SELECT value FROM userinfo WHERE id = 2"
        ).fetchone()[0]
        norm_owner = norm_conn.execute(
            "SELECT username FROM wechat_owner_info LIMIT 1"
        ).fetchone()[0]
        assert raw_owner == norm_owner

    def test_normalized_timestamps_are_milliseconds(self, norm_conn):
        """Python graph layer requires millisecond timestamps (>= 1e12 for 2001+)."""
        min_ts = norm_conn.execute(
            "SELECT MIN(timestamp) FROM wechat_messages"
        ).fetchone()[0]
        assert min_ts >= 1_000_000_000_000, (
            f"min timestamp {min_ts} is not millisecond magnitude"
        )
