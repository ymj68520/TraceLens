"""P5A §52 deterministic entity occurrence tests."""

import pytest

from httpserver.services.investigation.agent_entities import (
    build_occurrences_from_specialist_result,
    derive_entity_auto_links,
    derive_occurrence_id,
)
from httpserver.services.investigation.agent_identity import IdentityPolicy
from httpserver.services.investigation.agent_specialist_result import (
    SpecialistEntityCandidate,
    SpecialistResultV1,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "b" * 8
SCOPE = "img-1"


def _result(*candidates) -> SpecialistResultV1:
    return SpecialistResultV1(
        delegation_id="dlg-1",
        summary="s",
        entity_candidates=candidates,
    )


def _hash_candidate(refs=("file:C/iso.img",), value="ab" * 32):
    return SpecialistEntityCandidate(
        candidate_id="c-hash",
        raw_value=value,
        entity_type_candidate="file_hash",
        evidence_refs=refs,
    )


async def _lookup(task_id, evidence_ref):
    if evidence_ref == "file:C/ghost.doc":
        return None  # well-formed but not present in this task
    if evidence_ref == "file:C/foreign.doc":
        raise RuntimeError("evidence belongs to another task")
    if evidence_ref.startswith("cluster:"):
        return {"cluster_start": 1_700_000_000, "cluster_end": 1_700_000_060}
    return {"source_mtime": 1_700_000_123}


def _policy():
    return IdentityPolicy()


def test_same_input_yields_same_occurrence_id():
    kwargs = dict(
        task_id=TASK_ID,
        evidence_ref="file:C/a.doc",
        entity_type="email",
        source_field="f",
        raw_value="A@x.com",
        normalized_value="A@x.com",
        role="mention",
    )
    assert derive_occurrence_id(**kwargs) == derive_occurrence_id(**kwargs)


async def test_candidate_order_does_not_change_occurrence_ids():
    first = _result(
        _hash_candidate(),
        SpecialistEntityCandidate(
            candidate_id="c-mail",
            raw_value="a@x.com",
            entity_type_candidate="email",
            evidence_refs=("file:C/mail.eml",),
        ),
    )
    second = _result(
        SpecialistEntityCandidate(
            candidate_id="c-mail",
            raw_value="a@x.com",
            entity_type_candidate="email",
            evidence_refs=("file:C/mail.eml",),
        ),
        _hash_candidate(),
    )
    report_a = await build_occurrences_from_specialist_result(
        first, task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
        source_scope_id=SCOPE, identity_policy=_policy(),
        evidence_lookup=_lookup,
    )
    report_b = await build_occurrences_from_specialist_result(
        second, task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
        source_scope_id=SCOPE, identity_policy=_policy(),
        evidence_lookup=_lookup,
    )
    assert ([o.occurrence_id for o in report_a.occurrences]
            == [o.occurrence_id for o in report_b.occurrences])


async def test_path_occurrence_stays_source_scoped():
    candidate = SpecialistEntityCandidate(
        candidate_id="c-path",
        raw_value="C:\\Users\\x\\a.doc",
        entity_type_candidate="path",
        evidence_refs=("file:C/a.doc",),
    )
    report = await build_occurrences_from_specialist_result(
        _result(candidate), task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, source_scope_id=SCOPE,
        identity_policy=_policy(), evidence_lookup=_lookup,
    )
    assert len(report.occurrences) == 1
    occurrence = report.occurrences[0]
    # backslashes canonicalized to the evidence-path form
    assert occurrence.normalized_value == "C:/Users/x/a.doc"
    assert occurrence.match_key.startswith(f"path|{SCOPE}|")


async def test_hash_is_strong_identifier_and_auto_links():
    same_hash_other_file = SpecialistEntityCandidate(
        candidate_id="c-hash2",
        raw_value="AB" * 32,  # case-only difference: same digest
        entity_type_candidate="file_hash",
        evidence_refs=("file:D/usb.img",),
    )
    report_a = await build_occurrences_from_specialist_result(
        _result(_hash_candidate()), task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, source_scope_id="img-1",
        identity_policy=_policy(), evidence_lookup=_lookup,
    )
    report_b = await build_occurrences_from_specialist_result(
        _result(same_hash_other_file), task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, source_scope_id="img-2",
        identity_policy=_policy(), evidence_lookup=_lookup,
    )
    occurrences = (*report_a.occurrences, *report_b.occurrences)
    assert all(
        item.provenance["auto_link_allowed"] is True for item in occurrences
    )
    links = derive_entity_auto_links(occurrences)
    assert len(links) == 1
    assert len(links[0].member_occurrence_ids) == 2


async def test_same_ip_is_never_auto_merged():
    candidates = [
        SpecialistEntityCandidate(
            candidate_id=f"c-ip-{index}",
            raw_value="10.1.2.3",
            entity_type_candidate="ip",
            evidence_refs=(f"file:C/log{index}.txt",),
        )
        for index in range(2)
    ]
    report = await build_occurrences_from_specialist_result(
        _result(*candidates), task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, source_scope_id=SCOPE,
        identity_policy=_policy(), evidence_lookup=_lookup,
    )
    assert len(report.occurrences) == 2
    assert derive_entity_auto_links(report.occurrences) == ()


async def test_same_username_across_scopes_never_auto_merges():
    candidates = [
        SpecialistEntityCandidate(
            candidate_id=f"c-user-{index}",
            raw_value="administrator",
            entity_type_candidate="user_account",
            evidence_refs=(f"file:C/host{index}.pcap",),
        )
        for index in range(2)
    ]
    report = await build_occurrences_from_specialist_result(
        _result(*candidates), task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, source_scope_id=SCOPE,
        identity_policy=_policy(), evidence_lookup=_lookup,
    )
    assert len(report.occurrences) == 2
    assert derive_entity_auto_links(report.occurrences) == ()


async def test_duplicate_occurrence_insert_is_idempotent(tmp_path):
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )
    from httpserver.services.investigation.repository import (
        InvestigationRepository,
    )

    db = tmp_path / "investigation.db"
    store = InvestigationRepository(db, TASK_ID)
    repo = AgentRuntimeRepository(store)
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        working_state_to_json,
    )

    repo.create_investigation(
        working_state_to_json(
            AgentWorkingStateV1(
                task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
                objective="occ",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )

    report = await build_occurrences_from_specialist_result(
        _result(_hash_candidate()), task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, source_scope_id=SCOPE,
        identity_policy=_policy(), evidence_lookup=_lookup,
    )
    rows = [item.to_row() for item in report.occurrences]
    first = repo.record_entity_occurrences(INVESTIGATION_ID, rows)
    assert first["inserted_count"] == 1
    second = repo.record_entity_occurrences(INVESTIGATION_ID, rows)
    assert second["inserted_count"] == 0
    assert second["duplicate_count"] == 1
    assert len(repo.list_entity_occurrences(INVESTIGATION_ID)) == 1

    # the audit event was appended once per record call, counts only
    events = repo.list_trajectory(INVESTIGATION_ID)
    occurrence_events = [
        event for event in events
        if event.event_type.value == "entity_occurrences_recorded"
    ]
    assert len(occurrence_events) == 2
    assert occurrence_events[0].payload["inserted_count"] == 1
    assert "raw_value" not in occurrence_events[0].payload


async def test_cross_task_evidence_rejected(tmp_path):
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )
    from httpserver.services.investigation.repository import (
        InvestigationRepository,
    )

    db = tmp_path / "investigation.db"
    repo = AgentRuntimeRepository(InvestigationRepository(db, TASK_ID))
    repo.create_investigation(
        working_state_json(),
        investigation_id=INVESTIGATION_ID,
    )

    candidate = SpecialistEntityCandidate(
        candidate_id="c-foreign",
        raw_value="ab" * 32,
        entity_type_candidate="file_hash",
        evidence_refs=("file:C/foreign.doc",),  # lookup raises: other task
    )
    report = await build_occurrences_from_specialist_result(
        _result(candidate), task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, source_scope_id=SCOPE,
        identity_policy=_policy(), evidence_lookup=_lookup,
    )
    assert report.occurrences == ()
    assert report.limitations[0].code == "OCCURRENCE_EVIDENCE_UNRESOLVED"


def working_state_json():
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        working_state_to_json,
    )

    return working_state_to_json(
        AgentWorkingStateV1(
            task_id=TASK_ID, investigation_id=INVESTIGATION_ID, objective="occ"
        )
    )


async def test_no_evidence_ref_never_becomes_verified_occurrence():
    candidate = SpecialistEntityCandidate(
        candidate_id="c-noref",
        raw_value="a@x.com",
        entity_type_candidate="email",
        evidence_refs=(),
    )
    report = await build_occurrences_from_specialist_result(
        _result(candidate), task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, source_scope_id=SCOPE,
        identity_policy=_policy(), evidence_lookup=_lookup,
    )
    assert report.occurrences == ()
    assert report.limitations[0].code == "OCCURRENCE_NO_EVIDENCE_REF"


async def test_unknown_entity_type_and_invisible_ref_are_skipped():
    unknown = SpecialistEntityCandidate(
        candidate_id="c-unknown",
        raw_value="bc1qxyz",
        entity_type_candidate="cryptocurrency_wallet",
        evidence_refs=("file:C/a.doc",),
    )
    invisible = SpecialistEntityCandidate(
        candidate_id="c-invisible",
        raw_value="ab" * 32,
        entity_type_candidate="file_hash",
        evidence_refs=("file:C/notshown.doc",),
    )
    report = await build_occurrences_from_specialist_result(
        _result(unknown, invisible), task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, source_scope_id=SCOPE,
        identity_policy=_policy(), evidence_lookup=_lookup,
        allowed_evidence_ids=frozenset({"file:C/iso.img"}),
    )
    assert report.occurrences == ()
    codes = [limitation.code for limitation in report.limitations]
    assert "OCCURRENCE_UNKNOWN_ENTITY_TYPE" in codes
    assert "OCCURRENCE_EVIDENCE_NOT_VISIBLE" in codes
