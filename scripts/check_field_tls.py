#!/usr/bin/env python3
"""Verify an approved local TLS certificate/key without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import subprocess
from pathlib import Path


def _openssl(*args: str) -> bytes:
    result = subprocess.run(["openssl", *args], capture_output=True, timeout=8, check=False)
    if result.returncode:
        raise ValueError("TLS certificate, key, hostname or trust-chain verification failed")
    return result.stdout


def verify(cert: Path, key: Path, ca: Path, hostname: str, chain: Path | None = None) -> dict:
    files = [cert, key, ca, *([chain] if chain else [])]
    if (not hostname or "*" in hostname or "/" in hostname or
            any(not path.is_absolute() or path.is_symlink() or not path.is_file() for path in files)):
        raise ValueError("explicit regular TLS files and exact hostname are required")
    if key.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ValueError("TLS private key must be owner-only")
    cert_public = _openssl("x509", "-in", str(cert), "-pubkey", "-noout")
    key_public = _openssl("pkey", "-in", str(key), "-pubout")
    if cert_public != key_public:
        raise ValueError("TLS private key does not match the certificate")
    _openssl("x509", "-in", str(cert), "-checkend", str(7 * 24 * 3600), "-noout")
    command = ["verify", "-CAfile", str(ca), "-verify_hostname", hostname]
    if chain:
        command += ["-untrusted", str(chain)]
    _openssl(*command, str(cert))
    return {"status": "CERTIFICATE_FILES_VALIDATED_OFFLINE",
            "certificate_sha256": hashlib.sha256(cert.read_bytes()).hexdigest(),
            "hostname": hostname, "key_matches": True, "valid_for_at_least_days": 7,
            "chain_verified_against_selected_ca": True,
            "listener_and_client_trust_verified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--chain", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.cert, args.key, args.ca, args.hostname, args.chain),
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
