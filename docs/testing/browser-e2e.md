# Phase E Browser E2E

## Purpose

`scripts/browser_e2e.py` is the minimal browser harness for Phase E and D6-E7 closure. It deliberately avoids Playwright/Cypress/Puppeteer dependencies and uses only:

- the checked-in `web/dist` production build;
- Python standard-library HTTP serving and synthetic API responses;
- a locally installed Chrome/Chromium executable;
- the Chrome DevTools Protocol over a localhost WebSocket.

The harness does not use real evidence, real task directories, external LLM providers, Neo4j, PostgreSQL, or Redis. Its API responses are deterministic and scoped to synthetic `phase-e-small`, `phase-e-medium`, and `phase-e-large` task IDs.

## Invocation

From the repository root:

```bash
python3 scripts/browser_e2e.py \
  --dist web/dist \
  --output /tmp/tracelens-phase-e-browser.json
```

A frontend build is required first:

```bash
cd web
npm run build
cd ..
python3 scripts/browser_e2e.py
```

The output records, for each route:

- navigation time;
- approximate first meaningful render time;
- DOM node count;
- resource count and transfer size when Chrome reports it;
- JavaScript heap usage when supported;
- visible task marker;
- a short visible-body sample.

The harness visits:

- `/files?task_id=phase-e-small`;
- `/investigation?taskId=phase-e-medium`;
- `/knowledge-graph?task_id=phase-e-medium`;
- `/case-intelligence?task_id=phase-e-large`.

It then switches from the small synthetic task to the large synthetic task and checks that the visible task marker does not remain stale. Graph responses include `base_graph_unavailable` so graceful overlay-only rendering is observable without a Graphiti dependency.

## Result classification

- `PASS`: Chrome started, CDP attached, routes loaded, and measurements were collected.
- `ENVIRONMENT BLOCKED`: Chrome/Chromium is unavailable, CDP cannot be reached, or the browser cannot navigate to the local harness server. This is not a product pass.

The harness exits `0` only for `PASS` and exits `2` for an environment-blocked result. It never fabricates runtime measurements.

## Current environment result

On 2026-08-18, system Chrome was present and the CDP control endpoint answered, but headless Chrome did not complete navigation to the local synthetic HTTP server. The harness therefore remains `ENVIRONMENT BLOCKED`; no frontend runtime PASS is claimed. The failure is before React route execution and does not justify a product code change.

## Scope boundary

This harness closes the reproducibility requirement for E1 and provides the command for a browser-capable environment. It is not a full real-backend Journey B gate. Existing Python Investigation/Report tests, C++ CTest, MIUI CLI E2E, and frontend Vitest remain separate gates. A real cross-service/browser Journey B still requires a disposable running C++/Python stack and deterministic fake provider path.
