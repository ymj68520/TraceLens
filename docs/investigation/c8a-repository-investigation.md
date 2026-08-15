# Phase C8a — Graph Overlay Repository Investigation Report

Status: **FROZEN** (2026-08-15). Branch Dev at `d6c05cb`+. All conclusions come
from code actually read during the investigation, not from names or inference.
One path correction versus the original plan: the frontend lives in `web/src/`,
not `frontend/src/`.

This document is the architectural constraint record for C8b/C8c. Its most
important finding is the **Base KG provenance limitation** in section E.

---

## A. Base KG

- **Storage**: Graphiti SDK (graphiti-core 0.29.3, an *optional* dependency —
  not in `requirements.txt`) on Neo4j (`NEO4J_URI`, default
  `neo4j://127.0.0.1:7687`, `httpserver/config.py:187-200`). Each task is one
  graph via `group_id = task_id` (`services/graphiti_parts/_core.py:77-135`).
  No local SQLite graph. `/api/wechat/*` (networkx) is a separate feature.
- **Writers**: Path A (case-analysis pipeline) pushes per-file LLM
  descriptions as episodes through the single `add_episode` call site
  (`graphiti_integration/graphiti_ingestor.py:338`); Graphiti's LLM extracts
  entities + `RELATES_TO`. Path B (manual ingest job only) MERGEs raw
  `:File {id: sha256(path)}` / `:Task` nodes and builds `MENTIONED_IN` by
  *entity-name text match* (`ingestion_job_parts/_worker.py:755-757`).
  Reanalysis (fire-and-forget), event clusters, and Windows artifacts also
  write episodes outside initial analysis.
- **Node identity**: Graphiti `EntityNode.uuid`; `name`/`summary` are display
  fields. No `normalized_name` anywhere. Display fields ARE used as identity
  in auxiliary paths: episode-name string parsing (`_worker.py:688-711`),
  name-keyed `MENTIONED_IN`/`SAME_ENTITY` merges
  (`entity_relation_builder.py:273-277`), and array-index fallbacks
  (`file_analyzer.py:279`).
- **Edge identity**: `EntityEdge.uuid` in Graphiti; the HTTP layer constructs
  edges dynamically, and `get_graph_data` links carry **no id at all**
  (`graphiti_parts/_query.py:342-350`).
- **Evidence provenance**: initial-analysis `Entity` nodes persist **no**
  task_id/evidence_key/file_path. Task scoping exists only via
  `(:Episodic {group_id})-[:MENTIONS]->(:Entity)` joins; the file path
  survives only as *text* inside episode names (`_ingest.py:285`) —
  `ingest_episode()` drops the structured `EpisodeData.file_path` field
  (`graphiti_ingestor.py:338-346`). Path-B `:File` nodes have structured
  provenance but are created only by the manual job and are invisible to
  `/api/graphiti/graph`.
- **API**: mounted at `/api/graphiti` (`main.py:202`). Renderer-critical
  endpoint: `GET /api/graphiti/graph?task_id&max_nodes(1-1000, default 200)`
  → `{nodes: [{id, name, label, summary}], links: [{source, target, label}]}`
  (`_admin.py:102-135`, `_query.py:293-354`). Also ingest/search/entities/
  relationships/status/tasks/jobs/migrate endpoints. No neighbors or
  entity-detail endpoints.
- **Failure/fallback**: init failure silently disables the service
  (`_core.py:21-46`); search falls back to raw Neo4j `CONTAINS`
  (`_query.py:134-169`); `list_entities/relationships` return `([], 0)` on
  error. **`get_graph_data` has no fallback — Neo4j failure is HTTP 500**
  (`_admin.py:133-135`). No driver timeouts; a fresh driver per call.
- **Write-path isolation**: `routes/investigation.py` and
  `services/investigation/*.py` reference graphiti/neo4j **zero** times.
  The C++ side (`LLMPythonProxy.cpp`, `TaskManagerAnalysis.cpp:172-190`) is
  only an HTTP client that triggers ingestion; it has no graph data model.

## B. Frontend contract

- `web/src/pages/KnowledgeGraph.jsx` (783 lines), renderer =
  **react-force-graph-2d** v1.29.1, inline in the page (not extracted).
- Data contract (plain JSX, no TypeScript): node =
  `{id, name, label, summary}`, link = `{source, target, label}` — links have
  no id; consumed directly from `GET /api/graphiti/graph`
  (`web/src/services/graphitiService.js:122`).
- Node coloring by `label` via `NODE_COLORS`
  (`web/src/components/knowledge-graph/graphConstants.js`). **The `Event`
  color belongs to Base KG nodes** — overlay events must use a distinct label
  (`InvestigationEvent`). No type filtering; only a `max_nodes` cap selector.
- No stale-response protection (no AbortController/requestId); only
  wipe-state-on-task-change (`KnowledgeGraph.jsx:110-120`). Best in-repo
  precedent: `web/src/hooks/useReportSearch.js:29,52` (requestId sequence).
- No Investigation graph UI exists (`investigation` matches only the Timeline
  ClusterInvestigationDrawer, a list drawer).
- Renderer extraction precedent: `web/src/pages/WeChatGraph/components/
  GraphCanvas.jsx` — the only componentized ForceGraph2D wrapper.

## C. Investigation sources (verified)

| Semantics | Method | Location |
|---|---|---|
| latest accepted Analysis | `get_latest_accepted_analysis(evidence_key)` | `repository.py:1689` |
| latest any-status | `get_latest_analysis(evidence_key)` | `repository.py:1667` |
| per-status enumeration | `list_analyses(evidence_key, status=...)` | `repository.py:1644` |
| Claims + refs | `list_claims(analysis_id)` (refs from `claim_evidence_refs`) | `repository.py:1910` |
| Event→Evidence | `list_event_evidence(event_id)` | `repository.py:2126` |
| Evidence→Events | `list_events_for_evidence(evidence_key)` | `repository.py:2144` |
| Event enumeration | `list_events()` / `get_event(event_id)` | `repository.py:2035/2027` |

Gaps recorded (not invented around): no dedicated latest-review_pending
selector and no task-level analysis/evidence enumeration — both addressed as
read-only additions inside the C8b graph reader. No "latest effective"
abstraction may be introduced.

## D. Proven relationships

- **Authoritative**: Event→Evidence (`investigation_event_evidence`);
  Analysis→Claim (`analysis_claims`); Claim→Evidence (`claim_evidence_refs`);
  Analysis→Evidence+Snapshot (`secondary_analyses` columns);
  Entity–RELATES_TO→Entity *within* the Base KG.
- **Derived/heuristic** (must never feed overlay edges): Base KG
  Entity→File `MENTIONED_IN` (`source='name_match'`), episode-name parsing.
- **Not represented**: Event→Claim — correctly absent; C8 must not
  manufacture it from "Event links Evidence A, Analysis(A) contains Claim C".

## E. Merge feasibility — **NOT SAFE TO MERGE**

Base KG entities produced by initial analysis carry no canonical evidence
identity (no task_id/evidence_key/normalized path; provenance is episode
*text*). Identical display names are not a merge key — the Base KG's own
name-match paths are labeled heuristic. Path-B `:File {id: sha256(path)}`
nodes are the only structured-identity candidates but are manual-job-only,
use a different key namespace than `file:<normalized_path>`, and are
invisible to `/api/graphiti/graph` — out of scope for minimal C8.
**Rule: keep Base entity nodes and Investigation Evidence nodes separate;
never auto-merge by name/path substring/episode parsing/sha256 heuristic.**

## F. Reusable components

- **Direct reuse**: react-force-graph-2d + `{nodes, links}` contract +
  `getNodeColor` pattern + `pythonApi`; `graphiti_service.get_graph_data()`
  as the read-only Base input.
- **Adapter**: overlay→node/link projection (deterministic ids, synthesized
  `name`/`label`/`summary`); stale guard copied from `useReportSearch`;
  renderer extraction per `GraphCanvas.jsx`.
- **Must add**: `GET /api/investigation/graph` façade; graceful-degradation
  wrapper around `get_graph_data`; overlay label colors; read-only selectors
  (task-level selection, review_pending fallback).
- **Do not touch**: `KnowledgeGraph.jsx` semantics, `GraphitiService`
  internals, `/api/graphiti/*` return semantics, Investigation write paths,
  C++ side.

## G. Recommended minimal C8 scope — **B: read-only Investigation Graph façade**

`GET /api/investigation/graph` composes Base KG (catching `get_graph_data`
failures → `base_graph_available=false`, still 200) with a derived overlay
from Investigation SQLite. Zero new persistence. Option A (existing graph API
+ adapter) is insufficient — it cannot carry overlay semantics and its 500
behavior violates G11. Option C (Base KG provenance extension) is explicitly
deferred.

## G1–G14 verification summary

G1/G2/G6/G7/G10/G12/G13/G14 hold via existing read methods and deterministic
namespaces. G3/G5 hold via accepted-first, one-analysis-per-evidence
selection. G4 (unconfirmed fallback) and G11 (Base failure ≠ Investigation
failure) required the C8b additions below. G9 conclusion: NOT SAFE TO MERGE.

## Frozen C8b boundaries (user, 2026-08-15)

- **B1** Overlay must be task-level, not Event-anchored — analyses with no
  Event link must still appear.
- **B2** Graph GET must be strictly read-only. `InvestigationRepository`
  construction mkdir/migrates/self-heals (even at v7,
  `_ensure_v7_auxiliary_objects` runs DDL), so the GET path uses a
  dedicated `mode=ro` reader (`services/investigation/graph_reader.py`).
- **B3** Base KG failure degrades gracefully; a corrupt/unsupported
  Investigation store fails closed (503) — never silently Base-only.
- **B4** `max_base_nodes` bounds only the Base KG read; the overlay is never
  truncated.
