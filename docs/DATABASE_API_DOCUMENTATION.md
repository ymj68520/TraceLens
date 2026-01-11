# Database Query API Documentation

This document describes the comprehensive database query APIs implemented as Phase 1 of the HTTPServer enhancement plan. These APIs provide powerful querying capabilities for forensic analysis databases.

## Overview

The enhanced HTTP server now supports direct database queries across four database types:
- **Raw Database** (`*_raw.db`): Complete filesystem metadata with files and partitions tables
- **Events Database** (`*_events.db`): Timeline events (created, modified, accessed, changed, deleted)
- **Files Database** (`*_files.db`): 13 categorized file tables (images, videos, audio, documents, etc.)
- **Android Database** (`*_android.db`): Specialized Android forensics data

## Authentication and Authorization

All database query endpoints require a valid `task_id` parameter to ensure only authorized database access. The task must be in COMPLETED status to allow database access.

## Common Query Parameters

All GET endpoints support the following optional query parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 100 | Maximum number of records to return (capped at 1000) |
| `offset` | integer | 0 | Number of records to skip for pagination |
| `search` | string | - | Search term for text-based queries |
| `sort_by` | string | - | Column name to sort by |
| `sort_order` | string | ASC | Sort order: ASC or DESC |
| `filter_field` | string | - | Column name to filter on |
| `filter_value` | string | - | Value to filter with (uses LIKE operator) |

## API Endpoints

### Raw Database Endpoints

#### Get Raw Files
```
GET /api/raw/files?task_id={task_id}&limit={limit}&offset={offset}&sort_by={field}&sort_order={order}
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
      "atime": 1640995200,
      "mtime": 1640995200,
      "ctime": 1640995200,
      "crtime": 1640995200,
      "type": "file",
      "mode": 644,
      "uid": 1000,
      "gid": 1000,
      "is_deleted": false,
      "is_allocated": true
    }
  ]
}
```

#### Get Raw Partitions
```
GET /api/raw/partitions?task_id={task_id}&limit={limit}&offset={offset}
```

#### Search Raw Files
```
GET /api/raw/search?task_id={task_id}&q={search_term}&limit={limit}&offset={offset}
```

### Events Database Endpoints

#### Get Events Timeline
```
GET /api/events/timeline?task_id={task_id}&limit={limit}&offset={offset}&sort_by={field}
```

**Response:**
```json
{
  "data": [
    {
      "id": 1,
      "timestamp": 1640995200,
      "event_type": "created",
      "file_path": "/home/user/new_file.txt",
      "inode": 12346,
      "description": "File created",
      "file_size": 1024,
      "file_type": "text"
    }
  ]
}
```

#### Get Events Statistics
```
GET /api/events/statistics?task_id={task_id}
```

**Response:**
```json
{
  "data": [
    {
      "event_type": "created",
      "count": 1250
    },
    {
      "event_type": "modified",
      "count": 3400
    },
    {
      "event_type": "deleted",
      "count": 45
    }
  ]
}
```

#### Get Hourly Activity
```
GET /api/events/hourly-activity?task_id={task_id}
```

**Response:**
```json
{
  "data": [
    {"hour": "00", "count": 45},
    {"hour": "01", "count": 23},
    {"hour": "09", "count": 156},
    {"hour": "14", "count": 234}
  ]
}
```

### Files Database Endpoints

#### Get Files by Category
```
GET /api/files/category/{category}?task_id={task_id}&limit={limit}&offset={offset}
```

**Available categories:**
- `images` - Image files (jpg, png, gif, etc.)
- `videos` - Video files (mp4, avi, mov, etc.)
- `audio` - Audio files (mp3, wav, flac, etc.)
- `documents` - Document files (pdf, doc, txt, etc.)
- `archives` - Archive files (zip, tar, rar, etc.)
- `executables` - Executable files
- `databases` - Database files
- `source_code` - Source code files
- `web_files` - Web-related files
- `email_files` - Email files
- `system_files` - System files
- `encrypted_files` - Encrypted files
- `unknown_files` - Unknown file types

#### Get Deleted Files
```
GET /api/files/deleted?task_id={task_id}&limit={limit}&offset={offset}
```

**Response:**
```json
{
  "data": [
    {
      "name": "deleted_file.txt",
      "path": "/tmp/deleted_file.txt",
      "size": 512,
      "extension": "txt",
      "category": "documents",
      "is_deleted": true,
      "mtime": 1640995200
    }
  ],
  "total_count": 23
}
```

#### Get File Extensions
```
GET /api/files/extensions?task_id={task_id}
```

**Response:**
```json
{
  "data": [
    {
      "extension": "txt",
      "count": 1250,
      "total_size": 52428800
    },
    {
      "extension": "pdf",
      "count": 345,
      "total_size": 1073741824
    }
  ]
}
```

### Android Database Endpoints

#### Get Android SMS
```
GET /api/android/sms?task_id={task_id}&limit={limit}&offset={offset}&filter_field={field}&filter_value={value}
```

**Response:**
```json
{
  "data": [
    {
      "id": 1,
      "address": "+1234567890",
      "person": "John Doe",
      "date": 1640995200000,
      "date_sent": 1640995200000,
      "read": 1,
      "status": -1,
      "type": 1,
      "body": "Hello, how are you?",
      "subject": null
    }
  ]
}
```

#### Get Android Contacts
```
GET /api/android/contacts?task_id={task_id}&limit={limit}&offset={offset}&search={term}
```

#### Get Android Call Logs
```
GET /api/android/call-logs?task_id={task_id}&limit={limit}&offset={offset}&sort_by=number
```

### Advanced Query Endpoint

#### Execute Custom SQL Query
```
POST /api/query
Content-Type: application/json

{
  "task_id": "your-task-id",
  "database_type": "raw|events|files|android",
  "query": "SELECT name, path, size FROM files WHERE size > 1048576 ORDER BY size DESC LIMIT 50"
}
```

**Security Features:**
- Only SELECT statements are allowed
- Multiple statements are blocked
- Input validation and sanitization
- Database type validation

**Response:**
```json
{
  "data": [
    {
      "name": "large_video.mp4",
      "path": "/home/user/videos/large_video.mp4",
      "size": 1073741824
    }
  ],
  "row_count": 1
}
```

## Error Handling

All endpoints return consistent error responses:

**400 Bad Request:**
```json
{
  "error": "task_id parameter is required"
}
```

**404 Not Found:**
```json
{
  "error": "Invalid task_id or database type",
  "task_id": "invalid-task-id",
  "db_type": "raw"
}
```

**500 Internal Server Error:**
```json
{
  "error": "Failed to query raw files",
  "message": "Database connection failed",
  "task_id": "task-id"
}
```

## Performance Considerations

### Pagination
- Always use `limit` parameter to avoid returning too much data
- Use `offset` for pagination through large result sets
- Maximum limit is capped at 1000 records per request

### Indexing
The database schemas include proper indexing for:
- Primary keys (inode, timestamp)
- Foreign keys (file relationships)
- Common query fields (name, path, size, type)
- Event timestamps for timeline queries

### Caching
- Database connections are managed efficiently
- Query results are not cached by default to ensure real-time data
- Consider implementing application-level caching for frequently accessed data

## Security Features

1. **Task-based Access Control**: All queries require a valid task_id
2. **Database Isolation**: Each task can only access its own databases
3. **SQL Injection Protection**: Custom query endpoint only allows SELECT statements
4. **Input Validation**: All parameters are validated and sanitized
5. **Rate Limiting**: Consider implementing rate limiting for production use

## Usage Examples

### Example 1: Find Large Files
```bash
curl "http://localhost:8080/api/raw/files?task_id=abc123&sort_by=size&sort_order=DESC&limit=50"
```

### Example 2: Search for Specific File Type
```bash
curl "http://localhost:8080/api/files/category/documents?task_id=abc123&filter_field=extension&filter_value=pdf"
```

### Example 3: Get Recent Events
```bash
curl "http://localhost:8080/api/events/timeline?task_id=abc123&sort_by=timestamp&sort_order=DESC&limit=100"
```

### Example 4: Custom Analysis Query
```bash
curl -X POST http://localhost:8080/api/query \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "abc123",
    "database_type": "raw",
    "query": "SELECT extension, COUNT(*) as count, AVG(size) as avg_size FROM files WHERE is_deleted = 0 GROUP BY extension ORDER BY count DESC"
  }'
```

## Integration with Existing Forensic Workflows

These APIs are designed to integrate seamlessly with existing forensic analysis workflows:

1. **Post-analysis Querying**: Use after completing forensic analysis with the task management system
2. **Real-time Investigation**: Query results during live investigations
3. **Report Generation**: Feed API results into reporting tools
4. **Custom Analysis**: Build specialized analysis tools on top of the database APIs
5. **Dashboard Integration**: Power forensic dashboards and visualization tools

## Future Enhancements

Phase 2 will build upon these database query foundations to add:
- Advanced analytics and machine learning endpoints
- Cross-database correlation analysis
- Automated pattern detection
- Timeline visualization APIs
- Export and reporting capabilities