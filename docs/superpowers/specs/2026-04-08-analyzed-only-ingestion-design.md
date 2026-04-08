# Design: Re-ingest AI-Analyzed Data Feature

**Date:** 2026-04-08
**Status:** Draft - Updated for Review
**Author:** Claude Code
**Version:** 1.1

## Overview

Add a button to the knowledge graph page that triggers re-ingestion of only AI-analyzed files and event clusters into the Graphiti knowledge graph. This feature allows users to update the knowledge graph with existing AI analysis results without re-running expensive LLM analysis.

## Requirements

### Functional Requirements

1. **Backend API**: New ingestion mode `ANALYZED_ONLY` that processes only:
   - Files with `llm_analyzed_at` NOT NULL (has AI analysis)
   - Event clusters with AI analysis results

2. **Frontend UI**: New toolbar section on the Knowledge Graph page with:
   - "Re-ingest Analyzed Data" button
   - Progress indicator during ingestion
   - Success/error feedback

3. **Data Scope**:
   - Files: Only those with existing LLM analysis
   - Events: Regular timeline events
   - Event Clusters: Only those with AI analysis

4. **Non-Functional**:
   - Use existing AI analysis results (do NOT re-analyze)
   - Support background job processing with progress tracking
   - Handle errors gracefully with user feedback

## Architecture

### Backend Changes

#### 1. `IngestionMode` Enum

**File:** `python_service/httpserver/routes/graphiti.py`

```python
class IngestionMode(str, Enum):
    """Ingestion operation modes."""
    FULL = "full"
    FILES_ONLY = "files_only"
    EVENTS_ONLY = "events_only"
    SINGLE_FILE = "single_file"
    ANALYZED_ONLY = "analyzed_only"  # NEW
```

#### 2. `IngestionJobManager` Extension

**File:** `python_service/httpserver/services/ingestion_job_manager.py`

Add new mode handler with detailed implementation:

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

    # Use analyzed_only=True to filter files
    files = []
    for file_record in db.get_files_analyzed_batched(batch_size=self.settings.batch_size):
        files.append(file_record)

    file_result = await self._file_ingestor.batch_ensure_files(
        files,
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
        analyzed_paths = {f.path for f in files}
        events = [e for e in events_db_reader.get_events() if e.file_path in analyzed_paths]

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

    relation_result = await self._create_mentioned_in_edges(task_id, files)

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
            "analyzed_files_processed": len(files),
        }
    )
```

**Key Design Decision:** Use existing `FileEntityIngestor` and database reader methods rather than `MultiSourcePipeline`. This maintains consistency with current `IngestionJobManager` patterns (`_process_full_ingestion`, `_process_files_only`).

#### 3. Database Reader Extension

**File:** `python_service/graphiti_integration/database_reader/raw_reader.py`

Add method to iterate analyzed files in batches:

```python
def get_files_analyzed_batched(self, batch_size: int = 50):
    """
    Iterate over files with AI analysis in batches.

    Yields batches of file records where llm_analyzed_at IS NOT NULL.
    """
    offset = 0
    while True:
        query = f"""
            SELECT {self._file_columns}
            FROM files
            WHERE llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0
            ORDER BY llm_analyzed_at DESC
            LIMIT ? OFFSET ?
        """
        batch = self._execute_query(query, (batch_size, offset))
        if not batch:
            break
        yield batch
        offset += batch_size
        if len(batch) < batch_size:
            break
```

### Frontend Changes

#### 1. New Service Method

**File:** `web/src/services/graphitiService.js`

```javascript
/**
 * Re-ingest only AI-analyzed files and event clusters
 * @param {string} taskId - Task ID
 */
export const reingestAnalyzedData = async (taskId) => {
    const payload = {
        task_id: taskId,
        mode: 'analyzed_only',
    };
    return await pythonApi.post('/api/graphiti/ingest', payload);
};

/**
 * Get ingestion job status
 * @param {string} jobId - Job ID
 */
export const getJobStatus = async (jobId) => {
    return await pythonApi.get(`/api/graphiti/jobs/${jobId}`);
};
```

#### 2. Knowledge Graph Page UI

**File:** `web/src/pages/KnowledgeGraph.jsx`

Add new state (after existing ingestion state around line 68):

```javascript
// Re-ingestion state (separate from regular ingestion)
const [reingesting, setReingesting] = useState(false);
const [reingestJobId, setReingestJobId] = useState(null);
const [reingestProgress, setReingestProgress] = useState(0);
const [reingestMessage, setReingestMessage] = useState('');
```

Add job polling effect:

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

Add handler function:

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

Add new toolbar section (between task selector and status card):

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
                    <span className="text-primary-600">{reingestProgress}%</span>
                </div>
                <div className="w-full bg-slate-200 dark:bg-gray-600 rounded-full h-2">
                    <div className="bg-purple-600 h-2 rounded-full transition-all"
                         style={{ width: `${reingestProgress}%` }} />
                </div>
            </div>
        )}
    </Card>
);
```

Update render method to include toolbar:

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

## Data Flow

```
User clicks "📥 重新摄入已分析数据" button
    ↓
Frontend validates task_id selected
    ↓
Frontend calls POST /api/graphiti/ingest with mode=analyzed_only
    ↓
Backend: IngestionJobManager.queue_ingestion(task_id, mode=ANALYZED_ONLY)
    ├─ Creates IngestionJob with status=PENDING
    └─ Returns job_id to frontend
    ↓
Frontend stores job_id, starts polling every 2 seconds
    ↓
Backend: Background worker picks up job from queue
    ↓
Backend: _process_job() routes to _process_analyzed_only()
    ↓
Backend: _process_analyzed_only() executes:
    ├─ 5%: Find *_files.db database
    ├─ 10%: Check analyzed files count (get_analysis_stats)
    ├─ If count=0: Complete with "No AI-analyzed files found"
    ├─ 15%: Load analyzed files in batches (WHERE llm_analyzed_at IS NOT NULL)
    ├─ 15-70%: batch_ensure_files() with progress callback
    ├─ 70%: Attach events for analyzed files only
    ├─ 85%: Create MENTIONED_IN edges from episodes
    ├─ 90%: Merge duplicate files by MD5
    └─ 95%: Store result, mark COMPLETED
    ↓
Frontend: Poll detects COMPLETED status
    ├─ Shows success message
    ├─ Refreshes graph data
    └─ Clears polling interval
```

## Error Handling

| Scenario | Handling | Recovery Strategy |
|----------|----------|-------------------|
| No AI-analyzed files found | Return COMPLETED with message "No AI-analyzed files found" | N/A - not an error |
| Database not found | Return 404 with clear error | Prompt user to check task exists |
| Neo4j connection failure | Mark job as FAILED with error details | User can retry after fixing connection |
| Job cancelled | Stop processing, mark as CANCELLED | N/A - user initiated |
| Partial failure (some files fail) | Mark COMPLETED with warnings, log failures | Failed files can be retried |
| Schema mismatch (no llm_analyzed_at column) | Return 400 with upgrade instructions | Provide schema migration guidance |
| Connection timeout | Retry with exponential backoff (3 attempts) | Resume from last successful batch |
| Concurrent ingestion conflict | Queue job, process sequentially | N/A - job queue handles this |
| Empty events database | Continue without events, mark COMPLETED | Events are optional for this mode |

## Testing Plan

### Unit Tests

**Backend:**
```python
# test_ingestion_job_manager.py
def test_process_analyzed_only_with_analyzed_files():
    """Test processing when AI-analyzed files exist."""
    # Mock database with analyzed files
    # Verify batch_ensure_files called with correct filter
    # Verify progress updates at expected milestones

def test_process_analyzed_only_no_analyzed_files():
    """Test processing when no AI-analyzed files exist."""
    # Mock database with no analyzed files
    # Verify job completes immediately with message
    # Verify result.files_processed = 0

def test_process_analyzed_only_database_not_found():
    """Test handling of missing database."""
    # Mock _find_database to return None
    # Verify FileNotFoundError raised
    # Verify job marked as FAILED
```

**Database Schema Validation:**
```python
def test_database_schema_compatibility():
    """Verify database schema supports analyzed_only filtering."""
    # Check llm_analyzed_at column exists in files table
    # Verify index exists for performance
    # Test event cluster tables for llm_analyzed_at support
```

### Integration Tests

```python
def test_analyzed_only_ingestion_end_to_end():
    """End-to-end: POST request → job creation → processing → completion."""
    # Create test database with mixed analyzed/unanalyzed files
    # POST /api/graphiti/ingest with mode=analyzed_only
    # Verify job_id returned
    # Poll job status until COMPLETED
    # Verify only analyzed files in Neo4j
    # Verify events attached to analyzed files only
```

### UI Tests

- Button enabled/disabled based on task selection
- Button disabled when regular ingestion is running
- Progress bar updates correctly during re-ingestion
- Success/error messages display properly
- Job polling continues on page refresh (using jobId)

## Performance Considerations

### Database Query Optimization

The `WHERE llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0` filter should be supported by an index:

```sql
-- Recommended index for analyzed-only queries
CREATE INDEX IF NOT EXISTS idx_files_llm_analyzed
ON files(llm_analyzed_at)
WHERE llm_analyzed_at IS NOT NULL;
```

**Expected Performance:**
- 1000 analyzed files: ~2-5 seconds
- 10,000 analyzed files: ~15-30 seconds
- 100,000 analyzed files: ~2-5 minutes

**Batch Size Strategy:**
- Default batch size: 50 files
- For large datasets (>10k files), consider increasing to 100
- Progress callback updates every batch for smooth UI

### Memory Considerations

- Files are loaded in batches to limit memory usage
- Event attachment uses streaming to avoid loading all events at once
- Job state is persisted to Redis when available

## API Specification

### POST /api/graphiti/ingest (Extended)

**Updated docstring:**
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

**Request Body:**
```json
{
    "task_id": "string",
    "mode": "analyzed_only",  // NEW value
    "include_llm_descriptions": true,
    "batch_size": 50,
    "max_episodes": 100
}
```

**Response:**
```json
{
    "job_id": "job_abc123",
    "status": "PENDING",
    "message": "Re-ingestion of analyzed data queued"
}
```

### GET /api/graphiti/jobs/{job_id} (Existing)

Returns job status with progress:
```json
{
    "job_id": "job_abc123",
    "status": "RUNNING",
    "progress": 45,
    "current_phase": "processing_analyzed_files",
    ...
}
```

## Implementation Checklist

### Backend
- [ ] Add `ANALYZED_ONLY` to `IngestionMode` enum (`graphiti.py`)
- [ ] Implement `_process_analyzed_only()` in `IngestionJobManager`
- [ ] Update `_process_job()` to handle new mode
- [ ] Add `get_files_analyzed_batched()` to `ForensicsDatabase` (`raw_reader.py`)
- [ ] Add `get_analysis_stats()` to `ForensicsDatabase` if not present
- [ ] Update API docstring for `/api/graphiti/ingest` endpoint

### Frontend
- [ ] Add `reingestAnalyzedData()` to `graphitiService.js`
- [ ] Add `getJobStatus()` to `graphitiService.js` (if not exists)
- [ ] Add re-ingestion state to `KnowledgeGraph.jsx`
- [ ] Add job polling effect for re-ingestion
- [ ] Implement `handleReingestAnalyzed()` handler
- [ ] Implement `renderManagementToolbar()` component
- [ ] Update render method to include toolbar

### Testing
- [ ] Unit test: `_process_analyzed_only()` with analyzed files
- [ ] Unit test: `_process_analyzed_only()` with no analyzed files
- [ ] Unit test: `_process_analyzed_only()` database not found
- [ ] Integration test: End-to-end analyzed-only ingestion
- [ ] Schema validation test
- [ ] UI test: Button states and progress display

### Documentation
- [ ] Update API reference documentation
- [ ] Add migration guide for existing deployments (if needed)

## Rollout Plan

1. Phase 1: Backend implementation and testing
2. Phase 2: Frontend implementation and testing
3. Phase 3: Integration testing and documentation
4. Phase 4: Deploy to development environment for validation
