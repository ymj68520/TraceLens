# Forensic Analysis HTTP Server - Usage Examples

## Quick Start Examples

### 1. Basic System Check
```bash
# Check if server is running
curl -s http://localhost:8080/api/system/health | jq

# Expected output:
{
  "status": "healthy",
  "version": "1.0.0",
  "task_management": {
    "total_tasks": 0,
    "running_tasks": 0,
    "failed_tasks": 0,
    "system_load": "low"
  },
  "services": {
    "http_server": "running",
    "task_manager": "running",
    "database_access": "available"
  }
}
```

### 2. Server Information
```bash
curl -s http://localhost:8080/api/system/info | jq '.'
# output 
# {
#   "api_name": "Forensic Analysis HTTP Server",
#   "capabilities": {
#     "android_forensics": true,
#     "batch_operations": true,
#     "deleted_file_recovery": true,
#     "file_classification": true,
#     "timeline_analysis": true
#   },
#   "database_types": [
#     "raw",
#     "events",
#     "files",
#     "android"
#   ],
#   "description": "Comprehensive REST API for digital forensics analysis",
#   "endpoints_count": 40,
#   "supported_filesystems": [
#     "NTFS",
#     "FAT",
#     "EXT2/3/4",
#     "XFS"
#   ],
#   "supported_formats": [
#     "E01",
#     "DD"
#   ],
#   "version": "1.0.0"
# }
```

### 3. API Documentation
```bash
curl -s http://localhost:8080/api/docs/endpoints | jq '.total_endpoints'
# Output: 40
```

## Complete Forensic Analysis Workflow

### Step 1: Create Analysis Task
```bash
curl -X POST http://localhost:8080/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/home/ymj68520/ForensicsProject/David_USB_8GB.e01",
    "android_analyze": true,
    "priority": "high",
    "metadata": {
      "case_id": "CASE-2024-001",
      "analyst": "forensic_expert",
      "description": "USB device analysis"
    }
  }' | jq

# Expected response:
{
  "task_id": "c95065c7-624e-4fc7-83d8-9bee17f556e3",
  "status": "created",
  "priority": "high",
  "dependencies_count": 0
}
```

### Step 2: Monitor Task Progress
```bash
# Get task status
TASK_ID="c95065c7-624e-4fc7-83d8-9bee17f556e3"

curl -s "http://localhost:8080/tasks/$TASK_ID" | jq '{
  id,
  status,
  progress: .progress.current_phase,
  phase_percentage: .progress.phase_percentage,
  overall_percentage: .progress.overall_percentage,
  message
}'
```

### Step 3: Get Detailed Progress
```bash
curl -s "http://localhost:8080/api/tasks/$TASK_ID/progress" | jq
```

### Step 4: Get Results When Completed
```bash
curl -s "http://localhost:8080/tasks/$TASK_ID/results" | jq '.results.summary'
```

## File Investigation Examples

### Search for Specific Files
```bash
# Search by filename
curl -s "http://localhost:8080/api/raw/search?task_id=$TASK_ID&q=document.pdf&limit=10" | jq

# Get files by category
curl -s "http://localhost:8080/api/files/category/documents?task_id=$TASK_ID&limit=50" | jq

# Get deleted files
curl -s "http://localhost:8080/api/files/deleted?task_id=$TASK_ID&limit=20" | jq
```

### File Size Analysis
```bash
# Get largest files
curl -s "http://localhost:8080/api/forensics/files/largest?task_id=$TASK_ID&limit=20" | jq

# Get recently modified files (last 24 hours)
curl -s "http://localhost:8080/api/forensics/files/recent?task_id=$TASK_ID&hours=24" | jq
```

### Suspicious File Detection
```bash
# Get suspicious files analysis
curl -s "http://localhost:8080/api/forensics/files/suspicious?task_id=$TASK_ID" | jq '.suspicious_files'

# Check for duplicates
curl -s "http://localhost:8080/api/forensics/files/duplicates?task_id=$TASK_ID" | jq '.duplicates'
```

## Timeline Analysis Examples

### Comprehensive Timeline
```bash
# Get all timeline events
curl -s "http://localhost:8080/api/forensics/timeline/comprehensive?task_id=$TASK_ID" | jq

# Get timeline for specific date range
START_TIME="1640995200"  # Unix timestamp
END_TIME="1641081600"
curl -s "http://localhost:8080/api/forensics/timeline/comprehensive?task_id=$TASK_ID&start_time=$START_TIME&end_time=$END_TIME" | jq
```

### Activity Patterns
```bash
# Suspicious patterns detection
curl -s "http://localhost:8080/api/forensics/timeline/suspicious-patterns?task_id=$TASK_ID" | jq '.suspicious_patterns'

# User activity analysis
curl -s "http://localhost:8080/api/forensics/timeline/user-activity?task_id=$TASK_ID" | jq '.most_active_directories'
```

### File-Specific Timeline
```bash
# Track activity for specific file
curl -s "http://localhost:8080/api/forensics/timeline/file-activity?task_id=$TASK_ID&file_path=suspicious.exe" | jq

# Track by inode
curl -s "http://localhost:8080/api/forensics/timeline/file-activity?task_id=$TASK_ID&inode=12345" | jq
```

## Android Forensics Examples

### Communication Analysis
```bash
# Get communication summary
curl -s "http://localhost:8080/api/forensics/android/communication-summary?task_id=$TASK_ID" | jq

# Get SMS messages
curl -s "http://localhost:8080/api/android/sms?task_id=$TASK_ID&limit=50" | jq

# Get call logs
curl -s "http://localhost:8080/api/android/call-logs?task_id=$TASK_ID&sort_by=date" | jq
```

### Device Information
```bash
# Get device information
curl -s "http://localhost:8080/api/forensics/android/device-info?task_id=$TASK_ID" | jq '.build_properties'

# Get installed apps
curl -s "http://localhost:8080/api/forensics/android/app-usage?task_id=$TASK_ID" | jq '.installed_apps'
```

## Statistical Analysis Examples

### Overview Statistics
```bash
# Get complete overview
curl -s "http://localhost:8080/api/forensics/statistics/overview?task_id=$TASK_ID" | jq

# File distribution analysis
curl -s "http://localhost:8080/api/forensics/statistics/file-distribution?task_id=$TASK_ID" | jq '.size_distribution'
```

### Activity Patterns
```bash
# Hourly activity patterns
curl -s "http://localhost:8080/api/forensics/statistics/activity-patterns?task_id=$TASK_ID" | jq '.daily_pattern'

# Deleted files analysis
curl -s "http://localhost:8080/api/forensics/statistics/deleted-files-analysis?task_id=$TASK_ID" | jq
```

## Batch Operations Examples

### Create Multiple Tasks
```bash
curl -X POST http://localhost:8080/api/tasks/batch-create \
  -H "Content-Type: application/json" \
  -d '{
    "image_paths": [
      "/path/to/image1.e01",
      "/path/to/image2.e01",
      "/path/to/image3.e01"
    ],
    "priority": "normal"
  }' | jq
```

### Batch Status Check
```bash
curl -X POST http://localhost:8080/api/tasks/batch-status \
  -H "Content-Type: application/json" \
  -d '{
    "task_ids": [
      "task-id-1",
      "task-id-2",
      "task-id-3"
    ]
  }' | jq '.summary'
```

## Task Management Examples

### List All Tasks
```bash
# List all tasks
curl -s "http://localhost:8080/api/tasks/list" | jq '.tasks | length'

# List only running tasks
curl -s "http://localhost:8080/api/tasks/list?status=running" | jq '.tasks'

# List with pagination
curl -s "http://localhost:8080/api/tasks/list?limit=10&offset=0" | jq '.pagination'
```

### Task Statistics
```bash
# Get comprehensive statistics
curl -s "http://localhost:8080/api/tasks/statistics" | jq

# Cancel a task
curl -X DELETE "http://localhost:8080/api/tasks/$TASK_ID" \
  -H "Content-Type: application/json" \
  -d '{"reason": "No longer needed"}'
```

## Database Direct Access Examples

### Raw Database Queries
```bash
# Get first 100 files
curl -s "http://localhost:8080/api/raw/files?task_id=$TASK_ID&limit=100" | jq '.data'

# Get partition information
curl -s "http://localhost:8080/api/raw/partitions?task_id=$TASK_ID" | jq
```

### Events Database Queries
```bash
# Get timeline events
curl -s "http://localhost:8080/api/events/timeline?task_id=$TASK_ID&limit=50" | jq

# Get event statistics
curl -s "http://localhost:8080/api/events/statistics?task_id=$TASK_ID" | jq
```

### Custom SQL Queries
```bash
curl -X POST http://localhost:8080/api/query \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "'$TASK_ID'",
    "database_type": "raw",
    "query": "SELECT name, path, size FROM files WHERE size > 1000000 ORDER BY size DESC LIMIT 10"
  }' | jq
```

## System Monitoring Examples

### Health Check
```bash
# System health
curl -s http://localhost:8080/api/system/health | jq '.status'

# Database information for a task
curl -s "http://localhost:8080/api/system/databases?task_id=$TASK_ID" | jq '.databases'
```

### Schema Documentation
```bash
# Get raw database schema
curl -s http://localhost:8080/api/system/database-schema/raw | jq

# Get events database schema
curl -s http://localhost:8080/api/system/database-schema/events | jq
```

## Export Examples

### Export Task Results
```bash
# Export summary
curl -X POST "http://localhost:8080/api/export/$TASK_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "format": "json",
    "export_type": "summary"
  }' | jq

# Export database information
curl -X POST "http://localhost:8080/api/export/$TASK_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "format": "json",
    "export_type": "database"
  }' | jq '.databases'
```

## Error Handling Examples

### Handle Common Errors
```bash
#!/bin/bash

# Function to handle API responses
handle_response() {
    local response=$1
    local error_code=$(echo $response | jq -r '.error.code // "SUCCESS"')

    if [ "$error_code" != "SUCCESS" ]; then
        echo "Error: $error_code"
        echo "Message: $(echo $response | jq -r '.error.message')"
        return 1
    else
        echo "Success: $(echo $response | jq -c '.data // .')"
        return 0
    fi
}

# Example usage
TASK_ID="invalid-task-id"
RESPONSE=$(curl -s "http://localhost:8080/tasks/$TASK_ID")
handle_response "$RESPONSE"

# Expected output:
# Error: TASK_NOT_FOUND
# Message: Task not found
```

## Python Client Examples

### Simple Python Client
```python
import requests
import json
import time

class ForensicsAPI:
    def __init__(self, base_url="http://localhost:8080"):
        self.base_url = base_url
        self.session = requests.Session()

    def create_task(self, image_path, android_analyze=False, priority="normal"):
        """Create a new forensic analysis task"""
        data = {
            "image_path": image_path,
            "android_analyze": android_analyze,
            "priority": priority
        }
        response = self.session.post(f"{self.base_url}/tasks", json=data)
        return response.json()

    def get_task_status(self, task_id):
        """Get task status"""
        response = self.session.get(f"{self.base_url}/tasks/{task_id}")
        return response.json()

    def wait_for_completion(self, task_id, poll_interval=5, timeout=3600):
        """Wait for task to complete"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = self.get_task_status(task_id)

            if status.get("status") in ["completed", "failed", "cancelled"]:
                return status

            print(f"Task {task_id} status: {status.get('status')} - {status.get('message')}")
            time.sleep(poll_interval)

        raise TimeoutError(f"Task {task_id} did not complete within {timeout} seconds")

    def get_timeline(self, task_id, start_time=None, end_time=None):
        """Get comprehensive timeline"""
        params = {"task_id": task_id}
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        response = self.session.get(f"{self.base_url}/api/forensics/timeline/comprehensive", params=params)
        return response.json()

    def get_suspicious_files(self, task_id):
        """Get suspicious files analysis"""
        response = self.session.get(f"{self.base_url}/api/forensics/files/suspicious",
                                   params={"task_id": task_id})
        return response.json()

# Usage example
def analyze_disk_image(image_path):
    api = ForensicsAPI()

    # Create task
    print(f"Creating analysis task for {image_path}...")
    task_result = api.create_task(image_path, android_analyze=True, priority="high")
    task_id = task_result["task_id"]
    print(f"Task created with ID: {task_id}")

    # Wait for completion
    print("Waiting for analysis to complete...")
    final_status = api.wait_for_completion(task_id)

    if final_status["status"] == "completed":
        print("Analysis completed successfully!")

        # Get timeline
        timeline = api.get_timeline(task_id)
        print(f"Timeline contains {len(timeline.get('timeline', []))} events")

        # Get suspicious files
        suspicious = api.get_suspicious_files(task_id)
        print(f"Found {len(suspicious.get('suspicious_files', []))} suspicious file categories")

        return task_id
    else:
        print(f"Analysis failed: {final_status.get('message')}")
        return None

# Run analysis
if __name__ == "__main__":
    task_id = analyze_disk_image("/path/to/image.e01")
    if task_id:
        print(f"Analysis completed. Task ID: {task_id}")
```

## Performance Monitoring

### Monitor Server Performance
```bash
#!/bin/bash

# Performance monitoring script
MONITOR_URL="http://localhost:8080"
INTERVAL=30

while true; do
    echo "=== $(date) ==="

    # System health
    HEALTH=$(curl -s "$MONITOR_URL/api/system/health")
    TOTAL_TASKS=$(echo $HEALTH | jq '.task_management.total_tasks')
    RUNNING_TASKS=$(echo $HEALTH | jq '.task_management.running_tasks')

    echo "Total Tasks: $TOTAL_TASKS"
    echo "Running Tasks: $RUNNING_TASKS"

    # Task statistics
    STATS=$(curl -s "$MONITOR_URL/api/tasks/statistics")
    COMPLETED=$(echo $STATS | jq '.by_status.completed')
    FAILED=$(echo $STATS | jq '.by_status.failed')

    echo "Completed: $COMPLETED"
    echo "Failed: $FAILED"

    echo "------------------------"
    sleep $INTERVAL
done
```

These examples provide a comprehensive guide for using the Forensic Analysis HTTP Server API, covering everything from basic operations to advanced forensic analysis workflows.