# TraceLens Agent v0 — Phase 7A

# Report Planning / Retrieval / Frozen ReportContextPack

Status: **PASS / FROZEN** (pending final regression gate results below)

## 1. Baseline / branch / commits

```text
baseline : P6 frozen d39acdb6
branch   : mvp/agent-v0-phase7-agent-aware-report-runtime
P7A-1    : d59b7cfa feat: add report planning contracts
P7A-2    : 407d94f5 feat: add bounded report retrieval planning
P7A-3    : d108ca00 feat: add report evidence retrieval and dedup
P7A-4    : afee74f4 feat: freeze chapter report context packs
docs     : (this commit)
```

## 2. Repository report investigation (§3 questions)

1. **Formal report persistence owner**: `reports.db` under
   `report_output_dir` (R2 `ReportRepository`), shared by the legacy
   A-chain (`report_versions` deterministic snapshots) and the R2
   LLM-generation chain (`report_generation_inputs` +
   `GenerationReportManifest` snapshots). Investigation semantic state
   stays in the per-task `investigation.db` (schema v16).
2. **`report_generation_inputs`** freezes: `task_id`, canonical envelope
   JSON (`ReportGenerationEnvelopeV1/V2` — main/appendix Report Evidence
   snapshots + bound accepted analyses + claims), `input_hash`
   (SHA-256 of canonical JSON), `prompt_version` (`final-report:v2`
   current, `final-report:v1` legacy single-shot), execution state
   machine `admitted→running→completed|failed`.
3. **`ReportGenerationExecutor` contract** (R2c): claim CAS → re-canonicalize
   + hash-verify persisted envelope → LLM (envelope verbatim) →
   `validate_report_citations` against the frozen envelope boundary →
   publish (atomic `os.replace`) → allocate version + complete in ONE
   transaction. Failures never leave a Viewer-visible version.
4. **final-report:v2 citation validator** allows exactly:
   `evidence_key ∈ allowed_report_evidence_ids` (server-derived main+
   appendix keys), optional `analysis_id` equal to the frozen bound
   analysis, optional `claim_id` persisted inside that analysis. The v2
   sectioned pipeline nulls analysis/claim identities (evidence-only
   citations).
5. **manifest.json binding**: `GenerationReportManifest` = one canonical
   JSON with report identity, `generation_id`, `input_hash`, model,
   sections, citation manifest (frozen provenance metadata: captured_at /
   analysis version / claim type). Version identity stays in the
   `report_versions` row.
6. **Viewer** reads the immutable published manifest through the strict
   façade `read_narrative_version_strict` (mode=ro, task-scoped identity
   pair, re-validated against the row). Citation traceback comes from the
   manifest; live Investigation reads are separate C9a/C9b APIs.
7. **Report Evidence status** (`main`/`appendix`/`excluded`) lives in
   `investigation.db.report_evidence` (R1); reads go through
   `InvestigationGraphReader.list_report_evidence` (strict ro projection).
8. **analysis_id=NULL Report Evidence** resolves straight back to raw
   Evidence via the snapshot join (`evidence_snapshots` composite FK);
   the R2 envelope embeds the frozen snapshot either way.
9. **Accepted-only readers**: accepted Findings =
   `agent_runtime.list_investigation_findings(status=...)` over the
   guarded state machine (`review_pending→accepted/rejected` human-only);
   accepted Events = exact-version pin `investigation_event_versions`
   (`MAX(version)` current narrative); accepted Analyses =
   `secondary_analyses.status='accepted'` (terminal-immutable).
10. **Completed investigation required?** The legacy R2 chain does NOT
    require it (MVP auto-report runs off analysis). P7A adds the stricter
    gate: `ReportRuntimeAdmissionService` requires
    `investigation.status=completed` + exact `FinalizationRecord`.
11. **P7B publication backend**: the full R2c executor/publication chain
    (admission row → executor → `GenerationReportManifest` → viewer) is
    directly reusable via an adapter; nothing needs rewriting.
12. **P7A persistence owner**: `reports.db` — outline/spec/plan/pack are
    report artifact plane artifacts (§48 priority "existing report
    persistence owner"), with exact refs back to task / investigation /
    finalization / evidence.
13. **Outline/chapter concept pre-existing**: the R2c v2 sectioned
    pipeline has a transient LLM outline (`StructuredOutlineResponse`) and
    deterministic evidence groups (`group_report_evidence`); no persisted
    outline/chapter contract existed before P7A.
14. **API/frontend compatibility**: untouched — P7A adds a service plane
    only, no route changes, no frontend redesign (§58 default NO frontend).

## 3. Existing report chain reuse boundary (§3 hard rule)

Not a second report system. P7A reuses:

- R1 Report Evidence semantics (`report_evidence.status` untouched, §7);
- R2 envelope discipline (canonical JSON + SHA-256, frozen inputs);
- the R2c executor/publication/viewer chain (left for the P7B adapter);
- `ReportGenerationInputBuilder`'s read-transaction pattern (mirrored by
  `ReportPlanningContextBuilder`: mode=ro + query_only + schema gate +
  ONE read transaction);
- existing association sources by *name* in expansion kinds
  (`event_evidence_links`, `finding_evidence_provenance`,
  `analysis_evidence_refs`, `report_evidence_set`) — no association SQL
  copied (§27);
- P6 `ProvenanceGraphReader` (REPORT mode only) +
  `hydrate_graph_result_to_evidence` (§25).

## 4. Report runtime admission (§5-§6)

`ReportRuntimeAdmissionV1` (`report_admission.py`) binds `task_id`,
`investigation_id`, exact `finalization_id` + record hash, final
Working-State revision/hash, completion mode, template identity
(id/version/hash), `report_generation_request_id`, requester;
`input_hash` covers the semantic binding. Service denies: not-completed
investigation, missing FinalizationRecord, unknown template. Persisted
append-only in `report_runtime_admissions`.

## 5. Report Template registry (§8-§10, §E4)

`ReportTemplateRegistry` + `ReportTemplateDefinitionV1`
(`report_template.py`). Starter `forensic_investigation_report/starter:v1`
stable core: case_overview, scope_and_methodology, evidence_inventory,
investigation_findings, limitations, appendix. `narrative_rules_status =
"TBD"` — the registry never claims permanence. Dynamic chapters come from
accepted findings/events only (`DynamicChapterPolicyV1`, max 6, inserted
before limitations); never per-evidence/per-playbook/per-specialist.

## 6. ReportPlanningContext (§11, §E10-adjacent)

`ReportPlanningContextV1` (`report_outline.py`): frozen digests only —
finalization anchor, charter digest, required-question dispositions,
coverage dispositions, limitations, completion mode, accepted finding
digests (text hashed, never carried), exact-pinned event digests
(`event:<id>@v<N>`), accepted analysis digests, main/appendix Report
Evidence digests, template identity. Set-like fields canonically sorted;
`input_hash` excludes `context_id`/`created_at` (deterministic replay).
Forbidden content is unrepresentable (digest-only model). Built in ONE
read transaction; schema gate = `SUPPORTED_SCHEMA_VERSION`.

## 7. ReportOutlinePlan + versioning (§13-§15, §E5-§E6)

`ReportOutlinePlanV1`: content-addressed `outline_id` (`rout:` + hash),
chapters (structural: id/title/purpose/kind/section_id/basis refs/
ordering), planner kind `deterministic|model_assisted|analyst_modified`,
`parent_outline_id` + `revision_reason` for edits. Versioning is
append-only (`report_outline_versions` PK `(outline_id, revision)`);
replay of identical semantic input is a no-op row (§62).

`DeterministicReportOutlineBuilder` (§13): safe default outline from
template + accepted findings; LLM planner is organization enhancement
only; provider failure falls back to deterministic output (contract
tested).

## 8. Outline validation (§16)

`validate_outline_plan` fails closed on: identity/finalization/context/
template mismatch, missing/duplicated/reordered required stable-core
sections, duplicate/empty chapter ids, invalid orderings, unknown basis
refs, non-accepted semantic refs (incl. review_pending), rejected refs,
graph ids as semantic basis (`graph_ref_forbidden`), invented evidence
refs, illegal dynamic-chapter basis, dynamic overflow/disabled.

## 9. ChapterSpec (§17-§19, §E9)

`ChapterSpecV1` (`chapter-spec:v1`): chapter/outline identity pin, mode,
context stage, scopes, required/optional anchors, policy refs, ordering;
`input_hash` covers the semantic payload. Modes follow the frozen
mapping (§18): inventory/methodology/appendix/overview/limitations →
`deterministic`; findings + dynamic → `evidence_narrative`. Synthesis
chapters are structurally forced to
`context_stage=deferred_until_chapter_digests` (§19) — validator rejects
a `synthesis` spec marked `ready`.

## 10. RetrievalPlan + anchors + accepted-only semantics (§20-§24,
§E10-§E13)

`ReportRetrievalPlanV1` (`report-retrieval-plan:v1`): anchors +
kinds (§22 priority `report_evidence > accepted_finding > accepted_event
> accepted_analysis`), accepted-only semantic basis, graph queries
(intent-only, REPORT mode literal in the model), bounded deterministic
expansions, entity/time scope, hydration depths, policy versions.
`DeterministicReportRetrievalPlanner` is a pure function
(context, chapter_spec) — no store, no runtime (§20/§65 tested).
review_pending/rejected findings can never anchor or enter semantic
basis (planner + validator double gate). §24 second layer E2E-tested:
pending finding's *underlying evidence* may still enter via independent
anchor while its semantic text stays excluded.

## 11. Graph report-mode integration (§25-§26, §E15-§E17)

Retrieval uses ONLY `ProvenanceGraphReader.read(mode=REPORT)`. Results
go through `hydrate_graph_result_to_evidence`; unresolvable hydration
refs are dropped. Graph ids appear solely as
`GraphNavigationProvenanceV1` (retrieval provenance); a graph id that
reaches an evidence list makes allowlist derivation raise
(`graph_ref_in_pack`).

## 12. Evidence retrieval + roles (§27-§29, §E18)

All candidates resolve through the injected evidence resolver
(`(task_id, evidence_key)` — no client paths, §28). Roles
`anchor|supporting|retrieved_context` are pack-local context roles,
independent from `report_evidence.status` (which only feeds ranking).
Required-anchor resolution failure raises
`RequiredAnchorResolutionError` (blocked pack, §55); optional-context
failure degrades to a limitation (§55).

## 13. Dedup / independence (§33-§35, §E19-§E20 — CRITICAL)

`EvidenceIndependenceResolver` (`report_dedup.py`): every candidate
collapses to root `(task_id, evidence_key)`; multiple semantic layers
(finding / analysis / graph / report-evidence / direct) fold onto ONE
item's `retrieval_provenance`. Real cross-source corroboration
(distinct evidence keys) stays distinct. Graph ids are rejected as
candidates (`root_evidence_key` ValueError — defense in depth).

## 14. Ranking / budget / hydration (§30-§31, §36-§38, §E21-§22)

`rank_candidates` is deterministic-first (role base + report-evidence
status + accepted-semantic support + entity-scope match + graph
distance; total order by ref; no LLM gate). `apply_budget` never drops
mandatory anchors silently: anchors enter first, truncation sheds
retrieved_context → supporting, every drop records a limitation, missing
required anchors surface `BUDGET_EXHAUSTED_ANCHORS`. Hydration depths
`digest|structured|detailed` with per-role starter defaults (§31,
P8-calibration configurable, `RetrievalBudgetV1` all-configurable,
nothing frozen as architecture constants).

## 15. FrozenReportContextPack (§39, §45-§47, §E23)

`FrozenReportContextPackV1` (`report-context-pack:v1`): full binding
(task/investigation/finalization+hash/outline/revision/chapter+spec
hash/plan+hash), three role-separated evidence lists
(`ReportEvidenceItemV1` with digest, bounded excerpt ≤2000, depth,
independence key, retrieval provenance, `direct_fact_only=true`),
accepted semantic basis (`AcceptedSemanticBasisV1` with
`assertion_class` ceiling, §42-§43), graph navigation provenance,
question dispositions, coverage refs, limitations, policy versions.
Immutable frozen model; any change → new `context_pack_id`;
set-like fields canonical-sorted; replay-stable round trip.

## 16. Citation allowlist (§40-§41, §69-§70, §E24)

`allowed_citation_refs` is ALWAYS server-derived inside the pack
validator from the three evidence lists (a caller-supplied value is
discarded, never merged — tamper test). Contains only real Evidence refs
present in the pack; task-scoped by construction; graph / finding /
analysis / event / proposal ids excluded by derivation (raises). Case
evidence that failed resolution is absent (E2E §69 gate). Semantic ids
support the Writer's assertion strength only (§40).

## 17. Report Evidence status non-mutation (§7, §73, §E25)

Structural guarantees: `ReportRetrievalService` receives only an async
evidence resolver + optional graph-reader factory — it holds no
repository/runtime, writes nothing, consumes zero Working State revision
(source-scan test). Excluded Report Evidence never enters the planning
context at all (§7).

## 18. Failure / degradation (§54-§57, §72, §77, §E26)

Graph reader unavailable/raises → retrieval continues with Report
Evidence + accepted basis + associations; pack records
`GRAPH_RETRIEVAL_UNAVAILABLE`. Required anchor unresolved → blocked pack
(exception). Optional context unresolved → limitation. New investigation
leads → `ReportRetrievalGapV1` proposal objects only (gap_type /
description / basis refs / suggested question); no Finding, no reopen
(§56-§57).

## 19. P7A E2E (§74-§77)

`tests/unit/test_report_context_pack_e2e.py` (18 tests): accepted-finding
chapter E2E (§74), review_pending exclusion with underlying-evidence
entry (§75), duplicate-representation single item (§76), graph
unavailable degradation (§77), graph report-mode hydration, report-mode
literal assertion, allowlist hard gates, required-anchor block,
optional-failure limitation, replay/round-trip/hash-sensitivity
invariants, gap proposal.

## 20. Persistence (§48-§51, §62, §78 subset)

`ReportRuntimeRepository` (`report_repository.py`) on `reports.db`:
`report_runtime_admissions`, `report_outline_versions`
(PK outline_id+revision), `report_chapter_specs` (PK = spec input hash),
`report_retrieval_plans`, `report_context_packs` (planning plane ready;
pack writes land with P7B dispatch). All append-only INSERT OR IGNORE —
identical semantic artifact replays to the same id and does not grow
rows. Existing `report_versions`/`report_generation_inputs` tables are
untouched (coexistence test). No P7B tables (drafts/ledger/review/
publication) were created (§49).

## 21. P7B deferred boundary (§59)

P7A modules import no Chapter Writer / Assertion Ledger / Consistency
Reviewer (none exist). The pack carries everything §87 requires:
provenance, evidence, semantic basis with assertion ceiling, citation
allowlist — a Writer with tools=0 needs no DB or Graph.

## 22. Tests

```text
tests/unit/test_report_runtime_planning.py      26 passed
tests/unit/test_report_retrieval_planning.py    10 passed
tests/unit/test_report_evidence_dedup_budget.py 14 passed
tests/unit/test_report_context_pack_e2e.py      18 passed
```

## 23. Regression gate results

```text
tests/unit/forensic_report/ + tests/unit/investigation/ + P7A suites
  => 1145 passed, 1 skipped, 1 failed (PRE-EXISTING, baseline d39acdb6:
     test_file_response_rejects_nonstandard_json_constants_and_deep_recursion,
     unrelated to P7A; reproduced on a clean baseline with the P7A
     worktree stashed)
pip check  : two PRE-EXISTING environment conflicts (mcp/sse-starlette vs
             starlette 0.47.3), present on the untouched baseline too
py_compile : all new modules OK
git diff --check : clean
```

Environment note: `pydantic-ai-slim[openai]==2.30.0` (the P3 pin from
requirements.txt) was installed into this environment to run the P5/P6
suites that import it.

## 24. P7B deferred scope (§86)

Chapter Writer (tools=0), structured assertions
FACT/INFERENCE/HYPOTHESIS/LIMITATION, basis/citation refs, deterministic
citation validator, semantic assertion ceiling validator, ChapterDigest,
ReportAssertionLedger, cross-chapter consistency, Semantic Consistency
Reviewer, Executive Summary/Conclusion generation, report version
publication via the R2c adapter, immutable manifest, Viewer integration.

## 25. Known limitations

- Starter weights/thresholds (ranking bonuses, budget defaults, excerpt
  cap) are starter values for P8 calibration, recorded in versioned
  policy constants rather than architecture.
- `report_retrieval_plans` / `report_context_packs` tables exist but the
  service does not yet persist into them (pack persistence lands with
  the P7B dispatch path to avoid a half-wired write path in P7A).
- `event_evidence_links` expansion is bounded to context-pinned event
  refs in P7A (full event→evidence association expansion reuses the
  existing workbench reader in P7B when chapters need it).
- The LLM-assisted outline planner (PydanticAI adapter, planner
  `model_assisted` path) is contract-tested via the deterministic
  fallback; the live model adapter is P7B work with the Writer.
