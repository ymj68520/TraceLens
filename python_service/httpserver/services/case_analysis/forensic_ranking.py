"""
Forensic Ranking — deterministic value scoring for file selection.

When the deterministic file filter must cap its selection (request-level
``max_filter_files`` and/or ``settings.filter_max_files``), the cap can no
longer truncate alphabetically: the first N paths of a real image are almost
exclusively noise (``$OrphanFiles`` carve residue, shredder remnants such as
``Q3JU6CPH.85PB``, ``pagefile.sys``). Instead, records are ranked by a
transparent, layered forensic-value score and the top N are taken.

All inputs are deterministic products of the C++ pipeline (scene priority,
category) plus path/extension heuristics, so the same files.db always yields
the same selection. Scores are only an ordering device — without a cap
nothing is excluded.

Scoring layers (summed):
  1. ``scene_priority``   0-100, computed by the C++ FileClassifier scene
                          rules (android/windows/linux/server_cloud).
  2. ``scene_relevant``   +10 when the C++ rules marked the file relevant.
  3. ``category``         C++ FileClassifier category bonus (databases,
                          documents, email... 0-40; cache/temp/fs-metadata
                          are penalized).
  4. ``extension``        High-value forensic formats (databases, documents,
                          archives, email, evidence formats).
  5. ``path``             Evidence-rich directories (IM app data, user
                          profiles, web roots...) capped at +40.
  6. ``size``             +5 non-empty / -5 empty.
Any noise hit (see ``NOISE_*``) pins the score to ``NOISE_SCORE`` so real
files always outrank carve residue and memory/page dumps.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

# ── Noise (effectively useless for the extract+describe pipeline) ────────────

NOISE_SCORE = -1000

# Path segments that mark carve residue / filesystem internals / dumps.
NOISE_DIR_SEGMENTS = {
    "$orphanfiles",               # TSK unallocated-inode residue
    "system volume information",  # VSS catalog binaries
    "lost+found",                 # ext orphaned inodes
    "$extend", "$secure", "$upcase",  # NTFS metadata dirs
}

# Filenames of memory/page dumps and NTFS metadata files.
NOISE_FILENAMES = {
    "pagefile.sys", "hiberfil.sys", "swapfile.sys",
    "dumpstack.log", "dumpstack.log.tmp",
    "$mft", "$logfile", "$usnjrnl", "$badclus", "$boot", "$volume",
}

# File-shredder remnants leave random upper-case 8.3-ish names such as
# Q3JU6CPH.85PB. Only treated as noise when the extension is not a known
# format (so IMAGE0001.JPG or ARCHIVE.ZIP are never flagged).
SHREDDER_REMAINANT_RE = re.compile(r"^[A-Z0-9]{6,8}\.[A-Z0-9]{2,5}$")

# ── Extensions ───────────────────────────────────────────────────────────────

# Strong evidence formats (databases, office documents, email, archives,
# forensic evidence containers).
STRONG_EXTENSIONS = {
    "db", "sqlite", "sqlite3", "db-wal", "db-shm", "mdb", "accdb",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "pdf", "wps", "et", "dps",
    "eml", "msg", "pst", "ost",
    "zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz",
    "evtx", "pcap", "pcapng", "e01", "ex01", "lnk",
}

# Useful but secondary formats (config, code, logs, markup).
USEFUL_EXTENSIONS = {
    "json", "xml", "csv", "yaml", "yml", "ini", "conf", "cfg", "reg", "sql",
    "log", "txt", "htm", "html", "js", "py", "php", "jsp", "asp", "aspx",
    "java", "c", "cpp", "h", "sh", "bat", "ps1", "vbs", "plist", "properties",
    "env",
}

# Known formats with no score of their own — used only to whitelist names
# from the shredder-remnant heuristic and to keep noise detection conservative.
COMMON_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "tif", "tiff", "ico",
    "mp4", "avi", "mkv", "mov", "wmv", "3gp", "flv", "webm",
    "mp3", "wav", "flac", "wma", "m4a", "amr", "aac", "ogg",
    "exe", "dll", "sys", "msi", "so", "dylib", "bin", "o", "apk",
    "iso", "img", "vhd", "vhdx", "dmp",
    "dat", "bak", "old", "tmp", "idx",
    "key", "pem", "crt", "cer", "der", "pfx",
    "ttf", "otf", "woff", "woff2", "eot",
}

KNOWN_EXTENSIONS = STRONG_EXTENSIONS | USEFUL_EXTENSIONS | COMMON_EXTENSIONS

# ── C++ FileClassifier category bonuses (getCategoryName, lowercased) ────────

CATEGORY_BONUS = {
    "databases": 40,
    "documents": 35,
    "email files": 35,
    "encrypted files": 30,
    "archives": 25,
    "backup files": 20,
    "source code": 20,
    "certificates": 20,
    "os config files": 15,
    "images": 15,
    "web files": 12,
    "videos": 10,
    "audio files": 10,
    "log files": 8,
    "executables": 5,
    "system files": 3,
    "os boot files": 2,
    "unknown files": 0,
    "font files": 0,
    "os libraries": -3,
    "cache files": -10,
    "temp files": -10,
    "fs journal files": -12,
    "fs metadata": -12,
}

# ── Evidence-rich path bonuses (substring → bonus, capped at PATH_BONUS_MAX) ─

PATH_BONUS_MAX = 40
PATH_BONUS_PATTERNS = [
    # IM / chat application data
    ("wechat", 30), ("whatsapp", 30), ("tencent files", 25), ("telegram", 25),
    ("dingtalk", 20), ("discord", 20), ("skype", 20),
    # Mobile user data
    ("/data/data/", 25), ("/data/media/", 15), ("/sdcard", 12),
    ("/storage/emulated", 12), ("dcim", 12),
    # Desktop user profiles
    ("/users/", 12), ("/home/", 12), ("/root/", 10),
    ("desktop", 12), ("documents", 12), ("downloads", 12), ("pictures", 8),
    # Server / web evidence
    ("/var/www", 15), ("/srv/", 10), ("/opt/", 8), ("/etc/", 8),
    # Browser profiles
    ("chrome", 12), ("firefox", 12),
]


def _is_noise(path_lower: str, name: str, ext: str) -> bool:
    """Return True when the path is carve residue, FS metadata or a dump."""
    segments = re.split(r"[/\\]", path_lower)
    for segment in segments:
        if segment in NOISE_DIR_SEGMENTS:
            return True
    if name.lower() in NOISE_FILENAMES:
        return True
    if SHREDDER_REMAINANT_RE.match(name) and ext not in KNOWN_EXTENSIONS:
        return True
    return False


def _derive_extension(path: str) -> str:
    name = re.split(r"[/\\]", path)[-1]
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[1].lower()


def forensic_score(record: Dict[str, Any]) -> int:
    """Score one file record; higher = more forensic value.

    Missing columns (older files.db products) simply contribute their
    neutral defaults, so the score degrades gracefully.
    """
    path = str(record.get("path", "") or "")
    name = re.split(r"[/\\]", path)[-1]
    path_lower = path.lower()
    ext = str(record.get("extension", "") or "").lower().lstrip(".") or _derive_extension(path)

    if _is_noise(path_lower, name, ext):
        return NOISE_SCORE

    score = 0

    # Layer 1+2: C++ scene rules
    try:
        score += int(record.get("scene_priority") or 0)
    except (TypeError, ValueError):
        pass
    if record.get("scene_relevant"):
        score += 10

    # Layer 3: C++ FileClassifier category
    category = str(record.get("category", "") or "").strip().lower()
    score += CATEGORY_BONUS.get(category, 0)

    # Layer 4: extension value
    if ext in STRONG_EXTENSIONS:
        score += 20
    elif ext in USEFUL_EXTENSIONS:
        score += 8

    # Layer 5: evidence-rich path substrings (capped)
    path_bonus = sum(b for needle, b in PATH_BONUS_PATTERNS if needle in path_lower)
    score += min(path_bonus, PATH_BONUS_MAX)

    # Layer 6: empty files rarely survive extraction/description usefully
    try:
        score += 5 if int(record.get("size") or 0) > 0 else -5
    except (TypeError, ValueError):
        score -= 5

    return score


def resolve_effective_cap(
    request_max_files: Optional[int], settings_cap: Optional[int]
) -> Tuple[int, Optional[str]]:
    """Resolve the binding deterministic cap and what it is bound by.

    Both the request-level ``max_filter_files`` and the global
    ``settings.filter_max_files`` can constrain; the effective cap is the
    minimum of the positive values (0 = unlimited). Returns ``(cap, reason)``
    where ``reason`` names the binding source(s) or is ``None`` when no cap
    applies.
    """
    candidates: List[Tuple[int, str]] = []
    if request_max_files and int(request_max_files) > 0:
        candidates.append((int(request_max_files), "max_filter_files"))
    if settings_cap and int(settings_cap) > 0:
        candidates.append((int(settings_cap), "filter_max_files"))
    if not candidates:
        return 0, None
    cap = min(value for value, _ in candidates)
    reason = "+".join(name for value, name in candidates if value == cap)
    return cap, reason


def rank_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dedupe by path (best score wins), score, and sort best-first.

    Order: score descending, ties broken by path ascending so the result is
    fully deterministic. Each returned record carries ``_forensic_score``.
    """
    best: Dict[str, Dict[str, Any]] = {}
    for record in records:
        path = str(record.get("path", "") or "")
        if not path:
            continue
        score = forensic_score(record)
        current = best.get(path)
        if current is None or score > current["_forensic_score"]:
            ranked = dict(record)
            ranked["_forensic_score"] = score
            best[path] = ranked
    return sorted(best.values(), key=lambda r: (-r["_forensic_score"], r["path"]))


def apportion_quota(cap: int, pool_sizes: List[int]) -> List[int]:
    """Split ``cap`` across images so every image gets a fair share.

    Water-filling: an equal base share for every image with remaining
    demand, unused shares redistributed until ``cap`` is exhausted or every
    pool is saturated. Quotas never exceed their pool size, and an image can
    never crowd the others out regardless of how much junk it holds.

    Returns one quota per pool; deterministic for a given input.
    """
    n = len(pool_sizes)
    quotas = [0] * n
    if cap <= 0:
        return quotas
    remaining = cap
    active = [i for i in range(n) if pool_sizes[i] > 0]
    while remaining > 0 and active:
        share = remaining // len(active)
        if share == 0:
            # Give 1 each to the first `remaining` images, largest pool
            # first (then index) so the split stays deterministic.
            order = sorted(active, key=lambda i: (-pool_sizes[i], i))
            for i in order[:remaining]:
                quotas[i] += 1
            break
        for i in active:
            add = min(share, pool_sizes[i] - quotas[i])
            quotas[i] += add
            remaining -= add
        active = [i for i in active if quotas[i] < pool_sizes[i]]
    return quotas


def select_with_per_image_quota(
    pools: List[List[Dict[str, Any]]], cap: int
) -> Tuple[List[Dict[str, Any]], List[int]]:
    """Rank each image's pool, apportion the cap, and merge the winners.

    ``cap <= 0`` selects everything. The merged selection is re-sorted by
    (score desc, path asc) so downstream consumers see one deterministic
    ordering. Returns ``(selected_records, quotas_used)``.
    """
    ranked = [rank_records(pool) for pool in pools]
    if cap > 0:
        quotas = apportion_quota(cap, [len(pool) for pool in ranked])
    else:
        quotas = [len(pool) for pool in ranked]
    selected = [
        record
        for pool, quota in zip(ranked, quotas)
        for record in pool[:quota]
    ]
    selected.sort(key=lambda r: (-r["_forensic_score"], r["path"]))
    return selected, quotas
