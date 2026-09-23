# TraceLens Agent v0 — Phase 3: PydanticAI + Read-only Tool/Skill Substrate

Status: implemented on `mvp/agent-v0-phase3-tool-skill-substrate`.

## 1. Baseline / Branch / Commits

- P2 frozen baseline: `909504f3a1c1f68f096bdbdc47b33302f73c3785`
- Branch: `mvp/agent-v0-phase3-tool-skill-substrate` (created from the P2 frozen HEAD, verified by preflight)
- Commits:
  - `b0933cb3` — `feat: add pydantic agent runtime adapter` (P3-1)
  - `c5d585a9` — `feat: add forensic read-only tool registry` (P3-2)
  - `3a26e174` — `feat: add agent capability and skill resolution` (P3-3)
  - (P3-4) — `feat: add specialist context assembly` (context pack, bridge completion, docs, regression gate)

## 2. PydanticAI dependency decision

- Pinned: `pydantic-ai-slim[openai]==2.30.0` in `python_service/requirements.txt` (exact pin, not a range).
- Version selection: 2.30.0 is the newest release whose `[openai]` extra accepts the already-installed `openai 2.46.0` and whose core accepts installed `pydantic 2.13.4` / `httpx 0.28.1`. 2.35.x forces `openai>=3.0.0`; 2.40.0+ makes `httpx2` a hard core dependency — both would force upgrades of the existing runtime (§61 forbids). Python 3.12.3.
- Transitive additions (all additive, none replace existing pins): `pydantic-graph==2.30.0` (hard internal pin of pydantic-ai-slim itself — unavoidable, not a workflow-ecosystem adoption), `opentelemetry-api`, `genai-prices`, `griffelib`, `logfire-api` (API-only shim, not the Logfire service), `tiktoken`, `httpx2`/`httpcore2`, `truststore`, `regex`.
- `pip check`: green after install. FastAPI/Pydantic/httpx/OpenAI SDK versions unchanged.
- Opt-in provider smoke (`TRACELENS_AGENT_PROVIDER_SMOKE=1`, excluded from the default gate): adapter reached the configured DeepSeek endpoint and completed a live request round-trip; provider answered `402 Insufficient Balance` (cloud account billing state, not an adapter defect — base_url derivation, auth and model name were all accepted).

## 3. Repository facts the design rests on

- LLM config: `httpserver/config.py` `Settings` — `LLM_ENDPOINT` is stored as a *path* (`/v1/chat/completions`), resolved against `LLM_TEXT_BASE_URL`/`LLM_VISION_BASE_URL`; `LLM_THINKING_MODE` produces the DeepSeek `thinking` body quirk (`Settings.llm_thinking_body`). httpserver calls raw httpx (OpenAI-compatible Chat Completions); the OpenAI SDK 2.x exists for Graphiti.
- Evidence reads: canonical task-scoped resolver `services/evidence/` (`parse_evidence_key`, `file:`/`cluster:v1:` key grammar); legacy richer resolver facade `InvestigationService.resolve_evidence` (read-only, bounded content previews); `InvestigationReadService.list_evidence`; `SecondaryAnalysisExecutor.list_analyses/list_all_analyses`; `effective_event_claims` on the legacy facade. `evidence_detail()` is NOT used by tools because it triggers first-write-wins snapshot capture (a write).
- Platform identity: task metadata `scenarios` (`android|windows|linux|server_cloud`) and `scenario_databases` (platform → trusted DB path); platform artifact tables are deterministic content (sqlite_master) — same pattern as `intelligence_report._detect_platforms`. Platform readers `graphiti_integration/database_reader/{windows,linux,android}_reader.py` are safe typed facades (fixed per-artifact methods, limit/offset pagination, typed records).
- P1 `agent_tool_observations` (INSERT-only, canonical JSON payload) is sufficient for normalized observations — **no investigation.db schema bump in P3** (schema stays v9).

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

Tests: `tests/unit/investigation/test_agent_pydantic_adapter.py` (19), `test_agent_tool_registry.py` (16), `test_agent_tool_adapters.py` (16), `test_agent_tool_visibility.py` (7), `test_agent_capabilities_skills.py` (22), `test_agent_context_assembly.py` (14), `test_agent_provider_smoke.py` (opt-in only).

## 5. Modified

- `python_service/requirements.txt` — pinned dependency block (only existing-file change; no P1/P2 code was touched).

## 6. Reused (no reimplementation)

- Config: `Settings` attributes only (`llm_text_base_url`, `llm_endpoint`, `llm_api_key`, `llm_text_model`, `llm_thinking_body`, `llm_timeout_seconds`, `llm_text_temperature`, `llm_text_max_tokens`). No second env namespace, no `.env` reader in agent code.
- Evidence key grammar/resolver: `services/evidence/keys.py`, `InvestigationService.resolve_evidence`, `InvestigationReadService`, `SecondaryAnalysisExecutor`, `effective_event_claims`, `CppBackendService.get_task/get_task_files_paginated/get_task_events`, `make_file_evidence_key/make_cluster_key`.
- Platform readers: `WindowsDatabase/LinuxDatabase/AndroidDatabase` (typed methods) behind `query_platform_artifacts`.
- Persistence: P1 `append_tool_observation`/`list_tool_observations` (unchanged schema).
- Hash helpers: P1 `canonical_state_json`/`state_hash_of`.

## 7. Model adapter contract

`resolve_adapter_config(settings) -> ModelAdapterConfig` (normalized, secret-free); `derive_openai_base_url(base_url, endpoint_path)` translates the path-style endpoint to the OpenAI SDK base_url (`https://api.deepseek.com` + `/v1/chat/completions` → `.../v1`); `build_chat_model(settings, *, model_name=None) -> OpenAIChatModel` — fail-closed (`ModelAdapterError`) on empty/invalid config; performs no network I/O. Provider quirks centralized in one `OpenAIModelProfile`: `supports_json_schema_output=False` (DeepSeek 400s json_schema), `supports_json_object_output=True`, strict tool definitions off, `max_completion_tokens` off, single system message. `LLM_THINKING_MODE` rides `extra_body` (`{"thinking": {"type": ...}}`), mirroring `llm_service.py`. Empty API key → `"EMPTY"` sentinel (mirrors "no auth header" semantics for local endpoints; no secret copies anywhere, verified by repr tests).

## 8. Tool Registry contract

Execution pipeline (frozen order, `registry.py`): resolve → permission (registry re-checks `read` + run allow-list on every call; bridge visibility is never the boundary) → agent-type restriction → budget (per-run observation cap) → input validation (`extra="forbid"` input models) → source-scope enforcement (`source_scope_id` args must be inside the run grant, pre-adapter) → duplicate guard (deterministic fingerprint over tool identity + canonical args + source scope + context hash; threshold from `ToolBudgetPolicy`, default 2, configurable) → domain adapter → output normalization (must be `ToolExecutionOutcome` with the declared output model) → Evidence-ref validation (parse fail = `EVIDENCE_REF_INVALID`; injected validator fail = `EVIDENCE_REF_CROSS_TASK`; failures persist nothing) → observation persistence → compact model-facing result (large payloads elided; full payload stays in the observation).

Structured error codes: `TOOL_NOT_FOUND, TOOL_NOT_ALLOWED, TOOL_AGENT_NOT_ALLOWED, TOOL_SCOPE_DENIED, TOOL_INPUT_INVALID, TOOL_BUDGET_EXCEEDED, TOOL_DUPLICATE_CALL, TOOL_ADAPTER_FAILED, EVIDENCE_REF_INVALID, EVIDENCE_REF_CROSS_TASK, TOOL_RESULT_INVALID`. Messages never contain DB paths, stack traces or secrets (adapter exceptions are normalized to `TOOL_ADAPTER_FAILED` with only the exception type). `ForensicToolRegistry.schema_hash()` is deterministic over the whole catalog (tool_id/version/per-tool schema_hash); `REGISTRY_VERSION = "forensic-tool-registry:v1"`.

## 9. Initial read-only tool catalog (10 tools, all `access=read`)

`get_task_context`, `search_evidence`, `get_evidence`, `find_related_evidence`, `search_files`, `search_timeline`, `find_temporal_neighbors`, `get_existing_analyses`, `get_existing_claims`, `query_platform_artifacts`. Every input schema is auto-audited at registration for forbidden fields (`task_id`, `investigation_id`, `run_id`, `db_path`, `sql`, …); task/run identity is injected from the trusted `ForensicToolContext` only. No SQL/filesystem/Graphiti tools exist; Graph tools are P6. `search_timeline`/`find_temporal_neighbors` hand out server-derived `cluster:v1` keys — the model never constructs cluster keys.

## 10. Tool Observation / Evidence visibility

Normalized `ToolObservationRecord` (`tool-observation:v1`): tool id/version/schema hash, summary, data, entity_refs (empty in P3 — canonical entities are P5), warnings, limitations, result_count, truncated, continuation, pagination, input fingerprint, context hash. Storage: P1 `agent_tool_observations` via `AgentObservationSink` (single INSERT = observation + run/delegation linkage). **P3 storage decision:** the observation row is the durable tool action-trace; the frozen trajectory CHECK enum has no tool event type and P3 does not migrate the schema, so no trajectory row is emitted for tool calls (lifecycle events only).

Visibility (`visibility.py`): `reconstruct_allowed_evidence_ids(initial_context_refs, observations, *, delegation_id|run_id)` rebuilds one delegation's `allowed_evidence_ids` purely from durable records — ContextPack initial refs ∪ successful observation refs. Failed executions persist nothing and add no visibility; invalid refs are rejected pre-persistence; summary/data text never enters the set; Case Context stays `context_only`. Reconstruction is restart-safe (fresh repository objects re-derive identical sets).

## 11. ArtifactFamily registry

`ArtifactFamilyRegistry` (`artifact-family-registry:v1`) — 20 families bound 1:1 to real reader coverage (7 windows, 10 android incl. wechat/qq/telegram message exports, 4 linux; exact list in `agent_capabilities.default_family_catalog`). Each family carries `required_tables` (parser-output presence), `reader_method`/`reader_kwargs` (typed facade binding), `supported_filters` (`text_contains` server-side), and first-class `limitations`. No family is invented beyond existing parser/reader coverage.

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
  -> 94 passed

.venv/bin/python -m pytest tests/unit/investigation/            -> 582 passed (full investigation suite incl. P1/P2)
pip check                                                        -> No broken requirements found
py_compile (all new modules)                                     -> OK
TRACELENS_AGENT_PROVIDER_SMOKE=1 (opt-in, outside gate)          -> reached provider; 402 Insufficient Balance (billing state of the configured cloud key, not an adapter failure)
```

(Exact final counts re-verified at the freeze gate; see final report.)

## 19. Known limitations

- `file -> related clusters` has no read facade (route-level ±300s matching only); the tool returns an explicit limitation instead of faking results.
- Platform-artifact filters are limited to server-side `text_contains`; column-level typed filters wait for family schema declarations.
- `search_files` pagination rides the C++ facade's client-side pagination semantics.
- No trajectory event type for tool calls (see §10 decision); a lifecycle-visible tool event would need a schema v10 migration.
- Memory/`server_cloud`-as-own-profile are deliberately unregistered/limited.
- The P2 orchestrator does not consume any of this substrate yet (P4 boundary).

## 20. P4 deferred work

SupervisorAgent production execution; agent-backed Delegation execution consuming P2-admitted actions; SpecialistResult output contract (replacing the placeholder ref); Integration mode → StateTransitionPolicy → Working State revisions from agent results; bounded parallelism; wiring `AgentRuntimeAdapter`/orchestrator EXECUTE to PydanticAI; column-level typed artifact filters; optional trajectory tool-event type (schema v10 if ever justified).
