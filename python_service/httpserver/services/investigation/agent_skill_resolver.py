"""Deterministic SkillResolver (P3 §32-35).

Priority order (frozen): coverage mapping > question semantic hints >
known entities > available artifact families — with artifact families as a
HARD capability filter: a skill whose artifact families are explicitly
unavailable is never selected, no matter how well it scores.

No embeddings, no LLM classifier, no semantic model: pure deterministic
mapping. Thresholds (max active skills, split breadth) come from injected
policy config, never hardcoded architecture constants.
"""

from typing import Iterable, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from .agent_skills import SkillDefinition, SkillRegistry
from .agent_runtime import canonical_state_json, state_hash_of

RESOLVER_VERSION = "skill-resolver:v1"


class SkillResolverPolicy(BaseModel):
    """Configurable breadth limits (P8 benchmark calibrates the numbers)."""

    model_config = ConfigDict(frozen=True)

    max_primary_skills: int = Field(default=3, ge=1)
    max_total_skills: int = Field(default=5, ge=1)
    # distinct domains beyond this breadth force split_required
    max_domains_before_split: int = Field(default=4, ge=1)


class SkillResolutionInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str
    coverage_dimension_ids: tuple[str, ...] = ()
    playbook_bindings: tuple[str, ...] = ()  # digests/ids, advisory only
    source_scope_ids: tuple[str, ...] = ()
    known_entity_types: tuple[str, ...] = ()
    available_family_ids: frozenset[str] = frozenset()
    # family availability from the SourceCapabilityManifest; anything not
    # available/partial is a hard capability failure for its skills
    family_availability: Mapping[str, str] = {}
    policy: SkillResolverPolicy = SkillResolverPolicy()


class SkillResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    resolver_version: str = RESOLVER_VERSION
    profile_id: Optional[str] = None

    primary_skills: tuple[str, ...] = ()
    supporting_skills: tuple[str, ...] = ()

    resolved_tool_ids: tuple[str, ...] = ()
    unavailable_requirements: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    split_required: bool = False
    suggested_partitions: tuple[tuple[str, ...], ...] = ()

    def content_hash(self) -> str:
        return state_hash_of(canonical_state_json(self.model_dump()))


def _family_available(input_data: SkillResolutionInput, family_id: str) -> bool:
    if family_id not in input_data.available_family_ids:
        return False
    state = input_data.family_availability.get(family_id)
    if state is None:
        return True
    return state in ("available", "partial")


def resolve_skills(
    input_data: SkillResolutionInput,
    skill_registry: SkillRegistry,
    *,
    profile_id: Optional[str] = None,
    allowed_tool_ids: Optional[Iterable[str]] = None,
) -> SkillResolution:
    """Score, filter and rank skills deterministically."""
    question = input_data.question.casefold()
    coverage = {dim.casefold() for dim in input_data.coverage_dimension_ids}
    entities = {name.casefold() for name in input_data.known_entity_types}

    scored: list[tuple[int, str, tuple[str, ...]]] = []
    unavailable: list[str] = []
    reason_codes: set[str] = set()

    for skill in skill_registry.skills:
        missing = [
            family
            for family in skill.artifact_families
            if not _family_available(input_data, family)
        ]
        if missing:
            unavailable.extend(f"{skill.skill_id}:{family}" for family in missing)
            reason_codes.add("capability_filter_removed_skill")
            continue

        score = 0
        reasons: list[str] = []
        matched_dims = tuple(
            dim
            for dim in input_data.coverage_dimension_ids
            if dim.casefold() in {d.casefold() for d in skill.applicable_coverage_dimensions}
        )
        if matched_dims:
            score += 100
            reasons.append("coverage_mapping")
        matched_patterns = tuple(
            pattern
            for pattern in skill.question_patterns
            if pattern.casefold() in question
        )
        if matched_patterns:
            score += 40
            reasons.append("question_hint")
        matched_entities = tuple(
            entity
            for entity in sorted(entities)
            if entity and entity in {p.casefold() for p in skill.question_patterns}
        )
        if matched_entities:
            score += 10
            reasons.append("known_entity")
        if input_data.playbook_bindings:
            reason_codes.add("playbook_bindings_present")
        if score > 0:
            scored.append((score, skill.skill_id, tuple(reasons)))

    # deterministic order: score desc, then skill_id asc
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    for _score, _skill_id, reasons in scored:
        reason_codes.update(reasons)

    policy = input_data.policy
    primary_ids = [skill_id for _, skill_id, _ in scored[: policy.max_primary_skills]]
    supporting_ids = [
        skill_id
        for _, skill_id, _ in scored[policy.max_primary_skills : policy.max_total_skills]
    ]

    # domain breadth -> split recommendation
    domains = {
        skill_registry.resolve(skill_id).platform
        for skill_id in primary_ids + supporting_ids
        if skill_registry.resolve(skill_id) is not None
    }
    platforms_in_scope = set(input_data.source_scope_ids)
    split_required = len(domains) > policy.max_domains_before_split
    partitions: tuple[tuple[str, ...], ...] = ()
    if split_required:
        reason_codes.add("too_broad")
        grouped: dict[str, list[str]] = {}
        for skill_id in primary_ids + supporting_ids:
            skill = skill_registry.resolve(skill_id)
            grouped.setdefault(skill.platform, []).append(skill_id)
        partitions = tuple(
            tuple(sorted(members)) for _, members in sorted(grouped.items())
        )
    if platforms_in_scope:
        reason_codes.add("source_scopes_present")

    selected = primary_ids + supporting_ids
    tools: set[str] = set()
    for skill_id in selected:
        skill = skill_registry.resolve(skill_id)
        tools.update(skill.suggested_tool_ids)
    if allowed_tool_ids is not None:
        tools &= set(allowed_tool_ids)

    warnings: list[str] = []
    if unavailable:
        warnings.append(
            "some skills were excluded because their artifact families are "
            "unavailable for this source"
        )
    if not selected:
        warnings.append(
            "no skill matched the question; fall back to generic read-only tools"
        )

    return SkillResolution(
        profile_id=profile_id,
        primary_skills=tuple(primary_ids),
        supporting_skills=tuple(supporting_ids),
        resolved_tool_ids=tuple(sorted(tools)),
        unavailable_requirements=tuple(sorted(unavailable)),
        warnings=tuple(warnings),
        reason_codes=tuple(sorted(reason_codes)),
        split_required=split_required,
        suggested_partitions=partitions,
    )


__all__ = [
    "RESOLVER_VERSION",
    "SkillResolution",
    "SkillResolutionInput",
    "SkillResolverPolicy",
    "resolve_skills",
]
