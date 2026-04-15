"""
Linux database reader module for Linux artifacts.
"""

from typing import Iterator, Optional

from graphiti_integration.forensic_data_types import (
    LinuxLogEntry,
    LinuxUserInfo,
    LinuxShellHistory,
    LinuxLoginRecord,
    LinuxGroupInfo,
)
from .base_reader import _BaseForensicsReader


# =============================================================================
# Linux Database Reader (_linux.db)
# =============================================================================

class LinuxDatabase(_BaseForensicsReader):
    """Reader for Linux analysis database ({image}_linux.db)."""

    def get_log_entries(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("log_entries", limit=limit, offset=offset)
        return [
            LinuxLogEntry(
                id=r["id"], log_file=r["log_file"] or "",
                timestamp=r["timestamp"] or 0, facility=r["facility"] or "",
                severity=r["severity"] or "", hostname=r["hostname"] or "",
                process_name=r["process_name"] or "", pid=r["pid"] or 0,
                message=r["message"] or "",
            )
            for r in rows
        ]

    def get_user_accounts(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("user_accounts", limit=limit, offset=offset)
        return [
            LinuxUserInfo(
                id=r["id"], username=r["username"] or "",
                uid=r["uid"] or 0, gid=r["gid"] or 0,
                home_dir=r["home_dir"] or "", shell=r["shell"] or "",
                gecos=r["gecos"] or "", password_hash=r["password_hash"] or "",
                last_password_change=r["last_password_change"] or 0,
            )
            for r in rows
        ]

    def get_shell_history(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("shell_history", limit=limit, offset=offset)
        return [
            LinuxShellHistory(
                id=r["id"], username=r["username"] or "",
                command=r["command"] or "", timestamp=r["timestamp"] or 0,
                shell_type=r["shell_type"] or "",
                sequence_num=r["sequence_num"] or 0,
            )
            for r in rows
        ]

    def get_login_records(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("login_records", limit=limit, offset=offset)
        return [
            LinuxLoginRecord(
                id=r["id"], username=r["username"] or "",
                terminal=r["terminal"] or "", host=r["host"] or "",
                login_time=r["login_time"] or 0,
                logout_time=r["logout_time"] or 0,
                login_type=r["login_type"] or "",
            )
            for r in rows
        ]

    def get_groups(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("groups", limit=limit, offset=offset)
        return [
            LinuxGroupInfo(
                id=r["id"], group_name=r["group_name"] or "",
                gid=r["gid"] or 0, members=r["members"] or "",
            )
            for r in rows
        ]

    def get_stats(self) -> dict:
        tables = ["log_entries", "user_accounts", "shell_history", "login_records", "groups"]
        return {t: self._count_rows(t) for t in tables}

    def get_all_artifacts_batched(self, batch_size: int = 100) -> Iterator[tuple]:
        methods = [
            ("user_accounts", self.get_user_accounts),
            ("shell_history", self.get_shell_history),
            ("login_records", self.get_login_records),
            ("log_entries", self.get_log_entries),
            ("groups", self.get_groups),
        ]
        for artifact_type, method in methods:
            offset = 0
            while True:
                batch = method(limit=batch_size, offset=offset)
                if not batch:
                    break
                yield artifact_type, batch
                offset += len(batch)
