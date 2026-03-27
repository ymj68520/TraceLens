"""
Android database reader module for Android artifacts.
"""

from typing import Iterator, Optional

from ..forensic_data_types import (
    AndroidContact,
    AndroidSMS,
    AndroidCallLog,
    AndroidChatMessage,
    AndroidChromeHistory,
    AndroidInstalledPackage,
    AndroidWifiNetwork,
)
from .base_reader import _BaseForensicsReader


# =============================================================================
# Android Database Reader (_android.db)
# =============================================================================

class AndroidDatabase(_BaseForensicsReader):
    """Reader for Android analysis database ({image}_android.db)."""

    def get_contacts(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("contacts", limit=limit, offset=offset)
        return [
            AndroidContact(
                id=r["id"], display_name=r["display_name"] or "",
                phone_number=r["phone_number"] or "",
                email=r["email"] or "",
                account_type=r["account_type"] or "",
                account_name=r["account_name"] or "",
            )
            for r in rows
        ]

    def get_sms_messages(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("sms_messages", limit=limit, offset=offset)
        return [
            AndroidSMS(
                id=r["id"], address=r["address"] or "",
                body=r["body"] or "", date=r["date"] or 0,
                date_sent=r["date_sent"] or 0, read=r["read"] or 0,
                type=r["type"] or 0, service_center=r["service_center"] or "",
            )
            for r in rows
        ]

    def get_call_logs(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("call_logs", limit=limit, offset=offset)
        return [
            AndroidCallLog(
                id=r["id"], number=r["number"] or "",
                date=r["date"] or 0, duration=r["duration"] or 0,
                type=r["type"] or 0, name=r["name"] or "",
                geocoded_location=r["geocoded_location"] or "",
            )
            for r in rows
        ]

    def get_chat_messages(
        self, platform: str = "whatsapp", limit: Optional[int] = None, offset: int = 0,
    ) -> list:
        table_map = {
            "whatsapp": "whatsapp_messages",
            "telegram": "telegram_messages",
            "wechat": "wechat_messages",
        }
        table = table_map.get(platform)
        if not table:
            return []
        rows = self._query_table(table, limit=limit, offset=offset)
        return [
            AndroidChatMessage(
                id=r["id"], platform=platform,
                sender=r["sender"] or "", receiver=r["receiver"] or "",
                content=r["content"] or "", timestamp=r["timestamp"] or 0,
                media_url=r["media_url"] or "", media_type=r["media_type"] or "",
            )
            for r in rows
        ]

    def get_chrome_history(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("chrome_history", limit=limit, offset=offset)
        return [
            AndroidChromeHistory(
                id=r["id"], url=r["url"] or "", title=r["title"] or "",
                visit_count=r["visit_count"] or 0,
                last_visit_time=r["last_visit_time"] or 0,
                typed_count=r["typed_count"] or 0,
            )
            for r in rows
        ]

    def get_installed_packages(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("installed_packages", limit=limit, offset=offset)
        return [
            AndroidInstalledPackage(
                id=r["id"], package_name=r["package_name"] or "",
                code_path=r["code_path"] or "",
                first_install_time=r["first_install_time"] or 0,
                last_update_time=r["last_update_time"] or 0,
                version=r["version"] or "", installer=r["installer"] or "",
            )
            for r in rows
        ]

    def get_wifi_networks(self, limit: Optional[int] = None, offset: int = 0) -> list:
        rows = self._query_table("wifi_networks", limit=limit, offset=offset)
        return [
            AndroidWifiNetwork(
                id=r["id"], ssid=r["ssid"] or "",
                pre_shared_key=r["pre_shared_key"] or "",
                key_mgmt=r["key_mgmt"] or "",
                last_connected=r["last_connected"] or 0,
            )
            for r in rows
        ]

    def get_stats(self) -> dict:
        tables = [
            "contacts", "sms_messages", "call_logs",
            "whatsapp_messages", "telegram_messages", "wechat_messages",
            "chrome_history", "installed_packages", "wifi_networks",
            "usage_stats",
        ]
        return {t: self._count_rows(t) for t in tables}

    def get_all_artifacts_batched(self, batch_size: int = 100) -> Iterator[tuple]:
        methods = [
            ("contacts", self.get_contacts),
            ("sms_messages", self.get_sms_messages),
            ("call_logs", self.get_call_logs),
            ("chrome_history", self.get_chrome_history),
            ("installed_packages", self.get_installed_packages),
            ("wifi_networks", self.get_wifi_networks),
        ]
        # Add chat platforms
        for platform in ["whatsapp", "telegram", "wechat"]:
            methods.append(
                (f"{platform}_messages", lambda limit=None, offset=0, p=platform: self.get_chat_messages(p, limit, offset))
            )
        for artifact_type, method in methods:
            offset = 0
            while True:
                batch = method(limit=batch_size, offset=offset)
                if not batch:
                    break
                yield artifact_type, batch
                offset += len(batch)
