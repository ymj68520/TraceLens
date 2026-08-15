# Phase T1 Test Profiles

## Baseline

The C7c-2 freeze baseline was `863 passed, 1 warning` for `tests/unit/`, with a recorded runtime of about 32 minutes. The baseline test count is not a KPI. T1 preserves the full unit entry point and its migration, concurrency, recovery, and compatibility coverage.

The repository currently has no CI workflow or dedicated Python test runner. `python_service/pytest.ini` discovers `python_service/tests`; nested test roots outside that directory require explicit paths. The root `Makefile` keeps CTest and Python test targets separate.

## Profiles

| Profile | Command | Scope |
| --- | --- | --- |
| Focused | `python scripts/test.py focused <pytest paths/options>` | User-selected paths and options. No marker exclusions are added. |
| Investigation | `python scripts/test.py investigation` | Investigation core, routes, and ServiceManager smoke with `not slow and not concurrency and not migration_matrix`. |
| Fast Unit | `python scripts/test.py fast` | `tests/unit/` with `not slow and not concurrency and not migration_matrix`. |
| Full Unit | `python scripts/test.py full` | `tests/unit/ -q`, with no marker exclusions. |

The runner resolves its own `python_service` root and passes it as the subprocess working directory. The same focused command is valid from the repository root and from `python_service/`. `-k`, `-x`, `--maxfail`, `-vv`, and other focused arguments are forwarded unchanged.

Equivalent Makefile targets are `test-python-focused`, `test-python-investigation`, `test-python-fast`, and `test-python-full`. Use `ARGS=...` with the focused target.

## Marker ownership

- `slow`: real polling E2E tests and the generated 10,000+ message WeChat graph dataset. The two analyzed-only ingestion tests remain `integration`; the database-not-found contract remains integration but is not marked slow.
- `concurrency`: tests whose primary value is thread/async contention, worker claiming, lifecycle ordering, shutdown races, source-freeze offloading, or bounded parallel conversion. Deterministic ServiceManager property and wiring tests remain in Fast/Investigation.
- `migration_matrix`: historical schema transitions, rollback, future-version rejection, and legacy version compatibility. Current v7 validator smoke remains in Fast so schema fail-closed behavior is checked during ordinary development.
- `integration`: tests requiring Neo4j or other external services. This marker does not imply that every integration test is slow.

Full Unit must continue to collect every marker class. To report exclusions for a Fast run, collect with:

```bash
cd python_service
PYTHONPATH=.venv/lib/python3.12/site-packages .venv/bin/python -m pytest \
  tests/unit -m 'slow or concurrency or migration_matrix' --collect-only -q
```

## Investigation baseline fixture

`tests/unit/investigation/conftest.py` provides an explicit `copy_investigation_v7_baseline` fixture. It creates one real empty v7 repository store per session, verifies `PRAGMA integrity_check = ok`, `PRAGMA user_version = 7`, and verifies that `-wal` and `-shm` sidecars do not exist. A test receives an independent `shutil.copy2` destination only when it explicitly requests the fixture.

The fixture is appropriate for ordinary current-schema CRUD, analysis, event, propagation, and refresh setup. It is not autouse and does not replace fresh initialization. Fresh DB/schema-owner tests, historical v1-v6 migrations, rollback, future-version and corruption tests, missing-object tests, initializer concurrency, no-create tests, and invalid-store tests retain their original setup so their coverage meaning does not change. Source `files.db` and `events.db` remain separate per-test stores.

## Synchronization cleanup

Secondary executor tests now use `asyncio.Event` to wait until the mocked LLM has entered its critical section. The dual-worker test explicitly releases the LLM before gathering workers; graceful shutdown starts only after the worker has entered the cancellable wait. The real integration polling loops remain unchanged and are intentionally part of the slow/integration profile.

## Coverage ownership and removals

T1 removes zero tests. Repository tests continue to own SQL transactions, foreign keys, triggers, immutability, state machines, migrations, and rollback. Service tests own task/path resolution and error conversion. Route tests own HTTP contracts and dependency mapping. Executor tests own persisted-envelope consumption and worker lifecycle. Marker changes only select development profiles; Full continues to run all tests.

## External and heavy prerequisites

The Neo4j ingestion E2E tests require Neo4j and write temporary task data. The PostgreSQL fixture tests require `TEST_DATABASE_URL` and are not part of the Investigation profile. The WeChat dataset profile uses generated SQLite databases and real graph analysis. Operational scripts, evidence-image generation, privileged decryption, C++ CTest, and service smoke tests remain outside these Python profiles.

The README path for the E01 HTTP script is `scripts/test_e01_http.sh`, matching the tracked repository path.
