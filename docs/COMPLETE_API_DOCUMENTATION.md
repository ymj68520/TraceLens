# Forensic Analysis HTTP Server - Complete API Documentation

## Overview

This comprehensive HTTP server provides a complete REST API for digital forensics analysis, built on top of The Sleuth Kit (TSK) 4.14.0. The API supports disk image analysis (E01, DD formats), timeline generation, file classification, and specialized Android forensics.

## Base URL

```
http://localhost:8080/api
```

## Authentication

Currently, no authentication is required (keeping it simple as requested). All operations are authorized through task-based access control.

## Response Format

All API responses follow this standard structure:

### Success Response
```json
{
  "success": true,
  "data": {...},
  "timestamp": 1640995200000
}
```

### Error Response
```json
{
  "success": false,
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "Task not found",
    "details": "Task ID xyz does not exist"
  },
  "timestamp": 1640995200000
}
```

## Task Management Endpoints

### 1. Create Analysis Task
```
POST /tasks
```

**Request Body:**
```json
{
  "image_path": "/path/to/image.e01",
  "android_analyze": false,
  "priority": "normal",
  "metadata": {
    "case_id": "CASE-001",
    "analyst": "john.doe"
  },
  "dependencies": [],
  "xfs_mode": "auto",
  "db_output_dir": "/output/directory"
}
```

**Response:**
```json
{
  "task_id": "c95065c7-624e-4fc7-83d8-9bee17f556e3",
  "status": "created",
  "priority": "normal",
  "dependencies_count": 0
}
```

### 2. Get Task Status
```
GET /tasks/{task_id}
```

**Response:**
```json
{
  "id": "c95065c7-624e-4fc7-83d8-9bee17f556e3",
  "image_path": "/path/to/image.e01",
  "status": "completed",
  "priority": "normal",
  "message": "Analysis completed successfully",
  "progress": {
    "current_phase": "finalizing",
    "phase_percentage": 100,
    "overall_percentage": 100,
    "phase_description": "Analysis completed successfully"
  },
  "timestamps": {
    "created": 1640995200000,
    "started": 1640995260000,
    "completed": 1640995800000,
    "execution_time_seconds": 540
  }
}
```

### 3. Get Task Results
```
GET /tasks/{task_id}/results
```

**Response:**
```json
{
  "task_id": "c95065c7-624e-4fc7-83d8-9bee17f556e3",
  "status": "completed",
  "results": {
    "summary": [
      {
        "category": "documents",
        "file_count": 1250,
        "total_size": 524288000
      }
    ]
  }
}
```

### 4. List All Tasks
```
GET /api/tasks/list?status={status}&priority={priority}&limit={limit}&offset={offset}
```

### 5. Cancel Task
```
DELETE /api/tasks/{task_id}
```

**Request Body (optional):**
```json
{
  "reason": "User requested cancellation"
}
```

### 6. Get Task Statistics
```
GET /api/tasks/statistics
```

### 7. Batch Operations
```
POST /api/tasks/batch-create
POST /api/tasks/batch-status
POST /api/tasks/batch-cancel
```

## Database Query Endpoints

All database endpoints require a `task_id` parameter to ensure proper authorization.

### Raw Database Queries

#### Get Files
```
GET /api/raw/files?task_id={id}&limit={n}&offset={n}&sort_by={field}&sort_order={asc|desc}
```

**Response:**
```json
{
  "data": [
    {
      "inode": 12345,
      "name": "document.pdf",
      "path": "/home/user/documents/document.pdf",
      "size": 1048576,
      "mtime": 1640995200,
      "md5": "5d41402abc4b2a76b9719d911017c592"
    }
  ],
  "pagination": {
    "total": 5000,
    "limit": 100,
    "offset": 0,
    "has_more": true
  }
}
```

#### Search Files
```
GET /api/raw/search?task_id={id}&q={search_term}&limit={n}
```

#### Get Partitions
```
GET /api/raw/partitions?task_id={id}
```

### Events Database Queries

#### Get Timeline
```
GET /api/events/timeline?task_id={id}&limit={n}&sort_by={field}
```

#### Get Statistics
```
GET /api/events/statistics?task_id={id}
```

#### Get Hourly Activity
```
GET /api/events/hourly-activity?task_id={id}
```

### Files Database Queries

#### Get Files by Category
```
GET /api/files/category/{category}?task_id={id}&limit={n}
```

**Categories:** `images`, `videos`, `audio`, `documents`, `archives`, `executables`, `databases`, `source_code`, `web_files`, `email_files`, `system_files`, `encrypted_files`, `unknown_files`

#### Get Deleted Files
```
GET /api/files/deleted?task_id={id}&limit={n}
```

#### Get Extensions Analysis
```
GET /api/files/extensions?task_id={id}
```

### Android Database Queries (if available)

#### Get SMS Messages
```
GET /api/android/sms?task_id={id}&limit={n}&filter={value}
```

#### Get Contacts
```
GET /api/android/contacts?task_id={id}&search={term}
```

#### Get Call Logs
```
GET /api/android/call-logs?task_id={id}&sort_by={field}
```

## Specialized Forensic Analysis Endpoints

### Timeline Analysis

#### Comprehensive Timeline
```
GET /api/forensics/timeline/comprehensive?task_id={id}&start_time={timestamp}&end_time={timestamp}
```

#### File Activity Timeline
```
GET /api/forensics/timeline/file-activity?task_id={id}&file_path={path}&inode={number}
```

#### Suspicious Patterns
```
GET /api/forensics/timeline/suspicious-patterns?task_id={id}
```

#### User Activity Analysis
```
GET /api/forensics/timeline/user-activity?task_id={id}
```

### File Analysis

#### Get Largest Files
```
GET /api/forensics/files/largest?task_id={id}&limit={n}
```

#### Get Recent Files
```
GET /api/forensics/files/recent?task_id={id}&hours={n}
```

#### Get Suspicious Files
```
GET /api/forensics/files/suspicious?task_id={id}
```

#### Get Duplicate Files
```
GET /api/forensics/files/duplicates?task_id={id}
```

#### Extensions Analysis
```
GET /api/forensics/files/extensions-analysis?task_id={id}
```

### Android Forensics

#### Communication Summary
```
GET /api/forensics/android/communication-summary?task_id={id}
```

#### App Usage Analysis
```
GET /api/forensics/android/app-usage?task_id={id}
```

#### Device Information
```
GET /api/forensics/android/device-info?task_id={id}
```

#### Media Analysis
```
GET /api/forensics/android/media-analysis?task_id={id}
```

### Statistical Analysis

#### Overview Statistics
```
GET /api/forensics/statistics/overview?task_id={id}
```

#### File Distribution
```
GET /api/forensics/statistics/file-distribution?task_id={id}
```

#### Activity Patterns
```
GET /api/forensics/statistics/activity-patterns?task_id={id}
```

#### Deleted Files Analysis
```
GET /api/forensics/statistics/deleted-files-analysis?task_id={id}
```

## System Information and Monitoring

### System Health
```
GET /api/system/health
```

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "task_management": {
    "total_tasks": 25,
    "running_tasks": 2,
    "failed_tasks": 1
  },
  "services": {
    "http_server": "running",
    "task_manager": "running",
    "database_access": "available"
  }
}
```

### System Information
```
GET /api/system/info
```

### Database Information
```
GET /api/system/databases?task_id={id}
```

### Database Schema
```
GET /api/system/database-schema/{db_type}
```

**db_type options:** `raw`, `events`, `files`, `android`

## Utility Endpoints

### API Documentation
```
GET /api/docs/endpoints
```

### Database Schema Documentation
```
GET /api/docs/database-schema
```

### Export Results
```
POST /api/export/{task_id}
```

**Request Body:**
```json
{
  "format": "json",
  "export_type": "summary"
}
```

**export_type options:** `summary`, `database`

## Advanced Query Endpoint

For complex custom queries:

```
POST /api/query
```

**Request Body:**
```json
{
  "task_id": "c95065c7-624e-4fc7-83d8-9bee17f556e3",
  "database_type": "raw",
  "query": "SELECT * FROM files WHERE size > 1000000 ORDER BY size DESC LIMIT 50"
}
```

## Common Usage Patterns

### 1. Complete Forensic Analysis Workflow
```bash
# 1. Create analysis task
curl -X POST http://localhost:8080/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/path/to/image.e01",
    "android_analyze": true,
    "priority": "high"
  }'

# 2. Check task status
curl http://localhost:8080/tasks/{task_id}

# 3. Get results when completed
curl http://localhost:8080/tasks/{task_id}/results
```

### 2. Timeline Analysis
```bash
# Get comprehensive timeline
curl "http://localhost:8080/api/forensics/timeline/comprehensive?task_id={id}&start_time=1640995200&end_time=1641081600"

# Find suspicious patterns
curl "http://localhost:8080/api/forensics/timeline/suspicious-patterns?task_id={id}"
```

### 3. File Investigation
```bash
# Get largest files
curl "http://localhost:8080/api/forensics/files/largest?task_id={id}&limit=100"

# Get suspicious files
curl "http://localhost:8080/api/forensics/files/suspicious?task_id={id}"

# Search for specific files
curl "http://localhost:8080/api/raw/search?task_id={id}&q=document.pdf"
```

### 4. Android Forensics
```bash
# Get communication summary
curl "http://localhost:8080/api/forensics/android/communication-summary?task_id={id}"

# Get device information
curl "http://localhost:8080/api/forensics/android/device-info?task_id={id}"
```

## Error Codes

| Error Code | Description |
|------------|-------------|
| TASK_NOT_FOUND | Task ID does not exist |
| TASK_NOT_COMPLETED | Task must be completed before this operation |
| DATABASE_NOT_FOUND | Database file not found |
| INVALID_PARAMETERS | Request parameters are invalid |
| ACCESS_DENIED | Task-based access control failed |
| SYSTEM_ERROR | Internal system error |

## Performance Considerations

- Use pagination (`limit`, `offset`) for large result sets
- Cache frequently accessed results
- Monitor system health endpoint for performance metrics
- Use batch operations for multiple tasks
- Custom queries should include LIMIT clauses

## Rate Limiting

Currently no rate limiting is implemented, but consider implementing for production use.

## Supported File Formats

- **Disk Images:** E01 (via libewf), DD
- **Filesystems:** NTFS, FAT, EXT2/3/4, XFS
- **Android:** APK analysis, SQLite databases (SMS, WhatsApp, contacts, call logs)

## Database Schema Overview

### Raw Database (`*_raw.db`)
- `files` - Complete filesystem metadata
- `partitions` - Disk partition information

### Events Database (`*_events.db`)
- `events` - Timeline events (created, modified, accessed, changed, deleted)
- Specialized event tables for each event type

### Files Database (`*_files.db`)
- `files` - Master categorized files table
- Category-specific tables (images, videos, documents, etc.)

### Android Database (`*_android.db`) (optional)
- `sms_messages` - SMS message records
- `whatsapp_messages` - WhatsApp conversations
- `contacts` - Contact information
- `call_logs` - Call history

## SDK Integration

The API can be easily integrated with:
- **Python:** `requests` library
- **JavaScript:** `fetch` API or `axios`
- **Java:** Apache HttpClient
- **C#:** HttpClient
- **Go:** net/http package

Example Python client:
```python
import requests

class ForensicsAPI:
    def __init__(self, base_url="http://localhost:8080"):
        self.base_url = base_url

    def create_task(self, image_path, android_analyze=False):
        response = requests.post(f"{self.base_url}/tasks", json={
            "image_path": image_path,
            "android_analyze": android_analyze
        })
        return response.json()

    def get_task_status(self, task_id):
        response = requests.get(f"{self.base_url}/tasks/{task_id}")
        return response.json()

    def get_timeline(self, task_id):
        response = requests.get(f"{self.base_url}/api/forensics/timeline/comprehensive",
                              params={"task_id": task_id})
        return response.json()

# Usage
api = ForensicsAPI()
task = api.create_task("/path/to/image.e01", android_analyze=True)
task_id = task["task_id"]

# Wait for completion, then get results
import time
while True:
    status = api.get_task_status(task_id)
    if status["status"] == "completed":
        break
    time.sleep(5)

timeline = api.get_timeline(task_id)
```