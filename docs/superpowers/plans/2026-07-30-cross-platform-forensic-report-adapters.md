# Cross-Platform Forensic Report Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement read-only common, timeline, Android, Windows, and Linux adapters that stream every configured non-empty artifact table into the shared report protocol, plus specialized chat/media/timeline frontend renderers.

**Architecture:** A shared SQLite reader verifies identifiers against adapter-owned category registries, opens databases with URI read-only mode, tolerates missing tables/columns by emitting warnings, and streams rows rather than loading full tables. Each platform adapter is declarative: category specs define source tables, title/timestamp/path/state/severity mappings, renderer selection, searchable fields, and field aliases. The frontend registers specialized renderers without changing the report workspace.

**Tech Stack:** Python 3, sqlite3 read-only URI mode, Pydantic 2, pytest, React 18, Vitest, React Testing Library

## Global Constraints

- Reports contain both structured artifacts and the existing five-chapter AI analysis.
- Support both single-task (`task`) and multi-image case (`case`) scopes through one protocol.
- Deliver online browsing and offline HTML ZIP packages; PDF and DOCX are out of scope.
- Include every parsed artifact, not only evidence marked relevant to the case.
- Highlight deleted, recovered, high-risk, relevant, and analysis-referenced records.
- Published report versions are immutable; regeneration always creates a new monotonically increasing version.
- Sensitive values remain unmasked and are stored/displayed verbatim, including Android Wi-Fi keys and Linux password hashes.
- Platforms and categories are emitted from actual non-empty data; empty tables never become sections.
- One evidence item may contain multiple platforms.
- Missing database files, missing tables, and missing optional columns are non-critical adapter/category warnings; corrupt row serialization may skip that category but must not invalidate other adapters.
- Source forensic databases are opened read-only and are never migrated or mutated.
- Every table and column name used in SQL comes from an adapter-owned constant registry, never from HTTP input.
- Pagination is performed by the shared snapshot writer; adapter iteration order must be deterministic (`ORDER BY id`).
- The unrelated existing modification at `.superpowers/sdd/2026-07-29-miui-backup-forensics-phase1/final-remediation-round-report.md` must not be staged or committed.

## Consumed Interfaces

Plans 1 and 2 must be complete. This plan consumes:

```python
class ReportAdapter(Protocol):
    name: str
    platform: str
    def probe(self, context: AdapterContext) -> ProbeResult: ...
    def categories(self, context: AdapterContext) -> Sequence[CategorySpec]: ...
    def iter_records(self, context: AdapterContext, category: CategorySpec) -> Iterator[ReportRecord]: ...
```

and:

```javascript
registerReportRenderer(name, component)
```

---

### Task 1: Build the safe read-only SQLite adapter base

**Files:**
- Create: `python_service/httpserver/services/forensic_report/adapters/__init__.py`
- Create: `python_service/httpserver/services/forensic_report/adapters/sqlite_base.py`
- Create: `python_service/httpserver/services/forensic_report/adapters/registry.py`
- Test: `python_service/tests/unit/forensic_report/adapters/test_sqlite_base.py`

**Interfaces:**
- Consumes: `AdapterContext`, `CategorySpec`, `ProbeResult`, `ReportRecord`, `stable_record_id`.
- Produces: `SqliteCategoryDefinition`, `SqliteReportAdapter`, `open_readonly(path)`, `table_columns(conn, table)`, `table_count(conn, table)`, `serialize_value(value)`, and `build_default_adapters()`.

- [ ] **Step 1: Write failing read-only and missing-schema tests**

```python
# python_service/tests/unit/forensic_report/adapters/test_sqlite_base.py
import sqlite3
from pathlib import Path

import pytest

from httpserver.services.forensic_report.adapters.sqlite_base import (
    SqliteCategoryDefinition,
    SqliteReportAdapter,
    open_readonly,
)
from httpserver.services.forensic_report.models import AdapterContext, ScopeType


class FixtureAdapter(SqliteReportAdapter):
    name = "fixture"
    platform = "fixture"
    database_key = "fixture"
    definitions = (
        SqliteCategoryDefinition(
            category_id="fixture.rows", title="Rows", table="rows",
            renderer="table", title_fields=("name",), timestamp_field="timestamp",
            searchable_fields=("name", "secret"),
        ),
    )


def make_context(db: Path):
    return AdapterContext(
        scope_type=ScopeType.TASK, scope_id="t1", evidence_id="e1", task_id="t1",
        evidence_name="fixture", db_paths={"fixture": str(db)}, source_fingerprints={},
    )


def test_open_readonly_refuses_writes(tmp_path: Path):
    db = tmp_path / "fixture.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE rows (id INTEGER PRIMARY KEY, name TEXT)")
    with open_readonly(str(db)) as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO rows(name) VALUES ('mutate')")


def test_missing_table_is_not_returned_as_category(tmp_path: Path):
    db = tmp_path / "fixture.db"
    sqlite3.connect(db).close()
    adapter = FixtureAdapter()
    assert list(adapter.categories(make_context(db))) == []


def test_rows_stream_in_id_order_and_preserve_secret(tmp_path: Path):
    db = tmp_path / "fixture.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE rows (id INTEGER PRIMARY KEY, name TEXT, timestamp INTEGER, secret TEXT)")
        conn.executemany("INSERT INTO rows VALUES (?, ?, ?, ?)", [(2, 'B', 20, 'beta'), (1, 'A', 10, 'alpha')])
    adapter = FixtureAdapter()
    category = list(adapter.categories(make_context(db)))[0]
    rows = list(adapter.iter_records(make_context(db), category))
    assert [row.source_record_id for row in rows] == ['1', '2']
    assert rows[0].fields['secret'] == 'alpha'
```

- [ ] **Step 2: Run tests and verify missing adapter modules**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters/test_sqlite_base.py -v
```

Expected: collection fails because `adapters.sqlite_base` is absent.

- [ ] **Step 3: Implement the declarative category definition and read-only utilities**

```python
# python_service/httpserver/services/forensic_report/adapters/sqlite_base.py
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ..ids import stable_record_id
from ..models import (
    AdapterContext, CategorySpec, DataState, ProbeResult, ReportRecord, Severity,
)


@dataclass(frozen=True)
class SqliteCategoryDefinition:
    category_id: str
    title: str
    table: str
    renderer: str = "table"
    title_fields: tuple[str, ...] = ("id",)
    timestamp_field: str | None = None
    source_path_field: str | None = None
    deleted_field: str | None = None
    recovered_field: str | None = None
    severity_field: str | None = None
    severity_map: dict[Any, Severity] = field(default_factory=dict)
    searchable_fields: tuple[str, ...] = ()
    exclude_fields: tuple[str, ...] = ()
    page_size: int = 100


def open_readonly(path: str) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def quote_identifier(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"unsafe SQLite identifier: {identifier}")
    return f'"{identifier}"'


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
    return {row["name"] for row in rows}


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}").fetchone()[0])


def serialize_value(value):
    if isinstance(value, bytes):
        return {"encoding": "hex", "value": value.hex()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class SqliteReportAdapter:
    name = "sqlite"
    platform = "common"
    database_key = "files"
    definitions: tuple[SqliteCategoryDefinition, ...] = ()

    def _path(self, context: AdapterContext) -> str | None:
        return context.db_paths.get(self.database_key)

    def probe(self, context: AdapterContext) -> ProbeResult:
        path = self._path(context)
        return ProbeResult(
            available=bool(path and Path(path).is_file()),
            reason=None if path and Path(path).is_file() else f"{self.database_key} database missing",
        )

    def categories(self, context: AdapterContext):
        path = self._path(context)
        if not path or not Path(path).is_file():
            return []
        available = []
        with open_readonly(path) as conn:
            for definition in self.definitions:
                columns = table_columns(conn, definition.table)
                if "id" not in columns or table_count(conn, definition.table) == 0:
                    continue
                available.append(CategorySpec(
                    category_id=definition.category_id,
                    platform=self.platform,
                    title=definition.title,
                    renderer=definition.renderer,
                    source_table=definition.table,
                    page_size=definition.page_size,
                    searchable_fields=[name for name in definition.searchable_fields if name in columns],
                ))
        return available

    def iter_records(self, context: AdapterContext, category: CategorySpec) -> Iterator[ReportRecord]:
        definition = next(item for item in self.definitions if item.category_id == category.category_id)
        path = self._path(context)
        with open_readonly(path) as conn:
            columns = table_columns(conn, definition.table)
            rows = conn.execute(
                f"SELECT * FROM {quote_identifier(definition.table)} ORDER BY id"
            )
            for row in rows:
                values = {name: serialize_value(row[name]) for name in row.keys() if name not in definition.exclude_fields}
                row_id = str(row["id"])
                title = " · ".join(str(values.get(name, "")) for name in definition.title_fields if values.get(name) not in (None, "")) or f"{definition.title} #{row_id}"
                timestamp = values.get(definition.timestamp_field) if definition.timestamp_field in columns else None
                source_path = values.get(definition.source_path_field) if definition.source_path_field in columns else None
                state = DataState.UNKNOWN
                if definition.deleted_field in columns and values.get(definition.deleted_field):
                    state = DataState.DELETED
                elif definition.recovered_field in columns and values.get(definition.recovered_field):
                    state = DataState.RECOVERED
                elif definition.deleted_field or definition.recovered_field:
                    state = DataState.EXISTING
                severity = self._severity(definition, values)
                yield ReportRecord(
                    record_id=stable_record_id(
                        context.evidence_id, self.platform, category.category_id,
                        definition.table, row_id,
                    ),
                    category=category.category_id,
                    title=title,
                    timestamp=int(timestamp) if isinstance(timestamp, (int, float)) else None,
                    source_path=str(source_path) if source_path else None,
                    source_table=definition.table,
                    source_record_id=row_id,
                    data_state=state,
                    severity=severity,
                    is_relevant=bool(source_path and source_path in context.relevant_paths),
                    hashes=self._hashes(values),
                    fields=values,
                    attachments=self._attachments(context, definition, values),
                )

    def _severity(self, definition, values):
        raw = values.get(definition.severity_field) if definition.severity_field else None
        return definition.severity_map.get(raw, Severity.INFO)

    def _hashes(self, values):
        return {name: str(values[name]) for name in ("md5", "sha1", "sha256", "file_hash", "source_hash") if values.get(name)}

    def _attachments(self, context, definition, values):
        return []
```

Do not catch SQLite corruption inside this base iterator. Let `SnapshotWriter` convert the category exception into an `AdapterWarning` while other categories continue.

- [ ] **Step 4: Add the production adapter registry seam**

```python
# python_service/httpserver/services/forensic_report/adapters/registry.py
def build_default_adapters():
    from .common import CommonFilesReportAdapter
    from .timeline import TimelineReportAdapter
    from .android import AndroidReportAdapter
    from .windows import WindowsReportAdapter
    from .linux import LinuxReportAdapter
    return [
        CommonFilesReportAdapter(), TimelineReportAdapter(), AndroidReportAdapter(),
        WindowsReportAdapter(), LinuxReportAdapter(),
    ]
```

The imported modules are created in subsequent tasks; do not call `build_default_adapters()` until Task 6.

- [ ] **Step 5: Run base adapter tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters/test_sqlite_base.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit the adapter base**

```bash
git add python_service/httpserver/services/forensic_report/adapters python_service/tests/unit/forensic_report/adapters/test_sqlite_base.py
git commit -m "feat(report): add read-only SQLite adapter base"
```

---

### Task 2: Implement common file and comprehensive timeline adapters

**Files:**
- Create: `python_service/httpserver/services/forensic_report/adapters/common.py`
- Create: `python_service/httpserver/services/forensic_report/adapters/timeline.py`
- Test: `python_service/tests/unit/forensic_report/adapters/test_common.py`
- Test: `python_service/tests/unit/forensic_report/adapters/test_timeline.py`

**Interfaces:**
- Consumes: files database `files` table and events database `events`, `system_events` tables.
- Produces: categories `common.files`, `common.deleted_files`, `timeline.events`, and `timeline.system_events` with renderer values `table` and `timeline`.

- [ ] **Step 1: Write failing fixture tests**

```python
# python_service/tests/unit/forensic_report/adapters/test_common.py
import sqlite3
from pathlib import Path

from httpserver.services.forensic_report.adapters.common import CommonFilesReportAdapter
from httpserver.services.forensic_report.models import AdapterContext, ScopeType


def test_common_adapter_emits_all_files_and_deleted_subset(tmp_path: Path):
    db = tmp_path / "files.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE files (
            id INTEGER PRIMARY KEY, inode INTEGER, name TEXT, path TEXT, size INTEGER,
            extension TEXT, category TEXT, type TEXT, mtime INTEGER, ctime INTEGER,
            is_deleted INTEGER, md5 TEXT, scene_relevant INTEGER,
            llm_summary TEXT, llm_description TEXT)""")
        conn.executemany(
            "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, 10, 'a.txt', '/a.txt', 1, 'txt', 'Documents', 'REG', 11, 12, 0, 'aaa', 0, None, None),
                (2, 20, 'gone.db', '/gone.db', 2, 'db', 'Databases', 'REG', 21, 22, 1, 'bbb', 1, 'sum', 'desc'),
            ],
        )
    context = AdapterContext(
        scope_type=ScopeType.TASK, scope_id='t1', evidence_id='e1', task_id='t1',
        evidence_name='image', db_paths={'files': str(db)}, source_fingerprints={},
        relevant_paths={'/gone.db'},
    )
    adapter = CommonFilesReportAdapter()
    categories = {c.category_id: c for c in adapter.categories(context)}
    all_rows = list(adapter.iter_records(context, categories['common.files']))
    deleted = list(adapter.iter_records(context, categories['common.deleted_files']))
    assert len(all_rows) == 2
    assert [row.source_path for row in deleted] == ['/gone.db']
    assert deleted[0].is_relevant is True
```

```python
# python_service/tests/unit/forensic_report/adapters/test_timeline.py
import sqlite3
from pathlib import Path

from httpserver.services.forensic_report.adapters.timeline import TimelineReportAdapter
from httpserver.services.forensic_report.models import AdapterContext, ScopeType


def test_timeline_adapter_emits_file_and_system_events(tmp_path: Path):
    db = tmp_path / "events.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE events (
            id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT,
            file_path TEXT, description TEXT, severity TEXT, llm_is_relevant INTEGER)""")
        conn.execute(
            "INSERT INTO events VALUES (1, 1700000000, 'CREATE', '/data/a.db', 'created', 'WARNING', 1)"
        )
        conn.execute("""CREATE TABLE system_events (
            id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT,
            source TEXT, user TEXT, process TEXT, ip_address TEXT,
            service TEXT, description TEXT, severity TEXT)""")
        conn.execute(
            "INSERT INTO system_events VALUES (1, 1700000001, 'LOGIN', 'auth', 'root', 'sshd', '10.0.0.1', 'ssh', 'login', 'CRITICAL')"
        )
    context = AdapterContext(
        scope_type=ScopeType.TASK, scope_id='t1', evidence_id='e1', task_id='t1',
        evidence_name='image', db_paths={'events': str(db)}, source_fingerprints={},
    )
    adapter = TimelineReportAdapter()
    categories = {item.category_id: item for item in adapter.categories(context)}
    assert set(categories) == {'timeline.events', 'timeline.system_events'}
    assert all(item.renderer == 'timeline' for item in categories.values())
    event = list(adapter.iter_records(context, categories['timeline.events']))[0]
    system = list(adapter.iter_records(context, categories['timeline.system_events']))[0]
    assert event.timestamp == 1700000000
    assert event.is_relevant is True
    assert event.severity.value == 'medium'
    assert system.severity.value == 'critical'
```

- [ ] **Step 2: Run fixture tests and verify missing adapters**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters/test_common.py tests/unit/forensic_report/adapters/test_timeline.py -v
```

Expected: import failures for `common` and `timeline`.

- [ ] **Step 3: Implement common file categories**

Use a custom adapter because `common.deleted_files` applies a fixed predicate.

```python
# essential definitions in adapters/common.py
FILES = SqliteCategoryDefinition(
    category_id="common.files", title="文件证据", table="files",
    renderer="table", title_fields=("name", "path"), timestamp_field="mtime",
    source_path_field="path", deleted_field="is_deleted",
    searchable_fields=("name", "path", "extension", "category", "md5", "llm_summary", "llm_description"),
)
DELETED = SqliteCategoryDefinition(
    category_id="common.deleted_files", title="已删除/恢复文件", table="files",
    renderer="table", title_fields=("name", "path"), timestamp_field="mtime",
    source_path_field="path", deleted_field="is_deleted",
    searchable_fields=FILES.searchable_fields,
)
```

Override `categories()` to add `common.deleted_files` only when `SELECT COUNT(*) FROM files WHERE is_deleted = 1` is non-zero. Override row selection to add `WHERE is_deleted = 1` for that category. Map `scene_relevant = 1` or paths in `context.relevant_paths` to `is_relevant=True`.

- [ ] **Step 4: Implement timeline categories**

Define:

```python
EVENTS = SqliteCategoryDefinition(
    category_id="timeline.events", title="综合时间线", table="events",
    renderer="timeline", title_fields=("event_type", "description"),
    timestamp_field="timestamp", source_path_field="file_path",
    severity_field="severity",
    searchable_fields=("event_type", "file_path", "description", "system_context", "event_source", "llm_summary", "llm_description"),
)
SYSTEM_EVENTS = SqliteCategoryDefinition(
    category_id="timeline.system_events", title="系统事件", table="system_events",
    renderer="timeline", title_fields=("event_type", "description"),
    timestamp_field="timestamp", severity_field="severity",
    searchable_fields=("event_type", "source", "user", "process", "ip_address", "service", "description"),
)
```

Normalize case-insensitive severity values:

```python
{"INFO": Severity.INFO, "WARNING": Severity.MEDIUM, "ERROR": Severity.HIGH, "CRITICAL": Severity.CRITICAL}
```

Override relevance for `events.llm_is_relevant == 1`.

- [ ] **Step 5: Run common/timeline adapter tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters/test_common.py tests/unit/forensic_report/adapters/test_timeline.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit common adapters**

```bash
git add python_service/httpserver/services/forensic_report/adapters/common.py python_service/httpserver/services/forensic_report/adapters/timeline.py python_service/tests/unit/forensic_report/adapters/test_common.py python_service/tests/unit/forensic_report/adapters/test_timeline.py
git commit -m "feat(report): add file and timeline adapters"
```

---

### Task 3: Implement the Android adapter and chat/media renderers

**Files:**
- Create: `python_service/httpserver/services/forensic_report/adapters/android.py`
- Test: `python_service/tests/unit/forensic_report/adapters/test_android.py`
- Create: `web/src/components/reports/renderers/ChatRenderer.jsx`
- Create: `web/src/components/reports/renderers/MediaRenderer.jsx`
- Modify: `web/src/components/reports/renderers/registry.js`
- Test: `web/src/components/reports/renderers/ChatRenderer.test.jsx`
- Test: `web/src/components/reports/renderers/MediaRenderer.test.jsx`

**Interfaces:**
- Consumes: `android.db` schema in `src/core/DatabaseManager/SQL/android_analysis_sql.h`.
- Produces: non-empty Android categories with `android.*` IDs and renderers `key_value`, `table`, `chat`, and `media`.

- [ ] **Step 1: Write a failing Android fixture test covering sensitive and partial schemas**

```python
# python_service/tests/unit/forensic_report/adapters/test_android.py
import sqlite3
from pathlib import Path

from httpserver.services.forensic_report.adapters.android import AndroidReportAdapter
from httpserver.services.forensic_report.models import AdapterContext, ScopeType


def test_android_adapter_detects_non_empty_categories_and_keeps_sensitive_text(tmp_path: Path):
    db = tmp_path / "android.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE wifi_networks (id INTEGER PRIMARY KEY, ssid TEXT, pre_shared_key TEXT, key_mgmt TEXT)")
        conn.execute("INSERT INTO wifi_networks VALUES (1, 'Home', 'plain-secret', 'WPA2')")
        conn.execute("CREATE TABLE sms_messages (id INTEGER PRIMARY KEY, address TEXT, date INTEGER, type INTEGER, body TEXT)")
        conn.execute("INSERT INTO sms_messages VALUES (1, '13800138000', 1700000000, 1, '验证码 123456')")
        conn.execute("CREATE TABLE contacts (id INTEGER PRIMARY KEY, display_name TEXT)")
    context = AdapterContext(
        scope_type=ScopeType.TASK, scope_id='t1', evidence_id='e1', task_id='t1',
        evidence_name='phone', db_paths={'android': str(db)}, source_fingerprints={},
    )
    adapter = AndroidReportAdapter()
    categories = {item.category_id: item for item in adapter.categories(context)}
    assert set(categories) == {'android.wifi_networks', 'android.sms_messages'}
    wifi = list(adapter.iter_records(context, categories['android.wifi_networks']))[0]
    assert wifi.fields['pre_shared_key'] == 'plain-secret'
    assert categories['android.sms_messages'].renderer == 'chat'
```

- [ ] **Step 2: Run Android test and verify missing adapter**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters/test_android.py -v
```

Expected: import failure.

- [ ] **Step 3: Define every Android category from the actual schema**

Create one `SqliteCategoryDefinition` per table below. The mapping is exhaustive for current `android_analysis_sql.h`; empty/missing tables are omitted automatically.

```python
ANDROID_DEFINITIONS = (
    # Device/system
    D("android.system_build_properties", "系统属性", "system_build_properties", "key_value", ("property_key",), None, None, ("property_key", "property_value")),
    D("android.device_identifiers", "设备标识", "device_identifiers", "key_value", ("identifier_type", "value"), None, "source_path", ("identifier_type", "value", "package_name", "source_path")),
    D("android.wechat_owner_info", "微信账号", "wechat_owner_info", "key_value", ("nickname", "username"), None, None, ("username", "nickname", "uin", "imei")),
    # Communication/chat
    D("android.contacts", "通讯录", "contacts", "table", ("display_name", "phone_number"), None, None, ("display_name", "phone_number", "email", "account_name")),
    D("android.sms_messages", "短信", "sms_messages", "chat", ("address", "body"), "date", None, ("address", "person", "body", "service_center")),
    D("android.call_logs", "通话记录", "call_logs", "table", ("name", "number"), "date", None, ("number", "name", "geocoded_location")),
    D("android.whatsapp_messages", "WhatsApp 消息", "whatsapp_messages", "chat", ("sender", "receiver", "content"), "timestamp", "media_url", ("sender", "receiver", "content", "media_url")),
    D("android.telegram_messages", "Telegram 消息", "telegram_messages", "chat", ("sender", "receiver", "content"), "timestamp", "media_url", ("sender", "receiver", "content", "media_url")),
    D("android.wechat_messages", "微信消息", "wechat_messages", "chat", ("sender_nickname", "talker", "content"), "timestamp", "media_url", ("sender", "receiver", "content", "chatroom_name", "sender_nickname", "talker")),
    D("android.wechat_contacts", "微信联系人", "wechat_contacts", "table", ("nickname", "username"), None, "avatar_path", ("username", "nickname", "remark")),
    D("android.wechat_chatrooms", "微信群", "wechat_chatrooms", "table", ("chatroom_name", "owner"), "create_time", None, ("chatroom_name", "owner", "member_list")),
    # Apps/browser/network
    D("android.system_apps", "系统应用", "system_apps", "table", ("package_name", "version_name"), None, "apk_path", ("package_name", "apk_path", "version_name")),
    D("android.installed_packages", "安装包", "installed_packages", "table", ("package_name", "version"), "last_update_time", "code_path", ("package_name", "version", "installer", "code_path")),
    D("android.usage_stats", "应用使用", "usage_stats", "table", ("package_name",), "last_time_used", None, ("package_name",)),
    D("android.app_database_files", "应用数据库", "app_database_files", "table", ("package_name", "file_name"), None, "file_path", ("package_name", "file_name", "file_path")),
    D("android.chrome_history", "浏览器历史", "chrome_history", "table", ("title", "url"), "last_visit_time", "url", ("title", "url")),
    D("android.wifi_networks", "Wi-Fi 网络", "wifi_networks", "table", ("ssid",), "last_connected", None, ("ssid", "pre_shared_key", "key_mgmt")),
    # Logs/files/security/MIUI
    D("android.framework_files", "框架文件", "framework_files", "table", ("file_name", "file_type"), None, "file_path", ("file_name", "file_path", "file_type")),
    D("android.system_logs", "系统日志", "system_logs", "timeline", ("tag", "message"), "timestamp", "log_file", ("tag", "process", "message", "log_file", "log_source")),
    D("android.app_notes", "应用便签", "app_notes", "table", ("title", "package_name"), None, "source_db", ("title", "content", "tags", "package_name")),
    D("android.encrypted_db_inventory", "加密数据库与密码提示", "encrypted_db_inventory", "table", ("package_name", "db_path"), None, "db_path", ("package_name", "db_path", "key_hint_type", "key_hint_value", "key_source_path", "open_status")),
    D("android.miui_backup_manifest", "MIUI 备份信息", "miui_backup_manifest", "key_value", ("device", "miui_version"), "backup_date", "source_folder", ("device", "miui_version", "source_folder")),
    D("android.installed_apps", "备份应用", "installed_apps", "table", ("display_name", "package_name"), None, None, ("display_name", "package_name", "version_name", "manifest_summary")),
    D("android.app_db_inventory", "备份数据库清单", "app_db_inventory", "table", ("package_name", "table_name"), None, "db_path", ("package_name", "db_path", "table_name", "columns", "open_status")),
)
```

Implement a local helper `D(...)` that creates `SqliteCategoryDefinition` using named arguments; do not use positional construction in production because timestamp/path/search fields are easy to swap.

For messages, retain all row fields and derive title from sender/talker/address plus a 60-character content prefix. Attachments for non-empty `media_url` or `avatar_path` initially contain evidence references with `preview_type="none"`; Plan 5 will decide preview eligibility.

- [ ] **Step 4: Run Android adapter tests and an all-table schema smoke test**

Add a parametrized test that creates each listed table with `id` plus only its searchable/title columns and one row. Assert every category can stream despite absent optional columns.

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters/test_android.py -v
```

Expected: all Android tests pass.

- [ ] **Step 5: Write failing chat/media renderer tests**

```jsx
// ChatRenderer.test.jsx
// Assert incoming and outgoing messages have distinct alignment classes,
// timestamps/content render, and attachment metadata is visible.

// MediaRenderer.test.jsx
// Assert packaged image preview renders <img>; missing preview renders original
// evidence path, hash, and unavailable reason without a broken <img>.
```

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/components/reports/renderers/ChatRenderer.test.jsx src/components/reports/renderers/MediaRenderer.test.jsx
```

Expected: missing module failures.

- [ ] **Step 6: Implement and register chat/media renderers**

`ChatRenderer` determines direction from `fields.is_send`, `fields.type`, or sender/owner fields and groups consecutive messages by conversation key (`talker`, `chatroom_name`, `address`, or sender/receiver pair). It must not reorder records across timestamps supplied by the page shard.

`MediaRenderer` and shared attachment rendering use `dataSource.getPreviewUrl(reportId, attachment)`. If it returns null, show metadata only. Register:

```javascript
registerReportRenderer('chat', ChatRenderer);
registerReportRenderer('media', MediaRenderer);
```

- [ ] **Step 7: Run Android backend and renderer tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters/test_android.py -v
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/components/reports/renderers/ChatRenderer.test.jsx src/components/reports/renderers/MediaRenderer.test.jsx
```

Expected: all tests pass.

- [ ] **Step 8: Commit Android support**

```bash
git add python_service/httpserver/services/forensic_report/adapters/android.py python_service/tests/unit/forensic_report/adapters/test_android.py web/src/components/reports/renderers/ChatRenderer.jsx web/src/components/reports/renderers/MediaRenderer.jsx web/src/components/reports/renderers/ChatRenderer.test.jsx web/src/components/reports/renderers/MediaRenderer.test.jsx web/src/components/reports/renderers/registry.js
git commit -m "feat(report): add Android report artifacts"
```

---

### Task 4: Implement the Windows adapter

**Files:**
- Create: `python_service/httpserver/services/forensic_report/adapters/windows.py`
- Test: `python_service/tests/unit/forensic_report/adapters/test_windows.py`

**Interfaces:**
- Consumes: tables in `windows_analysis_sql_tables.h` and optional `windows_artifact_descriptions` enrichment.
- Produces: non-empty Windows categories under `windows.*`, including executable/DLL anomaly details and record-level severity/relevance enrichment.

- [ ] **Step 1: Write a failing Windows fixture test**

```python
# python_service/tests/unit/forensic_report/adapters/test_windows.py
# Create windows.db with:
# - event_logs containing CRITICAL level
# - mft_entries containing is_deleted=1
# - dll_base_info containing threat_score=90
# - dll_anomalies linked to dll_id
# - empty registry_values
# Assert:
# - empty registry category omitted
# - event severity is critical
# - MFT record data_state is deleted
# - DLL record severity is critical and retains sha256/signature fields
```

- [ ] **Step 2: Run test and verify missing Windows adapter**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters/test_windows.py -v
```

Expected: import failure.

- [ ] **Step 3: Define the exhaustive Windows category registry**

The registry must include every independent artifact table in the current schema:

```text
registry_values
 event_logs
 prefetch_files
 lnk_files
 jump_list_entries
 user_accounts
 usb_devices
 recycle_bin
 browser_history
 browser_downloads
 browser_bookmarks
 browser_cookies
 browser_logins
 browser_artifacts
 mft_entries
 windows_services
 scheduled_tasks
 amcache_entries
 srum_entries
 wifi_profiles
 rdp_connections
 shimcache_entries
 user_assist_entries
 shell_bag_entries
 dll_base_info
 dll_anomalies
 dll_dependencies
 dll_forensic_links
```

Child-detail tables `dll_sections`, `dll_imports`, and `dll_exports` are not separate top-level categories. Override `iter_records` for `windows.dlls` to add:

```python
fields["sections"] = query_children("dll_sections", "dll_id", row_id)
fields["imports"] = query_children("dll_imports", "dll_id", row_id)
fields["exports"] = query_children("dll_exports", "dll_id", row_id)
fields["anomalies"] = query_children("dll_anomalies", "dll_id", row_id)
fields["dependencies"] = query_children("dll_dependencies", "parent_dll_id", row_id)
fields["forensic_links"] = query_children("dll_forensic_links", "dll_id", row_id)
```

Only issue these child queries if the child table exists. Map:

- `event_logs.level`: `CRITICAL -> critical`, `ERROR -> high`, `WARNING -> medium`.
- `mft_entries.is_deleted == 1` and all `recycle_bin` rows to deleted state.
- `dll_base_info.threat_score >= 80 -> critical`, `>= 60 -> high`, `>= 30 -> medium`, otherwise info.
- `dll_anomalies.risk_level` using the same string severity normalization.
- `registry_values.forensic_importance` containing `high`/`critical` to matching severity.

Searchable fields must include paths, names, users/SIDs, URLs, serials, hashes, descriptions/messages, LLM summaries/descriptions/keywords, and encrypted login values without masking.

- [ ] **Step 4: Add Windows LLM enrichment without changing source DB**

If the table `windows_artifact_descriptions` exists in the same database, load matching `(artifact_type, artifact_id)` rows into memory by category iteration and merge only these report fields:

```python
fields["analysis_summary"] = enrichment["summary"]
fields["analysis_description"] = enrichment["description"]
fields["analysis_keywords"] = enrichment["keywords"]
severity = max_severity(severity, normalize_severity(enrichment["severity"]))
is_relevant = is_relevant or bool(enrichment["relevance"])
```

Do not update the forensic database.

- [ ] **Step 5: Run Windows tests including missing child tables**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters/test_windows.py -v
```

Expected: all tests pass with no mutation of `windows.db`.

- [ ] **Step 6: Commit Windows support**

```bash
git add python_service/httpserver/services/forensic_report/adapters/windows.py python_service/tests/unit/forensic_report/adapters/test_windows.py
git commit -m "feat(report): add Windows report artifacts"
```

---

### Task 5: Implement the Linux adapter

**Files:**
- Create: `python_service/httpserver/services/forensic_report/adapters/linux.py`
- Test: `python_service/tests/unit/forensic_report/adapters/test_linux.py`

**Interfaces:**
- Consumes: tables in `linux_analysis_sql_tables.h`, including `CREATE_ALL_TABLES` and `CREATE_LINUX_ANALYSIS_PROGRESS_TABLE` groups.
- Produces: non-empty Linux categories grouped under identity, activity, logs, networking, services/persistence, packages, browsers, containers, web/middleware, security findings, external devices/cloud, and correlation/timeline.

- [ ] **Step 1: Write a failing Linux fixture test**

```python
# python_service/tests/unit/forensic_report/adapters/test_linux.py
# Create linux.db with:
# - linux_users containing password_hash="$6$full-hash"
# - linux_shell_history containing "curl https://example"
# - linux_setuid_files is_suspicious=1
# - linux_security_bypass severity=90
# - linux_docker_containers empty
# Assert password hash remains verbatim, container category is absent,
# setuid is high, bypass is critical, and shell history is searchable.
```

- [ ] **Step 2: Run test and verify missing Linux adapter**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters/test_linux.py -v
```

Expected: import failure.

- [ ] **Step 3: Define all current Linux artifact categories**

Use a declarative tuple that includes every artifact table below except `linux_analysis_progress`, which is operational metadata and not evidence:

```text
linux_log_entries
linux_users
linux_groups
linux_login_records
linux_shell_history
linux_cron_jobs
linux_ssh_keys
linux_ssh_known_hosts
linux_packages
linux_network_connections
linux_systemd_services
linux_kernel_modules
linux_firewall_rules
linux_audit_logs
linux_audit_events
linux_tampering_findings
linux_browser_profiles
linux_browser_history
linux_browser_cookies
linux_browser_downloads
linux_browser_bookmarks
linux_recent_documents
linux_trash_entries
linux_desktop_files
linux_docker_containers
linux_docker_images
linux_docker_volumes
linux_podman_containers
linux_podman_pods
linux_apache_access_logs
linux_apache_vhosts
linux_nginx_access_logs
linux_nginx_server_blocks
linux_setuid_files
linux_capabilities
linux_selinux_status
linux_selinux_avc_denials
linux_apparmor_profiles
linux_apparmor_violations
linux_correlated_events
linux_attack_chains
linux_timeline_events
linux_timeline_gaps
linux_anomalies
linux_journal_entries
linux_boot_sessions
linux_journal_anomalies
linux_persistence_entries
linux_web_error_logs
linux_middleware_logs
linux_modsecurity_logs
linux_container_logs
linux_container_security_findings
linux_package_logs
linux_suspicious_packages
linux_account_security_findings
linux_ssh_security_findings
linux_database_logs
linux_database_security_findings
linux_email_logs
linux_email_security_findings
linux_vpn_logs
linux_vpn_security_findings
linux_firewall_logs
linux_security_product_logs
linux_security_product_findings
linux_usb_events
linux_mount_entries
linux_cloud_logs
linux_extended_history
linux_security_bypass
linux_rule_matches
```

Use renderer `timeline` for timestamped log/event tables; `key_value` for users, SELinux status, profiles/configuration; `table` for remaining categories.

- [ ] **Step 4: Implement Linux severity and state normalization**

Exact numeric mapping:

```python
def numeric_severity(value):
    score = int(value or 0)
    if score >= 80: return Severity.CRITICAL
    if score >= 60: return Severity.HIGH
    if score >= 30: return Severity.MEDIUM
    if score > 0: return Severity.LOW
    return Severity.INFO
```

String mapping recognizes `critical`, `fatal`, `emerg`, `alert`, `error`, `err`, `warning`, `warn`, `high`, `medium`, `low` case-insensitively.

Boolean suspicious fields (`is_suspicious`, `is_sensitive`, `is_confirmed`) raise severity to at least `HIGH`. Tables whose names end in `_findings`, `_anomalies`, `_bypass`, or `_violations` retain their explicit severity and default to `MEDIUM` when no usable severity exists. `linux_trash_entries` uses deleted state. No password hash, SSH key, cookie value, command, query text, or raw record is masked.

- [ ] **Step 5: Add a schema coverage test against the checked-in SQL header**

The test reads `src/core/DatabaseManager/SQL/linux_analysis_sql_tables.h`, extracts `CREATE TABLE IF NOT EXISTS (linux_[a-z0-9_]+)`, subtracts `{ "linux_analysis_progress" }`, and asserts exact equality with `LinuxReportAdapter.registered_tables()`.

```python
def test_linux_registry_covers_every_artifact_table():
    header = Path('../src/core/DatabaseManager/SQL/linux_analysis_sql_tables.h').read_text()
    schema_tables = set(re.findall(r'CREATE TABLE IF NOT EXISTS\s+(linux_[a-z0-9_]+)', header))
    schema_tables.remove('linux_analysis_progress')
    assert LinuxReportAdapter.registered_tables() == schema_tables
```

Use a project-root path derived from `Path(__file__).resolve()` so the test does not depend on current working directory.

- [ ] **Step 6: Run Linux tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters/test_linux.py -v
```

Expected: all tests pass and schema coverage catches future unregistered tables.

- [ ] **Step 7: Commit Linux support**

```bash
git add python_service/httpserver/services/forensic_report/adapters/linux.py python_service/tests/unit/forensic_report/adapters/test_linux.py
git commit -m "feat(report): add Linux report artifacts"
```

---

### Task 6: Register production adapters and add mixed-platform integration coverage

**Files:**
- Modify: `python_service/httpserver/services/service_manager.py` in `forensic_report_service` property
- Modify: `python_service/httpserver/services/forensic_report/adapters/__init__.py`
- Create: `python_service/tests/integration/forensic_report/test_mixed_platform_snapshot.py`
- Create: `web/src/components/reports/renderers/TimelineRenderer.jsx`
- Modify: `web/src/components/reports/renderers/registry.js`
- Test: `web/src/components/reports/renderers/TimelineRenderer.test.jsx`

**Interfaces:**
- Consumes: `build_default_adapters()` and all adapter modules.
- Produces: production mixed-platform snapshots and registered `timeline` renderer.

- [ ] **Step 1: Write a failing mixed-platform snapshot test**

```python
# python_service/tests/integration/forensic_report/test_mixed_platform_snapshot.py
import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from httpserver.services.forensic_report.adapters.registry import build_default_adapters
from httpserver.services.forensic_report.models import ReportStatus, ScopeType
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.forensic_report.service import ForensicReportService
from httpserver.services.forensic_report.snapshot_writer import SnapshotWriter
from httpserver.services.forensic_report.source_resolver import SourceResolver


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_one_evidence_emits_every_non_empty_platform_without_mutating_sources(tmp_path: Path):
    databases = {name: tmp_path / f"{name}.db" for name in ("files", "events", "android", "windows", "linux")}
    with sqlite3.connect(databases["files"]) as conn:
        conn.execute("CREATE TABLE files (id INTEGER PRIMARY KEY, name TEXT, path TEXT, mtime INTEGER, is_deleted INTEGER, md5 TEXT)")
        conn.execute("INSERT INTO files VALUES (1, 'a.txt', '/a.txt', 10, 0, 'aaa')")
    with sqlite3.connect(databases["events"]) as conn:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, file_path TEXT, description TEXT, severity TEXT)")
        conn.execute("INSERT INTO events VALUES (1, 11, 'CREATE', '/a.txt', 'created', 'INFO')")
    with sqlite3.connect(databases["android"]) as conn:
        conn.execute("CREATE TABLE sms_messages (id INTEGER PRIMARY KEY, address TEXT, date INTEGER, body TEXT)")
        conn.execute("INSERT INTO sms_messages VALUES (1, '13800138000', 12, '验证码')")
    with sqlite3.connect(databases["windows"]) as conn:
        conn.execute("CREATE TABLE event_logs (id INTEGER PRIMARY KEY, timestamp INTEGER, event_id INTEGER, message TEXT, level TEXT)")
        conn.execute("INSERT INTO event_logs VALUES (1, 13, 4624, 'logon', 'INFO')")
    with sqlite3.connect(databases["linux"]) as conn:
        conn.execute("CREATE TABLE linux_shell_history (id INTEGER PRIMARY KEY, username TEXT, command TEXT, timestamp INTEGER)")
        conn.execute("INSERT INTO linux_shell_history VALUES (1, 'root', 'whoami', 14)")

    before = {name: sha256(path) for name, path in databases.items()}
    backend = AsyncMock()
    backend.get_task.return_value = {
        "id": "task-1", "image_path": "/evidence/mixed.E01",
        "output_files_db": str(databases["files"]),
    }
    backend.get_task_databases.return_value = [
        {"type": name, "path": str(path)} for name, path in databases.items()
    ]
    repository = ReportRepository(tmp_path / "reports.db")
    service = ForensicReportService(
        repository=repository,
        resolver=SourceResolver(backend),
        writer=SnapshotWriter(tmp_path / "snapshots", "test"),
        adapters=build_default_adapters(),
    )
    version = await service.start(ScopeType.TASK, "task-1")
    for _ in range(100):
        status = service.get_status(version.report_id)
        if status.status in (ReportStatus.READY, ReportStatus.FAILED):
            break
        await asyncio.sleep(0.01)
    assert status.status is ReportStatus.READY
    manifest = json.loads(service.get_manifest_path(version.report_id).read_text("utf-8"))
    assert manifest["platforms"] == ["android", "common", "linux", "timeline", "windows"]
    assert all(category["total"] == 1 for category in manifest["categories"])
    assert {name: sha256(path) for name, path in databases.items()} == before
```

- [ ] **Step 2: Register production adapters in ServiceManager**

Replace `adapters=[]` with:

```python
from .forensic_report.adapters.registry import build_default_adapters

# inside ServiceManager.forensic_report_service construction
adapters=build_default_adapters(),
```

Export adapter classes and registry from `adapters/__init__.py`.

- [ ] **Step 3: Implement and register the timeline renderer**

`TimelineRenderer` renders records sorted in their supplied order with:

- localized timestamp;
- title and description;
- event source/type;
- severity/relevance/state badges;
- source path and record provenance;
- `data-record-id` for search/reference scrolling.

Register `timeline` in `registry.js` and test that a critical event and unknown timestamp render without crashing.

- [ ] **Step 4: Run all adapter and mixed-platform tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters tests/integration/forensic_report/test_mixed_platform_snapshot.py -v
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/components/reports/renderers
```

Expected: all tests pass.

- [ ] **Step 5: Verify database fixtures were not mutated**

In the integration test, capture SHA-256 of every source DB before report generation and assert the hashes are unchanged afterward.

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/integration/forensic_report/test_mixed_platform_snapshot.py -v
```

Expected: source hashes match.

- [ ] **Step 6: Commit production registration**

```bash
git add python_service/httpserver/services/service_manager.py python_service/httpserver/services/forensic_report/adapters/__init__.py python_service/tests/integration/forensic_report/test_mixed_platform_snapshot.py web/src/components/reports/renderers/TimelineRenderer.jsx web/src/components/reports/renderers/TimelineRenderer.test.jsx web/src/components/reports/renderers/registry.js
git commit -m "feat(report): generate mixed-platform snapshots"
```

---

## Plan 3 Completion Gate

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/python_service
python -m pytest tests/unit/forensic_report/adapters tests/integration/forensic_report/test_mixed_platform_snapshot.py -v
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/components/reports/renderers
npm run build
cd /home/ymj68520/projects/Forensics/TraceLens
git status --short
```

Expected:

- Source DB writes fail under `open_readonly`.
- Missing/empty tables are omitted.
- Common files and timeline are complete and paged.
- Android sensitive fields remain verbatim and chat categories use `chat`.
- Windows deleted/risk/LLM enrichment is normalized.
- Linux registry covers every checked-in artifact table except operational progress.
- One evidence can emit Android, Windows, Linux, common, and timeline sections.
- Specialized chat, media, and timeline renderers pass.
- Git status does not show the unrelated MIUI document staged.

Next plan: `docs/superpowers/plans/2026-07-30-cross-platform-forensic-report-case-analysis.md`.
