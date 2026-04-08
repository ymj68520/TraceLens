# [Analyzed-Only Re-Ingestion] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `ANALYZED_ONLY` ingestion mode to the Graphiti knowledge graph that re-ingests only AI-analyzed files and event clusters without re-running LLM analysis.

**Architecture:** Extend the existing `IngestionJobManager` with a new mode that filters files by `llm_analyzed_at IS NOT NULL`, uses the existing `FileEntityIngestor` for graph operations, and adds a management toolbar to the frontend Knowledge Graph page.

**Tech Stack:** Python 3.12 (FastAPI), React 18 (Vite), Neo4j, SQLite

---

## File Structure

### Backend Files

| File | Purpose | Changes |
|------|---------|---------|
| `python_service/httpserver/routes/graphiti.py` | API routes | Add `ANALYZED_ONLY` to enum, update docstring |
| `python_service/httpserver/services/ingestion_job_manager.py` | Job queue manager | Add `_process_analyzed_only()` method, update `_process_job()` |

### Frontend Files

| File | Purpose | Changes |
|------|---------|---------|
| `web/src/services/graphitiService.js` | API client | Add `reingestAnalyzedData()`, `getJobStatus()` |
| `web/src/pages/KnowledgeGraph.jsx` | Knowledge graph UI | Add toolbar, state, polling, handler |

### Note: No New Files

All changes are extensions to existing files. The `ForensicsDatabase` class already has `get_analysis_stats()` and `iter_files_batched(analyzed_only=True)` methods.

---

## Task 1: Backend - Add ANALYZED_ONLY to IngestionMode Enum

**Files:**
- Modify: `python_service/httpserver/routes/graphiti.py:28-33`

- [ ] **Step 1: Add ANALYZED_ONLY to enum**

Open `python_service/httpserver/routes/graphiti.py` and add the new mode:

```python
class IngestionMode(str, Enum):
    """Ingestion operation modes."""
    FULL = "full"
    FILES_ONLY = "files_only"
    EVENTS_ONLY = "events_only"
    SINGLE_FILE = "single_file"
    ANALYZED_ONLY = "analyzed_only"  # NEW
```

- [ ] **Step 2: Update endpoint docstring**

Find the `ingest_data` function docstring (around line 174) and update it:

```python
"""
Start Graphiti ingestion for a task.

Modes:
- full: Ingest files, events, and all platform data with File entities
- files_only: Update file entities only (skip events)
- events_only: Sync events to existing files
- analyzed_only: Re-ingest only AI-analyzed files and event clusters (NEW)
    - Only processes files with llm_analyzed_at IS NOT NULL
    - Attaches events only for analyzed files
    - Creates MENTIONED_IN edges from existing episodes
    - Does NOT re-run LLM analysis
"""
```

- [ ] **Step 3: Verify syntax**

Run: `python -m py_compile python_service/httpserver/routes/graphiti.py`
Expected: No syntax errors

- [ ] **Step 4: Commit**

```bash
git add python_service/httpserver/routes/graphiti.py
git commit -m "feat(graphiti): add ANALYZED_ONLY ingestion mode enum"
```

---

## Task 2: Backend - Implement _process_analyzed_only Method

**Files:**
- Modify: `python_service/httpserver/services/ingestion_job_manager.py`

- [ ] **Step 1: Add ANALYZED_ONLY to IngestionMode enum in service**

The service has its own enum. Add the new mode after line 32:

```python
class IngestionMode(str, Enum):
    """Ingestion operation modes."""
    FULL = "full"
    FILES_ONLY = "files_only"
    EVENTS_ONLY = "events_only"
    SINGLE_FILE = "single_file"
    ANALYZED_ONLY = "analyzed_only"  # NEW
```

- [ ] **Step 2: Add _process_analyzed_only method**

Add this method after `_process_events_only` (after line 684):

```python
async def _process_analyzed_only(self, job_id: str, task_id: str):
    """Process only AI-analyzed files and event clusters."""
    await self._update_job_status(job_id, JobStatus.RUNNING, "reading_databases", progress=5)

    # 1. Get database paths
    files_db = self._find_database(task_id, "files")
    events_db = self._find_database(task_id, "events")

    if not files_db:
        raise FileNotFoundError(f"Files database not found for task {task_id}")

    # 2. Check for AI-analyzed files
    db = self._ForensicsDatabase(files_db)
    stats = db.get_analysis_stats()
    analyzed_count = stats.get("analyzed_files", 0)
    total_files = stats.get("total_files", 0)

    await self._update_job_status(
        job_id, JobStatus.RUNNING, "checking_analyzed_files",
        progress=10, result={"analyzed_files": analyzed_count, "total_files": total_files}
    )

    if analyzed_count == 0:
        await self._update_job_status(
            job_id, JobStatus.COMPLETED, "completed", progress=100,
            result={"message": "No AI-analyzed files found", "files_processed": 0}
        )
        return

    # 3. Process only files with existing LLM analysis
    await self._update_job_status(job_id, JobStatus.RUNNING, "processing_files", progress=15)

    # Use iter_files_batched with analyzed_only=True
    all_files = []
    for batch in db.iter_files_batched(batch_size=100, analyzed_only=True):
        all_files.extend(batch)

    file_result = await self._file_ingestor.batch_ensure_files(
        all_files,
        task_id,
        progress_callback=lambda cur, total: asyncio.create_task(
            self._update_job_status(
                job_id, JobStatus.RUNNING, "processing_files",
                progress=15 + int(55 * cur / total)
            )
        )
    )

    # 4. Process events for analyzed files
    events_attached = 0
    if events_db:
        await self._update_job_status(job_id, JobStatus.RUNNING, "attaching_events", progress=70)

        events_db_reader = self._EventsDatabase(events_db)
        # Get events for analyzed files only
        analyzed_paths = {f.path for f in all_files}
        all_events = events_db_reader.get_events()
        events = [e for e in all_events if e.file_path in analyzed_paths]

        event_list = []
        for e in events:
            event_list.append((
                e.file_path,
                EventRecord(
                    file_inode=e.inode,
                    file_path=e.file_path,
                    event_type=e.event_type,
                    timestamp=e.timestamp,
                    task_id=task_id
                )
            ))

        events_attached = await self._file_ingestor.attach_events_batch(event_list)
        file_result.events_attached = events_attached

    # 5. Create MENTIONED_IN edges from existing episodes
    await self._update_job_status(job_id, JobStatus.RUNNING, "linking_entities", progress=85)

    relation_result = await self._create_mentioned_in_edges(task_id, all_files)

    # 6. Merge duplicate files
    await self._update_job_status(job_id, JobStatus.RUNNING, "deduplicating_files", progress=90)

    duplicates = await self._file_ingestor.merge_duplicate_files(task_id)
    file_result.duplicates_merged = duplicates

    # 7. Store final result
    await self._update_job_status(
        job_id,
        JobStatus.RUNNING,
        "finalizing",
        progress=95,
        result={
            "files_created": file_result.files_created,
            "files_updated": file_result.files_updated,
            "events_attached": events_attached,
            "entities_linked": relation_result.mentioned_in_edges_created,
            "duplicates_merged": duplicates,
            "analyzed_files_processed": len(all_files),
        }
    )
```

- [ ] **Step 3: Update _process_job to handle new mode**

Find the `_process_job` method (around line 506) and add the case:

```python
async def _process_job(self, queue_data: dict):
    """Process a single ingestion job."""
    job_id = queue_data["job_id"]
    task_id = queue_data["task_id"]
    mode = IngestionMode(queue_data["mode"])

    try:
        await self._update_job_status(job_id, JobStatus.RUNNING, "starting")

        if mode == IngestionMode.FULL:
            await self._process_full_ingestion(job_id, task_id)
        elif mode == IngestionMode.FILES_ONLY:
            await self._process_files_only(job_id, task_id)
        elif mode == IngestionMode.EVENTS_ONLY:
            await self._process_events_only(job_id, task_id)
        elif mode == IngestionMode.SINGLE_FILE:
            file_id = queue_data.get("file_id")
            await self._process_single_file(job_id, task_id, file_id)
        elif mode == IngestionMode.ANALYZED_ONLY:  # NEW
            await self._process_analyzed_only(job_id, task_id)  # NEW

        await self._update_job_status(job_id, JobStatus.COMPLETED, progress=100)

    except Exception as e:
        # ... existing error handling ...
```

- [ ] **Step 4: Verify syntax**

Run: `python -m py_compile python_service/httpserver/services/ingestion_job_manager.py`
Expected: No syntax errors

- [ ] **Step 5: Commit**

```bash
git add python_service/httpserver/services/ingestion_job_manager.py
git commit -m "feat(ingestion): implement _process_analyzed_only method"
```

---

## Task 3: Frontend - Add API Service Methods

**Files:**
- Modify: `web/src/services/graphitiService.js`

- [ ] **Step 1: Add getJobStatus function**

Add after `deleteTaskGraph` function (around line 95):

```javascript
/**
 * 获取导入任务状态
 * @param {string} jobId - 任务 ID
 */
export const getJobStatus = async (jobId) => {
    return await pythonApi.get(`/api/graphiti/jobs/${jobId}`);
};
```

- [ ] **Step 2: Add reingestAnalyzedData function**

Add after `getJobStatus`:

```javascript
/**
 * 重新摄入已分析的文件和事件簇
 * @param {string} taskId - 任务 ID
 */
export const reingestAnalyzedData = async (taskId) => {
    const payload = {
        task_id: taskId,
        mode: 'analyzed_only',
    };
    return await pythonApi.post('/api/graphiti/ingest', payload);
};
```

- [ ] **Step 3: Update default export**

Update the default export to include new functions (around line 108):

```javascript
export default {
    ingestTaskData,
    searchGraph,
    listEntities,
    listRelationships,
    getGraphitiStatus,
    listTaskGraphs,
    deleteTaskGraph,
    getGraphData,
    getJobStatus,  // NEW
    reingestAnalyzedData,  // NEW
};
```

- [ ] **Step 4: Update imports in KnowledgeGraph.jsx**

Open `web/src/pages/KnowledgeGraph.jsx` and update the import (around line 11):

```javascript
import {
    ingestTaskData,
    searchGraph,
    listEntities,
    listRelationships,
    getGraphitiStatus,
    listTaskGraphs,
    deleteTaskGraph,
    getGraphData,
    getJobStatus,  // NEW
    reingestAnalyzedData,  // NEW
} from '../services/graphitiService';
```

- [ ] **Step 5: Verify no TypeScript/linting errors**

Run: `cd web && npm run lint`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add web/src/services/graphitiService.js web/src/pages/KnowledgeGraph.jsx
git commit -m "feat(frontend): add getJobStatus and reingestAnalyzedData service methods"
```

---

## Task 4: Frontend - Add Re-Ingestion State

**Files:**
- Modify: `web/src/pages/KnowledgeGraph.jsx`

- [ ] **Step 1: Add state variables**

Add after the existing ingest state (after line 68):

```javascript
// Re-ingestion state (separate from regular ingestion)
const [reingesting, setReingesting] = useState(false);
const [reingestJobId, setReingestJobId] = useState(null);
const [reingestProgress, setReingestProgress] = useState(0);
const [reingestMessage, setReingestMessage] = useState('');
```

- [ ] **Step 2: Add job polling effect**

Add after the task reset effect (after line 118):

```javascript
// Poll re-ingestion job status
useEffect(() => {
    if (!reingestJobId) return;

    const pollStatus = async () => {
        try {
            const status = await getJobStatus(reingestJobId);
            setReingestProgress(status.progress || 0);
            setReingestMessage(status.current_phase || 'Processing...');

            if (status.status === 'COMPLETED') {
                setReingesting(false);
                setReingestMessage('重新摄入完成！');
                await fetchStatus();
                await fetchTaskGraphs();
                setGraphData({ nodes: [], links: [] }); // trigger reload
            } else if (status.status === 'FAILED') {
                setReingesting(false);
                setError(`重新摄入失败: ${status.error || '未知错误'}`);
            } else if (status.status === 'CANCELLED') {
                setReingesting(false);
                setReingestMessage('操作已取消');
            }
        } catch (err) {
            setError('获取任务状态失败: ' + (err.message || '未知错误'));
        }
    };

    // Poll every 2 seconds
    const interval = setInterval(pollStatus, 2000);
    pollStatus(); // Initial call

    return () => clearInterval(interval);
}, [reingestJobId]);
```

- [ ] **Step 3: Verify syntax**

Run: `cd web && npm run lint`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/KnowledgeGraph.jsx
git commit -m "feat(frontend): add re-ingestion state and polling effect"
```

---

## Task 5: Frontend - Add Re-Ingest Handler

**Files:**
- Modify: `web/src/pages/KnowledgeGraph.jsx`

- [ ] **Step 1: Add handleReingestAnalyzed function**

Add after `handleDeleteGraph` function (after line 271):

```javascript
const handleReingestAnalyzed = async () => {
    if (!taskId) {
        setError('请先选择一个任务');
        return;
    }

    setReingesting(true);
    setReingestJobId(null);
    setReingestProgress(0);
    setReingestMessage('正在准备重新摄入...');

    try {
        const result = await reingestAnalyzedData(taskId);
        if (result.job_id) {
            setReingestJobId(result.job_id);
            setReingestMessage('已提交重新摄入任务');
        } else {
            setReingesting(false);
            setError('未能提交重新摄入任务');
        }
    } catch (err) {
        setError('提交重新摄入任务失败: ' + (err.message || '未知错误'));
        setReingesting(false);
    }
};
```

- [ ] **Step 2: Update handleIngest to disable when reingesting**

Find the button in `renderStatus` that calls `handleIngest` (around line 328) and update:

```javascript
<Button size="sm" onClick={handleIngest} disabled={!taskId || ingesting || reingesting}>
    {ingesting ? <Spinner size="sm" /> : '导入数据'}
</Button>
```

- [ ] **Step 3: Verify syntax**

Run: `cd web && npm run lint`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/KnowledgeGraph.jsx
git commit -m "feat(frontend): add handleReingestAnalyzed handler"
```

---

## Task 6: Frontend - Add Management Toolbar

**Files:**
- Modify: `web/src/pages/KnowledgeGraph.jsx`

- [ ] **Step 1: Add renderManagementToolbar function**

Add after `renderTaskSelector` function (after line 302):

```javascript
const renderManagementToolbar = () => (
    <Card className="mb-4">
        <div className="flex items-center justify-between">
            <div>
                <h3 className="font-medium text-slate-900 dark:text-white">
                    🔧 图谱管理工具栏
                </h3>
                <p className="text-sm text-slate-500">
                    仅重新摄入包含AI分析结果的文件和事件簇
                </p>
            </div>
            <Button onClick={handleReingestAnalyzed} disabled={!taskId || reingesting || ingesting}>
                {reingesting ? <Spinner size="sm" /> : '📥 重新摄入已分析数据'}
            </Button>
        </div>
        {/* Progress indicator for re-ingestion */}
        {reingesting && reingestProgress > 0 && reingestProgress < 100 && (
            <div className="mt-4">
                <div className="flex justify-between text-sm mb-1">
                    <span className="text-slate-600 dark:text-slate-300">{reingestMessage}</span>
                    <span className="text-purple-600">{reingestProgress}%</span>
                </div>
                <div className="w-full bg-slate-200 dark:bg-gray-600 rounded-full h-2">
                    <div className="bg-purple-600 h-2 rounded-full transition-all"
                         style={{ width: `${reingestProgress}%` }} />
                </div>
            </div>
        )}
        {reingesting && reingestProgress === 100 && reingestMessage && (
            <div className="mt-4 p-3 bg-purple-50 dark:bg-purple-900/20 text-purple-800 dark:text-purple-200 rounded">
                ✅ {reingestMessage}
            </div>
        )}
    </Card>
);
```

- [ ] **Step 2: Add toolbar to render**

Find the return statement (around line 704) and add the toolbar after `renderTaskSelector()`:

```javascript
return (
    <div className="p-6">
        {/* ... existing header and error ... */}

        {renderTaskSelector()}
        {taskId && renderManagementToolbar()}  {/* NEW */}
        {taskId && renderStatus()}
        {taskId && renderTabs()}

        {/* ... existing tabs ... */}
    </div>
);
```

- [ ] **Step 3: Verify syntax**

Run: `cd web && npm run lint`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/KnowledgeGraph.jsx
git commit -m "feat(frontend): add management toolbar with re-ingestion button"
```

---

## Task 7: Testing - Backend Unit Tests

**Files:**
- Create: `python_service/tests/unit/test_ingestion_analyzed_only.py`

- [ ] **Step 1: Create test file**

Create the test file:

```python
"""
Unit tests for ANALYZED_ONLY ingestion mode.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ingestion_job_manager import IngestionMode, JobStatus, IngestionJob


@pytest.mark.asyncio
async def test_process_analyzed_only_with_analyzed_files():
    """Test processing when AI-analyzed files exist."""
    # Mock the dependencies
    with patch('ingestion_job_manager.IngestionJobManager._ForensicsDatabase') as mock_db_cls, \
         patch('ingestion_job_manager.IngestionJobManager._file_ingestor') as mock_ingestor, \
         patch('ingestion_job_manager.IngestionJobManager._entity_builder') as mock_builder:

        # Setup mocks
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        
        # Mock get_analysis_stats to return analyzed files
        mock_db.get_analysis_stats.return_value = {
            "analyzed_files": 100,
            "total_files": 500
        }
        
        # Mock iter_files_batched to return batches
        mock_file = MagicMock(path="/test/file.txt", llm_analyzed_at=123456)
        mock_db.iter_files_batched.return_value = [[mock_file]]
        
        # Mock file_ingestor methods
        mock_ingestor.initialize = AsyncMock()
        mock_ingestor.batch_ensure_files = AsyncMock(
            return_value=MagicMock(
                files_created=1,
                files_updated=0,
                events_attached=0,
                duplicates_merged=0
            )
        )
        mock_ingestor.attach_events_batch = AsyncMock(return_value=0)
        mock_ingestor.merge_duplicate_files = AsyncMock(return_value=0)
        
        mock_builder.initialize = AsyncMock()
        mock_builder.batch_create_mentioned_in_edges = AsyncMock(
            return_value=MagicMock(mentioned_in_edges_created=0)
        )
        
        # Create manager and test
        from ingestion_job_manager import IngestionJobManager
        manager = IngestionJobManager(settings=MagicMock())
        manager._file_ingestor = mock_ingestor
        manager._entity_builder = mock_builder
        
        # Mock _find_database
        manager._find_database = MagicMock(return_value="/path/to/files.db")
        manager._update_job_status = AsyncMock()
        
        # Run
        await manager._process_analyzed_only("test_job_id", "test_task_id")
        
        # Assertions
        assert mock_db.get_analysis_stats.called
        assert mock_db.iter_files_batched.called
        # Verify analyzed_only=True was passed
        call_args = mock_db.iter_files_batched.call_args
        assert call_args.kwargs.get('analyzed_only') is True
        assert mock_ingestor.batch_ensure_files.called


@pytest.mark.asyncio
async def test_process_analyzed_only_no_analyzed_files():
    """Test processing when no AI-analyzed files exist."""
    with patch('ingestion_job_manager.IngestionJobManager._ForensicsDatabase') as mock_db_cls:
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        
        # Mock get_analysis_stats to return NO analyzed files
        mock_db.get_analysis_stats.return_value = {
            "analyzed_files": 0,
            "total_files": 500
        }
        
        from ingestion_job_manager import IngestionJobManager
        manager = IngestionJobManager(settings=MagicMock())
        manager._find_database = MagicMock(return_value="/path/to/files.db")
        manager._update_job_status = AsyncMock()
        
        # Run
        await manager._process_analyzed_only("test_job_id", "test_task_id")
        
        # Verify early completion
        manager._update_job_status.assert_called()
        # Should complete with message about no analyzed files
        final_call = manager._update_job_status.call_args_list[-1]
        assert final_call[1]['progress'] == 100


@pytest.mark.asyncio
async def test_process_analyzed_only_database_not_found():
    """Test handling of missing database."""
    from ingestion_job_manager import IngestionJobManager
    import pytest
    
    manager = IngestionJobManager(settings=MagicMock())
    manager._find_database = MagicMock(return_value=None)
    manager._update_job_status = AsyncMock()
    
    # Should raise FileNotFoundError
    with pytest.raises(FileNotFoundError, match="Files database not found"):
        await manager._process_analyzed_only("test_job_id", "test_task_id")
```

- [ ] **Step 2: Run tests**

Run: `cd python_service && pytest tests/unit/test_ingestion_analyzed_only.py -v`
Expected: Tests pass

- [ ] **Step 3: Commit**

```bash
git add python_service/tests/unit/test_ingestion_analyzed_only.py
git commit -m "test(ingestion): add unit tests for ANALYZED_ONLY mode"
```

---

## Task 8: Testing - Integration Test

**Files:**
- Create: `python_service/tests/integration/test_analyzed_only_ingestion_e2e.py`

- [ ] **Step 1: Create integration test**

```python
"""
Integration test for ANALYZED_ONLY ingestion mode.
"""
import pytest
import asyncio
from pathlib import Path


@pytest.mark.asyncio
async def test_analyzed_only_ingestion_end_to_end(test_database_with_analyzed_files):
    """
    End-to-end test for analyzed-only ingestion.
    
    Prerequisites:
    - Test database with mixed analyzed/unanalyzed files
    - Neo4j instance running
    """
    from httpx import AsyncClient
    from main import app
    
    # Setup test database path
    test_db_path = test_database_with_analyzed_files
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        # 1. Start ingestion with analyzed_only mode
        response = await client.post("/api/graphiti/ingest", json={
            "task_id": "test_task",
            "mode": "analyzed_only",
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        job_id = data["job_id"]
        
        # 2. Poll for completion
        max_attempts = 30  # 30 seconds max
        for _ in range(max_attempts):
            status_response = await client.get(f"/api/graphiti/jobs/{job_id}")
            status_data = status_response.json()
            
            if status_data["status"] in ["COMPLETED", "FAILED", "CANCELLED"]:
                break
            await asyncio.sleep(1)
        
        # 3. Verify completion
        assert status_data["status"] == "COMPLETED"
        assert status_data["result"]["analyzed_files_processed"] > 0
        
        # 4. Verify only analyzed files are in Neo4j
        # (Add Neo4j query verification here)
```

- [ ] **Step 2: Create test database fixture**

Add to `python_service/tests/conftest.py`:

```python
@pytest.fixture
def test_database_with_analyzed_files(tmp_path):
    """Create a test database with mixed analyzed/unanalyzed files."""
    import sqlite3
    
    db_path = tmp_path / "test_files.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Create files table
    cursor.execute("""
        CREATE TABLE files (
            id INTEGER PRIMARY KEY,
            inode INTEGER,
            name TEXT,
            path TEXT,
            size INTEGER,
            extension TEXT,
            category TEXT,
            type TEXT,
            mtime INTEGER,
            ctime INTEGER,
            is_deleted INTEGER,
            md5 TEXT,
            llm_summary TEXT,
            llm_description TEXT,
            llm_keywords TEXT,
            llm_analyzed_at INTEGER,
            llm_model_used TEXT
        )
    """)
    
    # Insert analyzed files
    for i in range(5):
        cursor.execute("""
            INSERT INTO files VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            i + 1, 12345 + i, f"analyzed_{i}.txt", f"/path/to/analyzed_{i}.txt",
            1024, ".txt", "documents", "text", 1234567890, 1234567890,
            0, "abc123", "Summary", "Description", "keywords",
            1234567890, "gpt-4"
        ))
    
    # Insert unanalyzed files
    for i in range(10, 20):
        cursor.execute("""
            INSERT INTO files VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL
            )
        """, (
            i, 12345 + i, f"unanalyzed_{i}.txt", f"/path/to/unanalyzed_{i}.txt",
            1024, ".txt", "documents", "text", 1234567890, 1234567890,
            0, "def456", NULL, NULL, NULL, NULL, NULL
        ))
    
    conn.commit()
    conn.close()
    
    return str(db_path)
```

- [ ] **Step 3: Commit**

```bash
git add python_service/tests/integration/test_analyzed_only_ingestion_e2e.py
git add python_service/tests/conftest.py
git commit -m "test(integration): add e2e test for analyzed-only ingestion"
```

---

## Task 9: Documentation - Update API Reference

**Files:**
- Modify: `docs/API_REFERENCE.md`

- [ ] **Step 1: Find the Graphiti ingestion section**

Search for `### POST /api/graphiti/ingest` in the API reference

- [ ] **Step 2: Add ANALYZED_ONLY mode to documentation**

Add to the modes list:

```markdown
### POST /api/graphiti/ingest

Start Graphiti ingestion for a task.

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| task_id | string | Yes | Task ID to ingest |
| mode | string | No | Ingestion mode: `full`, `files_only`, `events_only`, `analyzed_only` (default: `full`) |
| include_llm_descriptions | boolean | No | Include LLM descriptions (default: true) |
| batch_size | integer | No | Batch size (1-500, default: 50) |

**Modes:**
- `full`: Ingest files, events, and all platform data
- `files_only`: Update file entities only
- `events_only`: Sync events to existing files  
- `analyzed_only`: **NEW** - Re-ingest only AI-analyzed files and event clusters
  - Only processes files with `llm_analyzed_at IS NOT NULL`
  - Attaches events only for analyzed files
  - Does NOT re-run LLM analysis
```

- [ ] **Step 3: Commit**

```bash
git add docs/API_REFERENCE.md
git commit -m "docs(api): document ANALYZED_ONLY ingestion mode"
```

---

## Verification Steps

After completing all tasks:

- [ ] **Verify backend starts without errors**
  Run: `cd python_service && python -m httpserver.main`
  Expected: Server starts on port 8090

- [ ] **Verify frontend builds without errors**
  Run: `cd web && npm run build`
  Expected: Build completes successfully

- [ ] **Manual smoke test**
  1. Start both servers
  2. Navigate to Knowledge Graph page
  3. Select a task with AI-analyzed files
  4. Click "📥 重新摄入已分析数据"
  5. Verify progress bar updates
  6. Verify completion message appears

- [ ] **Run all tests**
  Run: `cd python_service && pytest tests/ -v`
  Expected: All tests pass

---

## Rollback Plan

If issues arise:

1. **Backend only**: Revert commits from Task 1-2
   ```bash
   git revert HEAD~2..HEAD
   ```

2. **Frontend only**: Revert commits from Task 3-6
   ```bash
   git revert HEAD~6..HEAD~3
   ```

3. **Full rollback**: Revert all feature commits
   ```bash
   git revert HEAD~9..HEAD
   ```

---

## Notes

- The `ForensicsDatabase.iter_files_batched(analyzed_only=True)` method already exists - no changes needed
- Event cluster handling: Current implementation focuses on file events; event clusters with AI analysis would require additional database schema changes
- Progress percentage milestones: 5% (init), 10% (check), 15-70% (process files), 70% (events), 85% (link), 90% (dedupe), 95% (finalize)
