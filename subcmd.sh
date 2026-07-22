#!/usr/bin/env bash
set -e
git init /tmp/tracelens-snapshot >/dev/null 2>&1 || true
rm -rf /tmp/tracelens-snapshot/.git
git init /tmp/tracelens-snapshot >/dev/null
git -C /tmp/tracelens-snapshot config user.email team+codex@example.invalid
git -C /tmp/tracelens-snapshot config user.name 'Inspector Snapshot'
rm -rf /tmp/tracelens-snapshot/*
git -C /tmp/tracelens-snapshot add -A
copy_to_snapshot() {
  local src="$1"; local rel="$2"; local dst="/tmp/tracelens-snapshot/$rel"; mkdir -p "$(dirname "$dst")"; cp -a "$src" "$dst"
}
copy_to_snapshot /home/ymj68520/projects/TraceLens/.env TraceLens/.env
copy_to_snapshot /home/ymj68520/projects/TraceLens/CMakeLists.txt TraceLens/CMakeLists.txt
copy_to_snapshot /home/ymj68520/projects/TraceLens/python_service/config/extractor_mapping.json TraceLens/python_service/config/extractor_mapping.json
copy_to_snapshot /home/ymj68520/projects/TraceLens/python_service/httpserver/__init__.py TraceLens/python_service/httpserver/__init__.py
copy_to_snapshot /home/ymj68520/projects/TraceLens/python_service/httpserver/services/document_extractor.py TraceLens/python_service/httpserver/services/document_extractor.py
copy_to_snapshot /home/ymj68520/projects/TraceLens/python_service/httpserver/services/extractors/__init__.py TraceLens/python_service/httpserver/services/extractors/__init__.py
copy_to_snapshot /home/ymj68520/projects/TraceLens/python_service/httpserver/services/extractors/media_metadata.py TraceLens/python_service/httpserver/services/extractors/media_metadata.py
copy_to_snapshot /home/ymj68520/projects/TraceLens/python_service/httpserver/services/extractors/relational_db.py TraceLens/python_service/httpserver/services/extractors/relational_db.py
copy_to_snapshot /home/ymj68520/projects/TraceLens/python_service/tests/unit/test_cors_config.py TraceLens/python_service/tests/unit/test_cors_config.py
copy_to_snapshot /home/ymj68520/projects/TraceLens/setup.sh TraceLens/setup.sh
copy_to_snapshot "/home/ymj68520/projects/TraceLens/src/analyzers/LinuxFilesAnalyzer/Analysis/PersistenceDetector.cpp" "TraceLens/src/analyzers/LinuxFilesAnalyzer/Analysis/PersistenceDetector.cpp"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/src/analyzers/LinuxFilesAnalyzer/Analysis/PersistenceDetectorScripts.cpp" "TraceLens/src/analyzers/LinuxFilesAnalyzer/Analysis/PersistenceDetectorScripts.cpp"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerCore.cpp" "TraceLens/src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerCore.cpp"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerLogs.cpp" "TraceLens/src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerLogs.cpp"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/src/core/DatabaseManager/FileExtractor/FileExtractor_Extract.cpp" "TraceLens/src/core/DatabaseManager/FileExtractor/FileExtractor_Extract.cpp"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/src/integration/LLMIntegration/MarkitdownProxy.cpp" "TraceLens/src/integration/LLMIntegration/MarkitdownProxy.cpp"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/src/integration/LLMIntegration/MarkitdownProxy.h" "TraceLens/src/integration/LLMIntegration/MarkitdownProxy.h"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/src/report/ReportGenerator.cpp" "TraceLens/src/report/ReportGenerator.cpp"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/tests/UnitTest/test_markitdown_proxy.cpp" "TraceLens/tests/UnitTest/test_markitdown_proxy.cpp"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/tests/UnitTest/test_memory_volatility_runner_gtest.cpp" "TraceLens/tests/UnitTest/test_memory_volatility_runner_gtest.cpp"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/CHANGES.md" "TraceLens/CHANGES.md"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/docs/neo4j_local_verification_notes.md" "TraceLens/docs/neo4j_local_verification_notes.md"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/docs/review-todo.md" "TraceLens/docs/review-todo.md"
copy_to_snapshot "/home/ymj68520/projects/TraceLens/python_service/httpserver/services/extractors/text_dump.py" "TraceLens/python_service/httpserver/services/extractors/text_dump.py"
mkdir -p /tmp/tracelens-snapshot/snapshots &&:
git -C /tmp/tracelens-snapshot add -A
git -C /tmp/tracelens-snapshot commit -m "snapshot: include current working tree for review" >/dev/null
rm -rf /home/ymj68520/projects/TraceLens/submission
mkdir -p /home/ymj68520/projects/TraceLens/submission
cp -a /tmp/tracelens-snapshot/. /home/ymj68520/projects/TraceLens/submission/
