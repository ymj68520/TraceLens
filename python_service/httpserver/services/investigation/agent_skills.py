"""Skill definitions + starter catalog (P3 §29-31).

A Skill is not an Agent, not a Tool and not a workflow step: it is durable
domain knowledge (coverage mapping, question patterns, artifact families,
pitfalls) that the deterministic SkillResolver projects into a Specialist
Context. Pitfalls are first-class fields.

The starter catalog only registers skills backed by real parser/reader
capability in this repository. Unsupported items stay unregistered.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from .agent_runtime import canonical_state_json, state_hash_of

SKILL_REGISTRY_VERSION = "skill-registry:v1"


class SkillDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    skill_id: str
    version: str
    platform: str

    title: str
    description: str

    # coverage dimension labels this skill can satisfy
    applicable_coverage_dimensions: tuple[str, ...] = ()
    # deterministic lowercase keyword hints matched against the question text
    question_patterns: tuple[str, ...] = ()

    knowledge: tuple[str, ...] = ()
    artifact_families: tuple[str, ...] = ()
    suggested_tool_ids: tuple[str, ...] = ()

    interpretation_rules: tuple[str, ...] = ()
    pitfalls: tuple[str, ...] = ()
    escalation_signals: tuple[str, ...] = ()
    output_guidance: tuple[str, ...] = ()

    @field_validator("skill_id", "version")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("skill identifiers must be non-blank")
        return value

    def content_hash(self) -> str:
        return state_hash_of(canonical_state_json(self.model_dump()))


def _skill(
    skill_id: str,
    title: str,
    description: str,
    *,
    dimensions: tuple[str, ...],
    patterns: tuple[str, ...],
    families: tuple[str, ...],
    tools: tuple[str, ...],
    knowledge: tuple[str, ...] = (),
    pitfalls: tuple[str, ...] = (),
    escalation: tuple[str, ...] = (),
) -> SkillDefinition:
    platform = skill_id.split(".", 1)[0]
    return SkillDefinition(
        skill_id=skill_id,
        version="1",
        platform=platform,
        title=title,
        description=description,
        applicable_coverage_dimensions=dimensions,
        question_patterns=patterns,
        knowledge=knowledge,
        artifact_families=families,
        suggested_tool_ids=tools,
        interpretation_rules=(),
        pitfalls=pitfalls,
        escalation_signals=escalation,
        output_guidance=(
            "cite evidence_keys for every factual statement",
        ),
    )


_READ_TOOLS = (
    "search_evidence",
    "get_evidence",
    "search_timeline",
    "find_related_evidence",
    "find_temporal_neighbors",
    "get_existing_analyses",
    "get_existing_claims",
)


def default_skill_catalog() -> dict[str, SkillDefinition]:
    skills = [
        _skill(
            "windows.authentication",
            "Windows authentication analysis",
            "Logon/session activity from event logs and account metadata.",
            dimensions=("authentication", "logon", "account_usage"),
            patterns=("logon", "login", "authentication", "rdp", "account", "登录", "账户"),
            families=("windows.event_logs", "windows.user_accounts"),
            tools=_READ_TOOLS + ("query_platform_artifacts",),
            knowledge=(
                "event ID 4624/4625 logon types map to interactive/network/RDP usage",
            ),
            pitfalls=(
                "successful logon != unauthorized access",
                "same IP != same actor/device",
            ),
            escalation=("interactive logons outside business hours",),
        ),
        _skill(
            "windows.execution",
            "Windows execution analysis",
            "Program execution evidence from prefetch records.",
            dimensions=("execution", "program_execution"),
            patterns=("execution", "prefetch", "ran", "executable", "程序", "执行"),
            families=("windows.prefetch",),
            tools=_READ_TOOLS + ("query_platform_artifacts",),
            knowledge=(
                "prefetch records carry run counts and last-run times",
            ),
            pitfalls=(
                "file presence != execution",
                "prefetch absence != no execution (prefetch may be disabled)",
            ),
        ),
        _skill(
            "windows.persistence",
            "Windows persistence analysis",
            "Services and scheduled-task style persistence locations.",
            dimensions=("persistence",),
            patterns=("persistence", "service", "scheduled", "startup", "持久化"),
            families=("windows.services",),
            tools=_READ_TOOLS + ("query_platform_artifacts",),
            pitfalls=("service registration != successful execution",),
        ),
        _skill(
            "windows.usb",
            "Windows USB device analysis",
            "USB storage pairing and usage history.",
            dimensions=("usb", "device_activity"),
            patterns=("usb", "device", "removable", "u盘"),
            families=("windows.usb_devices",),
            tools=_READ_TOOLS + ("query_platform_artifacts",),
        ),
        _skill(
            "windows.browser",
            "Windows browser analysis",
            "Browser history and download activity.",
            dimensions=("browser", "web_activity"),
            patterns=("browser", "history", "download", "浏览"),
            families=("windows.browser_history",),
            tools=_READ_TOOLS + ("query_platform_artifacts",),
        ),
        _skill(
            "windows.file_activity",
            "Windows file activity",
            "File creation/modification activity on the timeline.",
            dimensions=("file_activity", "timeline"),
            patterns=("file", "created", "modified", "文件"),
            families=("windows.event_logs",),
            tools=_READ_TOOLS,
        ),
        _skill(
            "android.communication",
            "Android communication analysis",
            "SMS and call-log communication patterns.",
            dimensions=("communication",),
            patterns=("sms", "call", "message", "短信", "通话", "聊天"),
            families=("android.sms", "android.call_logs"),
            tools=_READ_TOOLS + ("query_platform_artifacts",),
            knowledge=(
                "MIUI app-data-form backups carry no SMS bodies",
            ),
            pitfalls=("absence of SMS bodies in a backup != absence of messages",),
        ),
        _skill(
            "android.app_activity",
            "Android app activity",
            "Installed packages and app footprint.",
            dimensions=("app_activity",),
            patterns=("app", "installed", "package", "应用"),
            families=("android.installed_packages",),
            tools=_READ_TOOLS + ("query_platform_artifacts",),
            pitfalls=("package installation != active usage",),
        ),
        _skill(
            "android.account_identity",
            "Android account identity",
            "Contact/account identity mapping.",
            dimensions=("account_identity", "identity"),
            patterns=("contact", "account", "identity", "联系人", "账号"),
            families=("android.contacts",),
            tools=_READ_TOOLS + ("query_platform_artifacts",),
        ),
        _skill(
            "android.browser",
            "Android browser analysis",
            "Mobile browser history.",
            dimensions=("browser", "web_activity"),
            patterns=("browser", "chrome", "浏览"),
            families=("android.browser",),
            tools=_READ_TOOLS + ("query_platform_artifacts",),
        ),
        _skill(
            "linux.auth",
            "Linux authentication analysis",
            "Login records and auth-style log entries.",
            dimensions=("authentication", "logon", "account_usage"),
            patterns=("ssh", "login", "auth", "sudo", "登录"),
            families=("linux.login_records", "linux.log_entries"),
            tools=_READ_TOOLS + ("query_platform_artifacts",),
            pitfalls=("successful login != unauthorized access",),
        ),
        _skill(
            "linux.execution",
            "Linux shell execution analysis",
            "Shell history as an execution proxy.",
            dimensions=("execution",),
            patterns=("shell", "command", "history", "命令"),
            families=("linux.shell_history",),
            tools=_READ_TOOLS + ("query_platform_artifacts",),
            pitfalls=("shell history absence != no execution",),
        ),
        _skill(
            "linux.persistence",
            "Linux persistence analysis",
            "Account topology and group membership as persistence surfaces.",
            dimensions=("persistence",),
            patterns=("persistence", "user", "group", "账号", "持久化"),
            families=("linux.user_accounts",),
            tools=_READ_TOOLS + ("query_platform_artifacts",),
        ),
    ]
    return {skill.skill_id: skill for skill in skills}


class FrozenSkillBinding(BaseModel):
    """Exact versioned skill binding frozen into a ContextPack / execution
    envelope (P4A freeze follow-up F1). The single binding contract — the
    tool registry hash never substitutes for a skill version."""

    model_config = ConfigDict(frozen=True)

    skill_id: str
    version: str

    @field_validator("skill_id", "version")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("skill binding fields must be non-blank")
        return value


class SkillRegistry(BaseModel):
    model_config = ConfigDict(frozen=True)

    registry_version: str = SKILL_REGISTRY_VERSION
    skills: tuple[SkillDefinition, ...]

    @classmethod
    def with_defaults(cls) -> "SkillRegistry":
        catalog = default_skill_catalog()
        return cls(skills=tuple(catalog[sid] for sid in sorted(catalog)))

    def resolve(self, skill_id: str) -> Optional[SkillDefinition]:
        return self._by_id().get(skill_id)

    def known_skill_ids(self) -> frozenset[str]:
        return frozenset(self._by_id())

    def _by_id(self) -> dict[str, SkillDefinition]:
        return {skill.skill_id: skill for skill in self.skills}

    def registry_hash(self) -> str:
        payload = {
            "registry_version": self.registry_version,
            "skills": sorted(self._by_id()),
        }
        return state_hash_of(canonical_state_json(payload))


__all__ = [
    "SKILL_REGISTRY_VERSION",
    "FrozenSkillBinding",
    "SkillDefinition",
    "SkillRegistry",
    "default_skill_catalog",
]
