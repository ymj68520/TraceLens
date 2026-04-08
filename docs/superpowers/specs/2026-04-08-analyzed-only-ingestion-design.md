# Design: Re-ingest AI-Analyzed Data Feature

**Date:** 2026-04-08
**Status:** Approved
**Author:** Claude Code

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

Add new mode handler:

```python
async def _process_analyzed_only(self, job_id: str, task_id: str):
    """Process only AI-analyzed files and event clusters."""
    # 1. Get database paths
    # 2. Use MultiSourcePipeline with filter_analyzed_only=True
    # 3. Report progress through job status
```

#### 3. `MultiSourcePipeline` Integration

**File:** `python_service/graphiti_integration/pipeline.py`

The `MultiSourcePipeline._process_files` and `_process_events` methods already support `analyzed_only` filtering. We'll ensure:
- `filter_analyzed_only=True` is passed
- Event clusters with AI analysis are included

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
```

#### 2. Knowledge Graph Page UI

**File:** `web/src/pages/KnowledgeGraph.jsx`

Add new toolbar section between task selector and status card:

```jsx
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
            <Button onClick={handleReingestAnalyzed} disabled={!taskId || reingesting}>
                {reingesting ? <Spinner size="sm" /> : '📥 重新摄入已分析数据'}
            </Button>
        </div>
        {/* Progress indicator */}
    </Card>
);
```

## Data Flow

```
User clicks "Re-ingest Analyzed Data"
    ↓
Frontend calls POST /api/graphiti/ingest with mode=analyzed_only
    ↓
IngestionJobManager.queue_ingestion(task_id, mode=ANALYZED_ONLY)
    ↓
Background worker picks up job
    ↓
_process_analyzed_only() called:
    1. Find *_files.db database
    2. Run MultiSourcePipeline with filter_analyzed_only=True
    3. Process only files with llm_analyzed_at NOT NULL
    4. Process event clusters with AI analysis
    5. Update job progress (0-100%)
    ↓
Job status: COMPLETED with result stats
    ↓
Frontend polls job status, shows completion
```

## Error Handling

| Scenario | Handling |
|----------|----------|
| No AI-analyzed files found | Return 0 processed with info message |
| Database not found | Return 404 with clear error |
| Neo4j connection failure | Mark job as FAILED with error details |
| Job cancelled | Stop processing, mark as CANCELLED |

## Testing Plan

### Unit Tests
- `IngestionJobManager._process_analyzed_only()` with mock databases
- Verify `filter_analyzed_only=True` is passed to pipeline

### Integration Tests
- End-to-end: POST request → job creation → processing → completion
- Verify only analyzed files are ingested
- Verify event clusters with AI analysis are included

### UI Tests
- Button enabled/disabled based on task selection
- Progress bar updates correctly
- Success/error messages display properly

## API Specification

### POST /api/graphiti/ingest (Extended)

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

- [ ] Backend: Add `ANALYZED_ONLY` to `IngestionMode` enum
- [ ] Backend: Implement `_process_analyzed_only()` in `IngestionJobManager`
- [ ] Backend: Update `_process_job()` to handle new mode
- [ ] Frontend: Add `reingestAnalyzedData()` service method
- [ ] Frontend: Add management toolbar component to KnowledgeGraph page
- [ ] Frontend: Add state for re-ingestion progress
- [ ] Frontend: Add job polling for re-ingestion status
- [ ] Testing: Unit tests for new mode
- [ ] Testing: Integration test end-to-end
- [ ] Documentation: Update API reference

## Rollout Plan

1. Phase 1: Backend implementation and testing
2. Phase 2: Frontend implementation and testing
3. Phase 3: Integration testing and documentation
4. Phase 4: Deploy to development environment for validation
