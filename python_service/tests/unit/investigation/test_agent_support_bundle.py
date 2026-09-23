"""P5A §58 EvidenceSupportBundle tests."""

import pytest

from httpserver.services.investigation.agent_claims import ProposedClaimV1
from httpserver.services.investigation.agent_grounding import (
    DeterministicGroundingValidator,
    GroundingStatus,
)
from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
)
from httpserver.services.investigation.agent_support_bundle import (
    HydrationPolicy,
    SupportBundleBuilder,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "1" * 8

_METADATA = {
    "file:C/a.doc": {
        "evidence_key": "file:C/a.doc",
        "normalized_path": "C:/a.doc",
        "source_hash": "d" * 64,
        "source_size": 2048,
        "source_mtime": 1_700_000_000,
        "excerpt": "LOG: user X logged on at 09:00 " + "filler " * 200,
    },
    "file:C/b.doc": {
        "evidence_key": "file:C/b.doc",
        "normalized_path": "C:/b.doc",
        "source_hash": "e" * 64,
        "source_size": 1,
    },
}


async def _resolver(task_id, ref):
    return _METADATA.get(ref)


def _proposal(refs=("file:C/a.doc",), text="a finding"):
    return ProposedClaimV1(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal_id="",
        text=text,
        assertion_class=AssertionClass.INFERENCE,
        evidence_refs=refs,
        input_hash="",
    )


async def _grounding(proposal, allowed=frozenset({"file:C/a.doc"})):
    return await DeterministicGroundingValidator().validate(
        proposal,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        allowed_evidence_ids=frozenset(allowed),
        evidence_resolver=_resolver,
    )


async def test_only_grounded_refs_included_with_digest_provenance():
    proposal = _proposal()
    grounding = await _grounding(proposal)
    bundle = await SupportBundleBuilder().build(
        grounding, proposal, task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, evidence_resolver=_resolver,
    )
    assert grounding.status is GroundingStatus.GROUNDED
    assert [item.evidence_ref for item in bundle.evidence_items] == [
        "file:C/a.doc"
    ]
    item = bundle.evidence_items[0]
    assert item.digest["source_hash"] == "d" * 64
    assert item.digest["source_size"] == 2048
    assert item.provenance["resolved"] is True
    # the invisible ref never enters the bundle
    other = _proposal(refs=("file:C/b.doc",))
    g2 = await _grounding(other, allowed=set())
    bundle2 = await SupportBundleBuilder().build(
        g2, other, task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, evidence_resolver=_resolver,
    )
    assert g2.status is GroundingStatus.UNGROUNDED
    assert bundle2.evidence_items == ()


async def test_excerpt_is_bounded_never_whole_file():
    proposal = _proposal()
    grounding = await _grounding(proposal)
    policy = HydrationPolicy(max_excerpt_chars=64)
    bundle = await SupportBundleBuilder(policy=policy).build(
        grounding, proposal, task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, evidence_resolver=_resolver,
    )
    assert len(bundle.evidence_items[0].excerpt) == 64
    assert bundle.hydration_policy == policy.name


async def test_same_inputs_same_bundle_id_and_grounding_change_moves_it():
    proposal = _proposal()
    builder = SupportBundleBuilder()
    first = await builder.build(
        await _grounding(proposal), proposal, task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, evidence_resolver=_resolver,
    )
    second = await builder.build(
        await _grounding(proposal), proposal, task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, evidence_resolver=_resolver,
    )
    assert first.bundle_id == second.bundle_id
    assert first.input_hash == second.input_hash

    # grounding change (visibility moved -> new grounding_id) moves the bundle
    moved = await builder.build(
        await _grounding(
            proposal, allowed=frozenset({"file:C/a.doc", "file:C/z.doc"})
        ),
        proposal, task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, evidence_resolver=_resolver,
    )
    assert moved.grounding_id != first.grounding_id
    assert moved.bundle_id != first.bundle_id


async def test_bundle_carries_no_semantic_support_status():
    proposal = _proposal()
    bundle = await SupportBundleBuilder().build(
        await _grounding(proposal), proposal, task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, evidence_resolver=_resolver,
    )
    row = bundle.to_row()
    forbidden = (
        "sufficient", "partially_sufficient", "insufficient",
        "contradicted", "indeterminate", "confidence", "probability",
        "support_status",
    )
    for key in forbidden:
        assert key not in row, key
    for item in row["evidence_items"]:
        for key in forbidden:
            assert key not in item
    # the only status present is the grounding status itself
    assert row["grounding_status"] == "grounded"
