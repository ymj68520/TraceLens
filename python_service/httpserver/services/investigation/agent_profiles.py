"""Source Specialist Profiles (P3 §27-28).

Profiles are THIN: long-lived platform identity, interpretation rules,
bound skills and default tool families. Investigation knowledge lives in
Skills, never here. A profile is only registered for platforms the repo can
identify deterministically (task scenarios). Memory images have no
deterministic task-level platform key in this repo, so no memory profile is
registered — absence is honest, not faked.
"""

from typing import Mapping

from pydantic import BaseModel, ConfigDict, field_validator

from .agent_capabilities import SourceCapabilityManifest
from .agent_runtime import canonical_state_json, state_hash_of

PROFILE_REGISTRY_VERSION = "source-specialist-profiles:v1"


class SourceSpecialistProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str
    version: str
    platform: str
    title: str
    mission: str

    supported_source_types: tuple[str, ...]

    default_tool_ids: tuple[str, ...] = ()
    available_skill_ids: tuple[str, ...] = ()

    interpretation_rules: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @field_validator("profile_id", "version")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("profile identifiers must be non-blank")
        return value

    def content_hash(self) -> str:
        return state_hash_of(canonical_state_json(self.model_dump()))

    def supports_source(self, source_type: str) -> bool:
        return source_type in self.supported_source_types

    def validate_registry_refs(
        self,
        *,
        known_tool_ids,
        known_skill_ids,
    ) -> None:
        """Every bound tool/skill must exist (fail closed at wiring time)."""
        missing_tools = [t for t in self.default_tool_ids if t not in known_tool_ids]
        missing_skills = [s for s in self.available_skill_ids if s not in known_skill_ids]
        if missing_tools or missing_skills:
            raise ValueError(
                f"profile {self.profile_id!r} binds unknown entries: "
                f"tools={missing_tools} skills={missing_skills}"
            )


def resolve_profile_for_source(
    profiles: Mapping[str, SourceSpecialistProfile],
    source_type: str,
) -> SourceSpecialistProfile:
    """Deterministic lookup; unknown sources fail deterministically."""
    profile = profiles.get(source_type)
    if profile is None or not profile.supports_source(source_type):
        raise KeyError(f"no profile for source type {source_type!r}")
    return profile


def default_profiles() -> dict[str, SourceSpecialistProfile]:
    windows = SourceSpecialistProfile(
        profile_id="windows.specialist",
        version="1",
        platform="windows",
        title="Windows Source Specialist",
        mission=(
            "Investigate Windows-derived evidence: account usage, execution "
            "traces, persistence, device activity and file activity."
        ),
        supported_source_types=("windows", "src_event_logs"),
        default_tool_ids=(
            "get_task_context",
            "search_evidence",
            "get_evidence",
            "search_files",
            "search_timeline",
            "find_related_evidence",
            "find_temporal_neighbors",
            "get_existing_analyses",
            "get_existing_claims",
            "query_platform_artifacts",
        ),
        available_skill_ids=(
            "windows.authentication",
            "windows.execution",
            "windows.persistence",
            "windows.usb",
            "windows.browser",
            "windows.file_activity",
        ),
        interpretation_rules=(
            "correlate logon events with account and source-ip context",
            "execution claims require prefetch/amcache corroboration",
        ),
        limitations=(
            "registry and event-log coverage depend on parser output presence",
        ),
    )
    android = SourceSpecialistProfile(
        profile_id="android.specialist",
        version="1",
        platform="android",
        title="Android Source Specialist",
        mission=(
            "Investigate Android-derived evidence: communication, app "
            "activity, account identity and device context."
        ),
        supported_source_types=("android",),
        default_tool_ids=(
            "get_task_context",
            "search_evidence",
            "get_evidence",
            "search_files",
            "search_timeline",
            "find_related_evidence",
            "find_temporal_neighbors",
            "get_existing_analyses",
            "get_existing_claims",
            "query_platform_artifacts",
        ),
        available_skill_ids=(
            "android.communication",
            "android.app_activity",
            "android.account_identity",
            "android.browser",
        ),
        interpretation_rules=(
            "distinguish backup-formed extractions from full-device images",
        ),
        limitations=(
            "app-data-form backups may lack SMS bodies entirely",
        ),
    )
    linux = SourceSpecialistProfile(
        profile_id="linux.specialist",
        version="1",
        platform="linux",
        title="Linux Source Specialist",
        mission=(
            "Investigate Linux/server-derived evidence: authentication, "
            "shell activity, persistence and account topology."
        ),
        supported_source_types=("linux", "server_cloud"),
        default_tool_ids=(
            "get_task_context",
            "search_evidence",
            "get_evidence",
            "search_files",
            "search_timeline",
            "find_related_evidence",
            "find_temporal_neighbors",
            "get_existing_analyses",
            "get_existing_claims",
            "query_platform_artifacts",
        ),
        available_skill_ids=(
            "linux.auth",
            "linux.execution",
            "linux.persistence",
        ),
        interpretation_rules=(
            "treat shell-history absence carefully: history is frequently "
            "disabled or cleared on servers",
        ),
        limitations=(
            "server_cloud sources expose the linux-family readers only",
        ),
    )
    return {
        "windows": windows,
        "android": android,
        "linux": linux,
        "src_event_logs": windows,
    }


__all__ = [
    "PROFILE_REGISTRY_VERSION",
    "SourceSpecialistProfile",
    "default_profiles",
    "resolve_profile_for_source",
]
