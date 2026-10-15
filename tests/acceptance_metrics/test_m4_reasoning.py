"""指标 4 案情推演：推演报告结构完整（背景→行为过程→证据关联→合理推断）、
角色基本一致、证据溯源定位。

对应验收申请指标：
  (1) 推演报告结构完整（背景信息→行为过程→证据关联→合理推断），角色基本一致
  (2) 支持证据溯源定位功能

报告由 POST /api/reports（scope_type=task）触发，LLM 生成后冻结为 manifest
（title/sections/citations）。生成端约束（生成提示词 v2/v3）：sections[0] 必须
为"案件背景"章、关键事实句须带 citation、不得虚构背景与证据之外的内容。
溯源定位：citation.evidence_key 必须能通过工作台 evidence/detail 端点定位回
具体证据（与前端 CitationTracebackPanel 同一链路）。

角色一致性判定（可复核、非主观）：夹具只植入 张伟（主管）/李娜（财务）/
王五（收款账户） 三个角色，报告中出现的具名角色必须都属于该集合。
"""

from __future__ import annotations

import re
import time

import pytest

from conftest import PY_BASE, fixture_path, run_analysis_task

KNOWN_ROLES = {"张伟", "李娜", "王五"}
REPORT_TIMEOUT = int(__import__("os").environ.get("TRACELENS_ACCEPT_REPORT_TIMEOUT", "1800"))


def _report_manifest(api):
    task = run_analysis_task(api, fixture_path("raw_llm.img"),
                             scenarios=["linux"], llm_analyze=True, llm_event_analyze=True,
                             platform_analyze=False, cache_key="raw-llm-acc")
    task_id = task["id"]

    status, _ = api.post(
        PY_BASE, f"/api/investigation/workbench/{task_id}/bootstrap",
        json={"mode": "cluster_seed", "generate_llm_summaries": False})
    assert status in (200, 202)

    # 播种报告证据：把 /home 下的已分析文件登记为正文证据（快照+report-evidence），
    # 报告的 citation 才有可回指的证据键。
    from conftest import task_db
    files_db = task_db(task_id, "files")
    conn = __import__("sqlite3").connect(f"file:{files_db}?mode=ro", uri=True)
    paths = [r[0] for r in conn.execute(
        "SELECT path FROM files WHERE path LIKE '/home/analyst/%' ORDER BY path")]
    conn.close()
    assert paths, "任务库中没有 /home 证据文件"
    for path in paths:
        key = "file:" + path
        api.post(PY_BASE, "/api/investigation/snapshots",
                 json={"task_id": task_id, "evidence_key": key})
        api.put(PY_BASE, f"/api/investigation/workbench/{task_id}/report-evidence",
                json={"evidence_key": key, "usage": "main",
                      "added_by": "acceptance-suite"})

    # LLM 叙事报告：POST /generate 冻结一次生成（202）→ 轮询 generations/{id}
    # → 拿到 report_id → 叙事内容在 narrative/versions 端点。
    # 生成是概率性 LLM 输出（citation_invalid/llm_timeout 间歇出现），最多重试 2 次。
    payload = {}
    report_id = None
    for attempt in (1, 2):
        status, gen = api.post(PY_BASE, "/api/reports/generate",
                               json={"task_id": task_id, "requested_by": "acceptance-suite"})
        assert status == 202, f"发起叙事生成失败({status}): {gen}"
        generation_id = gen["generation_id"]

        deadline = time.monotonic() + REPORT_TIMEOUT
        payload = {}
        while time.monotonic() < deadline:
            status, payload = api.get(
                PY_BASE, f"/api/reports/generations/{generation_id}",
                params={"task_id": task_id})
            assert status == 200, f"生成状态查询失败({status})"
            if str(payload.get("status", "")) in ("completed", "failed"):
                break
            time.sleep(3)
        if str(payload.get("status", "")) == "completed":
            report_id = payload.get("report_id")
            break
        print(f"\n[叙事] 第 {attempt} 次生成失败: "
              f"{payload.get('error_code')} {payload.get('error_message')}，重试")
    assert report_id, f"叙事生成两次均失败: {payload.get('error_code')} {payload.get('error_message')}"

    # 叙事版本的内容走 narrative 专用读取端点（/manifest 是确定性清单，
    # 对叙事版本返回 404）。
    status, manifest = api.get(
        PY_BASE, f"/api/reports/narrative/versions/{report_id}",
        params={"task_id": task_id})
    assert status == 200, f"叙事 manifest 拉取失败({status}): {manifest}"
    return task_id, report_id, manifest


_manifest_cache: tuple | None = None


def _report_manifest_cached(api):
    """三个 M4 用例共享同一次生成（叙事生成一次约 7-10 分钟）。"""
    global _manifest_cache
    if _manifest_cache is None:
        _manifest_cache = _report_manifest(api)
    return _manifest_cache


@pytest.mark.llm
def test_m4_1a_report_structure(api, llm_ready):
    """结构完整：sections[0]=案件背景章，含行为/证据/推断叙事，关键章带引用。"""
    if not llm_ready:
        pytest.skip("LLM 未配置")
    task_id, report_id, manifest = _report_manifest_cached(api)
    sections = manifest.get("sections", [])
    assert manifest.get("title"), "报告缺标题"
    assert len(sections) >= 3, f"章节数 {len(sections)} < 3"
    assert sections[0]["heading"].startswith("案件背景"), \
        f"首章非案件背景: {sections[0]['heading']}"

    full_text = "\n".join(s.get("content", "") for s in sections)
    headings = "\n".join(s.get("heading", "") for s in sections)
    assert re.search(r"背景|概况", sections[0]["heading"])
    assert re.search(r"行为|过程|活动|时间", headings + full_text), "缺行为过程叙事"
    assert re.search(r"证据|关联", headings + full_text), "缺证据关联叙事"
    assert re.search(r"推断|研判|结论|分析", headings + full_text), "缺推断章节内容"

    citation_ids = {c.get("citation_id") for c in manifest.get("citations", [])}
    cited = {cid for s in sections for cid in s.get("citation_ids", [])}
    assert cited, "全文无任何引用（证据关联缺失）"
    assert cited <= citation_ids, f"悬空引用: {sorted(cited - citation_ids)}"
    print(f"\n[结构] {len(sections)} 章, 引用 {len(cited)} 处")


@pytest.mark.llm
@pytest.mark.llm
def test_m4_1b_role_consistency(api, llm_ready):
    """角色基本一致：报告具名角色 ⊆ 夹具植入角色集，且身份不互换。

    判定（可复核、非主观）：
      1. 括号身份句式（X（…主管…）/X（…财务…），X 前不能是汉字，避免把
         "2日仓库主管" 这类时间+场所截断成假名字）中出现的名字必须在
         夹具植入集合 {张伟, 李娜, 王五} 内 —— 不虚构人物；
      2. 已知角色身份一致：张伟-主管、李娜-财务 在报告中不互换。
    """
    if not llm_ready:
        pytest.skip("LLM 未配置")
    task_id, report_id, manifest = _report_manifest_cached(api)
    full_text = "\n".join(s.get("content", "") for s in manifest.get("sections", []))
    assert full_text.strip()

    # 1) 括号身份句式里的人物必须属于植入集合
    bracket_roles = re.compile(
        r"(?<![\u4e00-\u9fa5])([\u4e00-\u9fa5]{2,3})（[^）]{0,8}"
        r"(?:主管|财务|经理|出纳|会计)[^）]{0,6}）")
    named = {m.group(1) for m in bracket_roles.finditer(full_text)}
    unknown = named - KNOWN_ROLES
    assert not unknown, f"报告虚构/错配角色: {sorted(unknown)}（允许集合: {sorted(KNOWN_ROLES)}）"

    # 2) 已知角色身份不互换（只认括号身份绑定，句子共现会误伤"财务异常"
    #    这类普通名词短语）
    binding = {}
    for m in bracket_roles.finditer(full_text):
        seg = m.group(0)
        for name in KNOWN_ROLES & {m.group(1)}:
            if "主管" in seg or "经理" in seg:
                binding[name] = binding.get(name) or "主管/经理"
            if "财务" in seg or "会计" in seg or "出纳" in seg:
                binding[name] = binding.get(name) or "财务"
    swapped = [n for n, r_ in binding.items()
               if (n == "张伟" and "财务" in r_) or (n == "李娜" and "主管" in r_)]
    assert not swapped, f"角色身份互换: {swapped}（绑定 {binding}）"
    print(f"\n[角色] 括号身份人物 {sorted(named)}；身份绑定 {binding}")


@pytest.mark.llm
def test_m4_2_evidence_traceback(api, llm_ready):
    """证据溯源定位：每个引用都能经工作台 evidence/detail 定位到具体证据。"""
    if not llm_ready:
        pytest.skip("LLM 未配置")
    task_id, report_id, manifest = _report_manifest_cached(api)
    citations = manifest.get("citations", [])
    assert citations, "报告无引用清单，无法溯源"

    unresolved = []
    for c in citations:
        key = c.get("evidence_key")
        if not key:
            unresolved.append((c.get("citation_id"), "no evidence_key"))
            continue
        status, detail = api.get(
            PY_BASE,
            f"/api/investigation/workbench/{task_id}/evidence/detail",
            params={"evidence_key": key})
        if status != 200 or not detail.get("success"):
            unresolved.append((c.get("citation_id"), f"{key} -> HTTP {status}"))
    assert not unresolved, f"无法溯源的引用: {unresolved[:5]}"
    print(f"\n[溯源] {len(citations)} 条引用全部定位成功")
