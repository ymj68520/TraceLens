"""Synthetic offline-report fixtures only; never commit real case material."""

import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes.android_report import router
from httpserver.routes import android_report as report_route
from httpserver.services import android_report_import as reports


@pytest.fixture
def sample(tmp_path, monkeypatch):
    root = tmp_path / "vendor-report"
    page_dir = root / "report" / "sample-phone" / "report" / "content"
    resource = root / "report" / "sample-phone" / "report" / "resource" / "attachment"
    resource.mkdir(parents=True)
    page_dir.mkdir(parents=True)
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    db = root / "report" / "sample-phone" / "export.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE archiveInfo(softName TEXT, softVersion TEXT)")
        con.execute("INSERT INTO archiveInfo VALUES ('Test Exporter', '1.0')")
    (resource / "photo.png").write_bytes(b"\x89PNGtest")
    source = page_dir / "content1.html"
    source.write_text(
        '<h3>微信聊天</h3><a id="42"></a><table><tr><th>时间</th><th>内容</th></tr>'
        '<tr><td>2026-07-17 10:15:50</td><td>测试消息<a href="../resource\\attachment\\photo.png">图片</a>'
        '<script>evil()</script></td></tr>'
        '<tr><td>2026-07-18</td><td>第二条<img src="../resource/attachment/missing.jpg"></td></tr>'
        '</table>', encoding="utf-8",
    )
    (root / "report" / "content0.html").write_text(
        "<h3>设备信息</h3><table><tr><td>安卓设备</td></tr></table>", encoding="utf-8"
    )
    monkeypatch.setattr(reports, "import_root", lambda: tmp_path / "indexes")
    return root, source


def test_import_search_provenance_and_media(sample):
    root, source = sample
    info = reports.create_import(str(root))
    assert info["source_type"] == "external_html_report"
    assert info["page_count"] == 2
    assert info["record_count"] == 3
    assert info["missing_attachment_count"] == 1
    assert info["missing_attachment_paths"] == ["report/sample-phone/report/resource/attachment/missing.jpg"]
    assert len(reports.list_imports()) == 1
    view = reports.overview(info["import_id"])
    assert {item["category"]: item["count"] for item in view["categories"]} == {"微信": 2, "设备": 1}
    assert {item["day"]: item["count"] for item in view["days"]} == {"2026-07-17": 1, "2026-07-18": 1}
    result = reports.records(info["import_id"], query="测试消息", category="微信")
    assert result["total"] == 1
    detail = reports.record_detail(info["import_id"], result["records"][0]["id"])
    assert "evil" not in detail["content"]
    assert detail["source_anchor"] == "42"
    assert detail["source_file"] == source.relative_to(root).as_posix()
    assert detail["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert detail["source_matches_import"] is True
    assert reports.source_page_file(info["import_id"], detail["source_file"]) == source.resolve()
    assert detail["attachments"] == [{
        "path": "report/sample-phone/report/resource/attachment/photo.png", "available": True,
        "size": 8, "sha256": hashlib.sha256(b"\x89PNGtest").hexdigest(),
    }]
    assert reports.attachment_file(info["import_id"], detail["attachments"][0]["path"]).read_bytes() == b"\x89PNGtest"
    with pytest.raises(ValueError):
        reports.attachment_file(info["import_id"], "../../etc/passwd")
    with pytest.raises(ValueError):
        reports.attachment_file(info["import_id"], "report/sample-phone/export.db")


def test_invalid_report_and_http_errors(sample, tmp_path, monkeypatch):
    root, _ = sample
    with pytest.raises(reports.InvalidReport):
        reports.create_import(str(tmp_path))
    monkeypatch.setattr(reports, "candidate_root", lambda: root.parent.resolve())
    client = TestClient(FastAPI())
    client.app.include_router(router, prefix="/api/android-report")
    candidate_id = client.get("/api/android-report/candidates").json()["candidates"][0]["id"]
    assert client.post("/api/android-report/imports", json={"source_path": str(root)}).status_code == 400
    response = client.post("/api/android-report/imports", json={"candidate_id": candidate_id})
    assert response.status_code == 201
    import_id = response.json()["import"]["import_id"]
    assert client.get(f"/api/android-report/imports/{import_id}/overview").status_code == 200
    row = client.get(f"/api/android-report/imports/{import_id}/records").json()["records"][0]
    assert client.get(f"/api/android-report/imports/{import_id}/source-page", params={"path": row["source_file"]}).status_code == 200
    assert client.get(f"/api/android-report/imports/{import_id}/records?page_size=0").status_code == 422
    assert client.get("/api/android-report/imports/invalid/overview").status_code == 400
    assert client.get(f"/api/android-report/imports/{import_id}/attachment", params={"path": "../../etc/passwd"}).status_code == 400


def test_untrusted_html_is_data_not_executed(sample):
    root, source = sample
    source.write_text(
        '<h3>短信</h3><table><tr><td>正常内容</td><td><a href="file:///etc/passwd">外链</a>'
        '<a href="../../../../../../etc/passwd">越界</a></td></tr></table>', encoding="utf-8"
    )
    info = reports.create_import(str(root))
    entry = reports.records(info["import_id"], category="短信")["records"][0]
    detail = reports.record_detail(info["import_id"], entry["id"])
    assert detail["attachments"] == []
    assert detail["content"] is None  # no explicit content header
    assert "正常内容" in detail["raw_text"]


def test_modified_page_refuses_source_download(sample):
    root, source = sample
    info = reports.create_import(str(root))
    source.write_text(source.read_text(encoding="utf-8") + "changed", encoding="utf-8")
    row = reports.records(info["import_id"], query="测试消息")["records"][0]
    assert reports.record_detail(info["import_id"], row["id"])["source_matches_import"] is False
    with pytest.raises(reports.InvalidReport):
        reports.source_page_file(info["import_id"], row["source_file"])


def test_modified_attachment_refuses_download(sample):
    root, _ = sample
    info = reports.create_import(str(root))
    attachment = root / "report/sample-phone/report/resource/attachment/photo.png"
    attachment.write_bytes(b"changed")
    with pytest.raises(reports.InvalidReport):
        reports.attachment_file(info["import_id"], "report/sample-phone/report/resource/attachment/photo.png")


def test_later_added_attachment_is_not_treated_as_imported_evidence(sample):
    root, _ = sample
    info = reports.create_import(str(root))
    missing = root / "report/sample-phone/report/resource/attachment/missing.jpg"
    missing.write_bytes(b"later file")
    with pytest.raises(reports.InvalidReport):
        reports.attachment_file(info["import_id"], "report/sample-phone/report/resource/attachment/missing.jpg")


def test_navigation_classifies_continuation_pages_without_false_anchor(sample):
    root, source = sample
    content_dir = source.parent
    (content_dir / "data.js").write_text(
        'var data = {"list":[{"a":1,"b":0,"c":"网盘","f":"content1.html#42"}]};',
        encoding="utf-8",
    )
    (content_dir / "content2.html").write_text(
        "<table><tr><td>2026-07-19 12:00</td><td>续页上传记录</td></tr></table>",
        encoding="utf-8",
    )
    info = reports.create_import(str(root))
    result = reports.records(info["import_id"], query="续页上传记录")
    assert result["total"] == 1
    item = reports.record_detail(info["import_id"], result["records"][0]["id"])
    assert item["category"] == "网盘"
    assert item["source_file"].endswith("content2.html")
    assert item["source_anchor"] == ""


def test_declared_gbk_report_text_is_preserved(sample):
    root, source = sample
    source.write_bytes(
        '<meta charset="gbk"><h3>短信</h3><table><tr><td>中文短信内容</td></tr></table>'.encode("gbk")
    )
    info = reports.create_import(str(root))
    assert reports.records(info["import_id"], query="中文短信内容", category="短信")["total"] == 1


def test_relative_path_is_resolved_from_project_root(sample, monkeypatch):
    root, _ = sample
    monkeypatch.setattr(reports, "get_project_root", lambda: root.parent)
    info = reports.create_import(root.name)
    assert info["source_path"] == str(root.resolve())


def test_server_report_picker_reuses_import_and_links_task(sample, monkeypatch):
    root, _ = sample
    monkeypatch.setattr(reports, "candidate_root", lambda: root.parent.resolve())
    candidates = reports.list_candidates()
    assert len(candidates) == 1
    assert candidates[0]["name"] == root.name
    info = reports.create_import_from_candidate(candidates[0]["id"])
    assert reports.create_import_from_candidate(candidates[0]["id"])["import_id"] == info["import_id"]
    linked = reports.set_task_link(info["import_id"], "task-a", linked=True)
    assert linked["task_ids"] == ["task-a"]
    assert reports.list_imports("task-a")[0]["import_id"] == info["import_id"]
    reports.set_task_link(info["import_id"], "task-a", linked=False)
    assert reports.list_imports("task-a") == []
    with pytest.raises(ValueError):
        reports.set_task_link(info["import_id"], "../other", linked=True)


def test_picker_reindexes_when_source_changes(sample, monkeypatch):
    root, source = sample
    monkeypatch.setattr(reports, "candidate_root", lambda: root.parent.resolve())
    candidate_id = reports.list_candidates()[0]["id"]
    original = reports.create_import_from_candidate(candidate_id)
    source.write_text(source.read_text(encoding="utf-8") + "<p>changed</p>", encoding="utf-8")
    updated = reports.create_import_from_candidate(candidate_id)
    assert updated["import_id"] != original["import_id"]
    assert reports.create_import_from_candidate(candidate_id)["import_id"] == updated["import_id"]


def test_picker_reindexes_when_referenced_attachment_changes(sample, monkeypatch):
    root, _ = sample
    monkeypatch.setattr(reports, "candidate_root", lambda: root.parent.resolve())
    candidate_id = reports.list_candidates()[0]["id"]
    original = reports.create_import_from_candidate(candidate_id)
    attachment = root / "report/sample-phone/report/resource/attachment/photo.png"
    attachment.write_bytes(b"changed but still present")
    updated = reports.create_import_from_candidate(candidate_id)
    assert updated["import_id"] != original["import_id"]


def test_task_link_route_requires_real_task(sample, monkeypatch):
    root, _ = sample
    info = reports.create_import(str(root))

    class Backend:
        async def get_task(self, task_id, **_kwargs):
            return {"id": task_id} if task_id == "task-a" else None

    monkeypatch.setattr(report_route, "get_service_manager", lambda: SimpleNamespace(cpp_backend=Backend()))
    app = FastAPI()
    app.include_router(router, prefix="/api/android-report")
    client = TestClient(app)
    base = f"/api/android-report/imports/{info['import_id']}"
    assert client.post(base + "/tasks", json={"task_id": "wrong"}).status_code == 404
    assert client.post(base + "/tasks", json={"task_id": "task-a"}).status_code == 200
    assert client.get("/api/android-report/imports?task_id=task-a").json()["imports"][0]["import_id"] == info["import_id"]
    assert client.delete(base + "/tasks/task-a").status_code == 200


def _write_page_js(root, entries):
    (root / "report" / "page.js").write_text(
        "var page = " + json.dumps({"page": entries}, ensure_ascii=False) + ";", encoding="utf-8"
    )


def _codes(info):
    return {item["code"] for item in reports.read_manifest(info["import_id"])["warnings"]}


def test_static_page_map_manifest_and_coverage(sample):
    root, source = sample
    _write_page_js(root, [
        {"currentPage": 1, "contenthtml": "content0.html"},
        {"currentPage": 2, "contenthtml": "sample-phone/report/content/content1.html"},
    ])
    (source.parent / "data.js").write_text('var data = {"list": []};', encoding="utf-8")
    (root / "report/sample-phone/report/resource/attachment/missing.jpg").write_bytes(b"image")
    info = reports.create_import(str(root))
    manifest = reports.read_manifest(info["import_id"])
    coverage = reports.read_coverage(info["import_id"])
    assert info["status"] == "COMPLETE"
    assert manifest["declared_page_count"] == 2
    assert len(manifest["parsed_content_pages"]) == 2
    assert manifest["page_mapping"][1]["source_file"] == source.relative_to(root).as_posix()
    assert len(manifest["source_sha256"]) == 64
    assert coverage["successful_pages"] == 2
    assert coverage["total_records"] == 3
    item = reports.record_detail(info["import_id"], reports.records(info["import_id"], query="测试消息")["records"][0]["id"])
    assert item["source_type"] == "external_html_report"
    assert item["source_vendor"] == "Test Exporter"
    assert item["source_page"] == 2
    assert item["source_locator"].endswith("content1.html#table-1-row-1")
    assert item["source_hash"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert item["content"] == "测试消息 图片"
    assert item["timestamp"] == "2026-07-17 10:15:50"
    assert item["application"] == "微信"
    safe_html = reports.source_location_html(info["import_id"], item["id"])
    assert '<mark id=\'source-row\'>' in safe_html
    assert "测试消息" in safe_html
    assert "<script>evil()" not in safe_html


def test_missing_unknown_and_malformed_page_js_do_not_block_safe_rows(sample):
    root, _ = sample
    absent = reports.create_import(str(root))
    assert absent["status"] == "PARTIAL"
    assert "PAGE_JS_MISSING" in _codes(absent)
    (root / "report/page.js").write_text("var page = getPages();", encoding="utf-8")
    unknown = reports.create_import(str(root))
    assert unknown["record_count"] == 3
    assert "UNSUPPORTED_PAGE_JS" in _codes(unknown)
    (root / "report/page.js").write_bytes(b"var page = \xff")
    malformed = reports.create_import(str(root))
    assert "UNSUPPORTED_PAGE_JS" in _codes(malformed)


def test_missing_page_and_mismatched_page_count(sample):
    root, _ = sample
    _write_page_js(root, [
        {"currentPage": 1, "contenthtml": "content0.html"},
        {"currentPage": 2, "contenthtml": "sample-phone/report/content/content1.html"},
        {"currentPage": 3, "contenthtml": "sample-phone/report/content/content2.html"},
    ])
    info = reports.create_import(str(root))
    assert info["status"] == "PARTIAL"
    assert "MISSING_PAGE" in _codes(info)
    assert reports.read_manifest(info["import_id"])["declared_page_count"] == 3
    assert reports.read_coverage(info["import_id"])["successful_pages"] == 2


def test_missing_data_js_and_conservative_fields(sample):
    root, source = sample
    source.write_text(
        '<h3>微信聊天</h3><table><tr><th>发送人</th><th>接收人</th><th>未知列</th><th>消息内容</th></tr>'
        '<tr><td>甲</td><td>乙</td><td>原样</td><td>文本</td></tr></table>', encoding="utf-8"
    )
    info = reports.create_import(str(root))
    assert "DATA_JS_MISSING" in _codes(info)
    row = reports.record_detail(info["import_id"], reports.records(info["import_id"], query="文本")["records"][0]["id"])
    assert row["sender"] == "甲" and row["receiver"] == "乙"
    assert row["raw_fields"]["未知列"] == "原样"
    assert row["account"] is None and row["file_path"] is None
    assert row["content"] == "文本"
    assert reports.read_coverage(info["import_id"])["unknown_fields"] >= 1


def test_locator_is_stable_and_page_read_is_confined(sample, tmp_path):
    root, source = sample
    first = reports.create_import(str(root))
    second = reports.create_import(str(root))
    a = reports.records(first["import_id"], query="测试消息")["records"][0]["id"]
    b = reports.records(second["import_id"], query="测试消息")["records"][0]["id"]
    assert a == b
    assert reports.record_detail(first["import_id"], a)["source_locator"] == reports.record_detail(second["import_id"], b)["source_locator"]
    for invalid in ("../etc/passwd", "/etc/passwd", "report/../../etc/passwd"):
        with pytest.raises(ValueError):
            reports.source_page_file(first["import_id"], invalid)
    outside = tmp_path / "outside.html"
    outside.write_text("outside", encoding="utf-8")
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(reports.InvalidReport):
        reports.source_page_file(first["import_id"], reports.record_detail(first["import_id"], a)["source_file"])


def test_import_root_symlink_replacement_blocks_source_trace(sample):
    root, source = sample
    info = reports.create_import(str(root))
    relative = source.relative_to(root).as_posix()
    moved = root.with_name(root.name + "-moved")
    root.rename(moved)
    root.symlink_to(moved, target_is_directory=True)
    with pytest.raises(reports.InvalidReport):
        reports.source_page_file(info["import_id"], relative)
    row_id = reports.records(info["import_id"], query="测试消息")["records"][0]["id"]
    assert reports.record_detail(info["import_id"], row_id)["source_matches_import"] is False


def test_page_js_path_traversal_and_symlink_escape(sample, tmp_path):
    root, source = sample
    _write_page_js(root, [{"currentPage": 1, "contenthtml": "../../outside/content1.html"}])
    outside = tmp_path / "outside.html"
    outside.write_text("<table><tr><td>outside</td></tr></table>", encoding="utf-8")
    source.unlink()
    source.symlink_to(outside)
    info = reports.create_import(str(root))
    assert "UNSUPPORTED_PAGE_JS" in _codes(info)
    assert "UNSAFE_PAGE_PATH" in _codes(info)
    assert reports.records(info["import_id"], query="outside")["total"] == 0


def test_symlinked_report_subdirectory_is_skipped_with_warning(sample, tmp_path):
    root, _ = sample
    outside = tmp_path / "external-content"
    outside.mkdir()
    (outside / "content99.html").write_text("<table><tr><td>outside</td></tr></table>", encoding="utf-8")
    (root / "report" / "linked").symlink_to(outside, target_is_directory=True)
    info = reports.create_import(str(root))
    assert "SYMLINK_DIRECTORY_SKIPPED" in _codes(info)
    assert reports.records(info["import_id"], query="outside")["total"] == 0


def test_oversized_and_deeply_nested_page_are_partial(sample, monkeypatch):
    root, source = sample
    monkeypatch.setattr(reports, "MAX_PAGE_BYTES", 100)
    too_big = reports.create_import(str(root))
    assert too_big["status"] == "PARTIAL"  # the small landing page remains readable
    assert "PAGE_LIMIT" in _codes(too_big)
    monkeypatch.setattr(reports, "MAX_PAGE_BYTES", 1)
    no_rows = reports.create_import(str(root))
    assert no_rows["status"] == "FAILED"
    monkeypatch.setattr(reports, "MAX_PAGE_BYTES", 25 * 1024 * 1024)
    source.write_text("<div>" * 300 + "<table><tr><td>x</td></tr></table>" + "</div>" * 300, encoding="utf-8")
    deep = reports.create_import(str(root))
    assert deep["status"] == "PARTIAL"  # root content0 still has trusted rows
    assert "PAGE_PARSE_FAILED" in _codes(deep)


def test_row_truncation_and_bounded_table_are_reported(sample, monkeypatch):
    root, source = sample
    monkeypatch.setattr(reports, "MAX_RECORD_CHARS", 8)
    info = reports.create_import(str(root))
    assert info["status"] == "PARTIAL"
    assert "TRUNCATED_ROW" in _codes(info)
    assert reports.read_coverage(info["import_id"])["truncated_rows"] > 0
    monkeypatch.setattr(reports, "MAX_ROWS_PER_PAGE", 1)
    bounded = reports.create_import(str(root))
    assert "PAGE_PARSE_FAILED" in _codes(bounded)


def test_unreadable_export_metadata_is_failed_with_manifest(sample):
    root, _ = sample
    (root / "report/sample-phone/export.db").write_bytes(b"not a sqlite database")
    info = reports.create_import(str(root))
    assert info["status"] == "FAILED"
    assert info["record_count"] == 0
    manifest = reports.read_manifest(info["import_id"])
    assert manifest["export_db_exists"] is True
    assert manifest["export_db_valid"] is False
    assert "EXPORT_DB_INVALID" in _codes(info)


def test_non_table_content_page_is_explicitly_unsupported(sample):
    root, source = sample
    source.write_text("<h2>Only narrative prose, no table</h2>", encoding="utf-8")
    info = reports.create_import(str(root))
    assert info["status"] == "PARTIAL"  # root landing page still has a row
    assert "UNSUPPORTED_PAGE_STRUCTURE" in _codes(info)
    assert reports.read_coverage(info["import_id"])["unsupported_pages"] >= 1


def test_non_table_section_text_is_indexed_without_guessing_fields(sample):
    root, source = sample
    source.write_text(
        '<h3>普通记录</h3><div>正文中提及微信但标题不声明应用。</div>'
        '<h3>微信聊天</h3><div>可见会话文本</div><script>not evidence</script>',
        encoding="utf-8",
    )
    info = reports.create_import(str(root))
    assert "UNSUPPORTED_PAGE_STRUCTURE" not in _codes(info)
    item = reports.records(info["import_id"], query="可见会话文本")["records"][0]
    detail = reports.record_detail(info["import_id"], item["id"])
    assert detail["record_kind"] == "section_text"
    assert detail["content"] is None
    assert detail["sender"] is None and detail["timestamp"] is None
    assert detail["application"] == "微信"
    assert detail["source_locator"].endswith("content1.html#section-2")
    assert "not evidence" not in detail["raw_text"]
    plain = reports.records(info["import_id"], query="正文中提及微信")["records"][0]
    assert reports.record_detail(info["import_id"], plain["id"])["application"] is None


def test_attachment_reference_limit_is_not_silent(sample, monkeypatch):
    root, source = sample
    monkeypatch.setattr(reports, "MAX_ATTACHMENTS", 1)
    source.write_text(
        '<h3>媒体</h3><table><tr><td>附件 '
        '<a href="../resource/attachment/photo.png">A</a>'
        '<a href="../resource/attachment/missing.jpg">B</a></td></tr></table>',
        encoding="utf-8",
    )
    info = reports.create_import(str(root))
    assert info["status"] == "PARTIAL"
    assert "ATTACHMENT_REF_LIMIT" in _codes(info)
    assert reports.read_coverage(info["import_id"])["attachment_refs_truncated"] == 1


def test_malformed_encoding_iframe_and_external_uri_are_inert(sample):
    root, source = sample
    source.write_bytes(b'<h3>SMS</h3><table><tr><td>ok\xff'
                       b'<iframe src="https://example.invalid/x">outside</iframe>'
                       b'<a href="data:text/html,evil">text</a></td></tr></table>')
    info = reports.create_import(str(root))
    assert "MALFORMED_ENCODING" in _codes(info)
    row = reports.record_detail(info["import_id"], reports.records(info["import_id"], query="ok")["records"][0]["id"])
    assert row["attachments"] == []
    assert "outside" not in row["raw_text"]


def test_complete_route_reports_manifest_coverage_and_inert_location(sample):
    root, source = sample
    _write_page_js(root, [
        {"currentPage": 1, "contenthtml": "content0.html"},
        {"currentPage": 2, "contenthtml": "sample-phone/report/content/content1.html"},
    ])
    (source.parent / "data.js").write_text('var data = {"list": []};', encoding="utf-8")
    (root / "report/sample-phone/report/resource/attachment/missing.jpg").write_bytes(b"image")
    info = reports.create_import(str(root))
    app = FastAPI()
    app.include_router(router, prefix="/api/android-report")
    client = TestClient(app)
    base = f"/api/android-report/imports/{info['import_id']}"
    assert client.get(base + "/manifest").json()["manifest"]["status"] == "COMPLETE"
    assert client.get(base + "/coverage").json()["coverage"]["total_records"] == 3
    row_id = client.get(base + "/records", params={"query": "测试消息"}).json()["records"][0]["id"]
    assert client.get(base + f"/records/{row_id}").json()["record"]["source_page"] == 2
    response = client.get(base + f"/source-location/{row_id}")
    assert response.status_code == 200
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert "测试消息" in response.text
