#!/usr/bin/env python3
"""Render an animated GIF visualizing the WeChat relationship graph analysis.

Reads the normalized ``wechat_dataset_android.db`` (produced by
``generate_wechat_dataset.py``), builds the NetworkX graph via
``WeChatGraphService``, and produces a multi-phase animation:

  Phase 1 (growth):   nodes & edges fade in progressively, ordered by the
                      timestamp of their first message — so the social network
                      visibly "grows" over the 90-day window.
  Phase 2 (communities): the Louvain community coloring is revealed, with a
                      legend.
  Phase 3 (centrality): nodes are re-sized/re-colored by PageRank, the owner
                      and top hubs are annotated.

Output: tests/wechat_graph_animation.gif  (also .png keyframe per phase).

The layout (spring) is computed ONCE on the full graph so positions are stable
across all frames — only alpha/size/color animate.

Stdlib + networkx + matplotlib + PIL only.
"""

from __future__ import annotations

import os
import sys
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NORM_DB = PROJECT_ROOT / "tests" / "wechat_dataset_android.db"
OUT_GIF = PROJECT_ROOT / "tests" / "wechat_graph_animation.gif"
OUT_DIR = PROJECT_ROOT / "tests" / "wechat_anim_frames"

# Ensure the python_service package is importable for WeChatGraphService.
PY_SVC = PROJECT_ROOT / "python_service"
sys.path.insert(0, str(PY_SVC))

# Bypass the latent CACHE_TTL NameError bug in _core.py:27 (see test docstring).
import httpserver.services.wechat_graph_parts._core as _core  # noqa: E402
if not hasattr(_core, "CACHE_TTL"):
    _core.CACHE_TTL = 1800

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
import networkx as nx  # noqa: E402

# ---------------------------------------------------------------------------
# Chinese font setup
# ---------------------------------------------------------------------------

def _set_cjk_font() -> str:
    """Pick a CJK-capable font; register it with matplotlib. Return font name."""
    candidates = ["Noto Sans CJK SC", "Noto Sans CJK JP", "AR PL UMing CN",
                  "WenQuanYi Zen Hei", "SimHei"]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return name
    # Fallback: try to load Noto from path.
    for path in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]:
        if os.path.exists(path):
            font_manager.fontManager.addfont(path)
            prop = font_manager.FontProperties(fname=path)
            plt.rcParams["font.sans-serif"] = [prop.get_name(), "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return prop.get_name()
    return "DejaVu Sans"


# ---------------------------------------------------------------------------
# Graph build
# ---------------------------------------------------------------------------

def build_graph_with_analysis(db_path: str):
    """Return (G, analysis_result, owner_username, contact_map)."""
    from httpserver.services.wechat_graph_service import WeChatGraphService
    svc = WeChatGraphService()
    result = svc._build_and_analyze("anim", str(db_path), include_metrics=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    owner = conn.execute("SELECT username FROM wechat_owner_info LIMIT 1").fetchone()["username"]
    contact_map = {}
    for r in conn.execute("SELECT username, nickname, remark FROM wechat_contacts"):
        contact_map[r["username"]] = r["remark"] or r["nickname"] or r["username"]
    contact_map[owner] = "机主"

    # first_time per (directed) edge from the analysis edges.
    G = nx.DiGraph()
    for n in result["nodes"]:
        G.add_node(n["id"], **n)
    for e in result["edges"]:
        G.add_edge(e["source"], e["target"], **e)
    conn.close()
    return G, result, owner, contact_map


def load_message_timeline(db_path: str):
    """Return lists of (timestamp_ms, sender, receiver, is_group) for ordering.

    Used to compute, per node, the first timestamp it appeared, and per edge,
    the first timestamp the interaction happened.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT sender, receiver, timestamp, chatroom_name FROM wechat_messages "
        "WHERE timestamp IS NOT NULL AND timestamp > 0 "
        "AND sender IS NOT NULL AND sender != '' "
        "ORDER BY timestamp ASC"
    ).fetchall()
    conn.close()

    node_first = {}
    # canonical undirected edge key -> first timestamp
    edge_first = {}
    for r in rows:
        ts = r["timestamp"]
        s, t = r["sender"], r["receiver"]
        for u in (s, t):
            if u and (u not in node_first or ts < node_first[u]):
                node_first[u] = ts
        if s and t:
            key = tuple(sorted((s, t)))
            if key not in edge_first or ts < edge_first[key]:
                edge_first[key] = ts
    ts_values = [r["timestamp"] for r in rows]
    t_min, t_max = (min(ts_values), max(ts_values)) if ts_values else (0, 1)
    return node_first, edge_first, t_min, t_max


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

COMMUNITY_COLORS = [
    "#e41a1c",  # red      - circle A
    "#377eb8",  # blue     - circle B
    "#4daf4a",  # green    - circle C
    "#984ea3",  # purple   - bridge
    "#ff7f00",  # orange
    "#a65628",  # brown
]


def draw_frame(
    ax,
    pos,
    G,
    nodes_list,
    edges_list,
    owner,
    contact_map,
    phase,
    *,
    node_alpha=None,
    edge_alpha=None,
    node_color_fn=None,
    node_size_fn=None,
    title="",
    subtitle="",
    legend_items=None,
):
    ax.clear()
    ax.set_axis_off()

    # Edges
    for nid_src, nid_tgt, data in edges_list:
        a = 1.0 if edge_alpha is None else edge_alpha.get((nid_src, nid_tgt), 0)
        if a <= 0:
            continue
        x0, y0 = pos[nid_src]
        x1, y1 = pos[nid_tgt]
        etype = data.get("edge_type", "private")
        color = "#b0b0b0" if etype == "private" else "#cfe2f3"
        lw = 0.8 if etype == "private" else 0.4
        ax.plot([x0, x1], [y0, y1], color=color, alpha=a * (0.5 if etype == "group" else 0.7),
                lw=lw, zorder=1)

    # Nodes
    xs, ys, colors, sizes, alphas = [], [], [], [], []
    labels = []
    for nid in nodes_list:
        x, y = pos[nid]
        nd = G.nodes[nid]
        a = 1.0 if node_alpha is None else node_alpha.get(nid, 0)
        if a <= 0:
            continue
        if node_color_fn is not None:
            c = node_color_fn(nid, nd)
        elif nd.get("is_owner"):
            c = "#ffd700"
        else:
            c = "#4c72b0"
        if node_size_fn is not None:
            s = node_size_fn(nid, nd)
        else:
            s = 60
        xs.append(x); ys.append(y); colors.append(c); sizes.append(s); alphas.append(a)
        if nd.get("is_owner") or nd.get("pagerank", 0) > 0.03:
            labels.append((x, y, contact_map.get(nid, nid), a, s))
    if xs:
        ax.scatter(xs, ys, c=colors, s=sizes, alpha=alphas, edgecolors="white",
                   linewidths=0.5, zorder=2)
    for x, y, txt, a, s in labels:
        ax.annotate(txt, (x, y), fontsize=6.5, alpha=a,
                    xytext=(4, 4), textcoords="offset points", zorder=3)

    # Title block
    ax.set_title(title, fontsize=15, fontweight="bold", pad=14, loc="left")
    ax.text(0.0, 1.0, subtitle, transform=ax.transAxes, fontsize=9.5,
            color="#555555", va="bottom")

    if legend_items:
        handles = [mpatches.Patch(color=c, label=l) for c, l in legend_items]
        ax.legend(handles=handles, loc="lower left", fontsize=8, framealpha=0.9)

    # stats footer
    n_shown = sum(1 for n in nodes_list if (node_alpha is None or node_alpha.get(n, 0) > 0))
    e_shown = sum(1 for et in edges_list if (edge_alpha is None or edge_alpha.get((et[0], et[1]), 0) > 0))
    ax.text(1.0, 0.02, f"可见节点 {n_shown}  ·  可见边 {e_shown}", transform=ax.transAxes,
            fontsize=8, color="#888888", ha="right")


def ease_in_out(t):
    """Smoothstep ease."""
    return t * t * (3 - 2 * t)


def render_animation(G, result, owner, contact_map, node_first, edge_first, t_min, t_max):
    font_name = _set_cjk_font()
    print(f"Using CJK font: {font_name}")

    # Stable spring layout computed once on the undirected full graph.
    H = G.to_undirected()
    # Larger k => stronger node repulsion => better spread. iterations tuned
    # for convergence on ~50 nodes.
    pos = nx.spring_layout(H, seed=42, k=0.62, iterations=500, weight="weight")

    nodes_list = list(G.nodes())
    edges_list = list(G.edges(data=True))

    # Precompute node/edge ordering & normalized appearance times.
    span = max(1, t_max - t_min)

    def node_t(nid):
        return (node_first.get(nid, t_max) - t_min) / span

    def edge_t(s, t):
        key = tuple(sorted((s, t)))
        return (edge_first.get(key, t_max) - t_min) / span

    # Community map
    cluster_of = {n["id"]: n["cluster"] for n in result["nodes"]}

    def color_by_cluster(nid, nd):
        c = cluster_of.get(nid, -1)
        if c < 0:
            return "#999999"
        return COMMUNITY_COLORS[c % len(COMMUNITY_COLORS)]

    pr_max = max((n.get("pagerank", 0) for n in result["nodes"]), default=1) or 1

    def size_by_pagerank(nid, nd):
        if nd.get("is_owner"):
            return 520
        return 40 + 900 * (nd.get("pagerank", 0) / pr_max)

    def color_by_pagerank(nid, nd):
        pr = nd.get("pagerank", 0) / pr_max
        if nd.get("is_owner"):
            return "#ffd700"
        # blue -> red ramp
        cmap = plt.cm.coolwarm
        return cmap(0.15 + 0.85 * pr)

    fig, ax = plt.subplots(figsize=(10, 7.5), dpi=110)
    fig.patch.set_facecolor("white")

    # ---- frame plan ----
    # Phase 1: growth (20 frames), Phase 2: communities (6), Phase 3: pagerank (6)
    N_GROW = 22
    frames = []

    for i in range(N_GROW):
        prog = i / (N_GROW - 1)
        prog_e = ease_in_out(prog)
        # threshold for this frame
        cut = prog_e * 1.05  # slightly over 1 at the end to ensure full reveal
        node_alpha, edge_alpha = {}, {}
        for nid in nodes_list:
            nt = node_t(nid)
            # node fades in over a window after its first-appearance time
            local = (cut - nt) / 0.06
            node_alpha[nid] = float(np.clip(local, 0.0, 1.0))
        for s, t, _ in edges_list:
            et = edge_t(s, t)
            local = (cut - et) / 0.06
            edge_alpha[(s, t)] = float(np.clip(local, 0.0, 1.0))
        date_label = _date_label(t_min + prog_e * span)
        frames.append(dict(
            phase=1, node_alpha=node_alpha, edge_alpha=edge_alpha,
            title="微信社交关系图谱  ·  消息时序生长",
            subtitle=f"按消息时间逐步揭示（第 {i+1}/{N_GROW} 帧）   {date_label}",
        ))

    # Phase 2: communities — fade color in over a few frames
    for i in range(6):
        blend = i / 5
        # alpha stays full now
        node_alpha = {nid: 1.0 for nid in nodes_list}
        edge_alpha = {(s, t): 1.0 for (s, t, _) in edges_list}
        legend = [(COMMUNITY_COLORS[k % len(COMMUNITY_COLORS)],
                  ["同事圈", "朋友圈", "家人圈", "跨圈桥梁"][k] if k < 4 else f"社区 {k+1}")
                 for k in range(max(4, len(set(cluster_of.values()))))]
        frames.append(dict(
            phase=2, node_alpha=node_alpha, edge_alpha=edge_alpha,
            node_color_fn=color_by_cluster, node_size_fn=None,
            title="社区结构检测  ·  Louvain 社区发现",
            subtitle=f"3 个社交圈 + 跨圈桥梁群   淡入进度 {int(blend*100)}%",
            legend_items=legend,
        ))

    # Phase 3: centrality — pagerank
    for i in range(6):
        blend = i / 5
        node_alpha = {nid: 1.0 for nid in nodes_list}
        edge_alpha = {(s, t): 1.0 for (s, t, _) in edges_list}

        def cfn(nid, nd, _b=blend):
            base = "#4c72b0"
            pr_c = color_by_pagerank(nid, nd)
            return _blend_color(base, pr_c, _b)

        def sfn(nid, nd, _b=blend):
            base = 60.0
            pr_s = size_by_pagerank(nid, nd)
            return base * (1 - _b) + pr_s * _b

        frames.append(dict(
            phase=3, node_alpha=node_alpha, edge_alpha=edge_alpha,
            node_color_fn=cfn, node_size_fn=sfn,
            title="中心性分析  ·  PageRank 影响力",
            subtitle=f"节点大小/颜色 ∝ PageRank   淡入进度 {int(blend*100)}%",
            legend_items=[("#ffd700", "机主 (核心)"),
                          ("#b40426", "枢纽联系人 (高 PR)"),
                          ("#3b4cc0", "普通联系人")],
        ))

    # Per-frame duration (ms) by phase: growth is quick, hold phases longer.
    # key by phase number.
    DURATION_MS = {1: 220, 2: 360, 3: 360}

    # Render each frame to an in-memory RGB PIL image, then assemble the GIF.
    # (Avoids FuncAnimation/PillowWriter fragility around _frames[0].)
    from io import BytesIO
    from PIL import Image

    OUT_GIF.parent.mkdir(parents=True, exist_ok=True)
    rgb_frames = []
    durations = []
    for idx, f in enumerate(frames):
        draw_frame(ax, pos, G, nodes_list, edges_list, owner, contact_map, f["phase"],
                   node_alpha=f.get("node_alpha"),
                   edge_alpha=f.get("edge_alpha"),
                   node_color_fn=f.get("node_color_fn"),
                   node_size_fn=f.get("node_size_fn"),
                   title=f["title"], subtitle=f["subtitle"],
                   legend_items=f.get("legend_items"))
        buf = BytesIO()
        fig.savefig(buf, format="png", facecolor="white", bbox_inches=None)
        buf.seek(0)
        rgb_frames.append(Image.open(buf).convert("RGB"))
        durations.append(DURATION_MS.get(f["phase"], 300))
        if (idx + 1) % 5 == 0 or idx == len(frames) - 1:
            print(f"  rendered frame {idx+1}/{len(frames)}")

    plt.close(fig)

    # Build a shared 256-color palette that is guaranteed to contain the vivid
    # colors we use (community colors, pagerank ramp, owner gold) PLUS a fine
    # grayscale ramp (for the growth phase). We do this by composing a palette
    # image from a representative strip of every distinct color, then letting
    # PIL quantize the union — so no frame loses its vivid color.
    from PIL import Image as _Image

    # A row of all the exact colors used anywhere in the animation.
    fixed_colors = (
        COMMUNITY_COLORS
        + ["#ffd700", "#4c72b0", "#b0b0b0", "#cfe2f3", "#3b4cc0", "#b40426",
           "#999999", "#555555", "#888888", "#ffffff"]
        # pagerank coolwarm ramp sampled (RGBA float -> RGB tuple)
        + [ _rgba_float_to_hex(plt.cm.coolwarm(0.15 + 0.85 * i / 8)) for i in range(9) ]
        # grayscale ramp (growth-phase default nodes/edges)
        + [ _gray_hex(g) for g in range(0, 256, 4) ]
    )
    swatch = _Image.new("RGB", (len(fixed_colors), 1))
    for i, hexc in enumerate(fixed_colors):
        swatch.putpixel((i, 0), _hex_to_rgb(hexc))

    # Quantize the swatch (all distinct colors present) to <=256 entries; this
    # becomes the shared palette mapped onto every frame.
    base_quant = swatch.quantize(colors=256, method=_Image.Quantize.MEDIANCUT)

    pil_frames = []
    for rgb in rgb_frames:
        p = rgb.quantize(palette=base_quant)  # map onto the shared palette
        pil_frames.append(p)

    # Assemble animated GIF with per-frame duration.
    print(f"Assembling GIF -> {OUT_GIF}")
    pil_frames[0].save(
        str(OUT_GIF),
        save_all=True,
        append_images=pil_frames[1:],
        duration=durations,
        loop=0,           # loop forever
        disposal=2,
        optimize=True,
    )
    print(f"Saved: {OUT_GIF} ({OUT_GIF.stat().st_size//1024} KB)")


def _date_label(ts_ms):
    import datetime as dt
    d = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.timezone.utc)
    return d.strftime("%Y-%m-%d")


def _blend_color(c1, c2, t):
    from matplotlib.colors import to_rgba
    a = np.array(to_rgba(c1)); b = np.array(to_rgba(c2))
    return tuple((a * (1 - t) + b * t))


def _to_rgb_tuple(c):
    from matplotlib.colors import to_rgba
    return tuple(int(v * 255) for v in to_rgba(c)[:3])


def _rgba_float_to_hex(rgba):
    """Convert a matplotlib colormap RGBA float tuple/array to '#rrggbb'."""
    return "#{:02x}{:02x}{:02x}".format(
        int(rgba[0] * 255), int(rgba[1] * 255), int(rgba[2] * 255)
    )


def _hex_to_rgb(hexc):
    h = hexc.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _to_hex(hexc):
    """normalize '#rrggbb' (strip alpha)"""
    return "#" + hexc.lstrip("#")[:6]


def _gray_hex(g):
    h = format(int(g) & 0xFF, "02x")
    return f"#{h}{h}{h}"


def main() -> int:
    if not NORM_DB.exists():
        print("Normalized DB not found. Run: python3 scripts/generate_wechat_dataset.py")
        return 1
    print("Building graph + analysis …")
    G, result, owner, contact_map = build_graph_with_analysis(NORM_DB)
    node_first, edge_first, t_min, t_max = load_message_timeline(NORM_DB)
    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, "
          f"{len(result['communities'])} communities")
    render_animation(G, result, owner, contact_map, node_first, edge_first, t_min, t_max)
    return 0


if __name__ == "__main__":
    sys.exit(main())
