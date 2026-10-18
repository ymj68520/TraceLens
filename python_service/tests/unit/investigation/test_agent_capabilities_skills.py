"""P3-3 tests: capability manifest (§56), profiles (§57), SkillResolver (§58)."""

import sqlite3
from types import SimpleNamespace

import pytest

from httpserver.services.investigation.agent_capabilities import (
    ArtifactFamilyRegistry,
    FamilyAvailability,
    build_source_capability_manifest,
    list_sqlite_tables,
)
from httpserver.services.investigation.agent_profiles import (
    default_profiles,
    resolve_profile_for_source,
)
from httpserver.services.investigation.agent_skill_resolver import (
    SkillResolutionInput,
    SkillResolverPolicy,
    resolve_skills,
)
from httpserver.services.investigation.agent_skills import SkillRegistry


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _task(**overrides):
    task = {
        "id": "task-A",
        "scenarios": ["windows", "android"],
        "scenario_databases": {"windows": "/fake/windows.db", "android": "/fake/android.db"},
        "output_files_db": "/fake/files.db",
        "output_events_db": "/fake/events.db",
    }
    task.update(overrides)
    return task


def _tables_of(names):
    def lister(_db_path):
        return frozenset(names)

    return lister


FAMILY_REGISTRY = ArtifactFamilyRegistry.with_defaults()
ALL_TOOL_IDS = (
    "get_task_context",
    "search_evidence",
    "get_evidence",
    "find_related_evidence",
    "search_files",
    "search_timeline",
    "find_temporal_neighbors",
    "get_existing_analyses",
    "get_existing_claims",
    "query_platform_artifacts",
)


# ---------------------------------------------------------------------------
# capability manifest (P3-E14)
# ---------------------------------------------------------------------------


def test_manifest_same_source_same_hash():
    first = build_source_capability_manifest(
        _task(), "windows", FAMILY_REGISTRY,
        available_tool_ids=ALL_TOOL_IDS, table_lister=_tables_of({"registry_values"}),
    )
    second = build_source_capability_manifest(
        _task(), "windows", FAMILY_REGISTRY,
        available_tool_ids=ALL_TOOL_IDS, table_lister=_tables_of({"registry_values"}),
    )
    assert first.input_hash() == second.input_hash()
    assert first.model_dump() == second.model_dump()


def test_manifest_hash_changes_with_capability_state():
    available = build_source_capability_manifest(
        _task(), "windows", FAMILY_REGISTRY,
        table_lister=_tables_of({"registry_values"}),
    )
    empty = build_source_capability_manifest(
        _task(), "windows", FAMILY_REGISTRY, table_lister=_tables_of(set())
    )
    assert available.input_hash() != empty.input_hash()


def test_manifest_family_availability_states():
    manifest = build_source_capability_manifest(
        _task(), "windows", FAMILY_REGISTRY,
        table_lister=_tables_of({"registry_values", "usb_devices"}),
    )
    by_id = {cap.family_id: cap for cap in manifest.artifact_families}
    assert by_id["windows.registry"].availability == FamilyAvailability.AVAILABLE
    assert by_id["windows.prefetch"].availability == FamilyAvailability.UNAVAILABLE
    assert by_id["windows.prefetch"].reason_codes == ("artifact_tables_absent",)


def test_manifest_platform_missing_database():
    manifest = build_source_capability_manifest(
        _task(scenario_databases={}), "windows", FAMILY_REGISTRY,
        table_lister=_tables_of(set()),
    )
    assert all(
        cap.availability == FamilyAvailability.UNAVAILABLE
        and cap.reason_codes == ("platform_database_missing",)
        for cap in manifest.artifact_families
    )


def test_manifest_not_applicable_for_unrelated_scope():
    manifest = build_source_capability_manifest(
        _task(), "linux", FAMILY_REGISTRY, table_lister=_tables_of(set())
    )
    assert all(
        cap.availability == FamilyAvailability.NOT_APPLICABLE
        for cap in manifest.artifact_families
    )


def test_manifest_does_not_assert_case_facts():
    manifest = build_source_capability_manifest(
        _task(), "windows", FAMILY_REGISTRY,
        table_lister=_tables_of({"registry_values"}),
    )
    serialized = str(manifest.model_dump())
    for claim in ("attacker", "did not", "no login", "innocent"):
        assert claim not in serialized


def test_manifest_unsupported_family_never_exposed():
    manifest = build_source_capability_manifest(
        _task(), "windows", FAMILY_REGISTRY,
        table_lister=_tables_of({"registry_values"}),
    )
    ids = {cap.family_id for cap in manifest.artifact_families}
    assert "android.contacts" not in ids
    assert "linux.shell_history" not in ids


def test_family_catalog_count_and_platform_breakdown():
    """D1: the documented catalog numbers are read from the real registry."""
    registry = ArtifactFamilyRegistry.with_defaults()
    ids = [family.family_id for family in registry.families]
    assert len(ids) == len(set(ids)) == 20
    breakdown = {"windows": 0, "android": 0, "linux": 0}
    for family in registry.families:
        breakdown[family.platform] += 1
    assert breakdown == {"windows": 7, "android": 9, "linux": 4}


def test_family_registry_hash_stable():
    assert FAMILY_REGISTRY.registry_hash() == ArtifactFamilyRegistry.with_defaults().registry_hash()


# ---------------------------------------------------------------------------
# profiles (P3-E15)
# ---------------------------------------------------------------------------


def test_profiles_stable_ids_and_versions():
    profiles = default_profiles()
    assert set(profiles) == {"windows", "android", "linux"}
    assert profiles["windows"].profile_id == "windows.specialist"
    assert profiles["windows"].version == "1"


def test_profiles_bind_supported_source_types_only():
    profiles = default_profiles()
    assert profiles["windows"].supports_source("windows")
    assert not profiles["windows"].supports_source("android")
    assert profiles["linux"].supports_source("server_cloud")


def test_profile_refs_exist_in_registries():
    profiles = default_profiles()
    skills = SkillRegistry.with_defaults()
    known_tools = frozenset(ALL_TOOL_IDS)
    for profile in profiles.values():
        profile.validate_registry_refs(
            known_tool_ids=known_tools,
            known_skill_ids=skills.known_skill_ids(),
        )


def test_unknown_source_profile_fails_deterministically():
    with pytest.raises(KeyError):
        resolve_profile_for_source(default_profiles(), "memory")


def test_profile_serialization_deterministic():
    profiles = default_profiles()
    windows = profiles["windows"]
    assert windows.content_hash() == windows.content_hash()
    again = default_profiles()["windows"]
    assert windows.content_hash() == again.content_hash()


def test_memory_profile_absent():
    # memory has no deterministic task-level platform key in this repo
    assert "memory" not in default_profiles()


# ---------------------------------------------------------------------------
# SkillResolver (P3-E16, P3-E17)
# ---------------------------------------------------------------------------


def _availability(**overrides):
    tables = {"registry_values", "event_log_entries", "prefetch_files",
              "user_accounts", "usb_devices", "browser_history", "windows_services",
              "contacts", "sms_messages", "call_logs", "chrome_history",
              "installed_packages", "wifi_networks"}
    tables.update(overrides.pop("tables", set()))
    return {cap.family_id: cap.availability.value for cap in build_source_capability_manifest(
        _task(), "windows", FAMILY_REGISTRY, table_lister=_tables_of(tables),
    ).artifact_families}


SKILLS = SkillRegistry.with_defaults()
AVAILABLE = frozenset(
    {
        "windows.registry", "windows.event_logs", "windows.prefetch",
        "windows.user_accounts", "windows.usb_devices", "windows.browser_history",
        "windows.services", "android.contacts", "android.sms", "android.call_logs",
        "android.browser", "android.installed_packages", "android.wifi",
        "linux.user_accounts", "linux.shell_history", "linux.login_records",
        "linux.log_entries",
    }
)


def test_coverage_mapping_selects_skill():
    resolution = resolve_skills(
        SkillResolutionInput(
            question="who logged into the machine?",
            coverage_dimension_ids=("authentication",),
            available_family_ids=AVAILABLE,
            family_availability=_availability(),
        ),
        SKILLS,
    )
    assert "windows.authentication" in resolution.primary_skills
    assert "coverage_mapping" in resolution.reason_codes


def test_question_hint_selects_skill():
    resolution = resolve_skills(
        SkillResolutionInput(
            question="was prefetch showing program execution?",
            available_family_ids=AVAILABLE,
            family_availability=_availability(),
        ),
        SKILLS,
    )
    assert "windows.execution" in resolution.primary_skills + resolution.supporting_skills
    assert "question_hint" in resolution.reason_codes


def test_capability_filter_removes_unavailable_skills():
    resolution = resolve_skills(
        SkillResolutionInput(
            question="usb device activity",
            coverage_dimension_ids=("usb",),
            available_family_ids=AVAILABLE - {"windows.usb_devices"},
            family_availability=_availability(),
        ),
        SKILLS,
    )
    assert "windows.usb" not in resolution.primary_skills
    assert "windows.usb" not in resolution.supporting_skills
    assert any(
        req.startswith("windows.usb:") for req in resolution.unavailable_requirements
    )


def test_deterministic_same_input_same_output():
    payload = dict(
        question="usb and browser activity",
        coverage_dimension_ids=("usb", "browser"),
        available_family_ids=AVAILABLE,
        family_availability=_availability(),
        policy=SkillResolverPolicy(max_primary_skills=2),
    )
    first = resolve_skills(SkillResolutionInput(**payload), SKILLS)
    second = resolve_skills(SkillResolutionInput(**payload), SKILLS)
    assert first == second
    assert first.content_hash() == second.content_hash()


def test_max_skills_policy_configurable():
    payload = dict(
        question="usb browser authentication execution persistence activity",
        coverage_dimension_ids=("usb", "browser", "authentication", "execution", "persistence"),
        available_family_ids=AVAILABLE,
        family_availability=_availability(),
    )
    strict = resolve_skills(
        SkillResolutionInput(**{**payload, "policy": SkillResolverPolicy(max_primary_skills=1, max_total_skills=2)}),
        SKILLS,
    )
    loose = resolve_skills(
        SkillResolutionInput(**{**payload, "policy": SkillResolverPolicy(max_primary_skills=4, max_total_skills=5)}),
        SKILLS,
    )
    assert len(strict.primary_skills) <= 1
    assert len(loose.primary_skills) <= 4
    assert strict.primary_skills != loose.primary_skills


def test_too_broad_requires_split():
    resolution = resolve_skills(
        SkillResolutionInput(
            question="everything about usb browser authentication execution persistence",
            coverage_dimension_ids=("usb", "browser", "authentication", "execution", "persistence"),
            available_family_ids=AVAILABLE,
            family_availability=_availability(),
            policy=SkillResolverPolicy(
                max_primary_skills=3, max_total_skills=5,
                max_domains_before_split=1,
            ),
        ),
        SKILLS,
    )
    assert resolution.split_required is True
    assert "too_broad" in resolution.reason_codes
    assert resolution.suggested_partitions


def test_resolver_blocks_nothing_outside_capability_map():
    """Without a manifest availability map, registered+available families pass."""
    resolution = resolve_skills(
        SkillResolutionInput(
            question="contacts",
            coverage_dimension_ids=("account_identity",),
            available_family_ids=AVAILABLE,
        ),
        SKILLS,
    )
    assert "android.account_identity" in resolution.primary_skills + resolution.supporting_skills


def test_resolver_uses_no_llm_and_resolves_tools():
    resolution = resolve_skills(
        SkillResolutionInput(
            question="logon analysis",
            coverage_dimension_ids=("authentication",),
            available_family_ids=AVAILABLE,
            family_availability=_availability(),
            policy=SkillResolverPolicy(),
        ),
        SKILLS,
        allowed_tool_ids=set(ALL_TOOL_IDS),
    )
    assert "query_platform_artifacts" in resolution.resolved_tool_ids
    assert all(tool in ALL_TOOL_IDS for tool in resolution.resolved_tool_ids)
