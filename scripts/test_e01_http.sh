#!/bin/bash
SERVER_CMD="./build/forensic_analyzer --http-server 8081"
# 使用 E01 文件的绝对路径
IMAGE_PATH="/home/ymj68520/David_USB_8GB.e01"

# Start server in background on port 8081 to avoid conflicts
$SERVER_CMD > server_e01.log 2>&1 &
SERVER_PID=$!
echo "Server started with PID $SERVER_PID on port 8081"

# Wait for server to start
sleep 3

# Create Task with android_analyze=true to verify robustness (like CLI test)
echo "Creating task for E01 image..."
RESPONSE=$(curl --noproxy '*' -s -X POST http://localhost:8081/tasks \
  -H "Content-Type: application/json" \
  -d "{\"image_path\": \"$IMAGE_PATH\", \"android_analyze\": true}")

echo "Create Response: $RESPONSE"
TASK_ID=$(echo $RESPONSE | grep -o '"task_id":"[^"]*"' | cut -d'"' -f4)

if [ -z "$TASK_ID" ]; then
  echo "Failed to create task"
  cat server_e01.log
  kill $SERVER_PID
  exit 1
fi

echo "Task ID: $TASK_ID"

# Poll Status
STATUS="pending"
while [ "$STATUS" != "completed" ] && [ "$STATUS" != "failed" ]; do
  sleep 2
  STATUS_RES=$(curl --noproxy '*' -s http://localhost:8081/tasks/$TASK_ID)
  STATUS=$(echo $STATUS_RES | grep -o '"status":"[^"].*"' | cut -d'"' -f4)
  echo "Status: $STATUS"
  if [ "$STATUS" == "running" ]; then
      MSG=$(echo $STATUS_RES | grep -o '"message":"[^"].*"' | cut -d'"' -f4)
      echo "  Message: $MSG"
  fi
done

if [ "$STATUS" == "failed" ]; then
  echo "Task failed!"
  # Print error message from status
  echo "Response: $STATUS_RES"
  cat server_e01.log
  kill $SERVER_PID
  exit 1
fi

# Get Results
echo "Retrieving results..."
RESULTS=$(curl --noproxy '*' -s http://localhost:8081/tasks/$TASK_ID/results)
echo "Results: $RESULTS"

# Kill server
kill $SERVER_PID
