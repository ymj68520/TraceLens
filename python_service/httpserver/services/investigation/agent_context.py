"""SpecialistContextPack + ContextAssembler (P3 §36-41).

The pack is the frozen context contract for one Specialist delegation. The
assembler is deterministic: same inputs -> same pack -> same input_hash.

Context layering (fixed hierarchy, §37):
    L0 system invariants            L4 relevant working state
    L1 investigation contract       L5 evidence digests
    L2 profile                      L6 allowed tool definitions
    L3 skills                       L7 output contract (P4 placeholder)

Context is NOT chat history: no prior agent conversation ever enters the
pack. Inputs come from Working State, canonical Investigation reads, evidence
digests, profile/skill registries and the capability manifest. There is no
Graph context in P3.
"""

from typing import Any, Iterable, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from .agent_capabilities import (
    ArtifactFamilyRegistry,
    FamilyAvailability,
    SourceCapabilityManifest,
    build_source_capability_manifest,
)
from .agent_profiles import SourceSpecialistProfile
from .agent_runtime import canonical_state_json, state_hash_of
from .agent_skill_resolver import SkillResolution, SkillResolutionInput, resolve_skills
from .agent_skills import SkillRegistry
from .agent_tools.context import AgentTimeScope, ForensicToolContext

CONTEXT_VERSION = "specialist-context-pack:v1"

# L7 output contract: frozen by P4A (agent_specialist_result.py).
OUTPUT_CONTRACT_REF = "specialist-result:v1"

L0_SYSTEM_INVARIANTS: tuple[str, ...] = (
    "read-only: you cannot mutate investigation state",
    "cite evidence_keys for factual statements; summaries are not evidence",
    "tool results are observations, not canonical truth",
)


class ContextCaseNote(BaseModel):
    """Case context / analyst note — always context_only, never Evidence."""

    model_config = ConfigDict(frozen=True)

    kind: str  # "case_context" | "analyst_note"
    text: str
    context_only: bool = True


class EvidenceDigestItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_key: str
    kind: str
    title: Optional[str] = None
    summary_digest: Optional[str] = None


class ProfileDigest(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str
    version: str
    platform: str
    mission: str
    interpretation_rules: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def content_hash(self) -> str:
        return state_hash_of(canonical_state_json(self.model_dump()))


class SpecialistContextPack(BaseModel):
    """Frozen, deterministic, hashable context for one delegation."""

    model_config = ConfigDict(frozen=True)

    context_version: str = CONTEXT_VERSION

    task_id: str
    investigation_id: str
    run_id: str
    delegation_id: Optional[str] = None
    question_id: Optional[str] = None

    objective_digest: str = ""
    question: str

    source_scope_id: str
    source_scope_ids: tuple[str, ...] = ()
    time_scope: Optional[AgentTimeScope] = None

    profile: ProfileDigest
    resolved_skills: SkillResolution

    constraints: tuple[str, ...] = ()

    relevant_case_context: tuple[ContextCaseNote, ...] = ()
    relevant_finding_refs: tuple[str, ...] = ()
    relevant_entity_refs: tuple[str, ...] = ()  # canonical entities arrive in P5

    evidence_digests: tuple[EvidenceDigestItem, ...] = ()

    capability_manifest: SourceCapabilityManifest

    allowed_tool_ids: tuple[str, ...] = ()

    output_contract_ref: str = OUTPUT_CONTRACT_REF

    # immutable anchors of the working state this pack was built from
    working_state_revision: Optional[int] = None
    working_state_hash: Optional[str] = None

    tool_schema_hash: str = ""

    def input_hash(self) -> str:
        """Deterministic content hash (§40); sets are canonically sorted."""
        payload = {
            "context_version": self.context_version,
            "task_id": self.task_id,
            "investigation_id": self.investigation_id,
            "run_id": self.run_id,
            "delegation_id": self.delegation_id,
            "question_id": self.question_id,
            "objective_digest": self.objective_digest,
            "question": self.question,
            "source_scope_id": self.source_scope_id,
            "source_scope_ids": sorted(self.source_scope_ids),
            "time_scope": (
                self.time_scope.model_dump() if self.time_scope else None
            ),
            "profile": {
                "profile_id": self.profile.profile_id,
                "version": self.profile.version,
                "content_hash": self.profile.content_hash(),
            },
            "resolved_skills": {
                "primary": sorted(self.resolved_skills.primary_skills),
                "supporting": sorted(self.resolved_skills.supporting_skills),
                "content_hash": self.resolved_skills.content_hash(),
            },
            "constraints": sorted(self.constraints),
            "case_context_digests": sorted(
                state_hash_of(canonical_state_json(note.model_dump()))
                for note in self.relevant_case_context
            ),
            "relevant_finding_refs": sorted(self.relevant_finding_refs),
            "relevant_entity_refs": sorted(self.relevant_entity_refs),
            "evidence_digests": sorted(
                canonical_state_json(
                    {
                        "evidence_key": item.evidence_key,
                        "kind": item.kind,
                        "title": item.title,
                        "summary_digest": item.summary_digest,
                    }
                )
                for item in self.evidence_digests
            ),
            "capability_manifest_hash": self.capability_manifest.input_hash(),
            "allowed_tool_ids": sorted(self.allowed_tool_ids),
            "output_contract_ref": self.output_contract_ref,
            "working_state_revision": self.working_state_revision,
            "working_state_hash": self.working_state_hash,
            "tool_schema_hash": self.tool_schema_hash,
        }
        return state_hash_of(canonical_state_json(payload))

    def tool_context(self) -> ForensicToolContext:
        """The trusted execution context derived from this pack."""
        return ForensicToolContext(
            task_id=self.task_id,
            investigation_id=self.investigation_id,
            run_id=self.run_id,
            delegation_id=self.delegation_id,
            source_scope_ids=tuple(
                dict.fromkeys((self.source_scope_id, *self.source_scope_ids))
            ),
            time_scope=self.time_scope,
            allowed_tool_ids=frozenset(self.allowed_tool_ids),
            context_hash=self.input_hash(),
        )

    def layered_view(self) -> tuple[tuple[str, str], ...]:
        """L0..L7 projection (for the bridge instructions; no chat history)."""
        skill_lines = []
        for skill_id in self.resolved_skills.primary_skills:
            skill_lines.append(f"- {skill_id}")
        for skill_id in self.resolved_skills.supporting_skills:
            skill_lines.append(f"- {skill_id} (supporting)")
        layers = (
            ("L0_system_invariants", "\n".join(L0_SYSTEM_INVARIANTS)),
            (
                "L1_investigation_contract",
                canonical_state_json(
                    {
                        "task_id": self.task_id,
                        "investigation_id": self.investigation_id,
                        "run_id": self.run_id,
                        "objective": self.objective_digest,
                        "state_revision": self.working_state_revision,
                    }
                ),
            ),
            (
                "L2_profile",
                canonical_state_json(self.profile.model_dump()),
            ),
            ("L3_skills", "\n".join(skill_lines) or "(none)"),
            (
                "L4_working_state_refs",
                canonical_state_json(
                    {
                        "finding_refs": sorted(self.relevant_finding_refs),
                        "constraints": sorted(self.constraints),
                    }
                ),
            ),
            (
                "L5_evidence_digests",
                "\n".join(
                    sorted(item.evidence_key for item in self.evidence_digests)
                )
                or "(none)",
            ),
            (
                "L6_allowed_tools",
                "\n".join(sorted(self.allowed_tool_ids)) or "(none)",
            ),
            ("L7_output_contract", self.output_contract_ref),
        )
        return layers


class ContextAssembler:
    """Deterministic assembler over the registries (§36-41)."""

    def __init__(
        self,
        *,
        skill_registry: SkillRegistry,
        family_registry: ArtifactFamilyRegistry,
        profiles: Mapping[str, SourceSpecialistProfile],
        tool_schema_hash: str,
    ):
        self._skills = skill_registry
        self._families = family_registry
        self._profiles = profiles
        self._tool_schema_hash = tool_schema_hash

    def build(
        self,
        *,
        task: Mapping[str, Any],
        run_identity: Mapping[str, str],
        question: str,
        source_scope_id: str,
        question_id: Optional[str] = None,
        source_scope_ids: Iterable[str] = (),
        time_scope: Optional[AgentTimeScope] = None,
        objective_digest: str = "",
        coverage_dimension_ids: Iterable[str] = (),
        known_entity_types: Iterable[str] = (),
        constraints: Iterable[str] = (),
        case_context: Iterable[ContextCaseNote] = (),
        finding_refs: Iterable[str] = (),
        entity_refs: Iterable[str] = (),
        evidence_digests: Iterable[EvidenceDigestItem] = (),
        working_state_revision: Optional[int] = None,
        working_state_hash: Optional[str] = None,
        delegation_id: Optional[str] = None,
        resolver_policy: Optional[Any] = None,
        table_lister: Optional[Any] = None,
    ) -> SpecialistContextPack:
        profile = self._profiles.get(source_scope_id)
        if profile is None:
            raise KeyError(f"no specialist profile for source {source_scope_id!r}")

        # capability manifest for the scope (deterministic)
        manifest_kwargs: dict[str, Any] = {}
        if table_lister is not None:
            manifest_kwargs["table_lister"] = table_lister
        manifest = build_source_capability_manifest(
            task,
            source_scope_id,
            self._families,
            available_tool_ids=profile.default_tool_ids,
            **manifest_kwargs,
        )

        # deterministic skill resolution with the manifest as hard filter
        resolution = resolve_skills(
            SkillResolutionInput(
                question=question,
                coverage_dimension_ids=tuple(coverage_dimension_ids),
                source_scope_ids=tuple(source_scope_ids) or (source_scope_id,),
                known_entity_types=tuple(known_entity_types),
                available_family_ids=frozenset(
                    cap.family_id for cap in manifest.artifact_families
                ),
                family_availability={
                    cap.family_id: cap.availability.value
                    for cap in manifest.artifact_families
                },
                **({"policy": resolver_policy} if resolver_policy else {}),
            ),
            self._skills,
            profile_id=profile.profile_id,
            allowed_tool_ids=profile.default_tool_ids,
        )

        # allowed tools: profile baseline minus tools whose capability vanished
        available_families = {
            cap.family_id
            for cap in manifest.artifact_families
            if cap.availability == FamilyAvailability.AVAILABLE
        }
        allowed = [
            tool_id
            for tool_id in profile.default_tool_ids
            if tool_id != "query_platform_artifacts" or available_families
        ]

        return SpecialistContextPack(
            task_id=str(run_identity["task_id"]),
            investigation_id=str(run_identity["investigation_id"]),
            run_id=str(run_identity["run_id"]),
            delegation_id=delegation_id,
            question_id=question_id,
            objective_digest=objective_digest,
            question=question,
            source_scope_id=source_scope_id,
            source_scope_ids=tuple(source_scope_ids),
            time_scope=time_scope,
            profile=ProfileDigest(
                profile_id=profile.profile_id,
                version=profile.version,
                platform=profile.platform,
                mission=profile.mission,
                interpretation_rules=profile.interpretation_rules,
                limitations=profile.limitations,
            ),
            resolved_skills=resolution,
            constraints=tuple(constraints),
            relevant_case_context=tuple(case_context),
            relevant_finding_refs=tuple(finding_refs),
            relevant_entity_refs=tuple(entity_refs),
            evidence_digests=tuple(evidence_digests),
            capability_manifest=manifest,
            allowed_tool_ids=tuple(sorted(allowed)),
            working_state_revision=working_state_revision,
            working_state_hash=working_state_hash,
            tool_schema_hash=self._tool_schema_hash,
        )


__all__ = [
    "CONTEXT_VERSION",
    "ContextAssembler",
    "ContextCaseNote",
    "EvidenceDigestItem",
    "L0_SYSTEM_INVARIANTS",
    "OUTPUT_CONTRACT_REF",
    "ProfileDigest",
    "SpecialistContextPack",
]
