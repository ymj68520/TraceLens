"""
Test associations API directly
"""
import requests
import json

# Test data - replace with actual task ID
task_id = "your_task_id"

# Test cluster-files (replace with actual cluster data)
cluster_request = {
    "task_id": task_id,
    "time_window": 123456789,  # Example value
    "event_type": "CREATED",
    "parent_directory": "/path/to/dir",
    "limit": 10
}

print("Testing /api/associations/cluster-files...")
print(f"Request: {json.dumps(cluster_request, indent=2)}")

try:
    response = requests.post(
        "http://localhost:8090/api/associations/cluster-files",
        json=cluster_request
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
except Exception as e:
    print(f"Error: {e}")

# Test file-clusters
file_request = {
    "task_id": task_id,
    "file_path": "/some/file/path.txt",
    "limit": 10
}

print("\nTesting /api/associations/file-clusters...")
print(f"Request: {json.dumps(file_request, indent=2)}")

try:
    response = requests.post(
        "http://localhost:8090/api/associations/file-clusters",
        json=file_request
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
except Exception as e:
    print(f"Error: {e}")
