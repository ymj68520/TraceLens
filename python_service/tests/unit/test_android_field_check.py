import importlib.util
import hashlib
import json
from pathlib import Path


def _load():
    script = Path(__file__).resolve().parents[3] / "scripts" / "android_field_check.py"
    spec = importlib.util.spec_from_file_location("android_field_check", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_reports_public_endpoint_without_printing_secret(tmp_path, monkeypatch):
    checker = _load()
    env = tmp_path / ".env"
    env.write_text("LLM_BASE_URL=https://secret:token@api.example.invalid/v1\n"
                   "LLM_API_KEY=never-print-me\n"
                   "HTTP_SERVER_HOST=0.0.0.0\n", encoding="utf-8")
    for name in checker.MODEL_URL_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("HTTP_SERVER_HOST", raising=False)
    result = checker.check(env, live=False)
    assert result["sensitive_evidence_admission"] == "BLOCKED"
    assert "api.example.invalid" in str(result)
    assert "never-print-me" not in str(result)
    assert "secret:token" not in str(result)


def test_explicit_sample_manifest_is_not_an_implicit_acceptance(tmp_path):
    script = Path(__file__).resolve().parents[3] / "scripts" / "android_field_sample_manifest.py"
    spec = importlib.util.spec_from_file_location("android_field_sample_manifest", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "synthetic.img"
    source.write_bytes(b"synthetic only")
    example = Path(__file__).resolve().parents[3] / "docs" / "android-field-sample-manifest.example.json"
    manifest = json.loads(example.read_text(encoding="utf-8"))
    manifest["files"][0]["local_path"] = str(source)
    manifest["files"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert module.validate(path)["files"][0]["status"] == "HASH_NOT_CHECKED"
    checked = module.validate(path, full_hash=True)
    assert checked["files"][0]["status"] == "MATCH"
    assert checked["real_sample_acceptance"] == "NOT_RUN_BY_THIS_TOOL"


def test_checker_separates_loaded_baseline_from_pending(tmp_path, monkeypatch):
    checker = _load()
    env = tmp_path / "field.env"
    env.write_text("TRACELENS_FIELD_AUTH=enabled\nTRACELENS_REQUIRE_FIELD_AUTH=1\nFIELD_OUTBOUND_POLICY=disabled\n"
                   "HTTP_SERVER_HOST=127.0.0.1\nPYTHON_HTTP_HOST=127.0.0.1\n"
                   "FIELD_JWT_SECRET=synthetic-independent-secret-12345678901234567890\n"
                   "FIELD_CPP_TO_PYTHON_TOKEN=synthetic-cpp-token-12345678901234567890\n"
                   "FIELD_PYTHON_TO_CPP_TOKEN=synthetic-python-token-12345678901234567890\n",
                   encoding="utf-8")
    for name in ("TRACELENS_FIELD_AUTH", "HTTP_SERVER_HOST", "PYTHON_HTTP_HOST",
                 "LLM_BASE_URL", "LLM_TEXT_BASE_URL", "LLM_VISION_BASE_URL", "EMBEDDING_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert checker.check(env, live=False)["security_baseline_status"] == "DEPLOYMENT_PENDING"
    monkeypatch.setattr(checker, "_listeners", lambda ports: [
        {"address": "127.0.0.1:8666", "pid": 1}, {"address": "127.0.0.1:8090", "pid": 2}])
    monkeypatch.setattr(checker, "_systemd_egress", lambda item: {
        "status": "POLICY_APPLIED_TO_RUNNING_UNIT"})
    monkeypatch.setattr(checker, "verify_os_egress", lambda: {
        "status": "SYNTHETIC_SYSTEMD_EGRESS_DENIAL_VERIFIED"})

    def probe(url, *, method="GET", headers=None, payload=None, read_json=False):
        if url.endswith("/api/field-auth/login"):
            return 200, {"access_token": "synthetic-signed-token"}
        service = (headers or {}).get("X-TraceLens-Service-Token")
        if service:
            if url.endswith("/api/security/status"):
                return (200 if service == "synthetic-python-token-12345678901234567890" else 401), None
            if url.endswith("/api/field-auth/introspect"):
                return (200 if service == "synthetic-cpp-token-12345678901234567890" else 401), None
        bearer = (headers or {}).get("Authorization", "")
        if bearer == "Bearer synthetic-signed-token" and url.endswith("/status"):
            return 200, {"field_security_version": checker.FIELD_SECURITY_VERSION,
                         "field_auth": True, "required_auth": True, "outbound_policy": "disabled"}
        return 401, None

    monkeypatch.setattr(checker, "_request", probe)
    result = checker.check(env, username="analyst", password="synthetic", isolated=True)
    assert result["security_baseline_status"] == "PASS_SECURITY_BASELINE"
    assert result["sensitive_evidence_admission"] != "PASS_SECURITY_BASELINE"


def test_release_template_placeholders_fail_closed(tmp_path, monkeypatch):
    checker = _load()
    template = Path(__file__).resolve().parents[3] / "deploy/field/field-release-local.env.example"
    for name in ("TRACELENS_RELEASE_ROOT", "TRACELENS_RELEASE_ID", "TRACELENS_PYTHON_BIN",
                 "TRACELENS_LOG_ROOT", "DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    result = checker.check(template, live=False)
    assert result["security_baseline_status"] == "BLOCKED"
    assert any("release ID" in blocker for blocker in result["blockers"])
    assert "REPLACE_WITH_INDEPENDENT" not in str(result)
