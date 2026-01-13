#!/bin/bash
set -e

# 1. Generate test data
python3 scripts/create_test_data.py

# 2. Create raw image file (100MB)
echo "Creating 100MB raw image..."
dd if=/dev/zero of=test_image.img bs=1M count=100

# 3. Format as ext4 (force non-interactive)
echo "Formatting as ext4..."
mkfs.ext4 -F test_image.img

# 4. Copy files using debugfs
echo "Copying files into image..."
DATA_DIR="tests/test_data_13"

# Create a command file for debugfs
CMD_FILE=debugfs_cmds.txt
echo "cd /" > $CMD_FILE

for file in "$DATA_DIR"/*; do
    if [ -f "$file" ]; then
        filename=$(basename "$file")
        echo "write $file $filename" >> $CMD_FILE
    fi
done

echo "ls -l" >> $CMD_FILE

# Execute debugfs
/usr/sbin/debugfs -w -f $CMD_FILE test_image.img

# Cleanup
rm $CMD_FILE

echo "Test image 'test_image.img' created successfully."
