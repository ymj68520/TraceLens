"""Opt-in integration test for a local, uncommitted third-party report sample."""

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes.android_report import router
from httpserver.services import android_report_import as reports


def test_real_sample_import_to_search_and_provenance(tmp_path, monkeypatch):
    sample = os.environ.get("TRACELENS_HTML_REPORT_SAMPLE")
    if not sample:
        pytest.skip("REAL_SAMPLE_VALIDATION_REQUIRED: set TRACELENS_HTML_REPORT_SAMPLE")
    root = Path(sample).resolve(strict=True)
    existing = os.environ.get("TRACELENS_HTML_REPORT_IMPORT_ID")
    if existing:
        import_id = existing
    else:
        monkeypatch.setattr(reports, "import_root", lambda: tmp_path / "imports")
        import_id = reports.create_import(str(root))["import_id"]

    manifest = reports.read_manifest(import_id)
    coverage = reports.read_coverage(import_id)
    overview = reports.overview(import_id)
    assert manifest["source_root"] == str(root)
    assert manifest["parser_version"] == reports.PARSER_VERSION
    assert len(manifest["parsed_content_pages"]) == coverage["successful_pages"]
    assert coverage["total_records"] > 0
    assert sum(row["count"] for row in overview["categories"]) == coverage["total_records"]
    first = reports.records(import_id, page_size=1)["records"][0]
    search = reports.records(import_id, query=first["excerpt"][:12], page_size=1)
    assert search["total"] >= 1
    detail = reports.record_detail(import_id, first["id"])
    assert detail["source_type"] == reports.SOURCE_TYPE
    assert detail["source_matches_import"] is True
    assert detail["source_locator"].startswith(detail["source_file"] + "#table-")
    assert reports.source_page_file(import_id, detail["source_file"]).is_file()
    assert "<mark id='source-row'>" in reports.source_location_html(import_id, first["id"])
    app = FastAPI()
    app.include_router(router, prefix="/api/android-report")
    client = TestClient(app)
    base = f"/api/android-report/imports/{import_id}"
    assert client.get(base + "/manifest").json()["manifest"]["parser_version"] == reports.PARSER_VERSION
    assert client.get(base + "/overview").json()["overview"]["coverage"]["total_records"] == coverage["total_records"]
    assert client.get(base + "/records", params={"query": first["excerpt"][:12]}).json()["total"] >= 1
    assert client.get(base + f"/records/{first['id']}").json()["record"]["source_matches_import"] is True
    response = client.get(base + f"/source-location/{first['id']}")
    assert response.status_code == 200
    assert "default-src 'none'" in response.headers["content-security-policy"]
    with sqlite3.connect(reports._db_path(import_id)) as con:
        text_section = con.execute(
            "SELECT id FROM records WHERE record_kind='section_text' LIMIT 1"
        ).fetchone()
    assert text_section is not None  # current sample has text-only pages
    assert "#section-" in reports.record_detail(import_id, text_section[0])["source_locator"]
    assert client.get(base + f"/source-location/{text_section[0]}").status_code == 200
