import os
import shutil

dir_path = "tests/test_data_13"
os.makedirs(dir_path, exist_ok=True)

# Define text-based files
files = {
    "file1.txt": "Simple text file for analysis.",
    "file2.md": "# Markdown Header\nThis is a markdown content example.",
    "file3.log": "2026-01-11 10:00:00 [INFO] System started successfully.",
    "file4.cpp": "const int x = 10;\nint main() { return 0; }",
    "file5.h": "#ifndef TEST_H\n#define TEST_H\n\nvoid test();\n\n#endif",
    "file6.html": "<!DOCTYPE html><html><body><h1>Hello World</h1></body></html>",
    "file7.json": "{\"key\": \"value\", \"id\": 123}",
    "file8.xml": "<?xml version=\"1.0\"?><root><item>Data</item></root>",
    "file9.csv": "id,name,role\n1,Admin,User\n2,Guest,User",
    "file10.sh": "#!/bin/bash\necho \"Hello from shell script\"",
    "file11.conf": "[General]\nenabled=true\nmode=test"
}

# Create text files
for filename, content in files.items():
    file_path = os.path.join(dir_path, filename)
    with open(file_path, "w") as f:
        f.write(content)
    print(f"Created {filename}")

# Copy image files (using existing samples in the project)
# We use existing images to ensure valid image data for the vision model routing
image_sources = [
    ("build/sample.jpg", "file12.jpg"),
    ("libs/cpp-dotenv/cpp-dotenv.png", "file13.png")
]

for src, dest_name in image_sources:
    dest_path = os.path.join(dir_path, dest_name)
    if os.path.exists(src):
        shutil.copy(src, dest_path)
        print(f"Copied {src} to {dest_name}")
    else:
        print(f"Warning: Source image {src} not found. Creating dummy {dest_name}")
        # Create a dummy file if source missing (won't work for real vision analysis but satisfies file existence)
        with open(dest_path, "wb") as f:
            f.write(b"Dummy image content")

print(f"\nTest data created in {dir_path}")
