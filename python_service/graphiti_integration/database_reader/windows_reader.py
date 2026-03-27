"""
Windows database reader module for Windows artifacts.
"""

from typing import Iterator, Optional

from ..forensic_data_types import (
    WindowsRegistryValue,
    WindowsEventLog,
    WindowsPrefetchInfo,
    WindowsUserInfo,
    WindowsUSBDevice,
    WindowsBrowserHistory,
    WindowsService,
)
from .base_reader import _BaseForensicsReader


# =============================================================================
# Windows Database Reader (_windows.db)
# =============================================================================

class WindowsDatabase(_BaseForensicsReader):
    """Reader for Windows analysis database ({image}_windows.db)."""

    def get_registry_values(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("registry_values", limit=limit, offset=offset)
        return [
            WindowsRegistryValue(
                id=r["id"], key_path=r["key_path"] or "",
                value_name=r["value_name"] or "", value_type=r["value_type"] or "",
                value_data=r["value_data"] or "", last_modified=r["last_modified"] or 0,
            )
            for r in rows
        ]

    def get_event_logs(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("event_log_entries", limit=limit, offset=offset)
        return [
            WindowsEventLog(
                id=r["id"], log_name=r["log_name"] or "",
                event_id=r["event_id"] or 0, level=r["level"] or "",
                source=r["source"] or "", timestamp=r["timestamp"] or 0,
                computer=r["computer"] or "", message=r["message"] or "",
                user_sid=r["user_sid"] or "",
            )
            for r in rows
        ]

    def get_prefetch_files(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("prefetch_files", limit=limit, offset=offset)
        return [
            WindowsPrefetchInfo(
                id=r["id"], executable_name=r["executable_name"] or "",
                prefetch_hash=r["prefetch_hash"] or "",
                run_count=r["run_count"] or 0,
                last_run_time=r["last_run_time"] or 0,
                file_path=r["file_path"] or "",
            )
            for r in rows
        ]

    def get_user_accounts(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("user_accounts", limit=limit, offset=offset)
        return [
            WindowsUserInfo(
                id=r["id"], username=r["username"] or "",
                sid=r["sid"] or "", full_name=r["full_name"] or "",
                account_type=r["account_type"] or "",
                last_login=r["last_login"] or 0,
                login_count=r["login_count"] or 0,
                is_disabled=bool(r["is_disabled"]),
                is_locked=bool(r["is_locked"]),
            )
            for r in rows
        ]

    def get_usb_devices(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("usb_devices", limit=limit, offset=offset)
        return [
            WindowsUSBDevice(
                id=r["id"], device_name=r["device_name"] or "",
                vendor_id=r["vendor_id"] or "", product_id=r["product_id"] or "",
                serial_number=r["serial_number"] or "",
                first_connected=r["first_connected"] or 0,
                last_connected=r["last_connected"] or 0,
                device_class=r["device_class"] or "",
            )
            for r in rows
        ]

    def get_browser_history(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("browser_history", limit=limit, offset=offset)
        return [
            WindowsBrowserHistory(
                id=r["id"], url=r["url"] or "", title=r["title"] or "",
                visit_count=r["visit_count"] or 0,
                last_visit=r["last_visit"] or 0,
                browser_name=r["browser_name"] or "",
            )
            for r in rows
        ]

    def get_services(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("windows_services", limit=limit, offset=offset)
        return [
            WindowsService(
                id=r["id"], service_name=r["service_name"] or "",
                display_name=r["display_name"] or "",
                binary_path=r["binary_path"] or "",
                start_type=r["start_type"] or "",
                service_type=r["service_type"] or "",
                account=r["account"] or "", state=r["state"] or "",
            )
            for r in rows
        ]

    def get_stats(self) -> dict:
        """Get Windows database statistics."""
        tables = [
            "registry_values", "event_log_entries", "prefetch_files",
            "user_accounts", "usb_devices", "browser_history",
            "windows_services", "amcache_entries", "srum_entries",
            "lnk_files", "jump_list_entries", "recycle_bin_entries",
        ]
        return {t: self._count_rows(t) for t in tables}

    def get_all_artifacts_batched(self, batch_size: int = 100) -> Iterator[tuple]:
        """Iterate over all artifact types, yielding (artifact_type, records)."""
        methods = [
            ("registry_values", self.get_registry_values),
            ("event_logs", self.get_event_logs),
            ("prefetch_files", self.get_prefetch_files),
            ("user_accounts", self.get_user_accounts),
            ("usb_devices", self.get_usb_devices),
            ("browser_history", self.get_browser_history),
            ("services", self.get_services),
        ]
        for artifact_type, method in methods:
            offset = 0
            while True:
                batch = method(limit=batch_size, offset=offset)
                if not batch:
                    break
                yield artifact_type, batch
                offset += len(batch)
