# TraceLens Agent v0 — Phase 7B

# Chapter Writer / Assertion Ledger / Consistency Review / Immutable Publication

Status: **HARDENING / NOT YET FROZEN**.

The initial P7B implementation exposed hard-gate gaps during a post-freeze
read-only audit: publication did not enforce a passing consistency review,
retry dropped admission binding, pack/spec/finalization identity checks were
incomplete, synthesis ceiling trusted caller-provided class mappings, and V3
provenance omitted exact pack/spec hashes. The prior PASS/FROZEN claim is
withdrawn until these fixes have their dedicated tests and a new full gate.


## 1. Baseline / branch / commits

```text
baseline : P7A frozen 8232fa10
branch   : mvp/agent-v0-phase7-agent-aware-report-runtime
P7B-1/2  : c37fcd9b feat: add durable report chapter execution
P7B-3    : 75a46b86 feat: add report assertion ledger and consistency gates
P7B-4    : b32f1622 feat: add deferred report synthesis gates
P7B-5    : cebdffe1 feat: publish validated agent-aware reports
docs     : this commit
```

## 2. Publication repository investigation (§2)

1. P7A's `reports.db` has no numeric `user_version`; it follows the existing
   additive `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` style used by
   `ReportRepository`. P7B adds only report-plane tables and leaves R2 rows
   untouched.
2. P7A already defines `report_retrieval_plans` and `report_context_packs`;
   `ReportRuntimeRepository` now has exact `record/get` methods. P7B's
   `commit_report_chapter_dispatch` inserts or verifies both in the same
   transaction before inserting a generation admission.
3. `ReportGenerationExecutor` invocation and R2 publication are coupled:
   `_execute` owns envelope verification, LLM calls, citation checks, writer
   publish, and `complete_generation_publication`.
4. There was no prevalidated-sections seam. `GenerationReportWriter.publish`
   itself is a reusable atomic filesystem primitive; `GenerationReportManifest`
   is strict `extra="forbid"`.
5. Therefore P7B uses **Adapter B**: a thin
   `PrevalidatedReportPublicationAdapter` reuses `GenerationReportWriter`
   for atomic `os.replace`, the new `ReportRepository.complete_prevalidated_publication`
   for version allocation, and `read_narrative_version_strict` for Viewer
   reads. It does not call the R2 LLM a second time.
6. Existing `final-report:v2` output is strict structured report sections and
   citations; P7B uses the same section/citation field models for V3.
7. Existing `GenerationReportManifest` is strict and cannot accept additive
   fields; P7B introduces `GenerationReportManifestV3` with
   `report_kind="agent_aware_generation"` and nested immutable provenance.
   v1/v2 manifests remain on their original strict models.
8. Existing citation validation is evidence-bound. P7B adds the stricter
   ContextPack gate before publication; V3 citations use evidence-only
   `CitationManifestEntry` values with null analysis/claim identity.
9. R2 version allocation is serialized by `BEGIN IMMEDIATE`; P7B's
   `complete_prevalidated_publication` follows the same allocator and makes
   the READY row visible only after the immutable manifest exists.
10. R2 restart recovery marks admitted/running legacy generations failed.
    P7B marks running chapter generations `runtime_restart`, keeps admitted
    rows dispatchable, and never auto-runs an LLM in `initialize`.
11. Writer model calls reuse the existing injected `LLMService.chat_completion`
    API and its existing provider/model configuration. No P7_REPORT_* config
    namespace was added.
12. P7A/P7B tables use append-only payload rows, content hashes and guarded
    chapter-generation lifecycle transitions; completed/failed chapter rows
    are terminally immutable.
13. Legacy R2 callers/tests remain production-compatible; the old executor,
    envelope, manifests and routes are unchanged.
14. Existing Viewer routes read title/sections/citations through the same
    response contract; V3 reuses `StructuredReportSection` and
    `CitationManifestEntry`, so no frontend redesign was required.

## 3. Persist-before-generate (§5-§8, E2-E3)

`commit_report_chapter_dispatch` performs one `BEGIN IMMEDIATE` transaction:

```text
verify exact ChapterSpec / RetrievalPlan / ContextPack identity
↓
INSERT OR VERIFY report_retrieval_plans
↓
INSERT OR VERIFY report_context_packs
↓
INSERT chapter generation admission (status=admitted)
↓
COMMIT
↓
only then execute_chapter_generation(generation_id)
```

Generation input is rebuilt solely from persisted `reports.db` rows after
restart. A plan/pack/generation hash conflict rolls back and no Writer call
is possible.

## 4. Chapter lifecycle / retry / renderer (§7, §22-§29)

Added `report_chapter_generations` with exact finalization/outline/chapter/
spec/pack/plan bindings, policy/output/prompt versions, input hash,
attempt history, admitted/running/completed/failed state, output/digest
payloads and failure audit.

`ChapterGenerationExecutor`:

- deterministic mode uses `DeterministicChapterRenderer` and makes no LLM
  call;
- evidence_narrative uses the tools=0 `ChapterWriter` against the persisted
  pack only;
- validates the entire draft before completing;
- persists validated output + output hash + deterministic `ChapterDigest` +
  completed state in one transaction;
- `initialize()` only marks running rows `runtime_restart` failed;
- retries create a new attempt row and preserve the old failed row.

## 5. Writer boundary / NarrativePolicy (§9-§13, E4-E7)

`NarrativePolicyV1` is versioned starter policy. `ChapterGenerationInputV1`
is the complete Writer universe: identity bindings, policy, output contract,
prompt version and persisted pack/plan hashes. It contains no repository,
DB path, Graph client, ToolRegistry, filesystem or live callback.

`ChapterWriter.tools == 0`. Static tests assert no ToolRegistry/Graphiti/
EvidenceResolver/SQLite references. The prompt explicitly forbids retrieval,
new conclusions, intent/causality invention and citation/basis confusion.

`ChapterDraftV1` contains only structured `ReportAssertionV1` statements plus
limitations and metadata. There is no untracked factual paragraph path.
Deterministic chapters use the same draft contract without a model call.

## 6. Assertion / citation validation (§14-§25, E7-E14)

`assertion_id` is derived from generation input hash + normalized text + class
+ basis/evidence/citation refs; it is never an LLM UUID or array index.
Duplicate semantic assertions fail.

`validate_chapter_draft` fails the whole chapter in this order:
contract/identity → pack binding → server-derived IDs → exact basis refs →
pack-visible Evidence refs → allowlisted citations → forbidden Graph IDs →
unsupported detailed basis types → assertion ceiling → direct Evidence
high-level overreach.

`basis_refs` authorize semantics; `citation_refs` remain Evidence-only and
must be a subset of both the assertion's evidence refs and the frozen pack
allowlist. No silent downgrade/repair.

Ceiling rules:

```text
FACT > INFERENCE > HYPOTHESIS

accepted INFERENCE basis -> INFERENCE/HYPOTHESIS only
accepted HYPOTHESIS basis -> HYPOTHESIS only
direct Evidence -> direct recorded facts only
```

## 7. ChapterDigest / Ledger (§28-§33, E15-E17)

`ChapterDigestV1` is deterministic and built only from validated draft
assertions. `ReportAssertionLedgerV1` is append-only/content-addressed and
aggregates all completed detailed chapter assertions, Evidence provenance,
semantic basis index and limitations.

`run_deterministic_consistency` executes before semantic review. It checks
Evidence digest availability, accepted-basis class drift, forbidden review
refs, finalization/outline identity and citation grounding. Any issue blocks
synthesis/publication; it cannot be explained away by a reviewer.

## 8. SemanticConsistencyReviewer (§34-§37, E18-E19)

`SemanticConsistencyReviewer.tools == 0`; input is only ChapterDigests,
Ledger, question dispositions and limitations. It cannot retrieve, mutate
assertions/citations, add Evidence, accept or publish.

`ReportConsistencyReviewV1` is immutable and strict. Unknown assertion or
chapter refs fail output validation. `issues_found` requires issues; `pass`
cannot carry issues. Provider/runtime failure is not disguised as
`indeterminate`.

## 9. Synthesis (§38-§45, E20-E23)

`SynthesisContextPackV1` contains only ChapterDigests, the assertion Ledger,
question dispositions, limitations, allowed ledger assertion refs and the
ledger's Evidence citation universe. No raw case, Graph query, Evidence
search or Working State callback is present.

`validate_synthesis_assertion` requires validated ledger assertion basis,
Evidence-only citations, and applies the lowest required class as the
ceiling. Summary/Conclusion cannot strengthen detailed chapters.

## 10. Publication adapter / V3 manifest (§51-§57, E24-E30)

`PrevalidatedReportPublicationAdapter`:

1. renders validated statement text deterministically (no semantic rewrite);
2. builds strict R2 `StructuredReportSection` and `CitationManifestEntry`
   values with global citation IDs;
3. writes `GenerationReportManifestV3` atomically through the existing
   `GenerationReportWriter`;
4. calls existing `ReportRepository.complete_prevalidated_publication` to
   allocate the immutable `report_versions` row;
5. leaves old R2 v1/v2 generation paths untouched.

V3 provenance binds finalization id/hash, outline/revision, chapter IDs,
chapter generation/output/digest hashes, ledger id/hash, review id/hash and
model/prompt metadata. Strict Viewer dispatch accepts V3 while preserving
v1/v2 behavior. Published content is the validated draft text plus
structural formatting only.

## 11. Tests

```text
tests/unit/test_report_runtime_p7b.py  11 passed
```

The focused suite covers persist-before-generate, failure atomicity,
deterministic no-LLM mode, Writer tools=0, hidden Evidence rejection,
review/citation boundaries, assertion ceiling, direct Evidence overreach,
restart/retry, deterministic digest/ledger/consistency, reviewer unknown
refs, synthesis ceiling, V3 publication and strict Viewer read.

## 12. Known limitations / P8 deferred

- Starter ranking/budget/narrative/reviewer policies remain versioned starter
  values; P8 owns calibration and benchmark thresholds.
- The model-assisted outline adapter is still optional; deterministic outline
  remains the correctness path.
- Reviewer semantic quality depends on provider output; structural gates remain
  deterministic and fail closed.
- Existing report test/environment baseline issues are tracked separately;
  no unrelated test was changed to normalize counts.
- P8 only: Truth Manifest, benchmark corpus, thresholds, dashboards, cost /
  performance calibration, large-case benchmark and negative-case corpus.

## 13. Regression gate and exit status

```text
P7B focused                                      11 passed
P7A focused                                      68 passed
P7A + P7B combined                               79 passed
P1–P6 investigation regression                   930 passed, 1 skipped
startup / ServiceManager                         48 passed
R2 forensic_report suite                         147 passed, 1 pre-existing fail
R2 + startup/SM combined                         193 passed, 3 failures
```

The three failures in the combined R2/startup command were not P7B
regressions: two `SnapshotWriter` process-claim tests passed when rerun
individually, and the deep-recursion route failure is the known clean
`8232fa10`/P7A baseline failure (`test_file_response_rejects_nonstandard_json_constants_and_deep_recursion`).
No P7B code path owns that route or SnapshotWriter behavior.

```text
py_compile        PASS
git diff --check   PASS
pip check         baseline environment conflicts only:
                  mcp/sse-starlette require newer starlette than 0.47.3
worktree           clean after final commit
```

P7B-E1…E34: **PASS**. P7A boundaries remain intact; P8 was not started.

```text
PHASE 7A: PASS / FROZEN
PHASE 7B: PASS / FROZEN
PHASE 7 OVERALL: PASS / FROZEN
P7 frozen HEAD = <final P7B commit after this document>
```


## 14. Post-freeze audit corrections

The initial P7B implementation exposed hard-gate gaps during a post-freeze
read-only audit: publication did not enforce a passing consistency review,
retry dropped admission binding, pack/spec/finalization identity checks were
incomplete, synthesis ceiling trusted caller-provided class mappings, and V3
provenance omitted exact pack/spec hashes. The prior PASS/FROZEN claim is
withdrawn until these fixes have their dedicated tests and a new full gate.

The audit fixes now in the working tree:

- publication rejects missing/non-pass review, validates deterministic
  consistency, requires non-empty validated chapter/digest/review sets;
- retries copy `admission_id` and terminal chapter writes revalidate the exact
  durable admission;
- dispatch/validation bind `context_pack.chapter_spec_hash` to the exact
  ChapterSpec, and supplied admissions must match finalization id/hash;
- synthesis ceiling derives assertion classes from the immutable Ledger rather
  than trusting a caller map;
- V3 provenance accepts exact chapter spec hashes, pack ids and pack hashes;
- P7B report schema migrates `admission_id` additively for existing P7A stores.

Focused tests remain green after these changes (`11 passed`). A new final
regression gate and completion commit are still required before P7B can be
called PASS/FROZEN.
