# Windows Artifacts Analysis Package

This package provides LLM-driven analysis of Windows forensic artifacts including registry values, event logs, browser history, prefetch files, and other Windows-specific traces.

## Overview

The Windows artifacts analysis pipeline integrates with the main case analysis service to provide comprehensive forensic analysis of Windows systems. All LLM processing is done on the Python side (C++ LLM code is deprecated).

## Components

### WindowsArtifactFilter (`windows_filter.py`)

Filters Windows artifacts by case description using LLM.

**Supported Artifact Types:**
- `registry_values` - Registry key/value pairs
- `event_log_entries` - Windows event log entries
- `prefetch_files` - Application prefetch records
- `browser_history` - Browser history entries
- `windows_services` - Windows service records
- `scheduled_tasks` - Scheduled task records
- `amcache_entries` - Amcache program execution entries
- `srum_entries` - SRUM usage tracking entries
- `usb_devices` - USB device connection records
- `user_accounts` - User account information

### WindowsArtifactAnalyzer (`windows_analyzer.py`)

Generates LLM descriptions for Windows artifacts.

**Analysis Output:**
- `summary` - Brief summary (50-100 chars)
- `description` - Detailed description (200-500 chars)
- `keywords` - Extracted keywords
- `severity` - low/medium/high/critical
- `relevance` - 0.0-1.0 relevance score
- `model_used` - LLM model name
- `analyzed_at` - Analysis timestamp

### WindowsArtifactTOONExporter (`windows_toon_exporter.py`)

Exports Windows artifacts to TOON format for efficient LLM prompt integration.

**TOON Schema Examples:**
```
TOON.schema: key_path | value_name | value_data | summary | keywords
TOON.schema: log_name | event_id | level | timestamp | message | summary
TOON.schema: url | title | visit_count | last_visit | summary | keywords
```

### WindowsArtifactsService (`windows_integration.py`)

Service coordinator for Windows artifact processing.

**Public API:**
- `run_full_analysis()` - Run the full analysis pipeline
- `get_artifact_report()` - Retrieve persisted report
- `reanalyze_artifacts()` - Re-analyze with user hints
- `get_filtered_artifacts()` - Get filtered artifacts

## Database Schema

### New Table in _windows.db

```sql
CREATE TABLE IF NOT EXISTS windows_artifact_descriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_type TEXT NOT NULL,
    artifact_id INTEGER NOT NULL,
    summary TEXT,
    description TEXT,
    keywords TEXT,
    severity TEXT DEFAULT 'low',
    relevance REAL DEFAULT 0.0,
    model_used TEXT,
    analyzed_at INTEGER,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    UNIQUE(artifact_type, artifact_id)
);
```

## Usage Examples

### Analyze Windows Artifacts

```python
from services.windows_artifacts import WindowsArtifactsService

# Create service instance
windows_service = WindowsArtifactsService(settings)
windows_service.set_llm_service(llm_service)
windows_service.set_graphiti_service(graphiti_service)

# Run full analysis
result = await windows_service.run_full_analysis(
    task_id="task_123",
    windows_db_path="/path/to/image_windows.db",
    case_description="数据泄露案件调查",
    max_artifacts=200,
)

print(f"Selected: {result['filter']['selected_count']}")
print(f"Analyzed: {result['analysis']['analyzed_count']}")
```

### Export to TOON Format

```python
from services.windows_artifacts import WindowsArtifactTOONExporter

exporter = WindowsArtifactTOONExporter()

# Export specific artifact type
toon_data = exporter.export_artifacts_toon(
    windows_db_path="/path/to/image_windows.db",
    artifact_type="registry_values",
    include_llm=True,
    limit=100,
)

# Export all artifacts with LLM analysis
all_toon = exporter.export_artifacts_toon(
    windows_db_path="/path/to/image_windows.db",
    include_llm=True,
)
```

### Get Windows Report

```python
# Get persisted report
report = windows_service.get_artifact_report(
    windows_db_path="/path/to/image_windows.db",
    task_id="task_123",
)

print(f"Total analyzed: {report['total_analyzed']}")
print(f"By type: {report['by_type']}")
print(f"High priority: {len(report['high_priority_artifacts'])}")
```

## API Endpoints

### Start Windows Analysis
```http
POST /api/case-analysis/windows
Content-Type: application/json

{
  "task_id": "task_123",
  "files_db_path": "/path/to/image_files.db",
  "case_description": "数据泄露案件调查",
  "max_filter_files": 200
}
```

### Get Windows Report
```http
GET /api/case-analysis/windows-report/task_123
```

### Export to TOON
```http
GET /api/case-analysis/windows-export/task_123/toon?artifact_type=registry_values&severity=high&limit=100
```

## Integration with Case Analysis

The Windows artifacts service integrates seamlessly with the main case analysis service:

```python
# In case_analysis_service.py
case_service.set_windows_service(windows_service)

# Run combined analysis
await case_service.analyze_windows_artifacts(...)
await case_service.generate_case_report(...)  # Includes Windows artifacts
```

## Report Integration

Windows artifacts are automatically included in the final case report with a dedicated section:

```markdown
## Windows系统痕迹分析

### 痕迹统计
- **注册表记录**: 150条 (12条高优先级)
- **事件日志**: 200条 (25条高优先级)
- **浏览器历史**: 80条 (5条高优先级)

### 关键发现
- 🟠 **注册表记录**: 可疑的自启动项配置
- 🔴 **事件日志**: 多次失败的登录尝试
- 🟠 **浏览器历史**: 访问已知恶意域名
```

## TOON Format Benefits

- **30-60% token reduction** compared to JSON
- **Schema declaration** for LLM understanding
- **Tabular format** for easy parsing
- **Lossless conversion** to JSON if needed

## Configuration

No additional configuration required. The package uses existing settings:

- `llm_service` - For LLM analysis
- `graphiti_service` - Optional knowledge graph integration
- `llm_max_concurrency` - Concurrent analysis limit (default: 3)

## Error Handling

All modules include robust error handling with fallback mechanisms:

- Missing LLM service → RuntimeError with clear message
- Database errors → Logged and graceful degradation
- LLM failures → Retry with alternative prompts
- Invalid artifact types → Warning and skip

## Logging

Comprehensive logging at all levels:

- `INFO` - Progress updates, statistics
- `WARNING` - Non-fatal errors, fallbacks
- `ERROR` - Failed operations with stack traces
- `DEBUG` - Detailed artifact processing

## Performance Considerations

- **Concurrency**: Limited to 3 concurrent LLM calls by default
- **Batch Processing**: Artifacts processed in batches of 50 for filtering
- **Database Indexing**: Artifact descriptions table indexed for fast queries
- **Progress Callbacks**: All long-running operations support progress tracking

## Future Enhancements

Potential improvements:

1. **Event Clustering** - Cluster related Windows events for timeline analysis
2. **Pattern Detection** - Detect attack patterns across artifact types
3. **Timeline Integration** - Correlate Windows events with file system timeline
4. **Threat Intelligence** - Match artifacts against known threat indicators
5. **Visual Reports** - Generate visual graphs of artifact relationships
