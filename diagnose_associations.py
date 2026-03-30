#!/usr/bin/env python3
"""
Quick diagnostic script for association API issues.
Run this after starting Python service.
"""
import sys
import json
import sqlite3

try:
    import requests
except ImportError:
    print("Installing requests module...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

def check_database_structure(db_path):
    """Check if files database exists and has correct structure."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        tables = [row[0] for row in cursor.fetchall()]

        print(f"✓ Database exists: {db_path}")
        print(f"  Tables: {tables}")

        # Check first table's structure
        if tables:
            table = tables[0]
            cursor.execute(f"PRAGMA table_info({table});")
            columns = cursor.fetchall()
            print(f"\n  Sample table '{table}' columns:")
            for col in columns:
                print(f"    - {col[1]} ({col[2]})")

        conn.close()
        return True
    except Exception as e:
        print(f"✗ Database error: {e}")
        return False

def check_events_structure(db_path):
    """Check events database structure."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get events table structure
        cursor.execute("PRAGMA table_info(events);")
        columns = cursor.fetchall()

        print(f"✓ Events database: {db_path}")
        print(f"  Events table columns:")
        for col in columns:
            print(f"    - {col[1]} ({col[2]})")

        # Check if data exists
        cursor.execute("SELECT COUNT(*) FROM events LIMIT 1;")
        count = cursor.fetchone()[0]
        print(f"  Events count: {count}")

        # Get sample row
        cursor.execute("SELECT * FROM events LIMIT 1;")
        row = cursor.fetchone()
        if row:
            print(f"  Sample event: {row[:5]}...")  # First 5 columns

        conn.close()
        return True
    except Exception as e:
        print(f"✗ Events database error: {e}")
        return False

def test_api_with_sample_data():
    """Test API with sample data."""
    import requests

    # Replace with actual task ID
    task_id = "test_task"

    # Test cluster-files
    print("\n=== Testing /api/associations/cluster-files ===")
    cluster_data = {
        "task_id": task_id,
        "time_window": 123456,
        "event_type": "CREATED",
        "parent_directory": "/test",
        "limit": 5
    }

    try:
        response = requests.post(
            "http://localhost:8090/api/associations/cluster-files",
            json=cluster_data,
            timeout=10
        )
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Success! Got {len(result.get('files', []))} files")
            print(f"Response structure: {list(result.keys())}")
        else:
            print(f"Error: {response.text}")
    except requests.exceptions.ConnectionError:
        print("✗ Connection refused - Is Python service running on port 8090?")
    except Exception as e:
        print(f"✗ Error: {e}")

    # Test file-clusters
    print("\n=== Testing /api/associations/file-clusters ===")
    file_data = {
        "task_id": task_id,
        "file_path": "/test/path.txt",
        "limit": 5
    }

    try:
        response = requests.post(
            "http://localhost:8090/api/associations/file-clusters",
            json=file_data,
            timeout=10
        )
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Success! Got {len(result.get('clusters', []))} clusters")
            print(f"Response structure: {list(result.keys())}")
        else:
            print(f"Error: {response.text}")
    except requests.exceptions.ConnectionError:
        print("✗ Connection refused - Is Python service running on port 8090?")
    except Exception as e:
        print(f"✗ Error: {e}")

def main():
    print("=== Forensics Association API Diagnostic ===\n")

    # Check if Python service is running
    try:
        response = requests.get("http://localhost:8090/health", timeout=5)
        if response.status_code == 200:
            print("✓ Python service is running on port 8090")
        else:
            print("✗ Python service returned non-200 status")
            return
    except requests.exceptions.ConnectionError:
        print("✗ Cannot connect to Python service on port 8090")
        print("  Start the service with: cd python_service && python -m httpserver.main")
        return

    # Check database structures if we can find them
    print("\n=== Checking Database Structures ===")
    # Try to find task databases
    import os
    task_dirs = []
    if os.path.exists("build/data/tasks"):
        task_dirs = [d for d in os.listdir("build/data/tasks") if os.path.isdir(os.path.join("build/data/tasks", d))]

    if task_dirs:
        print(f"Found task directories: {task_dirs[:3]}...")  # Show first 3
        for task_dir in task_dirs[:1]:  # Check first task
            files_db = None
            events_db = None

            # Find databases
            for root, dirs, files in os.walk(os.path.join("build/data/tasks", task_dir)):
                for file in files:
                    if file.endswith("_files.db"):
                        files_db = os.path.join(root, file)
                    elif file.endswith("_events.db"):
                        events_db = os.path.join(root, file)

            if files_db:
                check_database_structure(files_db)
            if events_db:
                check_events_structure(events_db)
    else:
        print("No local task databases found in build/data/tasks/")

    # Test API
    test_api_with_sample_data()

if __name__ == "__main__":
    main()
