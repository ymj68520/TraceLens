#!/usr/bin/env python3
"""Provision local field users without putting passwords on command lines."""

import argparse
import getpass
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_service"))
from httpserver.services.field_security import ROLES, _PASSWORDS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True, help="owner-only JSON outside Git")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", required=True, choices=sorted(ROLES))
    parser.add_argument("--create", action="store_true", help="create a new user file")
    args = parser.parse_args()
    path = args.file.absolute()
    if not args.username or len(args.username) > 128 or path.is_symlink():
        parser.error("invalid username or user file")
    if args.create:
        if path.exists():
            parser.error("user file already exists")
        data = {"users": {}}
    else:
        if not path.is_file() or path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            parser.error("existing user file must be owner-only")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("users"), dict):
            parser.error("invalid user file")
    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12 or password != confirmation:
        parser.error("passwords differ or are shorter than 12 characters")
    previous = data["users"].get(args.username, {})
    data["users"][args.username] = {
        "password_hash": _PASSWORDS.hash(password), "role": args.role,
        "active": True, "token_version": int(previous.get("token_version", -1)) + 1,
    }
    os.umask(0o077)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".field-users-", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    print("Field user updated; existing tokens for this user are revoked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
