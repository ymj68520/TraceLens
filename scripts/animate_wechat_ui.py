#!/usr/bin/env python3
"""Render an animated GIF that faithfully replicates the project's WeChat
relationship-graph frontend (web/src/pages/WeChatGraph/).

The real UI uses react-force-graph-2d (d3-force) on a dark slate canvas with a
right-hand community legend panel and a bottom recharts timeline. Rather than
approximate it, this script reconstructs the SAME visual language in matplotlib:

  - dark slate gradient background (#0f172a -> #1e293b)
  - the EXACT 8-color community palette from GraphCanvas.jsx
  - owner node gold (#fbbf24) radius 8 with a 25%-alpha glow halo (radius+2);
    other nodes radius 5 colored by Louvain cluster
  - uniform translucent slate edges (rgba(148,163,184,0.6)), width clipped to
    [1,8] = weight/10, with directional arrows
  - right CommunityLegend panel (社区分组, color swatches, member counts)
  - bottom TimelineSlider: a blue area chart (recharts style) of weekly msg counts
  - SearchBar at top

Animation phases (looping):
  1. Force simulation settle  — nodes spring into place from a compact cluster,
     simulating react-force-graph's cooldownTicks, then zoom-to-fit.
  2. Community highlight      — each community pulses in turn (legend row active).
  3. Node selection           — the owner is "clicked": the right panel switches
     to PersonDetail (消息数/PageRank/中介中心性/社区 stat grid + edges list).
  4. Edge selection           — a top private edge is "clicked": the panel shows
     a WeChat-style chat bubble history.

Output: tests/wechat_ui_animation.gif

Stdlib + networkx + numpy + matplotlib + PIL only.
"""

from __future__ import annotations

import os
import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NORM_DB = PROJECT_ROOT / "tests" / "wechat_dataset_android.db"
OUT_GIF = PROJECT_ROOT / "tests" / "wechat_ui_animation.gif"

PY_SVC = PROJECT_ROOT / "python_service"
sys.path.insert(0, str(PY_SVC))

# Bypass the latent CACHE_TTL NameError bug in _core.py:27.
import httpserver.services.wechat_graph_parts._core as _core  # noqa: E402
if not hasattr(_core, "CACHE_TTL"):
    _core.CACHE_TTL = 1800

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import FancyArrowPatch, Circle, FancyBboxPatch  # noqa: E402
import matplotlib.patheffects as path_effects  # noqa: E402
import networkx as nx  # noqa: E402
from PIL import Image  # noqa: E402

# ---------------------------------------------------------------------------
# Frontend color constants (copied verbatim from GraphCanvas.jsx / CommunityLegend.jsx)
# ---------------------------------------------------------------------------

COMMUNITY_COLORS = [
    "#3b82f6",  # blue-500
    "#ef4444",  # red-500
    "#22c55e",  # green-500
    "#f59e0b",  # amber-500
    "#8b5cf6",  # violet-500
    "#ec4899",  # pink-500
    "#06b6d4",  # cyan-500
    "#f97316",  # orange-500
]
OWNER_COLOR = "#fbbf24"          # amber-400
FALLBACK_COLOR = "#94a3b8"       # slate-400
EDGE_COLOR = (148 / 255, 163 / 255, 184 / 255, 0.6)  # rgba(148,163,184,0.6)
LABEL_COLOR = "#e2e8f0"          # slate-200
BG_TOP = "#0f172a"               # slate-900
BG_BOTTOM = "#1e293b"            # slate-800
PANEL_BG = "#1e293b"             # slate-800 (CommunityLegend / panel container)
PANEL_CARD = "#334155"           # slate-700 (stat cards)
PANEL_BORDER = "#334155"
TEXT_PRIMARY = "#f1f5f9"         # slate-100
TEXT_SECONDARY = "#94a3b8"       # slate-400
TEXT_MUTED = "#64748b"           # slate-500
TIMELINE_STROKE = "#3b82f6"
TIMELINE_FILL = (59 / 255, 130 / 255, 246 / 255, 0.5)  # #3b82f680
ACCENT_GREEN = "#16a34a"         # chat bubble owner (green-600-ish)


def _set_cjk_font() -> str:
    candidates = ["Noto Sans CJK SC", "Noto Sans CJK JP", "AR PL UMing CN",
                  "WenQuanYi Zen Hei", "SimHei"]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return name
    for path in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]:
        if os.path.exists(path):
            font_manager.fontManager.addfont(path)
            prop = font_manager.FontProperties(fname=path)
            plt.rcParams["font.sans-serif"] = [prop.get_name(), "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return prop.get_name()
    return "DejaVu Sans"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def build_graph(db_path: str):
    from httpserver.services.wechat_graph_service import WeChatGraphService
    svc = WeChatGraphService()
    result = svc._build_and_analyze("ui", str(db_path), include_metrics=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    owner = conn.execute("SELECT username FROM wechat_owner_info LIMIT 1").fetchone()["username"]
    labels = {}
    for r in conn.execute("SELECT username, nickname, remark FROM wechat_contacts"):
        labels[r["username"]] = r["remark"] or r["nickname"] or r["username"]
    labels[owner] = "机主"
    conn.close()
    return result, owner, labels


def load_timeline(db_path: str):
    from httpserver.services.wechat_graph_service import WeChatGraphService
    import asyncio
    svc = WeChatGraphService()
    res = asyncio.new_event_loop().run_until_complete(
        svc.compute_timeline("ui", str(db_path), granularity="week")
    )
    return res["intervals"]


def load_chat_history(db_path: str, owner: str, contact: str, limit: int = 8):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT sender, content, is_send, timestamp FROM wechat_messages
           WHERE chatroom_name = '' AND
                 ((sender=? AND receiver=?) OR (sender=? AND receiver=?))
           ORDER BY timestamp DESC LIMIT ?""",
        (owner, contact, contact, owner, limit),
    ).fetchall()
    conn.close()
    # chronological for display
    return list(reversed(rows))


# ---------------------------------------------------------------------------
# Layout: simulate d3-force settle with a few matplotlib-animated frames.
# Compute ONE final spring layout (stable), then animate nodes from a tight
# central cluster outward to their final positions over N frames.
# ---------------------------------------------------------------------------

def compute_layout(G):
    H = G.to_undirected()
    pos = nx.spring_layout(H, seed=7, k=0.55, iterations=600, weight="weight")
    # normalize to a fixed canvas coordinate box [0..1] x [0..1]
    xs = np.array([p[0] for p in pos.values()])
    ys = np.array([p[1] for p in pos.values()])
    def norm(v, lo, hi):
        if hi - lo < 1e-9:
            return np.zeros_like(v) + 0.5
        return (v - lo) / (hi - lo)
    nx_ = norm(xs, xs.min(), xs.max())
    ny_ = norm(ys, ys.min(), ys.max())
    return {n: np.array([nx_[i], ny_[i]]) for i, n in enumerate(pos.keys())}


def interpolate_positions(start_pos, end_pos, t):
    """t in [0,1]; ease-out."""
    t = 1 - (1 - t) ** 3  # ease-out cubic
    return {n: start_pos[n] * (1 - t) + end_pos[n] * t for n in end_pos}


# ---------------------------------------------------------------------------
# Drawing primitives matching GraphCanvas.jsx nodeCanvasObject
# ---------------------------------------------------------------------------

def node_color(node, cluster_of):
    if node.get("is_owner"):
        return OWNER_COLOR
    c = cluster_of.get(node["id"], -1)
    if c < 0:
        return FALLBACK_COLOR
    return COMMUNITY_COLORS[c % len(COMMUNITY_COLORS)]


def draw_graph(ax, pos, nodes, edges, cluster_of, labels, *,
               highlight_cluster=None, selected_node=None, zoom=1.0,
               label_alpha=0.9):
    """Draw the force-graph canvas exactly like GraphCanvas.jsx."""
    # canvas coordinate range: x,y in [0.04, 0.96]; size units in axes-fraction.
    def to_data(p):
        return p[0] * 0.9 + 0.05, p[1] * 0.88 + 0.06

    # ---- edges (uniform slate, width=clip(weight/10,1,8), arrows) ----
    for e in edges:
        s, t = e["source"], e["target"]
        if s not in pos or t not in pos:
            continue
        x0, y0 = to_data(pos[s])
        x1, y1 = to_data(pos[t])
        w = max(1.0, min(8.0, (e.get("weight", 1)) / 10.0))
        lw = w * 0.32
        a = FancyArrowPatch((x0, y0), (x1, y1),
                            arrowstyle="-|>", mutation_scale=6,
                            lw=lw, color=EDGE_COLOR, zorder=1,
                            shrinkA=6, shrinkB=6)
        ax.add_patch(a)

    # ---- nodes ----
    for n in nodes:
        nid = n["id"]
        if nid not in pos:
            continue
        x, y = to_data(pos[nid])
        is_owner = n.get("is_owner", False)
        size = 8 if is_owner else 5  # px radii from GraphCanvas.jsx
        r = size / 220.0  # scale to axes fraction
        color = node_color(n, cluster_of)

        # dim non-highlighted communities
        alpha = 1.0
        if highlight_cluster is not None and cluster_of.get(nid) != highlight_cluster:
            alpha = 0.18

        # glow halo (color + '40' = 25% alpha)
        glow = Circle((x, y), r * 1.35, facecolor=color, alpha=0.25 * alpha,
                      edgecolor="none", zorder=2)
        ax.add_patch(glow)
        # node circle
        ax.add_patch(Circle((x, y), r, facecolor=color, alpha=alpha,
                            edgecolor="white", linewidth=0.4, zorder=3))

        # selection ring
        if selected_node is not None and nid == selected_node:
            ax.add_patch(Circle((x, y), r * 1.9, facecolor="none",
                                edgecolor="#ffffff", linewidth=1.6, zorder=4))

        # labels: owner + high-pagerank always; others only if zoomed
        show_label = is_owner or n.get("pagerank", 0) > 0.03 or zoom >= 1.2
        if show_label and alpha > 0.5:
            txt = ax.text(x, y - r - 0.018, labels.get(nid, nid),
                          ha="center", va="top", fontsize=6.2, color=LABEL_COLOR,
                          alpha=label_alpha, zorder=5)
            txt.set_path_effects([path_effects.withStroke(linewidth=1.4, foreground=BG_TOP)])


# ---------------------------------------------------------------------------
# Panel renderers (right sidebar) — mimic the React components
# ---------------------------------------------------------------------------

def _rounded_card(ax, x, y, w, h, fc=PANEL_BG, ec=PANEL_BORDER):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.005,rounding_size=0.02",
                                facecolor=fc, edgecolor=ec, linewidth=0.8, zorder=6))


def draw_community_legend(ax, communities_info, selected=None):
    """Mimic CommunityLegend.jsx: 社区分分组 with color swatches + member counts."""
    PX, PY, PW, PH = 0.74, 0.06, 0.22, 0.88
    _rounded_card(ax, PX, PY, PW, PH, fc=PANEL_BG)
    ax.text(PX + 0.012, PY + PH - 0.03, "社区分组", color=TEXT_PRIMARY,
            fontsize=9, fontweight="bold", va="top", zorder=7)
    y = PY + PH - 0.085
    for c in communities_info:
        color = COMMUNITY_COLORS[c["cluster"] % len(COMMUNITY_COLORS)]
        row_bg = "#475569" if selected == c["cluster"] else None
        if row_bg:
            ax.add_patch(FancyBboxPatch((PX + 0.008, y - 0.005), PW - 0.02, 0.035,
                                        boxstyle="round,pad=0.002,rounding_size=0.01",
                                        facecolor=row_bg, edgecolor="none", zorder=7))
        ax.add_patch(Circle((PX + 0.025, y + 0.012), 0.0085, facecolor=color, zorder=8))
        ax.text(PX + 0.045, y + 0.012, c["label"], color="#cbd5e1",
                fontsize=7.5, va="center", zorder=8)
        ax.text(PX + PW - 0.015, y + 0.012, f"{c['count']}人", color=TEXT_MUTED,
                fontsize=7, va="center", ha="right", zorder=8)
        y -= 0.045


def draw_person_detail(ax, node, edges, cluster_of):
    """Mimic PersonDetail.jsx: header + 2x2 stat grid + connected edges."""
    PX, PY, PW, PH = 0.74, 0.06, 0.22, 0.88
    _rounded_card(ax, PX, PY, PW, PH, fc=PANEL_BG)
    # header
    ax.text(PX + 0.012, PY + PH - 0.03, node["label"], color=TEXT_PRIMARY,
            fontsize=10, fontweight="bold", va="top", zorder=7)
    ax.text(PX + 0.012, PY + PH - 0.06, node["id"], color=TEXT_SECONDARY,
            fontsize=7, va="top", zorder=7, family="monospace")
    # 2x2 stat grid
    grid_x = [PX + 0.012, PX + PW / 2 + 0.002]
    grid_y = PY + PH - 0.205
    stats = [
        ("消息数", str(node.get("message_count", 0))),
        ("PageRank", f"{node.get('pagerank', 0):.4f}"),
        ("中介中心性", f"{node.get('betweenness', 0):.4f}"),
        ("社区", f"社区{cluster_of.get(node['id'], 0)}"),
    ]
    for i, (k, v) in enumerate(stats):
        cx = grid_x[i % 2]
        cy = grid_y - (i // 2) * 0.075
        ax.add_patch(FancyBboxPatch((cx, cy), PW / 2 - 0.016, 0.06,
                                    boxstyle="round,pad=0.003,rounding_size=0.012",
                                    facecolor=PANEL_CARD, edgecolor="none", zorder=7))
        ax.text(cx + 0.01, cy + 0.042, k, color=TEXT_SECONDARY, fontsize=6.5, zorder=8)
        ax.text(cx + 0.01, cy + 0.012, v, color=TEXT_PRIMARY, fontsize=8.5,
                fontweight="bold", zorder=8)
    # connected edges
    ax.text(PX + 0.012, PY + 0.30, f"关联关系 ({len(edges)})", color="#cbd5e1",
            fontsize=8, va="top", zorder=7)
    y = PY + 0.27
    for e in edges[:8]:
        other = e["peer_label"]
        ax.text(PX + 0.016, y, other, color=TEXT_SECONDARY, fontsize=6.5, va="center", zorder=7)
        ax.text(PX + PW - 0.016, y, f"{e['weight']}条", color=TEXT_MUTED,
                fontsize=6.5, va="center", ha="right", zorder=7)
        y -= 0.028


def draw_chat_panel(ax, src_label, tgt_label, messages, total):
    """Mimic ChatPanel.jsx: header + WeChat-style chat bubbles."""
    PX, PY, PW, PH = 0.74, 0.06, 0.22, 0.88
    _rounded_card(ax, PX, PY, PW, PH, fc=PANEL_BG)
    ax.text(PX + 0.012, PY + PH - 0.03, f"{src_label} ↔ {tgt_label}",
            color=TEXT_PRIMARY, fontsize=8.5, fontweight="bold", va="top", zorder=7)
    ax.text(PX + 0.012, PY + PH - 0.058, f"共 {total} 条消息",
            color=TEXT_SECONDARY, fontsize=7, va="top", zorder=7)
    # bubbles: owner (is_send=1) right-aligned green, other left-aligned slate
    y = PY + PH - 0.10
    for m in messages:
        is_send = m["is_send"]
        text = (m["content"][:14] + "…") if len(m["content"]) > 14 else m["content"]
        bw = 0.10 + min(0.08, len(text) * 0.006)
        bh = 0.028
        if is_send == 1:
            bx = PX + PW - 0.012 - bw
            ax.add_patch(FancyBboxPatch((bx, y - bh), bw, bh,
                                        boxstyle="round,pad=0.002,rounding_size=0.008",
                                        facecolor=ACCENT_GREEN, edgecolor="none", zorder=7))
            ax.text(bx + bw - 0.008, y - bh / 2, text, color="white",
                    fontsize=6, va="center", ha="right", zorder=8)
        else:
            bx = PX + 0.012
            ax.add_patch(FancyBboxPatch((bx, y - bh), bw, bh,
                                        boxstyle="round,pad=0.002,rounding_size=0.008",
                                        facecolor="#475569", edgecolor="none", zorder=7))
            ax.text(bx + 0.008, y - bh / 2, text, color="white",
                    fontsize=6, va="center", ha="left", zorder=8)
        y -= 0.036


def draw_timeline(ax, intervals):
    """Mimic TimelineSlider.jsx: a blue filled area chart (recharts style)."""
    TX, TY, TW, TH = 0.01, 0.005, 0.71, 0.135
    _rounded_card(ax, TX, TY, TW, TH, fc=PANEL_BG)
    ax.text(TX + 0.012, TY + TH - 0.018, "消息时间线", color=TEXT_SECONDARY,
            fontsize=7, va="top", zorder=7)
    # plot area inside the card
    ax_pw = TW - 0.03
    ax_ph = TH - 0.045
    px0 = TX + 0.018
    py0 = TY + 0.012
    vals = [iv["total_messages"] for iv in intervals]
    vmax = max(vals) if vals else 1
    n = len(vals)
    xs = np.linspace(px0, px0 + ax_pw, n)
    ys_base = py0
    pts_y = [ys_base + (v / vmax) * ax_ph for v in vals]
    # filled area
    poly_x = np.concatenate([[xs[0]], xs, [xs[-1]]])
    poly_y = np.concatenate([[ys_base], pts_y, [ys_base]])
    ax.fill(poly_x, poly_y, color=TIMELINE_FILL, zorder=7)
    ax.plot(xs, pts_y, color=TIMELINE_STROKE, lw=1.3, zorder=8)
    # x-axis labels (period), show every other
    for i, iv in enumerate(intervals):
        if i % 3 == 0:
            ax.text(xs[i], py0 - 0.008, iv["period"][-2:] + "w",
                    color=TEXT_MUTED, fontsize=5.5, ha="center", va="top", zorder=7)


def draw_search_bar(ax):
    """Mimic SearchBar.jsx: a rounded input + refresh button."""
    SX, SY, SW, SH = 0.01, 0.945, 0.71, 0.045
    ax.add_patch(FancyBboxPatch((SX, SY), SW, SH,
                                boxstyle="round,pad=0.003,rounding_size=0.015",
                                facecolor=PANEL_BG, edgecolor=PANEL_BORDER, linewidth=0.8, zorder=6))
    ax.text(SX + 0.015, SY + SH / 2, "搜索联系人 / 备注 / 昵称...",
            color=TEXT_MUTED, fontsize=8, va="center", zorder=7)
    # refresh button on the right
    bx = SX + SW - 0.06
    ax.add_patch(FancyBboxPatch((bx, SY + 0.006), 0.05, SH - 0.012,
                                boxstyle="round,pad=0.002,rounding_size=0.012",
                                facecolor="#334155", edgecolor="none", zorder=7))
    ax.text(bx + 0.025, SY + SH / 2, "刷新", color="#cbd5e1",
            fontsize=7.5, ha="center", va="center", zorder=8)


def draw_title_badge(ax):
    ax.text(0.01, 0.995, "微信关系图谱  ·  WeChatGraph", color=TEXT_PRIMARY,
            fontsize=8, fontweight="bold", va="top", zorder=9)


# ---------------------------------------------------------------------------
# Frame compositing
# ---------------------------------------------------------------------------

def new_figure():
    fig = plt.figure(figsize=(11, 7.6), dpi=110)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_axis_off()
    # dark slate gradient background (from-slate-900 to-slate-800)
    grad = np.linspace(0, 1, 256).reshape(-1, 1)
    top = np.array([15 / 255, 23 / 255, 42 / 255])   # #0f172a
    bot = np.array([30 / 255, 41 / 255, 59 / 255])   # #1e293b
    img = top * (1 - grad) + bot * grad
    img = np.repeat(img, 2, axis=1)
    ax.imshow(img, extent=[0, 1, 0, 1], aspect="auto", origin="lower", zorder=0)
    return fig, ax


def render_to_rgb(fig):
    from io import BytesIO
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def build_palette(rgb_frames):
    """Shared 256-color palette preserving all frontend colors + grays."""
    fixed = (
        COMMUNITY_COLORS + [OWNER_COLOR, FALLBACK_COLOR, LABEL_COLOR, BG_TOP, BG_BOTTOM,
                            PANEL_BG, PANEL_CARD, "#475569", "#64748b", "#cbd5e1",
                            "#f1f5f9", "#94a3b8", "#ffffff", ACCENT_GREEN, "#334155",
                            TIMELINE_STROKE]
        + [_gray(g) for g in range(0, 256, 4)]
    )
    swatch = Image.new("RGB", (len(fixed), 1))
    for i, hx in enumerate(fixed):
        swatch.putpixel((i, 0), _hex(hx))
    base = swatch.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    return [rgb.quantize(palette=base) for rgb in rgb_frames]


def _gray(g):
    h = format(int(g) & 0xFF, "02x"); return f"#{h}{h}{h}"


def _hex(hx):
    h = hx.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------------------
# Main animation
# ---------------------------------------------------------------------------

def render(db_path, out_path):
    _set_cjk_font()
    result, owner, labels = build_graph(db_path)
    nodes = result["nodes"]
    edges = result["edges"]
    communities = result["communities"]
    cluster_of = {n["id"]: n["cluster"] for n in nodes}

    # Build a networkx graph for layout.
    G = nx.DiGraph()
    for n in nodes:
        G.add_node(n["id"])
    for e in edges:
        G.add_edge(e["source"], e["target"], weight=e.get("weight", 1))
    final_pos = compute_layout(G)
    # start positions: tight central cluster (simulate initial d3-force state)
    rng = np.random.default_rng(11)
    start_pos = {n: np.array([0.5 + rng.normal(0, 0.02), 0.5 + rng.normal(0, 0.02)])
                 for n in final_pos}

    # community info for legend
    comm_info = []
    for idx, members in enumerate(communities):
        comm_info.append({"cluster": idx, "count": len(members),
                          "label": ["同事圈", "朋友圈", "家人圈", "跨圈桥梁"][idx]
                          if idx < 4 else f"社区 {idx + 1}"})

    # timeline
    intervals = load_timeline(db_path)

    # owner node obj + top private contact for chat panel
    owner_node = next(n for n in nodes if n["is_owner"])
    # find the contact with most private msgs with owner
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    top_priv = conn.execute(
        """SELECT receiver AS u, COUNT(*) AS c FROM wechat_messages
           WHERE chatroom_name='' AND sender=? GROUP BY receiver ORDER BY c DESC LIMIT 1""",
        (owner,)).fetchone()
    top_contact = top_priv["u"]
    chat_msgs = load_chat_history(str(db_path), owner, top_contact, limit=8)
    chat_total = top_priv["c"]
    conn.close()

    # owner's connected edges (for PersonDetail)
    owner_edges = []
    for e in edges:
        if e["source"] == owner or e["target"] == owner:
            other = e["target"] if e["source"] == owner else e["source"]
            owner_edges.append({"peer_label": labels.get(other, other),
                                "weight": e.get("weight", 1)})
    owner_edges.sort(key=lambda x: x["weight"], reverse=True)

    # ---- frame generation ----
    rgb_frames = []
    durations = []

    def snap(duration):
        rgb_frames.append(render_to_rgb(fig))
        durations.append(duration)

    # Phase 1: force settle (12 frames) — nodes fly out to final positions
    fig, ax = new_figure()
    N_SETTLE = 12
    for i in range(N_SETTLE):
        ax.clear()
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_axis_off()
        # redraw gradient
        grad = np.linspace(0, 1, 256).reshape(-1, 1)
        top = np.array([15 / 255, 23 / 255, 42 / 255]); bot = np.array([30 / 255, 41 / 255, 59 / 255])
        img = top * (1 - grad) + bot * grad; img = np.repeat(img, 2, axis=1)
        ax.imshow(img, extent=[0, 1, 0, 1], aspect="auto", origin="lower", zorder=0)
        t = i / (N_SETTLE - 1)
        pos = interpolate_positions(start_pos, final_pos, t)
        draw_title_badge(ax)
        draw_search_bar(ax)
        draw_graph(ax, pos, nodes, edges, cluster_of, labels, zoom=0.9 + 0.4 * t)
        draw_community_legend(ax, comm_info)
        draw_timeline(ax, intervals)
        ax.text(0.5, 0.92, "力导向布局计算中…", color=TEXT_SECONDARY, fontsize=8,
                ha="center", alpha=0.7, zorder=9)
        snap(160)

    # Phase 2: community highlight (cycle through each community, 4 frames each)
    settle_pos = final_pos
    for ci, cinfo in enumerate(comm_info):
        for j in range(4):
            ax.clear()
            ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_axis_off()
            grad = np.linspace(0, 1, 256).reshape(-1, 1)
            top = np.array([15 / 255, 23 / 255, 42 / 255]); bot = np.array([30 / 255, 41 / 255, 59 / 255])
            img = top * (1 - grad) + bot * grad; img = np.repeat(img, 2, axis=1)
            ax.imshow(img, extent=[0, 1, 0, 1], aspect="auto", origin="lower", zorder=0)
            draw_title_badge(ax)
            draw_search_bar(ax)
            # pulse alpha on the highlighted community
            draw_graph(ax, settle_pos, nodes, edges, cluster_of, labels,
                       highlight_cluster=cinfo["cluster"], zoom=1.3)
            draw_community_legend(ax, comm_info, selected=cinfo["cluster"])
            draw_timeline(ax, intervals)
            ax.text(0.5, 0.92, f"高亮社区：{cinfo['label']}  ({cinfo['count']} 人)",
                    color=COMMUNITY_COLORS[cinfo["cluster"] % 8], fontsize=8.5,
                    ha="center", fontweight="bold", zorder=9)
            snap(260)

    # Phase 3: node selection -> PersonDetail (owner)
    for j in range(6):
        ax.clear()
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_axis_off()
        grad = np.linspace(0, 1, 256).reshape(-1, 1)
        top = np.array([15 / 255, 23 / 255, 42 / 255]); bot = np.array([30 / 255, 41 / 255, 59 / 255])
        img = top * (1 - grad) + bot * grad; img = np.repeat(img, 2, axis=1)
        ax.imshow(img, extent=[0, 1, 0, 1], aspect="auto", origin="lower", zorder=0)
        draw_title_badge(ax)
        draw_search_bar(ax)
        draw_graph(ax, settle_pos, nodes, edges, cluster_of, labels,
                   selected_node=owner, zoom=1.3)
        draw_person_detail(ax, owner_node, owner_edges, cluster_of)
        draw_timeline(ax, intervals)
        ax.text(0.5, 0.92, "已选中节点：机主 (owner)  ·  右侧显示 PersonDetail",
                color=OWNER_COLOR, fontsize=8.5, ha="center", fontweight="bold", zorder=9)
        snap(340)

    # Phase 4: edge selection -> ChatPanel
    for j in range(6):
        ax.clear()
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_axis_off()
        grad = np.linspace(0, 1, 256).reshape(-1, 1)
        top = np.array([15 / 255, 23 / 255, 42 / 255]); bot = np.array([30 / 255, 41 / 255, 59 / 255])
        img = top * (1 - grad) + bot * grad; img = np.repeat(img, 2, axis=1)
        ax.imshow(img, extent=[0, 1, 0, 1], aspect="auto", origin="lower", zorder=0)
        draw_title_badge(ax)
        draw_search_bar(ax)
        draw_graph(ax, settle_pos, nodes, edges, cluster_of, labels, zoom=1.3)
        draw_chat_panel(ax, "机主", labels.get(top_contact, top_contact),
                        chat_msgs, chat_total)
        draw_timeline(ax, intervals)
        ax.text(0.5, 0.92, f"已选中私聊关系：机主 ↔ {labels.get(top_contact, top_contact)}  ·  ChatPanel",
                color="#60a5fa", fontsize=8.5, ha="center", fontweight="bold", zorder=9)
        snap(340)

    plt.close(fig)
    print(f"Rendered {len(rgb_frames)} frames. Building palette + GIF…")
    pil_frames = build_palette(rgb_frames)
    pil_frames[0].save(
        str(out_path), save_all=True, append_images=pil_frames[1:],
        duration=durations, loop=0, disposal=2, optimize=False,
    )
    # NOTE: PIL's GIF writer still drops byte-identical consecutive frames even
    # with optimize=False. This is acceptable: near-identical late-settle frames
    # are visually redundant; all 4 animation phases remain present.
    print(f"Saved: {out_path} ({out_path.stat().st_size // 1024} KB)")


def main() -> int:
    if not NORM_DB.exists():
        print("Normalized DB not found. Run: python3 scripts/generate_wechat_dataset.py")
        return 1
    render(NORM_DB, OUT_GIF)
    return 0


if __name__ == "__main__":
    sys.exit(main())
