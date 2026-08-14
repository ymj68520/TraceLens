"""C5b structured output parser and atomic completion tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from httpserver.services.investigation import (
    ClaimCandidate,
    ClaimType,
    InvestigationRepository,
    SecondaryAnalysisStatus,
    StructuredOutputError,
    parse_structured_analysis_response,
)
from httpserver.services.investigation.prompts import (
    CURRENT_PROMPT_VERSION,
    PROMPT_OUTPUT_CONTRACT,
    PROMPT_REGISTRY,
    SECONDARY_ANALYSIS_SYSTEM_V3,
    SECONDARY_ANALYSIS_USER_TEMPLATE_V3,
)


def test_parser_valid_json():
    response = parse_structured_analysis_response(json.dumps({
        "description": "详细描述",
        "summary": "简要总结",
        "claims": [{
            "claim_type": "FACT",
            "claim_text": "事实",
            "evidence_refs": ["file:/case/a.txt"],
        }],
    }))
    assert response.description == "详细描述"
    assert response.claims[0].claim_type == ClaimType.FACT


@pytest.mark.parametrize("content", [
    "not json",
    "```json {\"description\":\"d\",\"summary\":\"s\",\"claims\":[]}```",
    "prefix {\"description\":\"d\",\"summary\":\"s\",\"claims\":[]}",
    "[1, 2]",
    "",
])
def test_parser_rejects_non_strict_json(content):
    with pytest.raises(StructuredOutputError):
        parse_structured_analysis_response(content)


@pytest.mark.parametrize("content", [
    '{"description":"d","summary":"s","claims":[],"claims":[]}',
    '{"description":"d","summary":"s","claims":[{"claim_type":"FACT","claim_text":"x","evidence_refs":[],"claim_text":"y"}]}',
    '{"description":"d","summary":"s","claims":[],"x":1}',
    '{"description":"d","summary":"s","claims":[{"claim_type":"FACT","claim_text":"x","evidence_refs":[],"grounding_status":"valid"}]}',
    '{"description":"d","summary":"s","claims":[{"claim_type":"BAD","claim_text":"x","evidence_refs":[]}]}',
    '{"description":"","summary":"s","claims":[]}',
    '{"description":"d","summary":"s","claims": [NaN]}',
])
def test_parser_rejects_invalid_schema(content):
    with pytest.raises(StructuredOutputError):
        parse_structured_analysis_response(content)


def test_parser_empty_claims_valid():
    response = parse_structured_analysis_response(
        '{"description":"d","summary":"s","claims":[]}'
    )
    assert response.claims == ()


def test_prompt_v3_contract_and_hash():
    import hashlib
    expected = "65b923b6d5cc09e5e3afbb2624ee1b02a88c2cce1812578ed69a3dd90be2f8f9"
    assert CURRENT_PROMPT_VERSION == "investigation-evidence-analysis:v3"
    assert PROMPT_OUTPUT_CONTRACT[CURRENT_PROMPT_VERSION] == "structured_claims_v1"
    assert hashlib.sha256((SECONDARY_ANALYSIS_SYSTEM_V3 + SECONDARY_ANALYSIS_USER_TEMPLATE_V3).encode()).hexdigest() == expected
    assert "grounding_status" in SECONDARY_ANALYSIS_SYSTEM_V3


def test_claim_candidate_forbids_extra_and_empty_text():
    with pytest.raises(ValueError):
        ClaimCandidate(claim_type=ClaimType.FACT, claim_text="", evidence_refs=())
    with pytest.raises(ValueError):
        ClaimCandidate(claim_type=ClaimType.FACT, claim_text="x", evidence_refs=(), extra_field="x")
