"""RCA-2A.2c — preflight artifact protection (directive §4).

Synthetic-file tests for the benchmark capacity-preflight output-path
contract:

- the output path is a REQUIRED explicit argument (no implicit default
  into any results/qualification directory);
- an existing artifact is never overwritten (atomic O_CREAT|O_EXCL
  exclusive create; exit code 3 on refusal);
- a refused or failed write leaves the pre-existing file byte-identical;
- no API key material ever reaches the artifact (only the boolean
  api_key_present).

Provider request content and preflight gate thresholds are untouched:
the probe functions are replaced with deterministic synthetic records
and no network client is ever constructed.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = PYTHON_SERVICE_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from benchmark_output_guard import OutputPathError, exclusive_output_file

PREFLIGHT_SCRIPTS = [
    "capacity_preflight_stepfun.py",
    "capacity_preflight_stepfun_step5preview.py",
    "capacity_preflight_openrouter.py",
]


# ---------------------------------------------------------------------------
# the shared guard (the exact function every preflight script writes through)
# ---------------------------------------------------------------------------


def test_exclusive_create_creates_fresh_file(tmp_path):
    target = tmp_path / "nested" / "capacity-preflight.json"
    with exclusive_output_file(target) as fh:
        fh.write('{"synthetic": true}\n')
    assert json.loads(target.read_text()) == {"synthetic": True}


def test_exclusive_create_refuses_existing_file_and_leaves_it_intact(tmp_path):
    target = tmp_path / "capacity-preflight.json"
    original = '{"historical": "artifact", "immutable": true}\n'
    target.write_text(original)

    with pytest.raises(OutputPathError):
        with exclusive_output_file(target) as fh:  # pragma: no cover
            fh.write("overwrite")

    assert target.read_text() == original


def test_exclusive_create_is_atomic_no_clobber(tmp_path):
    target = tmp_path / "capacity-preflight.json"
    target.write_text("original")
    import os

    with pytest.raises(FileExistsError):
        os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    assert target.read_text() == "original"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bit")
def test_exclusive_create_file_mode_0600(tmp_path):
    target = tmp_path / "artifact.json"
    with exclusive_output_file(target) as fh:
        fh.write("{}")
    assert (target.stat().st_mode & 0o777) == 0o600


# ---------------------------------------------------------------------------
# every preflight script requires an explicit --out (argparse, offline)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", PREFLIGHT_SCRIPTS)
def test_preflight_rejects_missing_out_flag(script):
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script)],
        capture_output=True,
        text=True,
        cwd=str(PYTHON_SERVICE_ROOT),
        timeout=120,
    )
    # argparse exits 2 on the missing required argument BEFORE any
    # settings load, probe or network activity
    assert proc.returncode == 2
    assert "--out" in (proc.stderr + proc.stdout)


@pytest.mark.parametrize("script", PREFLIGHT_SCRIPTS)
def test_preflight_writes_only_through_the_exclusive_guard(script):
    source = (SCRIPTS / script).read_text(encoding="utf-8")
    assert "exclusive_output_file(" in source
    # no direct artifact write survives the audit
    assert "out.write_text" not in source
    assert "RESULTS.mkdir" not in source
    assert "never overwritten" in source


# ---------------------------------------------------------------------------
# full write path with synthetic probes (monkeypatched, zero network)
# ---------------------------------------------------------------------------


def _load_script(name):
    spec = importlib.util.spec_from_file_location(
        name.replace(".py", "_audit"), SCRIPTS / name
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_probe(module_identity_exact=True):
    def _fake_asyncio_run(coro, *args):
        # the script passes the real probe coroutine; close it unawaited
        # (zero network) and return the deterministic synthetic record
        coro.close()
        return {
            "probe": 1,
            "requested_model": "synthetic-model",
            "returned_model": "synthetic-model",
            "content_ok": True,
            "identity_exact": module_identity_exact,
            "rate_limit_headers": {},
        }

    return _fake_asyncio_run


@pytest.mark.parametrize("script", PREFLIGHT_SCRIPTS)
def test_preflight_write_path_synthetic_and_fresh_out(script, tmp_path, monkeypatch):
    module = _load_script(script)
    monkeypatch.setattr(
        module.asyncio, "run", _synthetic_probe(), raising=True
    )
    out = tmp_path / "fresh" / "capacity-preflight.json"
    rc = module.main(["--out", str(out)]) if _main_accepts_argv(module) \
        else _with_argv(module, ["--out", str(out)])
    assert rc in (0, 2)  # gate verdict only — never an output failure
    record = json.loads(out.read_text())
    assert record["disposition"] in (
        "CAPACITY_PREFLIGHT_PASS", "PROVIDER_CAPACITY_BLOCKED"
    )
    # key hygiene: boolean presence only
    assert isinstance(record["api_key_present"], bool)
    artifact_text = out.read_text()
    assert "llm_api_key" not in artifact_text
    assert "OPENROUTER_API_KEY" not in artifact_text


@pytest.mark.parametrize("script", PREFLIGHT_SCRIPTS)
def test_preflight_refuses_existing_artifact_synthetic(script, tmp_path, monkeypatch):
    module = _load_script(script)
    monkeypatch.setattr(
        module.asyncio, "run", _synthetic_probe(), raising=True
    )
    out = tmp_path / "capacity-preflight.json"
    original = '{"historical": true}'
    out.write_text(original)

    rc = module.main(["--out", str(out)]) if _main_accepts_argv(module) \
        else _with_argv(module, ["--out", str(out)])
    assert rc == 3
    assert out.read_text() == original


def _main_accepts_argv(module) -> bool:
    import inspect

    return "argv" in inspect.signature(module.main).parameters


def _with_argv(module, argv):
    import sys as _sys

    old = _sys.argv
    _sys.argv = [module.__file__] + argv
    try:
        return module.main()
    finally:
        _sys.argv = old
