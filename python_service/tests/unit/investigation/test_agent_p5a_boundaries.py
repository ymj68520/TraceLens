"""P5A/P5B boundary tests.

P5A §62 originally forbade any SemanticVerifierAgent / CorrelationAgent /
AssertionPolicy / ClaimDisposition definition; P5B legitimately introduces
those (one multi-mode verifier, deterministic policy), so the forbidden set
now covers the P6 graph boundary. What stays permanently forbidden is
auto-wiring: neither the P4 orchestrator nor the ServiceManager may pull
the P5A pipeline or the P5B verifier/policy into automatic execution."""

import re
from pathlib import Path

_PRODUCTION_DIR = (
    Path(__file__).resolve().parents[3]
    / "httpserver" / "services" / "investigation"
)

# §62: these P5B constructs must not be DEFINED anywhere in production code.
# (Docstring *mentions* of the boundary are fine and intentional; only
# class/function definitions are violations.)
# P6A legitimately introduces GraphCandidate/GraphAdmissionPolicy/
# ForensicGraphEpisode; the remaining forbidden set covers the P6B/P7
# execution boundary (no backend materializer, no report runtime).
# P6B legitimately introduces the GraphMaterializationExecutor; the
# remaining forbidden set covers the P7 report runtime boundary.
_FORBIDDEN_DEFINITIONS = re.compile(
    r"^\s*(?:class|def)\s+("
    r"ReportRuntime|ReportWriter|ChapterPlanner|ReportOutlinePlan"
    r")\b",
    re.MULTILINE,
)

# §65: the P4 loop must not call the P5A pipeline (explicit entry only).
_ORCHESTRATOR = _PRODUCTION_DIR / "agent_orchestrator.py"
_P5A_ENTRY = "process_specialist_proposals"


def test_no_verifier_or_correlation_agent_definitions():
    violations = []
    for path in sorted(_PRODUCTION_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in _FORBIDDEN_DEFINITIONS.finditer(source):
            violations.append(f"{path.name}: {match.group(0).strip()}")
    assert violations == []


def test_orchestrator_never_invokes_the_p5a_pipeline():
    source = _ORCHESTRATOR.read_text(encoding="utf-8")
    assert _P5A_ENTRY not in source
    for module in (
        "agent_grounding",
        "agent_entities",
        "agent_claims",
        "agent_correlation",
        "agent_support_bundle",
        "agent_identity",
        "agent_verification",
        "agent_assertion_policy",
        "agent_correlation_agent",
        "agent_findings",
    ):
        assert f"from .{module}" not in source, module
        assert f"import {module}" not in source, module


def test_service_manager_gains_no_p5a_lifecycle_service():
    """F2 §15/§23: the ServiceManager may reference the P5B final-review
    adapter ONLY as a function-scoped lazy import (never a module-level
    import, never an eager lifecycle service)."""
    import re as _re

    service_manager = (
        _PRODUCTION_DIR.parent / "service_manager.py"
    ).read_text(encoding="utf-8")
    for module in (
        "agent_grounding",
        "agent_entities",
        "agent_claims",
        "agent_correlation",
        "agent_support_bundle",
        "agent_assertion_policy",
        "agent_correlation_agent",
        "agent_findings",
    ):
        assert module not in service_manager, module
    # P5B modules: function-scoped lazy references only
    top_level = _re.compile(
        r"^(from\s+\S*(agent_verification|agent_grounding|agent_entities|"
        r"agent_claims|agent_correlation|agent_support_bundle|"
        r"agent_assertion_policy|agent_correlation_agent|agent_findings)"
        r"|import\s+\S*(agent_verification|agent_grounding))",
        _re.MULTILINE,
    )
    assert top_level.search(service_manager) is None
    # P5A components are stateless objects (§64): no new executor service
    assert "grounding_executor" not in service_manager
    assert "verification_executor" not in service_manager


def test_p6a_modules_never_call_graph_backends():
    """P6A §63: production graph-admission modules contain zero Graphiti /
    Neo4j write calls - SQLite manifest is the only thing they touch."""
    for name in (
        "agent_graph_candidate.py",
        "agent_graph_admission.py",
    ):
        source = (_PRODUCTION_DIR / name).read_text(encoding="utf-8")
        for token in ("add_episode", "cypher", "neo4j", "Graphiti("):
            assert token not in source.lower(), (name, token)
