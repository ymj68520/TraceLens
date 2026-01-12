#!/bin/bash
SERVER_CMD="./build/forensic_analyzer --http-server 8082"
# 使用 E01 文件的绝对路径
IMAGE_PATH="/home/ymj68520/David_USB_8GB.e01"
OUTPUT_DIR="$(pwd)/tests"

# Clean up previous test artifacts in tests/ dir
rm -f "$OUTPUT_DIR"/David_USB_8GB_*.db

# Start server in background on port 8082 to avoid conflicts
$SERVER_CMD > server_tests_dir.log 2>&1 &
SERVER_PID=$!
echo "Server started with PID $SERVER_PID on port 8082"

# Wait for server to start
sleep 3

# Create Task with android_analyze=true and db_output_dir="tests"
echo "Creating task for E01 image with output dir 'tests'..."
RESPONSE=$(curl --noproxy '*' -s -X POST http://localhost:8082/tasks \
  -H "Content-Type: application/json" \
  -d "{\"image_path\": \"$IMAGE_PATH\", \"android_analyze\": true, \"db_output_dir\": \"$OUTPUT_DIR\"}")

echo "Create Response: $RESPONSE"
TASK_ID=$(echo $RESPONSE | grep -o '"task_id":"[^"]*"' | cut -d'"' -f4)

if [ -z "$TASK_ID" ]; then
  echo "Failed to create task"
  cat server_tests_dir.log
  kill $SERVER_PID
  exit 1
fi

echo "Task ID: $TASK_ID"

# Poll Status
STATUS="pending"
while [ "$STATUS" != "completed" ] && [ "$STATUS" != "failed" ]; do
  sleep 2
  STATUS_RES=$(curl --noproxy '*' -s http://localhost:8082/tasks/$TASK_ID)
  STATUS=$(echo $STATUS_RES | grep -o '"status":"[^"”]*"' | cut -d'"' -f4)
  echo "Status: $STATUS"
  if [ "$STATUS" == "running" ]; then
      MSG=$(echo $STATUS_RES | grep -o '"message":"[^"”]*"' | cut -d'"' -f4)
      echo "  Message: $MSG"
  fi
done

if [ "$STATUS" == "failed" ]; then
  echo "Task failed!"
  # Print error message from status
  echo "Response: $STATUS_RES"
  cat server_tests_dir.log
  kill $SERVER_PID
  exit 1
fi

# Kill server
kill $SERVER_PID

# Verify files exist in tests/ dir
echo "Verifying output files in $OUTPUT_DIR:"
ls -l "$OUTPUT_DIR"/David_USB_8GB_*.db
