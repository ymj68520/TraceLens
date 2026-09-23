"""P5A boundary tests: §62 no verifier/correlation-agent execution in
production modules, and §65 the P5A pipeline is never auto-wired into the
P4 cycle."""

import re
from pathlib import Path

_PRODUCTION_DIR = (
    Path(__file__).resolve().parents[3]
    / "httpserver" / "services" / "investigation"
)

# §62: these P5B constructs must not be DEFINED anywhere in production code.
# (Docstring *mentions* of the boundary are fine and intentional; only
# class/function definitions are violations.)
_FORBIDDEN_DEFINITIONS = re.compile(
    r"^\s*(?:class|def)\s+("
    r"SemanticVerifierAgent|CorrelationAgent|AssertionPolicy|"
    r"SemanticVerificationResult|ClaimDisposition|"
    r"claim_sufficiency|correlation_sufficiency|finalization_review"
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
    ):
        assert f"from .{module}" not in source, module
        assert f"import {module}" not in source, module


def test_service_manager_gains_no_p5a_lifecycle_service():
    service_manager = (
        _PRODUCTION_DIR.parent / "service_manager.py"
    ).read_text(encoding="utf-8")
    for module in (
        "agent_grounding",
        "agent_entities",
        "agent_claims",
        "agent_correlation",
        "agent_support_bundle",
    ):
        assert module not in service_manager, module
    # P5A components are stateless objects (§64): no new executor service
    assert "grounding_executor" not in service_manager
