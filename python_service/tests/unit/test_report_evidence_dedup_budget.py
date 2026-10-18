"""P7A-3 tests: dedup/independence (§67), ranking, budget, hydration
depth policy (§68 subset — depth selection is contract-level in P7A)."""

import pytest

from httpserver.services.report_runtime.report_dedup import (
    EvidenceIndependenceResolver,
)
from httpserver.services.report_runtime.report_hydration import (
    RetrievalBudgetV1,
    apply_budget,
    rank_candidates,
)

RESOLVER = EvidenceIndependenceResolver()


# ---------------------------------------------------------------------------
# §67 dedup — representation chains collapse; real corroboration preserved
# ---------------------------------------------------------------------------


def test_duplicate_representation_chain_is_one_root_evidence():
    """file:A -> Initial Analysis -> accepted Finding -> Graph node is ONE
    root Evidence source, not four independent sources (§67)."""
    verdicts = RESOLVER.resolve(
        [
            "file:C/a.doc",  # direct
            "file:C/a.doc",  # via Report Evidence selection
            "file:C/a.doc",  # via accepted Finding provenance
            "file:C/a.doc",  # via Graph navigation hydration
        ],
        layer_provenance={
            "file:C/a.doc": (
                "direct",
                "report_evidence",
                "finding:f1",
                "graph:gm_1",
            ),
        },
    )
    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict.root_evidence_key == "file:C/a.doc"
    # multiple layers of provenance preserved on the single item
    assert len(verdict.representation_layers) == 4


def test_duplicate_layers_from_distinct_provenance_paths_merge():
    """§76: one file reaching the pack via Report Evidence + accepted
    Finding + accepted Analysis + Graph navigation stays ONE evidence
    item, but keeps every accepted basis provenance path."""
    verdicts = RESOLVER.resolve(
        ["file:X/f.bin", "file:X/f.bin", "file:X/f.bin", "file:X/f.bin"],
        layer_provenance={
            "file:X/f.bin": (
                "report_evidence",
                "finding:f1",
                "analysis:sa_1",
                "graph:gm_1",
            ),
        },
    )
    assert len(verdicts) == 1
    assert verdicts[0].representation_layers == (
        "report_evidence",
        "finding:f1",
        "analysis:sa_1",
        "graph:gm_1",
    )


def test_real_cross_source_corroboration_preserved():
    """§35/§67: Windows Event + Browser History + File Metadata stay three
    genuinely independent sources even when they support one conclusion."""
    verdicts = RESOLVER.resolve(
        [
            "event:Security.evtx/Evt-100",
            "file:Users/bob/AppData/Chrome/History",
            "file:Users/bob/Documents/report.docx",
        ],
    )
    assert len(verdicts) == 3
    assert len({verdict.independence_key for verdict in verdicts}) == 3


def test_graph_id_never_a_candidate():
    with pytest.raises(ValueError):
        RESOLVER.resolve(["node-abc123"])


def test_first_occurrence_ref_wins_later_layers_merge():
    verdicts = RESOLVER.resolve(
        ["file:A", "file:B", "file:A"],
        layer_provenance={
            "file:A": ("direct",),
            "file:B": ("other",),
        },
    )
    # file:B is a different root; the second file:A merges layers
    assert [verdict.evidence_ref for verdict in verdicts] == ["file:A", "file:B"]
    first = verdicts[0]
    assert first.representation_layers == ("direct",)


# ---------------------------------------------------------------------------
# §36 deterministic ranking
# ---------------------------------------------------------------------------


def _independence(ref):
    return RESOLVER.resolve([ref])[0]


def test_ranking_is_deterministic_and_role_ordered():
    candidates = [
        (_independence("file:ctx1"), "retrieved_context"),
        (_independence("file:anchor1"), "anchor"),
        (_independence("file:support1"), "supporting"),
    ]
    ranked = rank_candidates(candidates)
    assert [item.independence.evidence_ref for item in ranked] == [
        "file:anchor1",
        "file:support1",
        "file:ctx1",
    ]
    ranked_again = rank_candidates(candidates)
    assert ranked == ranked_again


def test_ranking_prefers_main_report_evidence_and_semantic_support():
    anchor = (_independence("file:plain"), "anchor")
    ctx_main_supported = (
        _independence("file:main_semantic"),
        "retrieved_context",
    )
    ranked = rank_candidates(
        [anchor, ctx_main_supported],
        report_evidence_status={"file:main_semantic": "main"},
        accepted_semantic_refs=("file:main_semantic",),
    )
    scores = {
        item.independence.evidence_ref: item.rank_score for item in ranked
    }
    # anchor base 3.0; retrieved_context 1.0 + 0.5 main + 0.4 semantic
    assert scores["file:main_semantic"] == pytest.approx(1.9)
    assert scores["file:plain"] == pytest.approx(3.0)


def test_ranking_graph_distance_closer_better():
    near = (_independence("file:near"), "retrieved_context")
    far = (_independence("file:far"), "retrieved_context")
    ranked = rank_candidates(
        [far, near],
        graph_distance={"file:near": 1, "file:far": 8},
    )
    assert ranked[0].independence.evidence_ref == "file:near"


def test_ranking_total_order_tie_break_by_ref():
    a = (_independence("file:a"), "supporting")
    b = (_independence("file:b"), "supporting")
    ranked = rank_candidates([b, a])
    assert [item.independence.evidence_ref for item in ranked] == [
        "file:a",
        "file:b",
    ]


# ---------------------------------------------------------------------------
# §37/§38 budget
# ---------------------------------------------------------------------------


def _ranked(refs, role="retrieved_context"):
    return [
        (_independence(ref), role) for ref in refs
    ]


def test_budget_truncates_deterministically_with_limitation():
    budget = RetrievalBudgetV1(max_evidence_items=3)
    ranked = rank_candidates(_ranked(["file:1", "file:2", "file:3", "file:4"]))
    kept, accounting = apply_budget(
        ranked, required_anchor_refs=(), budget=budget
    )
    assert [item.independence.evidence_ref for item in kept] == [
        "file:1",
        "file:2",
        "file:3",
    ]
    assert accounting.truncated_refs == ["file:4"]
    assert any(
        limitation.startswith("EVIDENCE_BUDGET_TRUNCATED")
        for limitation in accounting.limitations
    )


def test_mandatory_anchor_never_silently_dropped():
    """§38: even at zero budget the required anchor stays and missing
    anchors surface explicitly."""
    budget = RetrievalBudgetV1(max_evidence_items=1)
    ranked = rank_candidates(
        _ranked(["file:noise1", "file:noise2"])
        + [(_independence("file:anchor"), "anchor")]
    )
    kept, accounting = apply_budget(
        ranked, required_anchor_refs=("file:anchor",), budget=budget
    )
    kept_refs = {item.independence.evidence_ref for item in kept}
    assert "file:anchor" in kept_refs
    assert len(kept) == 1


def test_missing_required_anchor_recorded_not_silent():
    budget = RetrievalBudgetV1(max_evidence_items=4)
    ranked = rank_candidates(_ranked(["file:1", "file:2"]))
    kept, accounting = apply_budget(
        ranked,
        required_anchor_refs=("file:missing",),
        budget=budget,
    )
    assert any(
        limitation.startswith("BUDGET_EXHAUSTED_ANCHORS")
        for limitation in accounting.limitations
    )
    assert "file:missing" in accounting.limitations[-1]


def test_detailed_depth_budget_capped():
    budget = RetrievalBudgetV1(max_detailed_items=1)
    ranked = rank_candidates(
        [(_independence("file:a"), "anchor"), (_independence("file:b"), "anchor")]
    )
    kept, accounting = apply_budget(
        ranked,
        required_anchor_refs=(),
        budget=budget,
        depth_overrides={"file:a": "detailed", "file:b": "detailed"},
    )
    assert accounting.detailed_count == 1
    assert any(
        limitation.startswith("DETAILED_DEPTH_BUDGET_EXCEEDED:file:b")
        for limitation in accounting.limitations
    )


def test_budget_retrieval_order_retrieved_first_shed():
    """Truncation order: with a tight budget, retrieved_context items shed
    before supporting items because ranking places them last."""
    budget = RetrievalBudgetV1(max_evidence_items=2)
    ranked = rank_candidates(
        _ranked(["file:r1", "file:r2"])
        + _ranked(["file:s1"], role="supporting")
    )
    kept, _accounting = apply_budget(
        ranked, required_anchor_refs=(), budget=budget
    )
    kept_refs = {item.independence.evidence_ref for item in kept}
    assert kept_refs == {"file:s1", "file:r1"}
