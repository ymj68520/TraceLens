#!/usr/bin/env python3
"""Generate a realistic WeChat forensic test dataset.

Produces two SQLite databases that together drive the full WeChat analysis
pipeline end-to-end:

1. tests/EnMicroMsg_dataset.db  -- raw EnMicroMsg.db schema
   Replicates the 4 tables the C++ parser reads (AndroidDataParsers.cpp):
     message (talker, content, createTime[sec], type, isSend)
     rcontact (username, nickname, conRemark, type, chatroomFlag)
     chatroom (chatroomname, roomowner, memberlist, membercount, addtime)
     userinfo (id, value)   -- id=2 -> username, id=4 -> nickname
   Group message content uses the real "wxid_xxx:\\n<body>" format.

2. tests/wechat_dataset_android.db  -- normalized _android.db schema
   Replicates parseWeChatEnhanced() transformation into the 4 wechat_* tables
   the Python WeChatGraphService reads. Timestamps are converted to MILLISECONDS.

Design goals (with defaults ~50 subjects, ~12k conversations):
  - 1 owner + 49 real contacts (+ weixin + filehelper system rows)
  - 3 social circles (family / colleague / friend) -> separable Louvain communities
  - 1-2 hub contacts per circle (high PageRank / betweenness)
  - 10 chatrooms, circle-clustered + 2 cross-circle bridge rooms
  - ~7000 private messages (power-law over ~25 active contacts)
  - ~5000 group messages, clustered in time to produce co-activity edges
  - msg_type in {1,3,34,43,47,49} with text dominant

Idempotent: rm -f before create. Only stdlib + sqlite3 (matches
scripts/create_test_data.py convention).

Usage:
    python3 scripts/generate_wechat_dataset.py [--seed N] [--scale 1.0]
"""

from __future__ import annotations

import argparse
import os
import random
import sqlite3
import string
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SEED = 20240601
DEFAULT_SCALE = 1.0

# Start/end of the 90-day message window (UTC). createTime is in SECONDS for
# the raw table (matches the gtest fixture convention 1700000001).
WINDOW_START = datetime(2024, 1, 1, 0, 0, 0)
WINDOW_END = datetime(2024, 3, 31, 23, 59, 59)
WINDOW_SECONDS = int((WINDOW_END - WINDOW_START).total_seconds())

# Message types kept by the C++ enhanced parser (parseWeChatEnhanced).
SUPPORTED_MSG_TYPES = (1, 3, 34, 43, 47, 49)
# Weighted distribution: text dominates.
MSG_TYPE_WEIGHTS = {1: 70, 3: 8, 34: 8, 43: 4, 47: 6, 49: 4}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DB_PATH = os.path.join(PROJECT_ROOT, "tests", "EnMicroMsg_dataset.db")
NORM_DB_PATH = os.path.join(PROJECT_ROOT, "tests", "wechat_dataset_android.db")

# ---------------------------------------------------------------------------
# Content pools (Chinese, realistic WeChat-style)
# ---------------------------------------------------------------------------

FAMILY_NAMES = list("王李张刘陈杨黄赵周吴徐孙马朱胡郭何高林郑谢罗梁宋唐许韩冯邓曹彭肖田董袁潘")
GIVEN_NAMES = [
    "伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "军", "洋",
    "勇", "艳", "杰", "娟", "涛", "明", "超", "霞", "平", "刚",
    "桂英", "晓东", "建国", "志强", "建华", "文博", "子涵", "梓萱", "浩然", "若曦",
    "嘉怡", "俊豪", "雨彤", "梓豪", "诗涵", "宇轩", "梦琪", "歆瑶", "瑞霖", "锦程",
]

# Three social circles with distinct messaging styles.
CIRCLE_WORK = "colleague"
CIRCLE_FAMILY = "family"
CIRCLE_FRIEND = "friend"

MSG_TEMPLATES: Dict[str, List[str]] = {
    CIRCLE_WORK: [
        "项目进展怎么样了？", "明天上午十点开会，别迟到。", "这份文档你帮忙review一下。",
        "客户那边催了，咱们加快进度。", "代码已经提交到dev分支了。", "这个bug我来修复。",
        "下周的评审材料准备好了吗？", "辛苦了，周末加班搞定它。", "需求又变了，重新评估一下排期。",
        "测试环境的账号发我一下。", "线上有个告警，帮忙看看。", "会议纪要我整理好发群里。",
        "这个功能上线前再回归一遍。", "年终述职的PPT改完了吗？", "团建订在周五，大家确认下。",
        "报销单走流程了，注意填写规范。", "新来的实习生你带一下。", "绩效面谈安排在下午。",
        "这个接口返回的数据格式不对。", "合并代码前先跑一遍单测。",
    ],
    CIRCLE_FAMILY: [
        "妈，我这周末回家。", "吃饭了没？", "天气冷了，多穿点。",
        "钱够花吗？我给你转点。", "身体怎么样？按时吃药。", "新年快乐，阖家幸福！",
        "爷爷的体检报告出来了，问题不大。", "晚上视频聊一下吧。", "孩子期末考得怎么样？",
        "家里的宽带我帮你续费了。", "记得早点休息，别熬夜。", "中秋快乐，记得吃月饼。",
        "下周全家去郊游怎么样？", "表弟结婚，记得来喝喜酒。", "菜谱发你了，照着做就行。",
        "血压有点高，少盐少油。", "生日快乐！", "年终奖发了请全家吃饭。",
        "快递我帮你拿了，放门口了。", "开车注意安全。",
    ],
    CIRCLE_FRIEND: [
        "周末一起打球吗？", "晚上约个饭？", "最近忙啥呢？",
        "这部电影挺好看的，推荐给你。", "游戏上线了，一起开黑？", "借我本书，下次还你。",
        "旅游的照片整理好发你。", "生日快乐！", "好久不见了，聚一聚？",
        "这家店味道不错，改天去试试。", "考试怎么样？过了吧？", "搬家需要帮忙说一声。",
        "演唱会票抢到了！", "考研复习得怎么样？", "健身房办卡了，一起锻炼？",
        "新出的手游要不要一起玩？", "周末去爬山吗？", "帮我砍一刀拼多多。",
        "这个段子笑死我了哈哈哈", "借你的充电宝下次还你。",
    ],
}

# Non-text type content placeholders.
MEDIA_CONTENT = {
    3: "[图片]",
    34: "[语音]",
    43: "[视频]",
    47: "[表情]",
    49: "[文件]",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Contact:
    username: str          # wxid_xxx
    nickname: str
    remark: str            # 备注名 (owner-set alias); "" if none
    circle: str            # CIRCLE_*
    is_hub: bool = False


@dataclass
class Chatroom:
    chatroom_name: str     # xxx@chatroom
    owner: str             # wxid of owner member
    members: List[str] = field(default_factory=list)  # wxid list
    circle: str = CIRCLE_FRIEND  # dominant circle (or "bridge" for cross-circle)
    create_time: int = 0   # seconds


@dataclass
class RawMessage:
    """A row of the raw `message` table."""
    talker: str            # wxid for private, xxx@chatroom for group
    content: str           # body for private; "wxid_xxx:\nbody" for group
    create_time: int       # SECONDS
    type: int              # msg_type in SUPPORTED_MSG_TYPES
    is_send: int           # 1 if owner sent, 0 if received


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def gen_wxid(rng: random.Random, idx: int) -> str:
    """Stable wxid like wxid_abc123."""
    suffix = "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    return f"wxid_{idx:02d}{suffix}"


def gen_name(rng: random.Random) -> str:
    return rng.choice(FAMILY_NAMES) + rng.choice(GIVEN_NAMES)


def build_contacts(rng: random.Random) -> Tuple[Contact, List[Contact]]:
    """Build owner + 49 real contacts split into 3 circles with hubs."""
    owner = Contact(username="wxid_owner", nickname="机主", remark="", circle="owner")

    contacts: List[Contact] = []
    circles = [CIRCLE_FAMILY, CIRCLE_WORK, CIRCLE_FRIEND]
    # ~16 per circle -> 48, plus 1 extra to reach 49 real contacts.
    per_circle = {CIRCLE_FAMILY: 16, CIRCLE_WORK: 17, CIRCLE_FRIEND: 16}

    idx = 1
    for circle in circles:
        for _ in range(per_circle[circle]):
            wxid = gen_wxid(rng, idx)
            nickname = gen_name(rng)
            # ~25% get a remark (备注名) -- distinct from nickname.
            remark = nickname + rng.choice(["哥", "姐", "总", "工", "老师"]) if rng.random() < 0.25 else ""
            contacts.append(Contact(username=wxid, nickname=nickname, remark=remark, circle=circle))
            idx += 1

    # Designate 1-2 hubs per circle (high owner-activity, high PageRank).
    for circle in circles:
        circle_contacts = [c for c in contacts if c.circle == circle]
        hubs = rng.sample(circle_contacts, k=min(2, len(circle_contacts)))
        for h in hubs:
            h.is_hub = True

    return owner, contacts


def build_chatrooms(rng: random.Random, contacts: List[Contact]) -> List[Chatroom]:
    """Build 10 chatrooms: 8 circle-clustered + 2 cross-circle bridges."""
    by_circle: Dict[str, List[Contact]] = {c: [] for c in (CIRCLE_FAMILY, CIRCLE_WORK, CIRCLE_FRIEND)}
    for c in contacts:
        by_circle[c.circle].append(c)

    rooms: List[Chatroom] = []

    def add_room(name: str, pool: List[Contact], size: int, circle: str) -> None:
        members = rng.sample(pool, k=min(size, len(pool)))
        owner_member = rng.choice(members)
        rooms.append(Chatroom(
            chatroom_name=name,
            owner=owner_member.username,
            members=[m.username for m in members],
            circle=circle,
            create_time=int(datetime(2023, 6, 1).timestamp()) + rng.randint(0, 1000000),
        ))

    # 3 work rooms, 3 friend rooms, 2 family rooms.
    add_room("work_project@chatroom", by_circle[CIRCLE_WORK], 12, CIRCLE_WORK)
    add_room("work_daily@chatroom", by_circle[CIRCLE_WORK], 10, CIRCLE_WORK)
    add_room("work_interns@chatroom", by_circle[CIRCLE_WORK], 6, CIRCLE_WORK)
    add_room("friends_basketball@chatroom", by_circle[CIRCLE_FRIEND], 8, CIRCLE_FRIEND)
    add_room("friends_gaming@chatroom", by_circle[CIRCLE_FRIEND], 7, CIRCLE_FRIEND)
    add_room("friends_alumni@chatroom", by_circle[CIRCLE_FRIEND], 15, CIRCLE_FRIEND)
    add_room("family_group@chatroom", by_circle[CIRCLE_FAMILY], 9, CIRCLE_FAMILY)
    add_room("family_siblings@chatroom", by_circle[CIRCLE_FAMILY], 5, CIRCLE_FAMILY)

    # 2 bridge rooms (cross-circle) -> high-betweenness bridging nodes.
    bridge_pool = (rng.sample(by_circle[CIRCLE_WORK], 5)
                   + rng.sample(by_circle[CIRCLE_FRIEND], 5)
                   + rng.sample(by_circle[CIRCLE_FAMILY], 3))
    rng.shuffle(bridge_pool)
    rooms.append(Chatroom(
        chatroom_name="bridge_reunion@chatroom",
        owner=bridge_pool[0].username,
        members=[m.username for m in bridge_pool],
        circle="bridge",
        create_time=int(datetime(2023, 9, 1).timestamp()),
    ))
    bridge2 = (rng.sample(by_circle[CIRCLE_WORK], 3)
               + rng.sample(by_circle[CIRCLE_FRIEND], 3)
               + rng.sample(by_circle[CIRCLE_FAMILY], 3))
    rng.shuffle(bridge2)
    rooms.append(Chatroom(
        chatroom_name="bridge_hobby@chatroom",
        owner=bridge2[0].username,
        members=[m.username for m in bridge2],
        circle="bridge",
        create_time=int(datetime(2023, 10, 1).timestamp()),
    ))

    # COVERAGE: ensure every contact is a member of at least one chatroom so
    # no node is isolated in the graph (keeps the spring layout balanced and
    # every subject reachable via group co-activity). Add any uncovered contact
    # to its own circle's primary room.
    covered: set = set()
    for r in rooms:
        covered.update(r.members)
    circle_primary = {
        CIRCLE_WORK: "work_daily@chatroom",
        CIRCLE_FRIEND: "friends_alumni@chatroom",
        CIRCLE_FAMILY: "family_group@chatroom",
    }
    for c in contacts:
        if c.username not in covered:
            primary_name = circle_primary[c.circle]
            for r in rooms:
                if r.chatroom_name == primary_name:
                    r.members.append(c.username)
                    break

    return rooms


def rand_timestamp_seconds(rng: random.Random) -> int:
    """Random second-granularity timestamp within the 90-day window."""
    return int(WINDOW_START.timestamp()) + rng.randint(0, WINDOW_SECONDS)


def pick_msg_type(rng: random.Random) -> int:
    pop = list(MSG_TYPE_WEIGHTS.keys())
    weights = list(MSG_TYPE_WEIGHTS.values())
    return rng.choices(pop, weights=weights, k=1)[0]


def body_for(msg_type: int, circle: str, rng: random.Random) -> str:
    if msg_type == 1:
        return rng.choice(MSG_TEMPLATES[circle])
    return MEDIA_CONTENT[msg_type]


def build_private_messages(
    rng: random.Random,
    owner: Contact,
    contacts: List[Contact],
    target: int,
) -> List[RawMessage]:
    """~target private messages between owner and ~25 active contacts (power-law)."""
    msgs: List[RawMessage] = []

    # Active contacts: all hubs (high count) + a sample of others (lower count).
    hubs = [c for c in contacts if c.is_hub]
    non_hubs = [c for c in contacts if not c.is_hub]
    active = hubs + rng.sample(non_hubs, k=min(25 - len(hubs), len(non_hubs)))

    # Power-law-ish message counts: hubs get many, others get fewer.
    total_assigned = 0
    per_contact: Dict[str, int] = {}
    for c in active:
        base = rng.randint(300, 500) if c.is_hub else rng.randint(20, 150)
        per_contact[c.username] = base
        total_assigned += base

    # Scale to hit the target while preserving the distribution.
    if total_assigned > 0:
        factor = target / total_assigned
        for u in per_contact:
            per_contact[u] = max(5, int(per_contact[u] * factor))

    for c in active:
        count = per_contact[c.username]
        # Spread messages across the window; owner:contact ratio ~ 1:1 with jitter.
        for _ in range(count):
            ts = rand_timestamp_seconds(rng)
            is_send = 1 if rng.random() < 0.5 else 0
            msg_type = pick_msg_type(rng)
            body = body_for(msg_type, c.circle, rng)
            msgs.append(RawMessage(
                talker=c.username,
                content=body,
                create_time=ts,
                type=msg_type,
                is_send=is_send,
            ))

    msgs.sort(key=lambda m: m.create_time)
    return msgs


def build_group_messages(
    rng: random.Random,
    rooms: List[Chatroom],
    contacts: List[Contact],
    target: int,
) -> List[RawMessage]:
    """~target group messages, time-clustered within rooms to create co-activity edges."""
    msgs: List[RawMessage] = []
    name_to_circle: Dict[str, str] = {}
    for r in rooms:
        # Pick the dominant circle for template selection (bridge -> friend default).
        name_to_circle[r.chatroom_name] = r.circle if r.circle != "bridge" else CIRCLE_FRIEND

    per_room = max(1, target // len(rooms))

    # GUARANTEE: every contact speaks at least once in some chatroom so no node
    # is isolated in the graph (keeps the spring layout balanced and every
    # subject connected to the network). Seed one message per not-yet-spoken
    # contact into a chatroom it belongs to.
    spoken: set = set()
    rooms_by_member: Dict[str, List[Chatroom]] = {}
    for r in rooms:
        for m in r.members:
            rooms_by_member.setdefault(m, []).append(r)

    for c in contacts:
        if c.username not in rooms_by_member:
            continue
        room = rng.choice(rooms_by_member[c.username])
        circle = name_to_circle[room.chatroom_name]
        ts = rand_timestamp_seconds(rng)
        body = body_for(1, circle, rng)
        msgs.append(RawMessage(
            talker=room.chatroom_name,
            content=f"{c.username}:\n{body}",
            create_time=ts,
            type=1,
            is_send=1 if c.username == "wxid_owner" else 0,
        ))
        spoken.add(c.username)

    for room in rooms:
        # Simulate bursts of conversation: several messages within a short window.
        n_clusters = max(1, per_room // rng.randint(8, 15))
        for _ in range(n_clusters):
            # Pick a cluster anchor time, then a burst of 5-15 messages within ~30 min.
            anchor = rand_timestamp_seconds(rng)
            burst_len = rng.randint(5, 15)
            # 2-4 distinct speakers per burst -> co-activity edges.
            speakers = rng.sample(room.members, k=min(rng.randint(2, 4), len(room.members)))
            circle = name_to_circle[room.chatroom_name]
            for _ in range(burst_len):
                offset = rng.randint(0, 1800)  # within 30 min of anchor
                ts = anchor + offset
                speaker = rng.choice(speakers)
                msg_type = pick_msg_type(rng)
                body = body_for(msg_type, circle, rng)
                # CRITICAL: group content must be "wxid_xxx:\n<body>".
                content = f"{speaker}:\n{body}"
                msgs.append(RawMessage(
                    talker=room.chatroom_name,
                    content=content,
                    create_time=ts,
                    type=msg_type,
                    is_send=1 if speaker == "wxid_owner" else 0,
                ))

    msgs.sort(key=lambda m: m.create_time)
    return msgs


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_raw_db(
    db_path: str,
    owner: Contact,
    contacts: List[Contact],
    rooms: List[Chatroom],
    messages: List[RawMessage],
) -> None:
    """Write the raw EnMicroMsg.db-style database (read by the C++ parser)."""
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS rcontact (
            username TEXT, nickname TEXT, conRemark TEXT,
            type INTEGER, chatroomFlag INTEGER
        );
        CREATE TABLE IF NOT EXISTS chatroom (
            chatroomname TEXT, roomowner TEXT, memberlist TEXT,
            membercount INTEGER, addtime INTEGER
        );
        CREATE TABLE IF NOT EXISTS message (
            talker TEXT, content TEXT, createTime INTEGER,
            type INTEGER, isSend INTEGER
        );
        CREATE TABLE IF NOT EXISTS userinfo (
            id INTEGER, value TEXT
        );
    """)

    # userinfo: owner identification (id=2 username, id=4 nickname).
    cur.executemany(
        "INSERT INTO userinfo (id, value) VALUES (?, ?)",
        [(2, owner.username), (4, owner.nickname)],
    )

    # rcontact: real contacts + system rows weixin / filehelper (filtered out by parser).
    contact_rows = [
        (c.username, c.nickname, c.remark, 0, 0) for c in contacts
    ] + [
        ("weixin", "微信团队", "", 0, 0),
        ("filehelper", "文件传输助手", "", 0, 0),
    ]
    cur.executemany(
        "INSERT INTO rcontact (username, nickname, conRemark, type, chatroomFlag) VALUES (?, ?, ?, ?, ?)",
        contact_rows,
    )

    # chatroom.
    room_rows = [
        (r.chatroom_name, r.owner, ",".join(r.members), len(r.members), r.create_time)
        for r in rooms
    ]
    cur.executemany(
        "INSERT INTO chatroom (chatroomname, roomowner, memberlist, membercount, addtime) VALUES (?, ?, ?, ?, ?)",
        room_rows,
    )

    # message.
    msg_rows = [
        (m.talker, m.content, m.create_time, m.type, m.is_send) for m in messages
    ]
    cur.executemany(
        "INSERT INTO message (talker, content, createTime, type, isSend) VALUES (?, ?, ?, ?, ?)",
        msg_rows,
    )

    conn.commit()
    conn.close()


def write_normalized_db(
    db_path: str,
    owner: Contact,
    contacts: List[Contact],
    rooms: List[Chatroom],
    messages: List[RawMessage],
) -> None:
    """Write the normalized _android.db (read by the Python WeChatGraphService).

    Faithfully replicates the parseWeChatEnhanced() transformation:
      - private: isSend==1 -> sender=owner,receiver=talker; else sender=talker,receiver=owner
      - group:   chatroom_name=talker; sender extracted from "wxid_xxx:\\n<body>" prefix
      - timestamp converted SECONDS -> MILLISECONDS (Python layer requires ms)
      - msg_type restricted to {1,3,34,43,47,49}
    """
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS wechat_owner_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            nickname TEXT,
            uin INTEGER,
            imei TEXT
        );
        CREATE TABLE IF NOT EXISTS wechat_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            nickname TEXT,
            remark TEXT,
            avatar_path TEXT,
            type INTEGER,
            chatroom_flag INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS wechat_chatrooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chatroom_name TEXT UNIQUE,
            owner TEXT,
            member_list TEXT,
            member_count INTEGER,
            create_time INTEGER
        );
        CREATE TABLE IF NOT EXISTS wechat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            receiver TEXT,
            content TEXT,
            timestamp INTEGER,
            media_url TEXT,
            media_type TEXT,
            msg_type INTEGER DEFAULT 1,
            is_send INTEGER DEFAULT 0,
            chatroom_name TEXT,
            sender_nickname TEXT,
            talker TEXT
        );
    """)

    # wechat_owner_info.
    cur.execute(
        "INSERT INTO wechat_owner_info (username, nickname, uin, imei) VALUES (?, ?, ?, ?)",
        (owner.username, owner.nickname, 123456789, "1234567890ABCDEF"),
    )

    # wechat_contacts (real contacts only; system rows excluded like the parser does).
    cur.executemany(
        "INSERT OR IGNORE INTO wechat_contacts (username, nickname, remark, avatar_path, type, chatroom_flag) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(c.username, c.nickname, c.remark, "", 0, 0) for c in contacts],
    )

    # wechat_chatrooms.
    cur.executemany(
        "INSERT OR IGNORE INTO wechat_chatrooms (chatroom_name, owner, member_list, member_count, create_time) "
        "VALUES (?, ?, ?, ?, ?)",
        [(r.chatroom_name, r.owner, ",".join(r.members), len(r.members), r.create_time) for r in rooms],
    )

    # nickname lookup: remark if set else nickname (matches parser logic).
    nick = {c.username: (c.remark or c.nickname) for c in contacts}
    nick[owner.username] = owner.nickname

    norm_rows = []
    for m in messages:
        talker = m.talker
        content = m.content
        is_group = "@chatroom" in talker
        if is_group:
            chatroom_name = talker
            # Extract sender from "wxid_xxx:\n<body>".
            colon_pos = content.find(":\n")
            if colon_pos != -1:
                sender = content[:colon_pos]
                content = content[colon_pos + 2:]
            else:
                sender = ""
            receiver = chatroom_name
        else:
            chatroom_name = ""
            if m.is_send == 1:
                sender = owner.username
                receiver = talker
            else:
                sender = talker
                receiver = owner.username

        sender_nickname = nick.get(sender, "")
        # SECONDS -> MILLISECONDS (Python graph layer requires ms).
        timestamp_ms = m.create_time * 1000
        norm_rows.append((
            sender, receiver, content, timestamp_ms,
            None, None,             # media_url, media_type
            m.type, m.is_send, chatroom_name, sender_nickname, talker,
        ))

    cur.executemany(
        "INSERT INTO wechat_messages "
        "(sender, receiver, content, timestamp, media_url, media_type, msg_type, is_send, chatroom_name, sender_nickname, talker) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        norm_rows,
    )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Self-check & report
# ---------------------------------------------------------------------------

def self_check(
    raw_path: str,
    norm_path: str,
    owner: Contact,
    contacts: List[Contact],
    rooms: List[Chatroom],
    messages: List[RawMessage],
) -> bool:
    """Run integrity assertions on both databases. Returns True if all pass."""
    ok = True

    def fail(msg: str) -> None:
        nonlocal ok
        ok = False
        print(f"  [FAIL] {msg}")

    # --- raw DB assertions ---
    rconn = sqlite3.connect(raw_path)
    rcur = rconn.cursor()

    raw_msg_total = rcur.execute("SELECT COUNT(*) FROM message").fetchone()[0]
    raw_contacts = rcur.execute(
        "SELECT COUNT(*) FROM rcontact WHERE username NOT LIKE '%@chatroom%' "
        "AND username != 'weixin' AND username != 'filehelper'"
    ).fetchone()[0]
    raw_owner_u = rcur.execute("SELECT value FROM userinfo WHERE id = 2").fetchone()[0]
    raw_owner_n = rcur.execute("SELECT value FROM userinfo WHERE id = 4").fetchone()[0]
    raw_rooms = rcur.execute("SELECT COUNT(*) FROM chatroom").fetchone()[0]
    # Messages that the enhanced parser would keep.
    raw_kept = rcur.execute(
        "SELECT COUNT(*) FROM message WHERE type IN (1,3,34,43,47,49)"
    ).fetchone()[0]
    rconn.close()

    if raw_contacts < 49:
        fail(f"raw rcontact real contacts = {raw_contacts} (< 49)")
    if raw_owner_u != owner.username:
        fail(f"raw userinfo id=2 = {raw_owner_u!r} (expected {owner.username})")
    if raw_owner_n != owner.nickname:
        fail(f"raw userinfo id=4 = {raw_owner_n!r} (expected {owner.nickname})")
    if raw_rooms != len(rooms):
        fail(f"raw chatroom count = {raw_rooms} (expected {len(rooms)})")

    # --- normalized DB assertions ---
    nconn = sqlite3.connect(norm_path)
    ncur = nconn.cursor()

    n_contacts = ncur.execute("SELECT COUNT(*) FROM wechat_contacts").fetchone()[0]
    n_rooms = ncur.execute("SELECT COUNT(*) FROM wechat_chatrooms").fetchone()[0]
    n_msgs = ncur.execute("SELECT COUNT(*) FROM wechat_messages").fetchone()[0]
    n_owner = ncur.execute("SELECT COUNT(*) FROM wechat_owner_info").fetchone()[0]
    n_private_owner = ncur.execute(
        "SELECT COUNT(*) FROM wechat_messages WHERE (chatroom_name IS NULL OR chatroom_name = '') "
        "AND (sender = ? OR receiver = ?)",
        (owner.username, owner.username),
    ).fetchone()[0]
    # Timestamps must be millisecond magnitude (>= 1e12 for 2001+).
    min_ts = ncur.execute("SELECT MIN(timestamp) FROM wechat_messages").fetchone()[0] or 0
    max_ts = ncur.execute("SELECT MAX(timestamp) FROM wechat_messages").fetchone()[0] or 0

    # All group senders must be members of their chatroom.
    member_map = {r.chatroom_name: set(r.members) for r in rooms}
    bad_group = ncur.execute(
        "SELECT chatroom_name, sender FROM wechat_messages "
        "WHERE chatroom_name IS NOT NULL AND chatroom_name != '' AND sender != ''"
    ).fetchall()
    for chatroom_name, sender in bad_group:
        if sender not in member_map.get(chatroom_name, set()):
            fail(f"group {chatroom_name} sender {sender} not in member list")
            break

    nconn.close()

    if n_contacts != len(contacts):
        fail(f"norm wechat_contacts = {n_contacts} (expected {len(contacts)})")
    if n_rooms != len(rooms):
        fail(f"norm wechat_chatrooms = {n_rooms} (expected {len(rooms)})")
    if n_msgs != raw_kept:
        fail(f"norm messages = {n_msgs} != raw kept = {raw_kept} (conversion loss)")
    if n_owner != 1:
        fail(f"norm wechat_owner_info rows = {n_owner} (expected 1)")
    if n_private_owner == 0:
        fail("owner never appears in private messages")
    if min_ts < 1_000_000_000_000:
        fail(f"normalized timestamp MIN = {min_ts} (not millisecond magnitude)")

    # --- report ---
    private_msgs = sum(1 for m in messages if "@chatroom" not in m.talker)
    group_msgs = len(messages) - private_msgs
    ts_min = datetime.fromtimestamp(min(m.create_time for m in messages), tz=timezone.utc).strftime("%Y-%m-%d")
    ts_max = datetime.fromtimestamp(max(m.create_time for m in messages), tz=timezone.utc).strftime("%Y-%m-%d")
    hubs = [c.nickname for c in contacts if c.is_hub]

    print("=" * 64)
    print("WeChat 测试数据集生成完成 / Dataset generation complete")
    print("=" * 64)
    print(f"  主体 (owner)         : {owner.username} ({owner.nickname})")
    print(f"  联系人 (contacts)    : {len(contacts)} 真人 (+ weixin, filehelper)")
    print(f"    - 家人圈           : {sum(1 for c in contacts if c.circle == CIRCLE_FAMILY)}")
    print(f"    - 同事圈           : {sum(1 for c in contacts if c.circle == CIRCLE_WORK)}")
    print(f"    - 朋友圈           : {sum(1 for c in contacts if c.circle == CIRCLE_FRIEND)}")
    print(f"    - 枢纽节点 (hubs)  : {len(hubs)} -> {', '.join(hubs)}")
    print(f"  群聊 (chatrooms)     : {len(rooms)}")
    for r in rooms:
        print(f"    - {r.chatroom_name:<28} ({len(r.members)} 成员, {r.circle})")
    print(f"  消息 (messages)      : {len(messages)} 总计")
    print(f"    - 私聊             : {private_msgs}")
    print(f"    - 群聊             : {group_msgs}")
    print(f"  时间跨度             : {ts_min} ~ {ts_max} (90 天)")
    print(f"  时间戳单位           : 原始=秒, 归一化=毫秒")
    print("-" * 64)
    print(f"  原始库  (raw)        : {raw_path}")
    print(f"    message 表         : {raw_msg_total} 行 (其中解析器保留 {raw_kept})")
    print(f"  归一化库 (normalized) : {norm_path}")
    print(f"    wechat_messages    : {n_msgs} 行")
    print(f"    timestamp 范围     : {min_ts} ~ {max_ts}")
    print("=" * 64)
    print(f"自检结果: {'PASS ✓' if ok else 'FAIL ✗ (见上方 [FAIL] 项)'}")
    print()

    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate a WeChat forensic test dataset.")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed (default %(default)s)")
    p.add_argument("--scale", type=float, default=DEFAULT_SCALE,
                   help="scale factor for message counts (default %(default)s)")
    p.add_argument("--force", action="store_true", help="overwrite even if unchanged")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)

    owner, contacts = build_contacts(rng)
    rooms = build_chatrooms(rng, contacts)

    private_target = int(7000 * args.scale)
    group_target = int(5000 * args.scale)

    private_msgs = build_private_messages(rng, owner, contacts, private_target)
    group_msgs = build_group_messages(rng, rooms, contacts, group_target)
    messages = private_msgs + group_msgs
    messages.sort(key=lambda m: m.create_time)

    os.makedirs(os.path.dirname(RAW_DB_PATH), exist_ok=True)
    write_raw_db(RAW_DB_PATH, owner, contacts, rooms, messages)
    write_normalized_db(NORM_DB_PATH, owner, contacts, rooms, messages)

    ok = self_check(RAW_DB_PATH, NORM_DB_PATH, owner, contacts, rooms, messages)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
