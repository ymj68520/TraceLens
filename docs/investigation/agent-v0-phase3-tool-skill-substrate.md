# TraceLens Agent v0 — Phase 3: PydanticAI + Read-only Tool/Skill Substrate

Status: implemented on `mvp/agent-v0-phase3-tool-skill-substrate`.

## 1. Baseline / Branch / Commits

- P2 frozen baseline: `909504f3a1c1f68f096bdbdc47b33302f73c3785`
- Branch: `mvp/agent-v0-phase3-tool-skill-substrate` (created from the P2 frozen HEAD, verified by preflight)
- Commits:
  - `b0933cb3` — `feat: add pydantic agent runtime adapter` (P3-1)
  - `c5d585a9` — `feat: add forensic read-only tool registry` (P3-2)
  - `3a26e174` — `feat: add agent capability and skill resolution` (P3-3)
  - `815398b3` — `feat: add specialist context assembly` (context pack, bridge completion, docs, regression gate)
  - (freeze follow-up) — `fix: align agent tool audit pipeline with frozen contract` (F1 pipeline order, F2 observation+trajectory atomic pair + schema v10, D1/D2 doc corrections)

## 2. PydanticAI dependency decision

- Pinned: `pydantic-ai-slim[openai]==2.30.0` in `python_service/requirements.txt` (exact pin, not a range).
- Version selection: 2.30.0 is the newest release whose `[openai]` extra accepts the already-installed `openai 2.46.0` and whose core accepts installed `pydantic 2.13.4` / `httpx 0.28.1`. 2.35.x forces `openai>=3.0.0`; 2.40.0+ makes `httpx2` a hard core dependency — both would force upgrades of the existing runtime (§61 forbids). Python 3.12.3.
- Transitive additions (all additive, none replace existing pins): `pydantic-graph==2.30.0` (hard internal pin of pydantic-ai-slim itself — unavoidable, not a workflow-ecosystem adoption), `opentelemetry-api`, `genai-prices`, `griffelib`, `logfire-api` (API-only shim, not the Logfire service), `tiktoken`, `httpx2`/`httpcore2`, `truststore`, `regex`.
- `pip check`: green after install. FastAPI/Pydantic/httpx/OpenAI SDK versions unchanged.
- Opt-in provider smoke (`TRACELENS_AGENT_PROVIDER_SMOKE=1`, excluded from the default gate): the opt-in request reached the configured DeepSeek provider and received a provider-level `402 Insufficient Balance` response. This confirms that the adapter reached the configured endpoint and the request progressed to provider-side handling. It does NOT validate successful generation — billing prevented completion. Model semantics, structured output and tool calling on the real provider remain unverified until the account regains balance and the opt-in smoke is rerun. The default freeze gate does not depend on any real provider.

## 3. Repository facts the design rests on

- LLM config: `httpserver/config.py` `Settings` — `LLM_ENDPOINT` is stored as a *path* (`/v1/chat/completions`), resolved against `LLM_TEXT_BASE_URL`/`LLM_VISION_BASE_URL`; `LLM_THINKING_MODE` produces the DeepSeek `thinking` body quirk (`Settings.llm_thinking_body`). httpserver calls raw httpx (OpenAI-compatible Chat Completions); the OpenAI SDK 2.x exists for Graphiti.
- Evidence reads: canonical task-scoped resolver `services/evidence/` (`parse_evidence_key`, `file:`/`cluster:v1:` key grammar); legacy richer resolver facade `InvestigationService.resolve_evidence` (read-only, bounded content previews); `InvestigationReadService.list_evidence`; `SecondaryAnalysisExecutor.list_analyses/list_all_analyses`; `effective_event_claims` on the legacy facade. `evidence_detail()` is NOT used by tools because it triggers first-write-wins snapshot capture (a write).
- Platform identity: task metadata `scenarios` (`android|windows|linux|server_cloud`) and `scenario_databases` (platform → trusted DB path); platform artifact tables are deterministic content (sqlite_master) — same pattern as `intelligence_report._detect_platforms`. Platform readers `graphiti_integration/database_reader/{windows,linux,android}_reader.py` are safe typed facades (fixed per-artifact methods, limit/offset pagination, typed records).
- P1 `agent_tool_observations` (INSERT-only, canonical JSON payload) is sufficient for normalized observation payloads. The P3 freeze follow-up added the **minimal v9 → v10 migration**: `agent_trajectory_events.event_type` CHECK gains exactly one value (`tool_observation_recorded`) so the tool action lands in the Action Trace as the frozen architecture requires. `SUPPORTED_SCHEMA_VERSION = 10`; nothing else in the schema changes.

## 4. Added (modules)

```
httpserver/services/investigation/
    agent_model_adapter.py        PydanticAI thin model adapter
    agent_deps.py                 ForensicAgentDeps
    agent_capabilities.py         ArtifactFamily registry + SourceCapabilityManifest
    agent_profiles.py             SourceSpecialistProfile + starter profiles
    agent_skills.py               SkillDefinition + starter catalog
    agent_skill_resolver.py       deterministic SkillResolver
    agent_context.py              SpecialistContextPack + ContextAssembler
    agent_tools/
        definitions.py            ForensicToolDefinition (+schema hash, schema audit)
        context.py                ForensicToolContext / ToolBudgetPolicy / AgentTimeScope
        errors.py                 ToolErrorCode / ToolExecutionError (stable codes)
        registry.py               ForensicToolRegistry (execution pipeline authority)
        observations.py           ToolObservationRecord + sinks + fingerprints
        visibility.py             reconstruct_allowed_evidence_ids
        pydantic_bridge.py        ForensicToolset + build_pydantic_toolset + build_specialist_agent
        adapters/                 10 read-only tools over trusted facades
```

Tests: `tests/unit/investigation/test_agent_pydantic_adapter.py` (19), `test_agent_tool_registry.py` (16), `test_agent_tool_adapters.py` (16), `test_agent_tool_visibility.py` (7), `test_agent_tool_pipeline_order.py` (5), `test_agent_tool_audit_atomicity.py` (7), `test_agent_schema_v10_migration.py` (6), `test_agent_capabilities_skills.py` (23), `test_agent_context_assembly.py` (14), `test_agent_provider_smoke.py` (opt-in only).

## 5. Modified

- `python_service/requirements.txt` — pinned dependency block (only existing-file change; no P1/P2 code was touched).

## 5b. Calibration status of numeric knobs (freeze follow-up)

All numeric thresholds are **provisional runtime defaults, configurable, not architecture-frozen, subject to P8 benchmark calibration**: `ToolBudgetPolicy.max_duplicate_calls` (default 2), `ToolBudgetPolicy.max_observations_per_run` (default 200), `ToolCatalogConfig` page sizes/bounds, `SkillResolverPolicy` breadth limits. None of these numbers is a normative Agent Architecture v0 limit; inject an explicit policy/config where a deployment needs different values.

## 6. Reused (no reimplementation)

- Config: `Settings` attributes only (`llm_text_base_url`, `llm_endpoint`, `llm_api_key`, `llm_text_model`, `llm_thinking_body`, `llm_timeout_seconds`, `llm_text_temperature`, `llm_text_max_tokens`). No second env namespace, no `.env` reader in agent code.
- Evidence key grammar/resolver: `services/evidence/keys.py`, `InvestigationService.resolve_evidence`, `InvestigationReadService`, `SecondaryAnalysisExecutor`, `effective_event_claims`, `CppBackendService.get_task/get_task_files_paginated/get_task_events`, `make_file_evidence_key/make_cluster_key`.
- Platform readers: `WindowsDatabase/LinuxDatabase/AndroidDatabase` (typed methods) behind `query_platform_artifacts`.
- Persistence: P1 `append_tool_observation`/`list_tool_observations` (unchanged schema).
- Hash helpers: P1 `canonical_state_json`/`state_hash_of`.

## 7. Model adapter contract

`resolve_adapter_config(settings) -> ModelAdapterConfig` (normalized, secret-free); `derive_openai_base_url(base_url, endpoint_path)` translates the path-style endpoint to the OpenAI SDK base_url (`https://api.deepseek.com` + `/v1/chat/completions` → `.../v1`); `build_chat_model(settings, *, model_name=None) -> OpenAIChatModel` — fail-closed (`ModelAdapterError`) on empty/invalid config; performs no network I/O. Provider quirks centralized in one `OpenAIModelProfile`: `supports_json_schema_output=False` (DeepSeek 400s json_schema), `supports_json_object_output=True`, strict tool definitions off, `max_completion_tokens` off, single system message. `LLM_THINKING_MODE` rides `extra_body` (`{"thinking": {"type": ...}}`), mirroring `llm_service.py`. Empty API key → `"EMPTY"` sentinel (mirrors "no auth header" semantics for local endpoints; no secret copies anywhere, verified by repr tests).

## 8. Tool Registry contract

Execution pipeline (frozen contract order, pinned by `test_agent_tool_pipeline_order.py` via a spy subclass — not inferred from error codes):

1. resolve tool
2. permission — `access=read`, `allowed_tool_ids`, `allowed_agent_types` (the registry re-checks on every call; bridge visibility is never the boundary)
3. scope validation — minimal deterministic pre-check on the raw mapping: extract the declared `source_scope_id` discriminator and validate against the run's source-scope grant, BEFORE full domain input acceptance
4. input schema validation (`extra="forbid"` input models)
5. budget / duplicate policy — per-run observation cap, then the duplicate fingerprint guard
6. domain adapter
7. output normalization (must be `ToolExecutionOutcome` with the declared output model)
8. Evidence-ref validation (parse fail = `EVIDENCE_REF_INVALID`; injected validator fail = `EVIDENCE_REF_CROSS_TASK`; failures persist nothing)
9. ToolObservation persistence
10. Trajectory append (`tool_observation_recorded`) — steps 9+10 run as ONE atomic repository transaction
11. compact model-facing result (large payloads elided; full payload stays in the observation)

A rejected step consumes no downstream state: no budget, no duplicate fingerprint, no adapter call, no persistence.

Structured error codes: `TOOL_NOT_FOUND, TOOL_NOT_ALLOWED, TOOL_AGENT_NOT_ALLOWED, TOOL_SCOPE_DENIED, TOOL_INPUT_INVALID, TOOL_BUDGET_EXCEEDED, TOOL_DUPLICATE_CALL, TOOL_ADAPTER_FAILED, EVIDENCE_REF_INVALID, EVIDENCE_REF_CROSS_TASK, TOOL_RESULT_INVALID`. Messages never contain DB paths, stack traces or secrets (adapter exceptions are normalized to `TOOL_ADAPTER_FAILED` with only the exception type). `ForensicToolRegistry.schema_hash()` is deterministic over the whole catalog (tool_id/version/per-tool schema_hash); `REGISTRY_VERSION = "forensic-tool-registry:v1"`.

## 9. Initial read-only tool catalog (10 tools, all `access=read`)

`get_task_context`, `search_evidence`, `get_evidence`, `find_related_evidence`, `search_files`, `search_timeline`, `find_temporal_neighbors`, `get_existing_analyses`, `get_existing_claims`, `query_platform_artifacts`. Every input schema is auto-audited at registration for forbidden fields (`task_id`, `investigation_id`, `run_id`, `db_path`, `sql`, …); task/run identity is injected from the trusted `ForensicToolContext` only. No SQL/filesystem/Graphiti tools exist; Graph tools are P6. `search_timeline`/`find_temporal_neighbors` hand out server-derived `cluster:v1` keys — the model never constructs cluster keys.

## 10. Tool Observation / Evidence visibility

Normalized `ToolObservationRecord` (`tool-observation:v1`): tool id/version/schema hash, summary, data, entity_refs (empty in P3 — canonical entities are P5), warnings, limitations, result_count, truncated, continuation, pagination, input fingerprint, context hash. Storage: `agent_tool_observations` via `AgentObservationSink`, which calls the new atomic repository primitive `AgentRuntimeRepository.record_tool_observation(...)` — one `BEGIN IMMEDIATE` transaction inserting the observation row AND the `tool_observation_recorded` trajectory action event. The invariant: a successful tool action leaves both records or neither (a failed trajectory insert rolls the observation back, and vice versa; failure-injection tests cover both directions).

Observation and trajectory have distinct duties and never substitute for each other:
- ToolObservation = what the tool returned (summary, data, evidence refs)
- Trajectory = what the investigation runtime did (action audit)

The trajectory payload carries pointers and counts only — `observation_id, tool_id, tool_version, tool_schema_hash, run_id, delegation_id, input_fingerprint, context_hash, evidence_ref_count, result_count, truncated, warning_count, limitation_count` — never a copy of the observation `data`, Evidence bodies, secrets, DB paths or model-private reasoning.

Visibility (`visibility.py`): `reconstruct_allowed_evidence_ids(initial_context_refs, observations, *, delegation_id|run_id)` rebuilds one delegation's `allowed_evidence_ids` purely from durable records — ContextPack initial refs ∪ successful observation refs. Failed executions persist nothing and add no visibility; invalid refs are rejected pre-persistence; summary/data text never enters the set; Case Context stays `context_only`. Reconstruction is restart-safe (fresh repository objects re-derive identical sets).

## 11. ArtifactFamily registry

`ArtifactFamilyRegistry` (`artifact-family-registry:v1`) — 20 families bound 1:1 to real reader coverage (7 windows, 9 android incl. wechat/qq/telegram message exports, 4 linux; counted directly from `agent_capabilities.default_family_catalog` and pinned by `test_family_catalog_count_and_platform_breakdown`). Each family carries `required_tables` (parser-output presence), `reader_method`/`reader_kwargs` (typed facade binding), `supported_filters` (`text_contains` server-side), and first-class `limitations`. No family is invented beyond existing parser/reader coverage.

## 12. SourceCapabilityManifest

`build_source_capability_manifest(task, source_scope_id, family_registry, *, table_lister)` — deterministic; sources: task metadata (scenarios, scenario_databases), parser outputs (artifact tables present via read-only sqlite_master listing), registered family catalog. Availability: scenario absent → `not_applicable`; platform DB missing → `unavailable(platform_database_missing)`; no backing table → `unavailable(artifact_tables_absent)`; strict-conjunction families partially present → `partial`; else `available`. `input_hash` covers everything except the audit-only `generated_at`. The manifest proves capability (un)availability only — never case facts. Registry hash stable across instantiations.

## 13. Profiles

`windows.specialist` / `android.specialist` / `linux.specialist` (linux binds `server_cloud` too), each thin: mission, supported source types, default tool ids (all exist in the registry — validated at wiring), skill ids (all exist in the skill registry), long-lived interpretation rules and limitations. **No memory profile**: memory images have no deterministic task-level platform key in this repo, and faking one is prohibited. `resolve_profile_for_source` fails deterministically (`KeyError`) for unknown sources.

## 14. Starter Skill catalog

13 skills (6 windows, 4 android, 3 linux), each with coverage dimensions, deterministic question keyword patterns (EN+中文), artifact-family bindings, suggested tools, knowledge, pitfalls (first-class: "file presence != execution", "successful logon != unauthorized access", "same IP != same actor/device", "prefetch/shell-history absence != no execution", "absence of SMS bodies in app-data backups != absence of messages") and escalation signals. Unsupported domains stay unregistered.

## 15. SkillResolver

`resolve_skills` (`skill-resolver:v1`) — deterministic scoring: coverage mapping (100) > question hints (40) > known entities (10), with manifest-driven family availability as a hard filter (any unavailable family → skill excluded, `unavailable_requirements` records `skill:family`). Output: primary/supporting skills, resolved tool ids (∩ allowed tools), warnings, reason codes, `split_required` + suggested semantic partitions when distinct domains exceed `SkillResolverPolicy.max_domains_before_split` (breadth limits are config, defaults provisional for P8 calibration). No embeddings, no LLM classifier.

## 16. SpecialistContextPack

Frozen pack (`specialist-context-pack:v1`): identity quad, objective digest, question, source/time scope, `ProfileDigest`, embedded `SkillResolution`, constraints, `relevant_case_context` (each note hard-marked `context_only`), finding refs, entity refs (empty until P5), `EvidenceDigestItem`s only (no full evidence bodies), `SourceCapabilityManifest`, allowed tool ids (profile baseline minus the platform-artifact tool when no family is available), `output_contract_ref` (`specialist-result:P4-placeholder`), working-state revision/hash anchors, tool schema hash. `input_hash()` is deterministic and order-insensitive over sets; `tool_context()` derives the trusted execution context stamped with the pack hash; `layered_view()` renders L0–L7. No Graph context, no chat history — structurally absent fields, tested.

## 17. Bridge completion

`build_specialist_agent(pack, registry, *, model)` — ContextPack + registry → PydanticAI `Agent(deps_type=ForensicAgentDeps, toolsets=[ForensicToolset(...)], instructions=<L0..L7>)`. Requires an explicit model (`ModelRequiredError` otherwise — P3 never implicitly builds a live provider model). ServiceManager wiring intentionally **not** added (§47 leaves it optional; the substrate is stateless and P4 owns runtime wiring).

## 18. Test commands + results

```text
.venv/bin/python -m pytest tests/unit/investigation/test_agent_pydantic_adapter.py \
  tests/unit/investigation/test_agent_tool_registry.py \
  tests/unit/investigation/test_agent_tool_adapters.py \
  tests/unit/investigation/test_agent_tool_visibility.py \
  tests/unit/investigation/test_agent_capabilities_skills.py \
  tests/unit/investigation/test_agent_context_assembly.py
  -> see freeze-gate counts in the final report (follow-up included)

.venv/bin/python -m pytest tests/unit/investigation/            -> 582 passed (full investigation suite incl. P1/P2)
pip check                                                        -> No broken requirements found
py_compile (all new modules)                                     -> OK
TRACELENS_AGENT_PROVIDER_SMOKE=1 (opt-in, outside gate)          -> request reached the provider, provider-level 402 Insufficient Balance; connectivity/configuration diagnostic only — NOT successful generation (see §2)
```

(Exact final counts re-verified at the freeze gate; see final report.)

## 19. Known limitations

- `file -> related clusters` has no read facade (route-level ±300s matching only); the tool returns an explicit limitation instead of faking results.
- Platform-artifact filters are limited to server-side `text_contains`; column-level typed filters wait for family schema declarations.
- Real-provider generation/structured-output/tool-calling validation is pending the DeepSeek account balance recovery (opt-in smoke only; see §2).
- `search_files` pagination rides the C++ facade's client-side pagination semantics.
- Memory/`server_cloud`-as-own-profile are deliberately unregistered/limited.
- The P2 orchestrator does not consume any of this substrate yet (P4 boundary).

## 20. P4 deferred work

SupervisorAgent production execution; agent-backed Delegation execution consuming P2-admitted actions; SpecialistResult output contract (replacing the placeholder ref); Integration mode → StateTransitionPolicy → Working State revisions from agent results; bounded parallelism; wiring `AgentRuntimeAdapter`/orchestrator EXECUTE to PydanticAI; column-level typed artifact filters; rerun the opt-in provider smoke once the cloud account regains balance.
