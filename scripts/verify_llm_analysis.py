import requests
import time
import sys
import json

BASE_URL = "http://localhost:8080"
IMAGE_PATH = "/home/ymj68520/projects/Forensics/ForensicsProject/test_image.img"

def wait_for_server():
    print("Waiting for server...")
    for i in range(10):
        try:
            requests.get(f"{BASE_URL}/api/system/health")
            print("Server is up!")
            return True
        except requests.exceptions.ConnectionError:
            time.sleep(1)
    return False

def create_task():
    print("Creating task...")
    payload = {
        "image_path": IMAGE_PATH,
        "llm_analyze": True,
        "llm_mode": "smart"
    }
    response = requests.post(f"{BASE_URL}/tasks", json=payload)
    if response.status_code == 201:
        data = response.json()
        print(f"Task created: {data['task_id']}")
        return data['task_id']
    else:
        print(f"Failed to create task: {response.text}")
        sys.exit(1)

def monitor_task(task_id):
    print(f"Monitoring task {task_id}...")
    while True:
        response = requests.get(f"{BASE_URL}/tasks/{task_id}")
        data = response.json()
        status = data['status']
        phase = data.get('progress', {}).get('current_phase', 'unknown')
        
        print(f"Status: {status}, Phase: {phase}")
        
        if status in ['completed', 'failed', 'cancelled']:
            return data
        
        time.sleep(2)

def verify_results(data):
    print("\nVerifying results...")
    if data['status'] != 'completed':
        print("Test FAILED: Task did not complete successfully")
        return

    # Check for LLM analysis fields
    if not data.get('llm_analyze'):
        print("Test FAILED: llm_analyze flag missing or false")
        print("Full response data:")
        print(json.dumps(data, indent=2))
        return
        
    print("Test PASSED: Task completed with LLM analysis enabled")
    print(json.dumps(data, indent=2))

if __name__ == "__main__":
    if not wait_for_server():
        print("Server failed to start")
        sys.exit(1)
        
    task_id = create_task()
    result = monitor_task(task_id)
    verify_results(result)
