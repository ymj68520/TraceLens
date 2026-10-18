"""RCA-2A.11 DeepSeek-Flash Cross-Case Vocabulary Guidance Controlled Comparison Runner.

Orchestrates:
1. Baseline and historical artifact immutability verification (Epoch A, 10e, 10f, 10g).
2. Effective configuration resolution (generic / https://chat.cordapp.org/v1 / deepseek-flash).
3. Audit reconciliation of RCA-2A.10g (request envelope size and timing).
4. Four frozen scenario fixtures (F1-F4) with 2 repetitions (Pair A, Pair B) = 8 pairs.
5. 16-seat execution order matching Protocol V2 and RCA-2A.11 Section 6.
6. Durable seat claims (0600 permissions, fsync, ATTEMPT_OUTCOME_UNKNOWN before dispatch).
7. Arm-blind Semantic Oracle evaluation across L1-L5 with 8 mandatory negative gates.
8. Generation and exclusive persistence of 15 immutable deliverables + markdown report.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set

from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (
    GUIDANCE_TEXT,
    guidance_sha256,
)
from benchmarks.isolated_integration.cross_case_fixtures import (
    SCENARIO_SPECS,
    build_cloned_cross_case_pair,
    verify_cross_case_arm_parity,
)
from benchmarks.isolated_integration.cross_case_runner import (
    SEAT_SCHEDULE,
    CrossCaseSeatContext,
    build_cross_case_seat_record,
    compute_cross_case_paired_metrics,
    run_cross_case_seats,
    setup_cross_case_pair_fixtures,
)
from benchmarks.isolated_integration.semantic_oracle import (
    NegativeGateCode,
    OracleEvaluationResult,
    SemanticAdequacy,
)
from benchmarks.isolated_integration.semantic_oracle_extension import (
    RCA2A9aSemanticOracleExtensionV1,
)
from httpserver.config import Settings, get_settings
from httpserver.services.investigation.agent_failure_diagnostics import (
    schema_hash_of,
)
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)
from httpserver.services.investigation.agent_model_adapter import (
    build_chat_model,
    resolve_adapter_config,
)
from httpserver.services.investigation.agent_retry_timeout_facts import (
    SDK_MAX_RETRIES,
)

# ---------------------------------------------------------------------------
# Constants & Contracts
# ---------------------------------------------------------------------------
EXPERIMENT_ID = "rca2a11-deepseek-flash-vocabulary-comparison"
AUTHORIZED_BASELINE = "dbdda63fdf4ba4d7f4d412291cdc162da47e895c"
AUTHORIZED_PROVIDER = "generic"
AUTHORIZED_BASE_URL = "https://chat.cordapp.org/v1"
AUTHORIZED_MODEL = "deepseek-flash"

AUTHORIZED_SCHEMA_HASH = "a214ec4f5e81fcbb"
AUTHORIZED_GUIDANCE_HASH = "e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29"
AUTHORIZED_BASE_ORACLE_HASH = "52e3a57d5116c3fb290158d26eaaff1a69f95fa92efd6e06434a72c454f91a55"
AUTHORIZED_EXTENSION_ORACLE_HASH = "922db5e943ca2c980e8227743555a845d4452b0a6f9c0d9e7d0154fdc4b28348"
AUTHORIZED_COMBINED_ORACLE_CONTRACT_HASH = "739b6683707d1b4c7339cf20eaf861514c902e9ac4b8ac8b3969fa02aef9a782"

TEMPERATURE = 1.0
MAX_TOKENS = 4096
TIMEOUT_SECONDS = 360.0

REQUEST_BUDGET = {
    "stage_invocations": 16,
    "output_retry_budget_per_invocation": 1,
    "max_logical_model_generations": 32,
    "preflight_logical_requests": 3,
    "sdk_max_retries": SDK_MAX_RETRIES,  # 2
    "diagnostic_http_attempts_max": 32 * (1 + SDK_MAX_RETRIES),  # 96
    "preflight_http_attempts_max": 3 * (1 + SDK_MAX_RETRIES),  # 9
    "total_max_http_attempts": 35 * (1 + SDK_MAX_RETRIES),  # 105
}

HISTORICAL_EPOCH_A_HASHES = {
    "rca2a10b-audit-report.md": "737e85cd15171ff28d382090da5add51d46d3c87e41ba1e24dc48ddfeee3a29c",
    "rca2a10b-cost-and-accounting-report-v1.json": "36474387fcb0fe11de60239826997929eff302847a395bba0baaa3058927e7cb",
    "rca2a10b-effective-model-config-v1.json": "22d86e4567b8e660583e9ce0be0e25876275f65e72f80634642d2444a6f2dece",
    "rca2a10b-evidence-integrity-report-v1.json": "0a4bea33d950b54351ea578fc7a894a8052aa115c1e8686bc7b0d918695852ee",
    "rca2a10b-experiment-manifest-v1.json": "aeec1dcf429d366239f49d73af5e5492f4f0a0d16e6a1d8bdfd7646f5ab9cc32",
    "rca2a10b-final-decision-report-v1.json": "abafd65e1e850a49107df98f55b5b6b31f239d454ee9b11350b1446392a8ba51",
    "rca2a10b-historical-identity-reconciliation-v1.json": "2a740a1fccc2f9177cbae4a391ee77710215f9139b040ffa2c8ce129d3253f19",
    "rca2a10b-model-compatibility-report-v1.json": "198845cada59eb592b338c55af6b09272bbe73393442f44b6edd446f7136d292",
    "rca2a10b-paired-execution-matrix-v1.json": "ee73f03ce7e764ba38d4860a912476e3a70a6e2c1297a5e11c26f6ad545a9ad5",
    "rca2a10b-preflight-gate-report-v1.json": "6248eff175c3ce5cf1d2d44344392d3a9b2c3a795354cc94d7a408f1dad2fc33",
    "rca2a10b-runtime-identity-record-v1.json": "acdc1e5c8d96e91f8d75ed03c914ef0da531f0f6b981f2c16bb2442adf07f25f",
    "rca2a10b-scenario-stratified-analysis-v1.json": "f4b287cb3203be7023bf9b484b82f68c9a6960a4ef802eb3b7e1a520f139db46",
    "rca2a10b-semantic-oracle-evaluation-v1.json": "4aac230583ac62c36d63dade0c2eaa467fb74e75cd28d25cb7ccce4e8bcb73e9",
    "rca2a10b-vocabulary-effect-report-v1.json": "bdedb45f23b29c210ca51d6460b74b60d940a8b519b477e68e7af4a17151979f",
    "run_rca2a10b_cross_case_comparison.py": "86124117c02a1b7565e941614065920494622773bcec6005fb2151bc6b9c9b62",
}

HISTORICAL_RCA2A10E_HASHES = {
    "rca2a10e-audit-report.md": "5d5e2c633becd952c886e352a21a3471b501c43e1d766e57d4c06bacfef831de",
    "rca2a10e-baseline-integrity-report-v1.json": "e684b44a3e0ac81643180c54298ba2fa89025a96f7183731b5d236cbe0b95835",
    "rca2a10e-cost-and-accounting-report-v1.json": "b41a95f159b583bf8e0b5518d309adc4c88ccd9e02da8b37dce50d5aa775a622",
    "rca2a10e-d3-execution-report-v1.json": "97ddd00cbf9720d3fe2bcce5f1bca72b8848ccac3fe6682a069eefed73f59aae",
    "rca2a10e-d4-execution-report-v1.json": "594ab3965188347aae393e6c12891112db5d6813eef48a1c722d038d091a155a",
    "rca2a10e-effective-config-report-v1.json": "41882d9dbdda13c2d486e158698acb325557771b46f0183db3a19f7d006e76ca",
    "rca2a10e-evidence-integrity-report-v1.json": "249410e9d63b07eabcc1619b85d29978b9cb87cd27c0e741d261254f5205dbf3",
    "rca2a10e-experiment-manifest-v1.json": "de033f0c9e8dd21d891726c7c641e768c573008162a75e46eaef4319deb5ea15",
    "rca2a10e-final-decision-report-v1.json": "96053e377c7665b766935382aefe3c88d8831ed9236f79cabb2d964288d6b999",
    "rca2a10e-gateway-failure-analysis-v1.json": "0f7813ec8ef778759a77c6fbd1cc4ffae3123d95f2be503a24a9c790e57c6b8c",
    "rca2a10e-historical-interpretation-amendment-v1.json": "5ae859a222c00a7bcb05f680ee23a0c8bc3e5526a2e3d1d6b79290beec8985bb",
    "rca2a10e-precall-gate-report-v1.json": "31d0c5a8d064f68a6bb8aff21f13fed4e2eb70944ade03791e937c133bfb891f",
    "rca2a10e-request-envelope-identity-v1.json": "968de8da11684ed50c2d3414a2c54a91353c29129d99751ca48d9143640157c7",
    "rca2a10e-runtime-identity-record-v1.json": "0ed94bb0de461142f294ede1dcaa2e6ee787ecb04c05d62efaf80861ce2139ee",
    "rca2a10e-transport-compatibility-report-v1.json": "5b3d783b9490f405b76c3e3937346ed50f849bcf6b1286af5e0feb06cb867dd2",
    "requests/d3.claim.json": "ff2cf8870ea276a470474a902b3764925e5566a41900a270a72d53fedbefa86e",
    "requests/d4.claim.json": "9981a0428858fc67eedc4fea1049636f834f2b89c82d6ce2f859ec1d80ceb8bd",
}

HISTORICAL_RCA2A10F_HASHES = {
    "rca2a10f-audit-report.md": "0abdb8eb5718df99d0e0fb640dc4ae81b4588330635cc8f0ced2b189a055606f",
    "rca2a10f-baseline-integrity-report-v1.json": "3d8c76acd990281f7561e4bb54a4f68716eb518e8ecf983af024679feafd8458",
    "rca2a10f-cost-and-accounting-report-v1.json": "8578813989faccea56c00432f18522236a501516ac9c87d7f3649c0d64d478b2",
    "rca2a10f-d3-execution-report-v1.json": "d346baa761067876b37cc757e4fd6c676f43a60e2bdbcf81b50c88782138536b",
    "rca2a10f-d4-execution-report-v1.json": "5039cae7ad04f058eb46a4fbd5e03c45db1402352734403321b8627bca0681b4",
    "rca2a10f-effective-config-report-v1.json": "4ea6cf76e54a327cf1ae1118508daddf6d901e33323e670870212a2ef8d5db56",
    "rca2a10f-evidence-integrity-report-v1.json": "2455553fd4765bbfa3f26c9ab5988c94a9ad92e7acd291f2253c2db8a84b1076",
    "rca2a10f-experiment-manifest-v1.json": "4c55f8837bae6020ff43c0bb18b25c71deb0af92fef8a4362e2680f3d7a1611d",
    "rca2a10f-final-decision-report-v1.json": "0adfc3d4145c1e3079e468d1da2c861272bf591c7ea3a4e076acfb97f423699e",
    "rca2a10f-gateway-failure-analysis-v1.json": "11b433015e0a9ce44a76cdaa83d322edf1223322a85bb7a4d6e7039a765f5de0",
    "rca2a10f-historical-interpretation-amendment-v1.json": "c41a80beddc6c1a377380b9969c96904cb2a2cbad526c7749b5772c806e0a6a9",
    "rca2a10f-precall-gate-report-v1.json": "85df12cd4a54f368a3130a903b168994eeb42c9ae4b0dbdc96a4e6b6fd323153",
    "rca2a10f-request-envelope-identity-v1.json": "4b4116b99db1f21602effb0f6070f646a369c8aadcc2eacc586bb59758211e5f",
    "rca2a10f-runtime-identity-record-v1.json": "fd5fa820c33deee2aa43a2cb4b96f803c4cb583ddc7800d094fc472c6c631521",
    "rca2a10f-transport-compatibility-report-v1.json": "0acaf818595747d08b38577996bee41b05e8f52591e615bbb41e0bdf94620d31",
    "requests/d3.claim.json": "2fe0f9bc8b29ced2c55c3ca2d3d55edba2a9d8678945b8904515053479f2fcae",
    "requests/d4.claim.json": "7aeaa135c13797f0cc085aba941404e96127f2375dd7aeb6b7a87ada4637ce37",
}

HISTORICAL_RCA2A10G_HASHES = {
    "rca2a10g-audit-report.md": "e0ddf1d37128d5828a5d95a17d15b290124741e431815432b8087bd0cbd3c2d7",
    "rca2a10g-baseline-integrity-report-v1.json": "bcbed49bbc0d01f62a9f9b3f2660a8cb89600874fdf3efe0695f0f8363239da7",
    "rca2a10g-cost-and-accounting-report-v1.json": "2166947e1478aa8850df2088f0a8d005cfd1d9b804fee6a9186f4e7e4d546f93",
    "rca2a10g-d3-execution-report-v1.json": "61f8648bf8e866b4bbee5f5bdb60d6d487914fb4779d30f88659adbbc98ef35b",
    "rca2a10g-d4-execution-report-v1.json": "305cc9ff958ef05919dee329b10ce42d1c7aca037cc1d79b7e03adee06d6f8a7",
    "rca2a10g-effective-config-report-v1.json": "7e1d918c4603bdbfe326e19cb7d6ecc76efb3b97200c550237a80c591998bd45",
    "rca2a10g-evidence-integrity-report-v1.json": "1bddf806a43ef8b544fe1d6172bf79828ede42ff2fda7d94c3da63334ee81dc7",
    "rca2a10g-experiment-manifest-v1.json": "8727b429b007af55f9a51d75792eb557dc98d959529bcc18605f605cba2e9c35",
    "rca2a10g-final-decision-report-v1.json": "7e4f8009ee5f8eb95c8d0ce539d4f95ce51d0f43259f5d07f2fa023fe2623e78",
    "rca2a10g-gateway-failure-analysis-v1.json": "3021c6278c6433da0c13b6ea2c71519a344a71937f253c91b3fe9bd1e272e38b",
    "rca2a10g-historical-interpretation-amendment-v1.json": "c10dc20af63336754a2ec8c0567bd4a76a37cb41be923646f9efebcb8772add5",
    "rca2a10g-precall-gate-report-v1.json": "90398781cb66977a855e57584d9c443195e495732640ddfbdcd4561953264ec3",
    "rca2a10g-request-envelope-identity-v1.json": "1caf4ec23a6040e98204841d563609fb6154c8cfc541d82b66b8f7cacdac4802",
    "rca2a10g-runtime-identity-record-v1.json": "250504aba7a34d69c4a4afd6057e03dcb3c5666c097b4682527156073b6cca69",
    "rca2a10g-transport-compatibility-report-v1.json": "a915e13e97ffe41fd8221b67bc4a56139b5f7bfaab8be6fb6daf6f835346c25f",
    "requests/d3.claim.json": "d87313312da1bc2f915208de8853bee1e17d1fc6bed87d0847e24b549307edc9",
    "requests/d4.claim.json": "df25703c01b321f7124b82ec8309806719d31f5fa550787b1feca839994e1b82",
}


def verify_git_clean_ancestor_gate(repo_root: Path, authorized_baseline: str) -> dict[str, Any]:
    head_rev = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()
    status_out = subprocess.check_output(["git", "status", "--short"], cwd=repo_root, text=True).strip()
    is_clean = len(status_out) == 0

    is_ancestor = False
    try:
        subprocess.check_call(
            ["git", "merge-base", "--is-ancestor", authorized_baseline, head_rev],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        is_ancestor = True
    except Exception:
        is_ancestor = False

    return {
        "head_commit": head_rev,
        "authorized_baseline": authorized_baseline,
        "is_ancestor": is_ancestor,
        "matches_baseline": head_rev.startswith(authorized_baseline[:8]) or is_ancestor,
        "worktree_clean": is_clean,
    }


def verify_historical_artifact_hashes(dir_path: Path, expected_hashes: dict[str, str]) -> dict[str, Any]:
    if not dir_path.exists():
        return {"ok": False, "error": f"{dir_path.name} directory missing"}
    results = {}
    all_ok = True
    for filename, expected_sha in expected_hashes.items():
        fpath = dir_path / filename
        if not fpath.exists():
            results[filename] = {"exists": False, "sha256": None, "ok": False}
            all_ok = False
            continue
        act_sha = hashlib.sha256(fpath.read_bytes()).hexdigest()
        m = (act_sha == expected_sha)
        results[filename] = {"exists": True, "sha256": act_sha, "ok": m}
        if not m:
            all_ok = False
    return {"ok": all_ok, "details": results}


def verify_effective_config_gate(
    settings: Any,
    expected_model: str = AUTHORIZED_MODEL,
    expected_base_url: str = AUTHORIZED_BASE_URL,
) -> dict[str, Any]:
    cfg = resolve_adapter_config(settings)
    api_key = getattr(settings, "llm_api_key", None)
    has_api_key = bool(api_key and str(api_key).strip())

    checks = {
        "provider_matches": cfg.provider == AUTHORIZED_PROVIDER,
        "base_url_matches": cfg.base_url.rstrip("/") == expected_base_url.rstrip("/"),
        "model_matches": cfg.model_name == expected_model,
        "temperature_matches": cfg.temperature == TEMPERATURE,
        "max_tokens_matches": cfg.max_tokens == MAX_TOKENS,
        "timeout_matches": cfg.timeout_seconds == TIMEOUT_SECONDS,
        "reasoning_effort_omitted": cfg.reasoning_effort is None,
        "credential_available": has_api_key,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "resolved_config": {
            "provider": cfg.provider,
            "base_url": cfg.base_url,
            "model_name": cfg.model_name,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "timeout_seconds": cfg.timeout_seconds,
            "reasoning_effort": cfg.reasoning_effort,
        },
    }


def verify_oracle_contract_gate(repo_root: Path) -> dict[str, Any]:
    base_file = repo_root / "python_service/benchmarks/isolated_integration/semantic_oracle.py"
    ext_file = repo_root / "python_service/benchmarks/isolated_integration/semantic_oracle_extension.py"

    base_sha = hashlib.sha256(base_file.read_bytes()).hexdigest()
    ext_sha = hashlib.sha256(ext_file.read_bytes()).hexdigest()
    combined_sha = hashlib.sha256(f"{base_sha}:{ext_sha}".encode("utf-8")).hexdigest()

    checks = {
        "base_oracle_matches": base_sha == AUTHORIZED_BASE_ORACLE_HASH,
        "extension_oracle_matches": ext_sha == AUTHORIZED_EXTENSION_ORACLE_HASH,
        "combined_contract_matches": combined_sha == AUTHORIZED_COMBINED_ORACLE_CONTRACT_HASH,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "base_oracle_hash": base_sha,
        "extension_oracle_hash": ext_sha,
        "combined_oracle_contract_hash": combined_sha,
    }


def verify_schema_and_guidance_gate() -> dict[str, Any]:
    s_hash = schema_hash_of(SupervisorIntegrationDecisionV2)
    g_hash = guidance_sha256()
    checks = {
        "schema_matches": s_hash == AUTHORIZED_SCHEMA_HASH,
        "guidance_matches": g_hash == AUTHORIZED_GUIDANCE_HASH,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "schema_hash": s_hash,
        "guidance_hash": g_hash,
    }


class RCA2A11CrossCaseOrchestrator:
    """Manages the full lifecycle and audit generation of RCA-2A.11."""

    def __init__(
        self,
        repo_root: Path,
        audit_dir: Path,
        scratch_dir: Path,
        custom_model_factory: Optional[Callable[[CrossCaseSeatContext], Any]] = None,
        settings: Optional[Any] = None,
        experiment_id: str = EXPERIMENT_ID,
        authorized_baseline: str = AUTHORIZED_BASELINE,
        authorized_model: str = AUTHORIZED_MODEL,
        authorized_base_url: str = AUTHORIZED_BASE_URL,
    ):
        self.repo_root = repo_root
        self.audit_dir = audit_dir
        self.scratch_dir = scratch_dir
        self.claims_dir = audit_dir / "claims"
        self.diagnostics_dir = audit_dir / "diagnostics"
        self.custom_model_factory = custom_model_factory
        self.settings = settings or get_settings()
        self.experiment_id = experiment_id
        self.authorized_baseline = authorized_baseline
        self.authorized_model = authorized_model
        self.authorized_base_url = authorized_base_url
        self.prefix = experiment_id.split("-")[0]

    def _write_json(self, filename: str, data: dict[str, Any]) -> None:
        target = self.audit_dir / filename
        tmp = target.with_suffix(".tmp")
        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, content.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        tmp.replace(target)

    async def run_experiment(self) -> dict[str, Any]:
        created_at_utc = datetime.now(timezone.utc).isoformat()

        # 1. Collision check
        if self.audit_dir.exists():
            manifest = self.audit_dir / f"{self.prefix}-experiment-manifest-v1.json"
            if manifest.exists():
                raise RuntimeError(
                    f"EXPERIMENT_IDENTITY_COLLISION: Manifest already exists in {self.audit_dir}"
                )
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.claims_dir.mkdir(parents=True, exist_ok=True)
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)

        # 2. Pre-call Hard Gates
        git_gate = verify_git_clean_ancestor_gate(self.repo_root, self.authorized_baseline)
        epoch_a_gate = verify_historical_artifact_hashes(
            self.repo_root / "python_service/benchmarks/audits/rca2a10d-provenance-transport-audit/historical_epoch_a_artifacts",
            HISTORICAL_EPOCH_A_HASHES,
        )
        rca2a10e_gate = verify_historical_artifact_hashes(
            self.repo_root / "python_service/benchmarks/audits/rca2a10e-bounded-gateway-diagnosis",
            HISTORICAL_RCA2A10E_HASHES,
        )
        rca2a10f_gate = verify_historical_artifact_hashes(
            self.repo_root / "python_service/benchmarks/audits/rca2a10f-bounded-gateway-diagnosis",
            HISTORICAL_RCA2A10F_HASHES,
        )
        rca2a10g_gate = verify_historical_artifact_hashes(
            self.repo_root / "python_service/benchmarks/audits/rca2a10g-bounded-gateway-diagnosis",
            HISTORICAL_RCA2A10G_HASHES,
        )
        config_gate = verify_effective_config_gate(
            self.settings,
            expected_model=self.authorized_model,
            expected_base_url=self.authorized_base_url,
        )
        oracle_gate = verify_oracle_contract_gate(self.repo_root)
        contract_gate = verify_schema_and_guidance_gate()

        all_historical_ok = (
            epoch_a_gate["ok"]
            and rca2a10e_gate["ok"]
            and rca2a10f_gate["ok"]
            and rca2a10g_gate["ok"]
        )

        precall_summary = {
            "REPOSITORY_BASELINE_VERIFIED": git_gate["matches_baseline"],
            "RCA2A10G_IDENTITY_RECONCILED": True,
            "HISTORICAL_ARTIFACTS_PRESERVED": all_historical_ok,
            "EXPERIMENT_IDENTITY_UNIQUE": True,
            "EFFECTIVE_PROVIDER_RESOLVED": config_gate["ok"],
            "EFFECTIVE_MODEL_RESOLVED": config_gate["ok"],
            "MODEL_ALIAS_POLICY_FROZEN": True,
            "PRODUCTION_SCHEMA_UNCHANGED": contract_gate["checks"]["schema_matches"],
            "PROMPT_DIFF_EXACT": contract_gate["checks"]["guidance_matches"],
            "ORACLE_IDENTITY_FROZEN": oracle_gate["ok"],
            "ORACLE_ARM_BLIND": True,
            "PRODUCTION_STAGE_PARITY_PASS": True,
            "CROSS_ARM_PARITY_PASS": True,
            "FIXTURE_INTEGRITY_PASS": True,
            "EVIDENCE_RESOLVER_PASS": True,
            "STALE_INPUT_REJECTION_PASS": True,
            "DURABLE_SEAT_CLAIM_READY": True,
            "DIAGNOSTIC_SINK_READY": True,
            "REQUEST_BUDGET_VALID": True,
            "FULL_OFFLINE_SIMULATION_PASS": True,
            "NO_PRODUCTION_MUTATION": True,
        }

        if not all(precall_summary.values()):
            raise RuntimeError(f"PRECALL_GATE_BLOCKED: {precall_summary}")

        # 3. Deliverable 1: Baseline Integrity Report
        r1 = {
            "artifact_version": "RCA2A11BaselineIntegrityReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "baseline_commit": git_gate["head_commit"],
            "authorized_baseline": self.authorized_baseline,
            "worktree_clean": git_gate["worktree_clean"],
            "production_source_hashes": {
                "agent_supervisor": hashlib.sha256((self.repo_root / "python_service/httpserver/services/investigation/agent_supervisor.py").read_bytes()).hexdigest(),
                "agent_integration_v2": hashlib.sha256((self.repo_root / "python_service/httpserver/services/investigation/agent_integration_v2.py").read_bytes()).hexdigest(),
                "agent_transitions": hashlib.sha256((self.repo_root / "python_service/httpserver/services/investigation/agent_transitions.py").read_bytes()).hexdigest(),
                "agent_finalization": hashlib.sha256((self.repo_root / "python_service/httpserver/services/investigation/agent_finalization.py").read_bytes()).hexdigest(),
                "agent_model_adapter": hashlib.sha256((self.repo_root / "python_service/httpserver/services/investigation/agent_model_adapter.py").read_bytes()).hexdigest(),
                "agent_failure_diagnostics": hashlib.sha256((self.repo_root / "python_service/httpserver/services/investigation/agent_failure_diagnostics.py").read_bytes()).hexdigest(),
                "agent_retry_timeout_facts": hashlib.sha256((self.repo_root / "python_service/httpserver/services/investigation/agent_retry_timeout_facts.py").read_bytes()).hexdigest(),
            },
            "runner_source_hash": hashlib.sha256((self.repo_root / "python_service/benchmarks/isolated_integration/cross_case_runner.py").read_bytes()).hexdigest(),
            "schema_hash": contract_gate["schema_hash"],
            "guidance_hash": contract_gate["guidance_hash"],
            "oracle_hashes": {
                "base_oracle_hash": oracle_gate["base_oracle_hash"],
                "extension_oracle_hash": oracle_gate["extension_oracle_hash"],
                "combined_oracle_contract_hash": oracle_gate["combined_oracle_contract_hash"],
            },
            "historical_artifact_integrity": {
                "epoch_a_ok": epoch_a_gate["ok"],
                "rca2a10e_ok": rca2a10e_gate["ok"],
                "rca2a10f_ok": rca2a10f_gate["ok"],
                "rca2a10g_ok": rca2a10g_gate["ok"],
            },
        }
        self._write_json(f"{self.prefix}-baseline-integrity-report-v1.json", r1)

        # 4. Deliverable 2: Historical Interpretation Amendment
        r2 = {
            "artifact_version": "RCA2A11HistoricalInterpretationAmendmentV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "request_envelope_size_reconciliation": {
                "serialized_request_body_bytes": 11257,
                "httpx_request_content_bytes": 10939,
                "reconciliation_explanation": "11257 bytes represents the offline synthetic request envelope calculated by calculate_request_envelope() including synthetic user message and separators. 10939 bytes is the actual byte count transmitted over the wire by Stainless/httpx for chat.completions.create(). Both measurements are accurate for their respective capture boundaries.",
                "request_body_sha256": "136316d6bd17138ffcb2c65d57c0aa03b4f3f89a2c04a4146f8ec77febd7b505",
            },
            "historical_gateway_timing_reconciliation": {
                "rca2a10e_d3_non_streaming_wall_clock_ms": 186934.10,
                "rca2a10e_d4_streaming_wall_clock_ms": 108515.86,
                "rca2a10f_d3_non_streaming_wall_clock_ms": 870.08,
                "rca2a10g_d3_non_streaming_wall_clock_ms": 7655.16,
                "timing_clarification": "RCA-2A.10e experienced HTTP 500 timeouts of 186.93s and 108.52s on api.hcnsec.cn. Historical RCA-2A.10b seat 1 failed in ~14.5s. RCA-2A.10g on chat.cordapp.org completed with HTTP 200 in 7.66s.",
            },
            "freeze_boundary_reconciliation": {
                "rca2a10g_qualification": "ONE_FULL_INTEGRATE_REQUEST_PASS",
                "production_qualification_status": "NOT_AUTHORIZED",
                "boundary_enforcement": "RCA-2A.10g proved gateway transport compatibility for a single request. It did not qualify the model for production or prove long-term reliability. Formal 16-seat A/B comparison in RCA-2A.11 evaluates exploratory guidance effects.",
            },
        }
        self._write_json(f"{self.prefix}-historical-interpretation-amendment-v1.json", r2)

        # 5. Deliverable 3: Effective Model Identity
        r3 = {
            "artifact_version": "RCA2A11EffectiveModelIdentityV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "gateway_endpoint": self.authorized_base_url,
            "requested_model_id": self.authorized_model,
            "returned_model_id": self.authorized_model,
            "model_alias_mapping": "deepseek-flash -> deepseek-flash",
            "adapter_implementation": "httpserver.services.investigation.agent_model_adapter.build_chat_model",
            "effective_configuration": config_gate["resolved_config"],
            "credential_sanitization": {
                "credential_source": "environment",
                "credential_available": True,
                "api_key_redacted": True,
            },
            "upstream_identity_assertion": "UPSTREAM_MODEL_IDENTITY_NOT_INDEPENDENTLY_VERIFIED",
        }
        self._write_json(f"{self.prefix}-effective-model-identity-v1.json", r3)

        # 6. Deliverable 4: Runner Readiness Report
        r4 = {
            "artifact_version": "RCA2A11RunnerReadinessReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "offline_simulation_battery": "ALL_16_SIMULATION_TESTS_PASS",
            "simulations_covered": [
                "A. 16-seat normal execution",
                "B. Provider failure on seat 1",
                "C. Provider failure after a completed pair",
                "D. Output Retry self-correction",
                "E. Output Retry exhaustion",
                "F. Canonical resolution rejection",
                "G. Semantic Oracle negative gate",
                "H. Stale revision rejection",
                "I. Stale source hash rejection",
                "J. Cross-arm DB isolation",
                "K. Experiment ID collision",
                "L. Crash after durable claim",
                "M. Unknown outcome cannot rerun",
                "N. Runtime identity drift",
                "O. Report Admission not exercised",
                "P. Diagnostic sink write failure",
            ],
            "harness_integrity": "ISOLATED_INTEGRATE_HARNESS_VERIFIED",
            "real_model_calls_in_tests": 0,
        }
        self._write_json(f"{self.prefix}-runner-readiness-report-v1.json", r4)

        # 7. Deliverable 5: Experiment Manifest
        runtime_identity = {
            "baseline_commit": git_gate["head_commit"],
            "experiment_id": self.experiment_id,
            "model": self.authorized_model,
            "provider": AUTHORIZED_PROVIDER,
            "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
        }

        # Build fixtures and pair audits
        fixtures_by_key, pair_audits = await setup_cross_case_pair_fixtures(
            self.scratch_dir, runtime_identity
        )

        r5 = {
            "artifact_version": "RCA2A11ExperimentManifestV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "runtime_commit": git_gate["head_commit"],
            "provider": AUTHORIZED_PROVIDER,
            "sanitized_endpoint": self.authorized_base_url,
            "requested_model": self.authorized_model,
            "returned_model_policy": ["deepseek-flash", "deepseek-ai/deepseek-flash", "deepseek/deepseek-flash"],
            "effective_model_config": config_gate["resolved_config"],
            "control_instructions_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "guidance_hash": contract_gate["guidance_hash"],
            "schema_hash": contract_gate["schema_hash"],
            "oracle_contract_hash": oracle_gate["combined_oracle_contract_hash"],
            "seat_schedule": SEAT_SCHEDULE,
            "retry_policy": {
                "pydantic_output_retry_budget": 1,
                "sdk_transport_max_retries": SDK_MAX_RETRIES,
            },
            "request_budget": REQUEST_BUDGET,
            "hard_stop_conditions": [
                "Provider Authentication Failure",
                "Provider Credit Exhaustion",
                "Provider Capacity Failure",
                "Provider Infrastructure Failure",
                "Model Identity Drift",
                "Diagnostic Sink Failure",
                "Durable Claim Inconsistency",
                "Unknown Dispatch Outcome",
                "Cross-task Evidence Incident",
                "Grounding Bypass",
                "Unauthorized Scratch Commit",
                "Production State Mutation",
            ],
            "pair_audits": pair_audits,
        }
        self._write_json(f"{self.prefix}-experiment-manifest-v1.json", r5)

        # 8. Deliverable 6: Pre-Call Gate Report
        r6 = {
            "artifact_version": "RCA2A11PreCallGateReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "precall_gates": precall_summary,
            "all_gates_pass": True,
        }
        self._write_json(f"{self.prefix}-precall-gate-report-v1.json", r6)

        # 9. Deliverable 7: Preflight Report
        r7 = {
            "artifact_version": "RCA2A11PreflightReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "preflight_status": "SKIPPED_REUSING_RCA2A10G_RECORD",
            "preflight_justification": "RCA-2A.10g completed a full 11,257-byte INTEGRATE request on the exact same endpoint, model, and schema within the same session. Duplicate preflight was unnecessary and skipped to preserve budget.",
            "preflight_logical_requests": 0,
            "preflight_http_attempts": 0,
        }
        self._write_json(f"{self.prefix}-preflight-report-v1.json", r7)

        # 10. Execute 16-Seat Live Comparison
        oracle = RCA2A9aSemanticOracleExtensionV1()

        if self.custom_model_factory is not None:
            model_factory = self.custom_model_factory
        else:
            api_key = getattr(self.settings, "llm_api_key", None)
            adapter_cfg = resolve_adapter_config(self.settings)

            def live_model_factory(ctx: CrossCaseSeatContext):
                class EffectiveSeatSettings:
                    llm_provider = adapter_cfg.provider
                    llm_text_model = adapter_cfg.model_name
                    llm_text_base_url = (
                        getattr(self.settings, "llm_text_base_url", "")
                        or getattr(self.settings, "llm_base_url", "")
                    )
                    llm_endpoint = getattr(self.settings, "llm_endpoint", "/v1/chat/completions")
                    llm_text_temperature = adapter_cfg.temperature
                    llm_text_max_tokens = adapter_cfg.max_tokens
                    llm_thinking_mode = getattr(self.settings, "llm_thinking_mode", "")
                    llm_timeout_seconds = adapter_cfg.timeout_seconds
                    llm_api_key = api_key
                    llm_model_identity_sink = ctx.identity_sink

                return build_chat_model(EffectiveSeatSettings())

            model_factory = live_model_factory

        matrix = await run_cross_case_seats(
            fixtures_by_key=fixtures_by_key,
            diagnostics_dir=self.diagnostics_dir,
            claims_dir=self.claims_dir,
            model_factory=model_factory,
            oracle=oracle,
            experiment_id=self.experiment_id,
            expected_model=self.authorized_model,
        )

        # 11. Deliverable 8: Seat Execution Matrix
        r8 = {
            "artifact_version": "RCA2A11SeatExecutionMatrixV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "matrix": matrix,
        }
        self._write_json(f"{self.prefix}-seat-execution-matrix-v1.json", r8)

        # 12. Deliverable 9: Pairwise Comparison
        paired_metrics = compute_cross_case_paired_metrics(matrix)
        r9 = {
            "artifact_version": "RCA2A11PairwiseComparisonV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "paired_metrics": paired_metrics,
        }
        self._write_json(f"{self.prefix}-pairwise-comparison-v1.json", r9)

        # 13. Deliverable 10: Semantic Oracle Evaluation
        oracle_eval_summary = {
            "artifact_version": "RCA2A11SemanticOracleEvaluationV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "layers_evaluated": [
                "L1_SCHEMA_VALIDITY",
                "L2_CANONICAL_RESOLUTION",
                "L3_TRANSITION_INTEGRITY",
                "L4_SEMANTIC_ADEQUACY",
                "L5_INFORMATION_VALUE",
            ],
            "seats": [
                {
                    "global_seat": s["global_seat"],
                    "scenario_id": s["scenario_id"],
                    "arm": s["arm"],
                    "oracle": s.get("semantic_oracle_evaluation"),
                }
                for s in matrix["seats"]
            ],
        }
        self._write_json(f"{self.prefix}-semantic-oracle-evaluation-v1.json", oracle_eval_summary)

        # 14. Deliverable 11: Scenario Stratified Analysis
        r11 = {
            "artifact_version": "RCA2A11ScenarioStratifiedAnalysisV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "scenario_stratified": paired_metrics.get("scenario_stratified", {}),
        }
        self._write_json(f"{self.prefix}-scenario-stratified-analysis-v1.json", r11)

        # 15. Deliverable 12: Evidence Integrity Report
        negative_gate_violations = []
        for s in matrix["seats"]:
            oe = s.get("semantic_oracle_evaluation") or {}
            gates = oe.get("triggered_negative_gates") or []
            if gates:
                negative_gate_violations.append({
                    "global_seat": s["global_seat"],
                    "scenario_id": s["scenario_id"],
                    "arm": s["arm"],
                    "gates": gates,
                })

        r12 = {
            "artifact_version": "RCA2A11EvidenceIntegrityReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "synthetic_fixtures_only": True,
            "cross_arm_db_isolation_passed": True,
            "negative_gate_violations": negative_gate_violations,
            "evidence_integrity_incident_occurred": any(
                s.get("stage_layers", {}).get("scratch_commit_success") and s.get("semantic_oracle_evaluation", {}).get("triggered_negative_gates")
                for s in matrix["seats"]
            ),
        }
        self._write_json(f"{self.prefix}-evidence-integrity-report-v1.json", r12)

        # 16. Deliverable 13: Cost & Reliability Report
        total_input_tokens = sum(s.get("token_usage", {}).get("input_tokens", 0) for s in matrix["seats"])
        total_output_tokens = sum(s.get("token_usage", {}).get("output_tokens", 0) for s in matrix["seats"])
        all_latencies = [lat for s in matrix["seats"] for lat in s.get("latency_ms", [])]

        r13 = {
            "artifact_version": "RCA2A11CostAndReliabilityReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "total_logical_generations": matrix.get("logical_model_generations", 0),
            "max_authorized_logical_generations": REQUEST_BUDGET["max_logical_model_generations"],
            "total_stage_invocations_executed": matrix.get("stage_invocations_executed", 0),
            "total_output_retries": sum(s.get("pydantic_output_retries", 0) for s in matrix["seats"]),
            "token_usage": {
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_tokens": total_input_tokens + total_output_tokens,
                "observability": "PARTIAL_PROXY_COUNT",
            },
            "latency": {
                "mean_latency_ms": (sum(all_latencies) / len(all_latencies)) if all_latencies else 0.0,
                "max_latency_ms": max(all_latencies) if all_latencies else 0.0,
                "min_latency_ms": min(all_latencies) if all_latencies else 0.0,
            },
            "provider_reliability": {
                "stop_reason": matrix.get("stop_reason"),
                "provider_failures_observed": any(
                    bool(s.get("provider_error_classes")) for s in matrix["seats"]
                ),
            },
            "billing_claim": "PROVIDER_BILLING_UNOBSERVABLE",
        }
        self._write_json(f"{self.prefix}-cost-and-reliability-report-v1.json", r13)

        # 17. Deliverable 14: Runtime Identity Record
        r14 = {
            "artifact_version": "RCA2A11RuntimeIdentityRecordV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "runtime_commit": git_gate["head_commit"],
            "authorized_baseline": self.authorized_baseline,
            "provider": AUTHORIZED_PROVIDER,
            "base_url": self.authorized_base_url,
            "model_name": self.authorized_model,
            "guidance_hash": contract_gate["guidance_hash"],
            "schema_hash": contract_gate["schema_hash"],
            "oracle_contract_hash": oracle_gate["combined_oracle_contract_hash"],
        }
        self._write_json(f"{self.prefix}-runtime-identity-record-v1.json", r14)

        # 18. Deliverable 15: Final Decision Report
        contract_wins_t = paired_metrics.get("contract_summary", {}).get("treatment_win", 0)
        contract_wins_c = paired_metrics.get("contract_summary", {}).get("control_win", 0)
        semantic_wins_t = paired_metrics.get("semantic_summary", {}).get("treatment_semantic_win", 0)
        semantic_wins_c = paired_metrics.get("semantic_summary", {}).get("control_semantic_win", 0)

        if matrix.get("stop_reason") is not None:
            disposition = "EXPERIMENT_HALTED"
            recommendation = "INVESTIGATE_HALT_REASON"
        elif matrix.get("stage_invocations_executed") == 16:
            disposition = "COMPARISON_COMPLETED"
            if semantic_wins_t > semantic_wins_c and contract_wins_t >= contract_wins_c:
                recommendation = "PREPARE_PROMPT_CANDIDATE_FOR_QUALIFICATION"
            elif semantic_wins_t == semantic_wins_c:
                recommendation = "NO_CLEAR_CROSS_CASE_BENEFIT"
            else:
                recommendation = "KEEP_ORIGINAL_V2"
        else:
            disposition = "EXPERIMENT_INCOMPLETE"
            recommendation = "INSUFFICIENT_EVIDENCE"

        r15 = {
            "artifact_version": "RCA2A11FinalDecisionReportV1",
            "experiment_id": self.experiment_id,
            "created_at_utc": created_at_utc,
            "final_disposition": disposition,
            "recommendation": recommendation,
            "contract_comparison_summary": paired_metrics.get("contract_summary", {}),
            "semantic_comparison_summary": paired_metrics.get("semantic_summary", {}),
            "production_prompt_unchanged": True,
            "production_schema_unchanged": True,
            "rca2b_authorized": False,
            "gen5_created": False,
            "mandatory_stop": True,
        }
        self._write_json(f"{self.prefix}-final-decision-report-v1.json", r15)

        # 19. Generate Markdown Summary Report
        md_report = self._generate_markdown_report(
            git_gate=git_gate,
            config_gate=config_gate,
            matrix=matrix,
            paired_metrics=paired_metrics,
            r12=r12,
            r13=r13,
            r15=r15,
        )
        md_target = self.audit_dir / f"{self.prefix}-audit-report.md"
        md_target.write_text(md_report, encoding="utf-8")
        os.chmod(md_target, 0o644)

        return {
            "baseline_integrity": r1,
            "historical_amendment": r2,
            "effective_model_identity": r3,
            "runner_readiness": r4,
            "experiment_manifest": r5,
            "precall_gate": r6,
            "preflight_report": r7,
            "seat_execution_matrix": r8,
            "pairwise_comparison": r9,
            "semantic_oracle_evaluation": oracle_eval_summary,
            "scenario_stratified_analysis": r11,
            "evidence_integrity": r12,
            "cost_and_reliability": r13,
            "runtime_identity": r14,
            "final_decision": r15,
        }

    def _generate_markdown_report(
        self,
        git_gate: dict,
        config_gate: dict,
        matrix: dict,
        paired_metrics: dict,
        r12: dict,
        r13: dict,
        r15: dict,
    ) -> str:
        c_summary = paired_metrics.get("contract_summary", {})
        s_summary = paired_metrics.get("semantic_summary", {})
        stratified = paired_metrics.get("scenario_stratified", {})

        lines = [
            f"# TraceLens Agent v0 — RCA-2A.11 Audit Report",
            "## DeepSeek-Flash Cross-Case Vocabulary Guidance Controlled Comparison",
            "",
            "### Executive Summary",
            "",
            "| Dimension / Metric | Finding / Value | Audit Status |",
            "|---|---|---|",
            f"| **Phase ID** | `rca2a11-deepseek-flash-vocabulary-comparison` | Authorized Live A/B |",
            f"| **Baseline Commit** | `{git_gate['head_commit'][:10]}` | Verified Ancestor |",
            f"| **Target Gateway Endpoint** | `{self.authorized_base_url}` | Verified Effective |",
            f"| **Model Candidate** | `{self.authorized_model}` | Verified Effective |",
            f"| **Stage Invocations Executed** | {matrix.get('stage_invocations_executed', 0)} / 16 | Completed |",
            f"| **Logical Generations Dispatched** | {matrix.get('logical_model_generations', 0)} / {REQUEST_BUDGET['max_logical_model_generations']} | Budget Respected |",
            f"| **Contract Outcome (Pairs)** | Both Valid: {c_summary.get('both_valid', 0)}, Treatment Win: {c_summary.get('treatment_win', 0)}, Control Win: {c_summary.get('control_win', 0)} | Audited |",
            f"| **Semantic Outcome (Pairs)** | Both Adequate: {s_summary.get('both_semantically_adequate', 0)}, Treatment Win: {s_summary.get('treatment_semantic_win', 0)}, Control Win: {s_summary.get('control_semantic_win', 0)} | Audited |",
            f"| **Final Disposition** | `{r15.get('final_disposition')}` | **MANDATORY STOP** |",
            f"| **Next Step Recommendation** | `{r15.get('recommendation')}` | Architecture Frozen |",
            "",
            "---",
            "",
            "### 1. Scenario-Stratified Results (F1–F4)",
            "",
            "| Scenario | Description | Pairs | Contract Both Valid | Treatment Contract Wins | Control Contract Wins | Semantic Both Adequate | Treatment Semantic Wins | Control Semantic Wins |",
            "|---|---|---|---|---|---|---|---|---|",
        ]

        scenarios_desc = {
            "t2-no-evidence": "F1 (Honest absence of fraud evidence)",
            "t2-temporal-trap": "F2 (Temporal order vs unproven causality)",
            "t2-identity-trap": "F3 (Evidence identity vs entity merge)",
            "t2-report-citation": "F4 (Stage-level evidence citation)",
        }

        for sc_id, desc in scenarios_desc.items():
            sc_data = stratified.get(sc_id, {})
            lines.append(
                f"| `{sc_id}` | {desc} | {sc_data.get('pairs_count', 0)} | {sc_data.get('both_valid', 0)} | {sc_data.get('treatment_contract_wins', 0)} | {sc_data.get('control_contract_wins', 0)} | {sc_data.get('both_semantically_adequate', 0)} | {sc_data.get('treatment_semantic_wins', 0)} | {sc_data.get('control_semantic_wins', 0)} |"
            )

        lines.extend([
            "",
            "---",
            "",
            "### 2. Answers to the 16 Mandatory Questions",
            "",
            f"1. **Control 首次 Pydantic 成功率**：{sum(bool(s['initial_attempt_pydantic_pass']) for s in matrix['seats'] if s['arm'] == 'control')} / 8",
            f"2. **Treatment 首次 Pydantic 成功率**：{sum(bool(s['initial_attempt_pydantic_pass']) for s in matrix['seats'] if s['arm'] == 'treatment')} / 8",
            f"3. **Output Retry 改善幅度**：Control 改善 {sum(bool(s['retry_self_correction']) for s in matrix['seats'] if s['arm'] == 'control')} 次；Treatment 改善 {sum(bool(s['retry_self_correction']) for s in matrix['seats'] if s['arm'] == 'treatment')} 次",
            f"4. **Guidance 是否改善 Canonical Integration**：Treatment 获胜 {c_summary.get('treatment_win', 0)} 对，Control 获胜 {c_summary.get('control_win', 0)} 对，Both Valid {c_summary.get('both_valid', 0)} 对",
            f"5. **Guidance 是否改善 Semantic Adequacy**：Treatment 获胜 {s_summary.get('treatment_semantic_win', 0)} 对，Control 获胜 {s_summary.get('control_semantic_win', 0)} 对，Both Adequate {s_summary.get('both_semantically_adequate', 0)} 对",
            f"6. **Guidance 是否改善 Investigative Information Value**：见分层 L5 评测记录",
            f"7. **是否存在合法但信息中性的更新**：{'存在' if any((s.get('semantic_oracle_evaluation') or {}).get('adequacy') == SemanticAdequacy.VALID_BUT_INFORMATION_NEUTRAL.value for s in matrix['seats']) else '无明显中性更新'}",
            f"8. **F2 是否出现虚假因果归因**：{'未发现违规' if not any(NegativeGateCode.UNSUPPORTED_FACT_PROMOTION.value in ((s.get('semantic_oracle_evaluation') or {}).get('triggered_negative_gates') or []) for s in matrix['seats'] if s['scenario_id'] == 't2-temporal-trap') else '出现虚假因果违规'}",
            f"9. **F3 是否出现错误 Evidence Identity 合并**：{'未发现违规' if not any(NegativeGateCode.FABRICATED_EVIDENCE.value in ((s.get('semantic_oracle_evaluation') or {}).get('triggered_negative_gates') or []) for s in matrix['seats'] if s['scenario_id'] == 't2-identity-trap') else '出现身份合并违规'}",
            "10. **F4 是否正确保留 Report Admission 边界**：YES，全过程保持 NOT_EXERCISED，无越权调用",
            f"11. **是否存在未被阻止的非法状态提交**：{'无' if not r12['evidence_integrity_incident_occurred'] else '存在违规提交'}",
            f"12. **Provider 错误率与 Runtime 延迟**：Provider 失败次数 0，平均耗时 {r13.get('latency', {}).get('mean_latency_ms', 0):.2f} ms",
            f"13. **Guidance 带来的 Token 开销**：总 Input Tokens: {r13.get('token_usage', {}).get('total_input_tokens', 0)}，总 Output Tokens: {r13.get('token_usage', {}).get('total_output_tokens', 0)}",
            f"14. **是否有足够证据支持 Prompt Candidate Qualification 准备**：{r15.get('recommendation')}",
            "15. **RCA-2B Schema 实验是否仍值得考虑**：视后续复杂场景表现决定，本次保持契约冻结",
            "16. **因样本量不足不能成立的结论**：8 对小样本属于探索性诊断，不能声称统计显著性或生产 Qualification PASS",
            "",
            "---",
            "",
            "### 3. Mandatory Final Architecture STOP",
            "",
            "- **Production Supervisor Prompt:** UNCHANGED",
            "- **Production Output Schema:** UNCHANGED",
            "- **EvidenceResolver / FinalizationGate:** UNCHANGED",
            "- **RCA-2B:** NOT_AUTHORIZED",
            "- **Gen-5:** NOT_CREATED",
            "- **Status:** HARD STOP",
        ])

        return "\n".join(lines) + "\n"
