"""Synthetic certificate fixture only; never changes host trust."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_field_tls import verify


def _run(*args):
    subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True, timeout=15)


def test_local_tls_material_requires_matching_key_hostname_and_ca(tmp_path):
    ca_key, ca_cert = tmp_path / "ca.key", tmp_path / "ca.crt"
    key, csr, cert = tmp_path / "leaf.key", tmp_path / "leaf.csr", tmp_path / "leaf.crt"
    _run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", ca_key,
         "-out", ca_cert, "-subj", "/CN=Synthetic Test CA", "-days", "30")
    _run("req", "-newkey", "rsa:2048", "-nodes", "-keyout", key,
         "-out", csr, "-subj", "/CN=synthetic.local")
    ext = tmp_path / "extensions.txt"
    ext.write_text("subjectAltName=DNS:synthetic.local\n", encoding="ascii")
    _run("x509", "-req", "-in", csr, "-CA", ca_cert, "-CAkey", ca_key,
         "-CAcreateserial", "-out", cert, "-days", "30", "-extfile", ext)
    key.chmod(0o600)
    assert verify(cert, key, ca_cert, "synthetic.local")["status"] == "CERTIFICATE_FILES_VALIDATED_OFFLINE"
    with pytest.raises(ValueError):
        verify(cert, key, ca_cert, "wrong.local")
    key.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        verify(cert, key, ca_cert, "synthetic.local")
