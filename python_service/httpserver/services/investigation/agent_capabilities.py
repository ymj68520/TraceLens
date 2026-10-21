"""ArtifactFamily registry + deterministic SourceCapabilityManifest (P3).

The manifest is runtime capability metadata built ONLY from task metadata,
parser outputs (artifact tables actually present in the platform database)
and the registered family catalog. No LLM classification, no filename
guessing, no heuristic text inference.

A manifest proves a capability is (un)available — it never proves a case
fact ("EVTX parser unavailable" supports "coverage unavailable", never
"the attacker did not log in").
"""

import enum
import sqlite3
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from .agent_runtime import canonical_state_json, state_hash_of

MANIFEST_VERSION = "source-capability-manifest:v1"
FAMILY_REGISTRY_VERSION = "artifact-family-registry:v1"


# ---------------------------------------------------------------------------
# family catalog
# ---------------------------------------------------------------------------


class ArtifactFamilyDefinition(BaseModel):
    """A safe query category — never a raw DB table exposed to callers."""

    model_config = ConfigDict(frozen=True)

    family_id: str
    version: str = "1"
    platform: str
    title: str
    description: str

    source_types: tuple[str, ...] = ()

    # whitelist of filter keys query_platform_artifacts may accept
    supported_filters: tuple[str, ...] = ("text_contains",)

    # artifact tables whose presence makes this family available
    required_tables: tuple[str, ...] = ()
    # "any": one backing table present -> available; "all": strict conjunction
    table_presence: str = "any"

    # typed platform-reader facade binding (graphiti database readers)
    reader_method: str = ""
    reader_kwargs: Mapping[str, str] = {}

    tool_binding: str = "query_platform_artifacts"
    limitations: tuple[str, ...] = ()


def _family(
    family_id: str, title: str, description: str, tables: tuple[str, ...],
    reader_method: str = "", reader_kwargs: Mapping[str, str] | None = None,
    limitations: tuple[str, ...] = (),
) -> ArtifactFamilyDefinition:
    platform = family_id.split(".", 1)[0]
    return ArtifactFamilyDefinition(
        family_id=family_id,
        platform=platform,
        title=title,
        description=description,
        source_types=(platform,),
        required_tables=tables,
        reader_method=reader_method,
        reader_kwargs=dict(reader_kwargs or {}),
        limitations=limitations,
    )


def default_family_catalog() -> tuple[ArtifactFamilyDefinition, ...]:
    """Families backed by real platform readers / parser outputs.

    Windows families mirror the Windows platform reader coverage
    (registry/event logs/prefetch/user accounts/USB/browser/services);
    Android families mirror the Android reader (contacts/sms/calls/
    browser/installed packages/wifi/im exports); Linux families mirror the
    Linux reader (accounts/shell history/login records/logs). No family is
    invented beyond this parser coverage.
    """
    return (
        _family(
            "windows.registry", "Windows Registry artifacts",
            "Registry value extraction (SOFTWARE/SYSTEM/NTUSER hives).",
            ("registry_values",),
            reader_method="get_registry_values",
        ),
        _family(
            "windows.event_logs", "Windows Event Log entries",
            "Parsed Windows event log records.",
            ("event_log_entries", "event_logs"),
            reader_method="get_event_logs",
        ),
        _family(
            "windows.prefetch", "Windows Prefetch",
            "Prefetch execution artifacts (absence is not proof of no execution).",
            ("prefetch_files",),
            reader_method="get_prefetch_files",
            limitations=("prefetch absence != no execution",),
        ),
        _family(
            "windows.user_accounts", "Windows user accounts",
            "Local account metadata (SAM/System readers).",
            ("user_accounts",),
            reader_method="get_user_accounts",
        ),
        _family(
            "windows.usb_devices", "USB device history",
            "USB storage/device pairing history.",
            ("usb_devices",),
            reader_method="get_usb_devices",
        ),
        _family(
            "windows.browser_history", "Windows browser history",
            "Browser history rows (Chrome/Edge readers).",
            ("browser_history",),
            reader_method="get_browser_history",
        ),
        _family(
            "windows.services", "Windows services",
            "Service configuration and state records.",
            ("windows_services", "services"),
            reader_method="get_services",
        ),
        _family(
            "android.contacts", "Android contacts",
            "Contact records from Android databases/MIUI backups.",
            ("contacts",),
            reader_method="get_contacts",
        ),
        _family(
            "android.sms", "Android SMS",
            "SMS messages. Backup-only extractions may carry no bodies.",
            ("sms_messages",),
            reader_method="get_sms_messages",
            limitations=("app-data-form backups may contain no SMS bodies",),
        ),
        _family(
            "android.call_logs", "Android call logs",
            "Call log entries.",
            ("call_logs",),
            reader_method="get_call_logs",
        ),
        _family(
            "android.browser", "Android browser history",
            "Chrome/browser history rows.",
            ("chrome_history",),
            reader_method="get_chrome_history",
        ),
        _family(
            "android.installed_packages", "Android installed packages",
            "Installed application packages.",
            ("installed_packages", "system_apps", "installed_apps"),
            reader_method="get_installed_packages",
        ),
        _family(
            "android.wifi", "Android Wi-Fi networks",
            "Known Wi-Fi network records.",
            ("wifi_networks",),
            reader_method="get_wifi_networks",
        ),
        _family(
            "android.wechat_messages", "WeChat message exports",
            "WeChat message export tables.",
            ("wechat_messages",),
            reader_method="get_chat_messages",
            reader_kwargs={"platform": "wechat"},
        ),
        _family(
            "android.qq_messages", "QQ message exports",
            "QQ message export tables.",
            ("qq_messages",),
            reader_method="get_chat_messages",
            reader_kwargs={"platform": "wechat"},
            limitations=("QQ imports reuse the wechat table mapping",),
        ),
        _family(
            "android.telegram_messages", "Telegram message exports",
            "Telegram message export tables.",
            ("telegram_messages",),
            reader_method="get_chat_messages",
            reader_kwargs={"platform": "telegram"},
        ),
        _family(
            "linux.user_accounts", "Linux user accounts",
            "passwd/group derived account records.",
            ("user_accounts",),
            reader_method="get_user_accounts",
        ),
        _family(
            "linux.shell_history", "Linux shell history",
            "Shell history entries (absence is not proof of no execution).",
            ("shell_history",),
            reader_method="get_shell_history",
            limitations=("shell history may be disabled or cleared",),
        ),
        _family(
            "linux.login_records", "Linux login records",
            "wtmp/btmp/lastlog-derived login records.",
            ("login_records",),
            reader_method="get_login_records",
        ),
        _family(
            "linux.log_entries", "Linux log entries",
            "Parsed syslog/auth.log style entries.",
            ("log_entries",),
            reader_method="get_log_entries",
        ),
    )


class ArtifactFamilyRegistry(BaseModel):
    """Deterministic family catalog (frozen, hashable content)."""

    model_config = ConfigDict(frozen=True)

    registry_version: str = FAMILY_REGISTRY_VERSION
    families: tuple[ArtifactFamilyDefinition, ...]

    @classmethod
    def with_defaults(cls) -> "ArtifactFamilyRegistry":
        return cls(families=default_family_catalog())

    def resolve(self, family_id: str) -> Optional[ArtifactFamilyDefinition]:
        return self._by_id().get(family_id)

    def _by_id(self) -> dict[str, ArtifactFamilyDefinition]:
        return {family.family_id: family for family in self.families}

    def families_for_platform(self, platform: str) -> tuple[ArtifactFamilyDefinition, ...]:
        return tuple(f for f in self.families if f.platform == platform)

    def registry_hash(self) -> str:
        payload = {
            "registry_version": self.registry_version,
            "families": sorted(
                f.family_id for f in self.families
            ),
        }
        return state_hash_of(canonical_state_json(payload))


# ---------------------------------------------------------------------------
# deterministic table discovery (parser-output presence)
# ---------------------------------------------------------------------------


def list_sqlite_tables(db_path: str | Path) -> frozenset[str]:
    """Read-only sqlite_master listing (same pattern as platform detection)."""
    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        conn.close()
    return frozenset(row[0] for row in rows)


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


class FamilyAvailability(str, enum.Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class FamilyCapability(BaseModel):
    model_config = ConfigDict(frozen=True)

    family_id: str
    family_version: str
    availability: FamilyAvailability
    reason_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class SourceCapabilityManifest(BaseModel):
    """Frozen capability view of one source scope (never Evidence)."""

    model_config = ConfigDict(frozen=True)

    manifest_version: str = MANIFEST_VERSION
    task_id: str
    source_scope_id: str
    source_type: str
    platform: str

    artifact_families: tuple[FamilyCapability, ...] = ()
    available_tool_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    generated_at: Optional[str] = None  # audit stamp only, outside input_hash

    def input_hash(self) -> str:
        """Deterministic hash; same source state -> same hash.

        generated_at is deliberately excluded (audit stamp, not capability
        state)."""
        payload = self.model_dump(exclude={"generated_at"})
        return state_hash_of(canonical_state_json(payload))


def build_source_capability_manifest(
    task: Mapping[str, Any],
    source_scope_id: str,
    family_registry: ArtifactFamilyRegistry,
    *,
    available_tool_ids: Iterable[str] = (),
    table_lister: Callable[[str], frozenset[str]] = list_sqlite_tables,
) -> SourceCapabilityManifest:
    """Build the manifest deterministically from trusted task metadata.

    Availability rules (content-based, never filename guessing):
      scenario absent from task.scenarios            -> NOT_APPLICABLE
      scenario db missing from scenario_databases    -> UNAVAILABLE
      none of the family's artifact tables present   -> UNAVAILABLE
      some artifact tables present                   -> PARTIAL
      all artifact tables present                    -> AVAILABLE
    """
    scenarios = {
        str(item) for item in (task.get("scenarios") or ())
    }
    scenario_dbs = dict(task.get("scenario_databases") or {})

    # Resolve platform alias (e.g. src_server -> linux, src_pc -> windows, src_phone -> android)
    target_platform = source_scope_id
    scope_lower = source_scope_id.lower()
    if "server" in scope_lower or "linux" in scope_lower:
        target_platform = "linux"
    elif "android" in scope_lower or "phone" in scope_lower:
        target_platform = "android"
    elif "pc" in scope_lower or "windows" in scope_lower:
        target_platform = "windows"

    families = family_registry.families_for_platform(target_platform)
    capabilities: list[FamilyCapability] = []
    limitations: list[str] = []

    if source_scope_id not in scenarios and target_platform not in scenarios:
        caps = tuple(
            FamilyCapability(
                family_id=f.family_id,
                family_version=f.version,
                availability=FamilyAvailability.NOT_APPLICABLE,
                reason_codes=("source_type_not_in_task_scenarios",),
                limitations=f.limitations,
            )
            for f in families
        )
        return SourceCapabilityManifest(
            task_id=str(task.get("id") or ""),
            source_scope_id=source_scope_id,
            source_type=target_platform,
            platform=target_platform,
            artifact_families=caps,
            available_tool_ids=tuple(sorted(set(available_tool_ids))),
            limitations=(
                "source scope is not part of this task's detected scenarios",
            ),
        )

    db_path = scenario_dbs.get(source_scope_id) or scenario_dbs.get(target_platform)
    if not db_path:
        caps = tuple(
            FamilyCapability(
                family_id=f.family_id,
                family_version=f.version,
                availability=FamilyAvailability.UNAVAILABLE,
                reason_codes=("platform_database_missing",),
                limitations=f.limitations,
            )
            for f in families
        )
        limitations.append(
            "platform scenario declared but no platform database is attached"
        )
        return SourceCapabilityManifest(
            task_id=str(task.get("id") or ""),
            source_scope_id=source_scope_id,
            source_type=source_scope_id,
            platform=source_scope_id,
            artifact_families=caps,
            available_tool_ids=tuple(sorted(set(available_tool_ids))),
            limitations=tuple(limitations),
        )

    tables = set(table_lister(db_path))
    for family in families:
        present = [t for t in family.required_tables if t in tables]
        if not present:
            availability = FamilyAvailability.UNAVAILABLE
            reason = ("artifact_tables_absent",)
        elif family.table_presence == "all" and len(present) < len(family.required_tables):
            availability = FamilyAvailability.PARTIAL
            reason = ("artifact_tables_partially_present",)
        else:
            availability = FamilyAvailability.AVAILABLE
            reason = ()
        capabilities.append(
            FamilyCapability(
                family_id=family.family_id,
                family_version=family.version,
                availability=availability,
                reason_codes=reason,
                limitations=family.limitations,
            )
        )
    if not tables:
        limitations.append("platform database exposes no parsed artifact tables")

    return SourceCapabilityManifest(
        task_id=str(task.get("id") or ""),
        source_scope_id=source_scope_id,
        source_type=source_scope_id,
        platform=source_scope_id,
        artifact_families=tuple(capabilities),
        available_tool_ids=tuple(sorted(set(available_tool_ids))),
        limitations=tuple(limitations),
    )


__all__ = [
    "ArtifactFamilyDefinition",
    "ArtifactFamilyRegistry",
    "FamilyAvailability",
    "FamilyCapability",
    "MANIFEST_VERSION",
    "SourceCapabilityManifest",
    "build_source_capability_manifest",
    "default_family_catalog",
    "list_sqlite_tables",
]
