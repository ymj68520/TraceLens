"""Unit tests for the deterministic forensic-value ranking helpers."""

from httpserver.services.case_analysis.forensic_ranking import (
    apportion_quota,
    forensic_score,
    rank_records,
    resolve_effective_cap,
    select_with_per_image_quota,
)


# ── forensic_score ───────────────────────────────────────────────────────────

def test_noise_paths_score_below_every_real_file():
    noise = [
        {"path": "$OrphanFiles/OrphanFile-2331", "size": 10},
        {"path": "Q3JU6CPH.85PB", "size": 10},          # shredder remnant
        {"path": "/pagefile.sys", "size": 8589934592},  # page dump
        {"path": "/System Volume Information/IndexerVolumeGuid/", "size": 10},
    ]
    real = [
        {"path": "/home/u/Documents/contract.pdf", "size": 100},
        {"path": "/etc/app/config.ini", "size": 10},
        {"path": "/tmp/notes.txt", "size": 1},
    ]
    for rec in noise:
        assert forensic_score(rec) < 0
    for rec in real:
        assert forensic_score(rec) > 0


def test_shredder_regex_does_not_flag_known_extensions():
    # 8-char upper-case names with known extensions are legitimate files.
    assert forensic_score({"path": "/dcim/IMAGE0001.JPG", "size": 10}) > 0
    assert forensic_score({"path": "/srv/ARCHIVE.ZIP", "size": 10}) > 0


def test_scene_priority_and_category_dominates():
    high = {
        "path": "/data/data/com.android.providers.contacts/contacts.db",
        "size": 100, "scene_priority": 100, "scene_relevant": 1,
        "category": "Databases",
    }
    low = {"path": "/var/log/syslog", "size": 100}
    assert forensic_score(high) > forensic_score(low)


def test_missing_optional_columns_degrade_to_neutral():
    bare = {"path": "/opt/tool/data.bin", "size": 5}
    assert forensic_score(bare) > 0  # no scene/category/extension -> still fine


# ── resolve_effective_cap ────────────────────────────────────────────────────

def test_resolve_effective_cap():
    assert resolve_effective_cap(0, 0) == (0, None)
    assert resolve_effective_cap(None, None) == (0, None)
    assert resolve_effective_cap(200, 0) == (200, "max_filter_files")
    assert resolve_effective_cap(0, 50) == (50, "filter_max_files")
    assert resolve_effective_cap(200, 50) == (50, "filter_max_files")
    assert resolve_effective_cap(100, 300) == (100, "max_filter_files")
    cap, reason = resolve_effective_cap(100, 100)
    assert cap == 100 and reason == "max_filter_files+filter_max_files"


# ── rank_records ─────────────────────────────────────────────────────────────

def test_rank_records_orders_and_dedupes():
    records = [
        {"path": "/a/junk", "size": 0, "category": "Cache Files"},
        {"path": "/b/doc.pdf", "size": 10},
        {"path": "/b/doc.pdf", "size": 10, "scene_priority": 75},  # duplicate path
        {"path": "/a/junk", "size": 0, "scene_priority": 100},     # duplicate path
        {"path": "", "size": 5},  # dropped
    ]
    ranked = rank_records(records)
    paths = [r["path"] for r in ranked]
    assert paths == ["/b/doc.pdf", "/a/junk"]
    scores = [r["_forensic_score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)
    # best-scoring duplicate wins
    best = ranked[0]
    assert best["_forensic_score"] == forensic_score(
        {"path": "/b/doc.pdf", "size": 10, "scene_priority": 75}
    )


def test_rank_records_ties_break_by_path():
    ranked = rank_records([{"path": "/m", "size": 0}, {"path": "/a", "size": 0},
                           {"path": "/z", "size": 0}])
    assert [r["path"] for r in ranked] == ["/a", "/m", "/z"]


# ── apportion_quota ──────────────────────────────────────────────────────────

def test_apportion_quota_equal_split():
    assert apportion_quota(3, [12, 2, 1]) == [1, 1, 1]
    assert apportion_quota(6, [5, 5, 5]) == [2, 2, 2]


def test_apportion_quota_skips_empty_pools():
    assert apportion_quota(4, [100, 0, 50]) == [2, 0, 2]


def test_apportion_quota_water_filling_redistributes():
    # small pool saturates, leftover flows to the big pool
    assert apportion_quota(10, [2, 8]) == [2, 8]
    assert apportion_quota(5, [1, 6]) == [1, 4]


def test_apportion_quota_caps_at_pool_size():
    # pools smaller than the cap: quota == pool size, cap unspent
    assert apportion_quota(7, [3, 3]) == [3, 3]
    assert apportion_quota(5, [1, 1, 1]) == [1, 1, 1]


def test_apportion_quota_remainder_deterministic():
    assert apportion_quota(2, [5, 5, 5]) == [1, 1, 0]
    assert apportion_quota(0, [5, 5]) == [0, 0]


# ── select_with_per_image_quota ──────────────────────────────────────────────

def test_select_with_quota_merges_and_sorts():
    pools = [
        [{"path": "$OrphanFiles/OrphanFile-0001", "size": 1},
         {"path": "$OrphanFiles/OrphanFile-0002", "size": 1}],
        [{"path": "/home/u/Documents/contract.pdf", "size": 100},
         {"path": "/home/u/Pictures/photo.jpg", "size": 50}],
        [{"path": "/var/www/html/index.php", "size": 30}],
    ]
    selected, quotas = select_with_per_image_quota(pools, 3)
    assert quotas == [1, 1, 1]
    assert [r["path"] for r in selected] == [
        "/home/u/Documents/contract.pdf",
        "/var/www/html/index.php",
        "$OrphanFiles/OrphanFile-0001",
    ]


def test_select_unlimited_selects_everything():
    pools = [[{"path": "/a", "size": 1}], [{"path": "/b", "size": 1}, {"path": "/c", "size": 1}]]
    selected, quotas = select_with_per_image_quota(pools, 0)
    assert quotas == [1, 2]
    assert {r["path"] for r in selected} == {"/a", "/b", "/c"}
