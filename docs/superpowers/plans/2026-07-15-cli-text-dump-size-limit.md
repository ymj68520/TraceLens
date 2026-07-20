# CLI Text Dump Total-Size Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--dump-text-max-size <SIZE>` so CLI text dumping can stop gracefully at a deterministic, per-file soft limit while preserving complete original and Markdown outputs.

**Architecture:** Keep the current unlimited `extractAll() -> batch-convert` path unchanged. When the optional byte limit is present, a new `TextDumpExporter` accounts existing files, obtains deterministically ordered image records from a `FileExtractor` adapter, then extracts and converts one complete file at a time through a new Python `/api/markitdown/convert-one` endpoint. Interfaces around the file source and Markdown converter make the budget policy independently testable without a disk image or running HTTP service.

**Tech Stack:** C++20, GoogleTest/GoogleMock, `std::filesystem`, SQLite3, The Sleuth Kit, cpp-httplib, nlohmann/json, Python 3.12, FastAPI, Pydantic, pytest/pytest-asyncio.

## Global Constraints

- The size limit applies only to regular files under `<base>_extracted_files/` and `<base>_extracted_text/`.
- Core databases, `--report`, stdout/stderr, HTTP-created tasks, and web UI behavior remain outside this feature.
- `SIZE` is a positive decimal integer followed by exactly one case-insensitive unit: `K`, `M`, `G`, or `T`.
- Units are binary: `K=1024`, `M=1024²`, `G=1024³`, and `T=1024⁴` bytes.
- `0M`, negative values, decimals, missing units, multi-character units, unknown units, missing values, and `uint64_t` overflow are rejected before analysis starts.
- Supplying `--dump-text-max-size` automatically enables `--dump-text`; it neither requires nor implies `--no-ai`.
- Omitting `--dump-text-max-size` preserves the existing unlimited extraction and batch-conversion behavior.
- Existing regular files in both output trees count toward the limit; symlinks are not followed or counted as target content.
- Limited mode orders records by image path using SQLite `COLLATE BINARY`, then partition number, then inode.
- The limit is checked only before a file starts. The active file's original plus Markdown may take the final logical usage over the limit; neither file is intentionally truncated.
- Once the limit is reached, completed files are preserved, no later file starts, a clear warning is printed, and the main analysis command remains successful.
- Original and Markdown writes use same-directory temporary files with prefix `.tracelens-textdump-tmp-`, followed by atomic replacement.
- Per-file extraction/conversion failures are isolated; a Python HTTP 5xx or transport failure stops further dump work to avoid repeated timeouts.
- The approved design is `docs/superpowers/specs/2026-07-15-cli-text-dump-size-limit-design.md`.

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `src/export/TextDumpExporter.h` | Domain result types, dependency interfaces, options, stop reasons, and exporter public API |
| `src/export/TextDumpExporter.cpp` | Output-tree validation/accounting, stale-temp cleanup, unlimited dispatch, limited per-file policy, and summary formatting helpers |
| `src/export/TextDumpAdapters.h` | Production adapters connecting `FileExtractor` and `MarkitdownProxy` to exporter interfaces |
| `src/export/TextDumpAdapters.cpp` | Adapter initialization and result mapping |
| `tests/UnitTest/test_command_line_parser.cpp` | CLI size grammar, conversion, implication, and error tests |
| `tests/UnitTest/test_file_extractor_text_dump.cpp` | Deterministic SQLite ordering and safe destination-path tests |
| `tests/UnitTest/test_markitdown_proxy.cpp` | C++ single-file HTTP response and service-error mapping tests |
| `tests/UnitTest/test_text_dump_exporter.cpp` | Soft-limit policy, accounting, resumption, failure isolation, and stop-reason tests with fakes |
| `python_service/tests/unit/test_markitdown_routes.py` | Shared conversion primitive and `/convert-one` route tests |

### Modified files

| File | Responsibility of change |
|---|---|
| `src/CommandLineParser.h` | Store optional byte limit and parse error |
| `src/CommandLineParser.cpp` | Parse checked binary sizes and document CLI option |
| `src/main.cpp` | Reject parser errors before any execution mode starts |
| `src/core/DatabaseManager/FileExtractor/FileExtractor.h` | Expose ordered record enumeration, safe path resolution, and atomic single-record extraction result |
| `src/core/DatabaseManager/FileExtractor/FileExtractor_Extract.cpp` | Implement ordered query, path confinement, reuse detection, temporary extraction, and atomic replacement |
| `src/integration/LLMIntegration/MarkitdownProxy.h` | Add injectable constructor and typed single-file conversion result |
| `src/integration/LLMIntegration/MarkitdownProxy.cpp` | Call `/api/markitdown/convert-one` and classify 200/4xx/5xx/transport outcomes |
| `python_service/httpserver/routes/markitdown.py` | Share one per-file conversion primitive between single and batch endpoints; atomically write Markdown |
| `src/AnalysisOrchestrator.cpp` | Delegate all `--dump-text` work to exporter and print structured result |
| `CMakeLists.txt` | Compile exporter and adapters and add export include directory |
| `tests/CMakeLists.txt` | Build and register four focused C++ test targets |
| `scripts/ONSITE_TEST_GUIDE.md` | Document constrained export command, binary units, existing-file accounting, and soft-limit behavior |

### Locked interfaces

Use these names and signatures across tasks; later tasks depend on them exactly.

```cpp
// src/CommandLineParser.h
std::optional<uint64_t> dump_text_max_bytes;
std::string parse_error;
```

```cpp
// src/core/DatabaseManager/FileExtractor/FileExtractor.h
enum class AtomicExtractionStatus { Extracted, Reused, Failed, UnsafePath };

struct AtomicExtractionResult {
    AtomicExtractionStatus status = AtomicExtractionStatus::Failed;
    std::filesystem::path output_path;
    uint64_t previous_bytes = 0;
    uint64_t output_bytes = 0;
    std::string error;
};

std::vector<FileRecord> listRegularFilesOrdered(std::string* error = nullptr);
static std::vector<FileRecord> queryRegularFilesOrdered(sqlite3* db,
                                                        std::string* error = nullptr);
static std::optional<std::filesystem::path> resolveSafeOutputPath(
    const std::filesystem::path& outputRoot,
    const std::string& imagePath,
    std::string* error = nullptr);
AtomicExtractionResult extractRecordAtomically(
    const FileRecord& record,
    const std::filesystem::path& outputRoot);
```

```cpp
// src/integration/LLMIntegration/MarkitdownProxy.h
enum class SingleConversionStatus { Converted, Skipped, Failed, ServiceError };

struct SingleConversionResult {
    SingleConversionStatus status = SingleConversionStatus::Failed;
    std::string output_path;
    uint64_t previous_bytes = 0;
    uint64_t output_bytes = 0;
    std::string error;
};

explicit MarkitdownProxy(std::string pythonServiceUrl);
SingleConversionResult convertOneToMarkdown(
    const std::string& inputRoot,
    const std::string& inputFile,
    const std::string& outputRoot);
```

```cpp
// src/export/TextDumpExporter.h
namespace forensics::textdump {

enum class OriginalStatus { Extracted, Reused, Failed, UnsafePath };
enum class MarkdownStatus { Converted, Reused, Skipped, Failed, ServiceError };
enum class StopReason { Completed, SizeLimitReached, ServiceUnavailable, OutputError };

struct FileDeltaResult {
    OriginalStatus status = OriginalStatus::Failed;
    std::filesystem::path output_path;
    uint64_t previous_bytes = 0;
    uint64_t output_bytes = 0;
    std::string error;
};

struct MarkdownDeltaResult {
    MarkdownStatus status = MarkdownStatus::Failed;
    std::filesystem::path output_path;
    uint64_t previous_bytes = 0;
    uint64_t output_bytes = 0;
    std::string error;
};

struct BatchConversionResult {
    bool ok = false;
    int total = 0;
    int converted = 0;
    int skipped = 0;
    int failed = 0;
    std::string error;
};

class ITextDumpFileSource {
public:
    virtual ~ITextDumpFileSource() = default;
    virtual bool initialize(std::string& error) = 0;
    virtual std::vector<FileRecord> listRegularFilesOrdered(std::string& error) = 0;
    virtual FileDeltaResult extractOne(const FileRecord& record,
                                       const std::filesystem::path& outputRoot) = 0;
    virtual int extractAll(const std::filesystem::path& outputRoot,
                           std::string& error) = 0;
};

class ITextDumpConverter {
public:
    virtual ~ITextDumpConverter() = default;
    virtual bool isAvailable() = 0;
    virtual MarkdownDeltaResult convertOne(
        const std::filesystem::path& inputRoot,
        const std::filesystem::path& inputFile,
        const std::filesystem::path& outputRoot,
        bool force) = 0;
    virtual BatchConversionResult convertBatch(
        const std::filesystem::path& inputRoot,
        const std::filesystem::path& outputRoot) = 0;
};

struct TextDumpOptions {
    std::filesystem::path original_root;
    std::filesystem::path markdown_root;
    std::optional<uint64_t> max_bytes;
};

struct TextDumpResult {
    StopReason stop_reason = StopReason::Completed;
    size_t candidate_files = 0;
    size_t processed_files = 0;
    size_t originals_extracted = 0;
    size_t originals_reused = 0;
    size_t originals_failed = 0;
    size_t markdown_converted = 0;
    size_t markdown_reused = 0;
    size_t markdown_skipped = 0;
    size_t markdown_failed = 0;
    uint64_t initial_bytes = 0;
    uint64_t final_bytes = 0;
    std::optional<uint64_t> max_bytes;
    bool truncated = false;
    std::string message;
};

class TextDumpExporter {
public:
    TextDumpExporter(ITextDumpFileSource& source, ITextDumpConverter& converter);
    TextDumpResult run(const TextDumpOptions& options);
    static std::optional<uint64_t> calculateUsage(
        const std::filesystem::path& originalRoot,
        const std::filesystem::path& markdownRoot,
        std::string& error);
    static std::string formatBytes(uint64_t bytes);
};

} // namespace forensics::textdump
```

---

### Task 1: Parse and Reject CLI Size Limits Before Analysis

**Files:**
- Modify: `src/CommandLineParser.h:3-54`
- Modify: `src/CommandLineParser.cpp:8-170`
- Modify: `src/main.cpp:71-84`
- Create: `tests/UnitTest/test_command_line_parser.cpp`
- Modify: `tests/CMakeLists.txt` after the core-module test registrations

**Interfaces:**
- Consumes: existing `CommandLineParser::parse(int, char**)` and `CommandLineArgs::dump_text`.
- Produces: `CommandLineArgs::dump_text_max_bytes`, `CommandLineArgs::parse_error`, and early rejection in `main()`.

- [ ] **Step 1: Write the failing CLI parser tests**

Create `tests/UnitTest/test_command_line_parser.cpp` with a helper that preserves writable argument storage and tests exact binary conversions, implication, compatibility, invalid grammar, overflow, and a missing value:

```cpp
#include <gtest/gtest.h>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>
#include "CommandLineParser.h"

namespace {

forensics::CommandLineArgs parse(std::vector<std::string> values) {
    std::vector<char*> argv;
    argv.reserve(values.size());
    for (auto& value : values) argv.push_back(value.data());
    return forensics::CommandLineParser::parse(
        static_cast<int>(argv.size()), argv.data());
}

TEST(CommandLineParserSizeLimit, ConvertsBinaryUnitsAndIgnoresCase) {
    const auto oneK = parse({"analyzer", "disk.E01", "--dump-text-max-size", "1K"});
    const auto fiveHundredM = parse({"analyzer", "disk.E01", "--dump-text-max-size", "500M"});
    const auto twoG = parse({"analyzer", "disk.E01", "--dump-text-max-size", "2g"});
    const auto oneT = parse({"analyzer", "disk.E01", "--dump-text-max-size", "1T"});

    ASSERT_TRUE(oneK.dump_text_max_bytes.has_value());
    EXPECT_EQ(*oneK.dump_text_max_bytes, 1024ULL);
    EXPECT_EQ(*fiveHundredM.dump_text_max_bytes, 500ULL * 1024ULL * 1024ULL);
    EXPECT_EQ(*twoG.dump_text_max_bytes, 2ULL * 1024ULL * 1024ULL * 1024ULL);
    EXPECT_EQ(*oneT.dump_text_max_bytes, 1024ULL * 1024ULL * 1024ULL * 1024ULL);
    EXPECT_TRUE(oneK.dump_text);
    EXPECT_TRUE(oneK.parse_error.empty());
}

TEST(CommandLineParserSizeLimit, LeavesLegacyDumpUnlimited) {
    const auto args = parse({"analyzer", "disk.E01", "--dump-text"});
    EXPECT_TRUE(args.dump_text);
    EXPECT_FALSE(args.dump_text_max_bytes.has_value());
    EXPECT_TRUE(args.parse_error.empty());
}

class InvalidSize : public ::testing::TestWithParam<const char*> {};
TEST_P(InvalidSize, RejectsInvalidValue) {
    const auto args = parse({"analyzer", "disk.E01", "--dump-text-max-size", GetParam()});
    EXPECT_FALSE(args.parse_error.empty());
    EXPECT_FALSE(args.dump_text_max_bytes.has_value());
}
INSTANTIATE_TEST_SUITE_P(
    Grammar, InvalidSize,
    ::testing::Values("0M", "-1G", "1.5G", "500", "10MB", "2GiB", "4P", ""));

TEST(CommandLineParserSizeLimit, RejectsOverflow) {
    const auto args = parse({
        "analyzer", "disk.E01", "--dump-text-max-size", "18446744073709551615T"});
    EXPECT_FALSE(args.parse_error.empty());
}

TEST(CommandLineParserSizeLimit, RejectsMissingValue) {
    const auto args = parse({"analyzer", "disk.E01", "--dump-text-max-size"});
    EXPECT_FALSE(args.parse_error.empty());
}

} // namespace
```

- [ ] **Step 2: Register and run the new test target to prove it fails**

Append this target to `tests/CMakeLists.txt`:

```cmake
add_executable(
  test_command_line_parser
  UnitTest/test_command_line_parser.cpp
  ../src/CommandLineParser.cpp)

target_include_directories(test_command_line_parser PRIVATE ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(test_command_line_parser ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)
add_test(NAME CommandLineParserTests COMMAND test_command_line_parser)
```

Run:

```bash
cmake -S . -B build
cmake --build build --target test_command_line_parser -j2
```

Expected: compilation fails because `dump_text_max_bytes` and `parse_error` do not exist.

- [ ] **Step 3: Add the CLI state and checked parser**

In `src/CommandLineParser.h`, add the standard headers and fields:

```cpp
#include <cstdint>
#include <optional>

// inside CommandLineArgs, next to dump_text
bool dump_text = false;
std::optional<uint64_t> dump_text_max_bytes;
std::string parse_error;
```

In the anonymous namespace at the top of `src/CommandLineParser.cpp`, implement strict parsing with `std::from_chars` and checked multiplication:

```cpp
#include <charconv>
#include <cctype>
#include <limits>
#include <optional>

namespace {

std::optional<uint64_t> parseBinarySize(const std::string& text,
                                        std::string& error) {
    if (text.size() < 2) {
        error = "--dump-text-max-size expects a positive integer followed by K, M, G, or T";
        return std::nullopt;
    }

    const char unit = static_cast<char>(
        std::toupper(static_cast<unsigned char>(text.back())));
    uint64_t multiplier = 0;
    switch (unit) {
        case 'K': multiplier = 1024ULL; break;
        case 'M': multiplier = 1024ULL * 1024ULL; break;
        case 'G': multiplier = 1024ULL * 1024ULL * 1024ULL; break;
        case 'T': multiplier = 1024ULL * 1024ULL * 1024ULL * 1024ULL; break;
        default:
            error = "--dump-text-max-size unit must be one of K, M, G, or T";
            return std::nullopt;
    }

    const std::string digits = text.substr(0, text.size() - 1);
    if (digits.empty()) {
        error = "--dump-text-max-size requires a positive integer before the unit";
        return std::nullopt;
    }
    for (const unsigned char ch : digits) {
        if (!std::isdigit(ch)) {
            error = "--dump-text-max-size does not accept signs or decimals";
            return std::nullopt;
        }
    }

    uint64_t value = 0;
    const auto [end, ec] = std::from_chars(
        digits.data(), digits.data() + digits.size(), value);
    if (ec != std::errc{} || end != digits.data() + digits.size() || value == 0) {
        error = "--dump-text-max-size must contain a positive integer";
        return std::nullopt;
    }
    if (value > std::numeric_limits<uint64_t>::max() / multiplier) {
        error = "--dump-text-max-size exceeds the maximum supported byte count";
        return std::nullopt;
    }
    return value * multiplier;
}

} // namespace
```

Add the parser branch immediately after `--dump-text`:

```cpp
} else if (arg == "--dump-text-max-size") {
    if (i + 1 >= argc) {
        args.parse_error = "Missing value for --dump-text-max-size";
        return args;
    }
    std::string error;
    auto parsed = parseBinarySize(argv[++i], error);
    if (!parsed.has_value()) {
        args.parse_error = error;
        return args;
    }
    args.dump_text_max_bytes = *parsed;
    args.dump_text = true;
```

Add help text directly under `--dump-text`:

```cpp
std::cout << "  --dump-text-max-size <SIZE> Limit dump originals + Markdown (e.g. 500M, 2G)\n";
std::cout << "                              Binary K/M/G/T soft limit; implies --dump-text\n";
```

- [ ] **Step 4: Reject parser errors before any mode dispatch**

In `src/main.cpp`, immediately after parsing and before help/version/mode routing, add:

```cpp
if (!cmdArgs.parse_error.empty()) {
    std::cerr << "Error: " << cmdArgs.parse_error << std::endl;
    std::cerr << "Expected: --dump-text-max-size <positive integer><K|M|G|T>"
              << std::endl;
    return 2;
}
```

- [ ] **Step 5: Run focused tests and verify pass**

Run:

```bash
cmake --build build --target test_command_line_parser -j2
ctest --test-dir build -R '^CommandLineParserTests$' --output-on-failure
```

Expected: `100% tests passed, 0 tests failed`.

- [ ] **Step 6: Commit the parser slice**

```bash
git add src/CommandLineParser.h src/CommandLineParser.cpp src/main.cpp \
  tests/UnitTest/test_command_line_parser.cpp tests/CMakeLists.txt
git commit -m "feat(cli): parse text dump size limit"
```

---

### Task 2: Share Atomic Python Per-File Conversion and Add `/convert-one`

**Files:**
- Create: `python_service/tests/unit/test_markitdown_routes.py`
- Modify: `python_service/httpserver/routes/markitdown.py:7-343`

**Interfaces:**
- Consumes: `get_document_extractor_locator()`, existing `_is_likely_binary()`, and current batch response fields.
- Produces: `POST /api/markitdown/convert-one`, `ConvertOneRequest`, `ConvertOneResponse`, `FileConversionOutcome`, and `_convert_file_to_output()` shared with `/batch-convert`.

- [ ] **Step 1: Write failing tests for text fallback, status outcomes, confinement, and atomic cleanup**

Create `python_service/tests/unit/test_markitdown_routes.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import markitdown


@pytest.mark.asyncio
async def test_convert_file_to_output_uses_specialized_extractor(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    source = input_root / "etc" / "auth.log"
    source.parent.mkdir(parents=True)
    source.write_text("ignored", encoding="utf-8")

    extractor = MagicMock()
    extractor.extract_to_markdown = AsyncMock(return_value="# specialized\n")
    locator = MagicMock()
    locator.get_extractor.return_value = extractor
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)

    result = await markitdown._convert_file_to_output(source, input_root, output_root)

    assert result.status == "converted"
    assert result.output_path == output_root / "etc" / "auth.log.md"
    assert result.output_path.read_text(encoding="utf-8") == "# specialized\n"
    assert result.output_size == len("# specialized\n".encode("utf-8"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("plain utf-8 text".encode("utf-8"), "plain utf-8 text"),
        ("caf\xe9".encode("latin-1"), "café"),
    ],
)
async def test_convert_file_to_output_falls_back_to_text(
    tmp_path, monkeypatch, payload, expected
):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    source = input_root / "notes.txt"
    source.write_bytes(payload)
    locator = MagicMock()
    locator.get_extractor.return_value = None
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)

    result = await markitdown._convert_file_to_output(source, input_root, output_root)

    assert result.status == "converted"
    assert expected in result.output_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_convert_file_to_output_skips_binary_and_empty(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    locator = MagicMock()
    locator.get_extractor.return_value = None
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)

    binary = input_root / "binary.dat"
    binary.write_bytes(b"\x00\x01\x02")
    empty = input_root / "empty.txt"
    empty.write_bytes(b"")

    assert (await markitdown._convert_file_to_output(
        binary, input_root, output_root)).status == "skipped"
    assert (await markitdown._convert_file_to_output(
        empty, input_root, output_root)).status == "skipped"


@pytest.mark.asyncio
async def test_convert_file_to_output_isolates_extractor_failure(tmp_path, monkeypatch):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    source = input_root / "bad.evtx"
    source.write_bytes(b"data")
    extractor = MagicMock()
    extractor.extract_to_markdown = AsyncMock(side_effect=RuntimeError("broken"))
    locator = MagicMock()
    locator.get_extractor.return_value = extractor
    monkeypatch.setattr(markitdown, "get_document_extractor_locator", lambda: locator)

    result = await markitdown._convert_file_to_output(source, input_root, output_root)

    assert result.status == "failed"
    assert "broken" in result.error
    assert not list(output_root.rglob(".tracelens-textdump-tmp-*"))


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(markitdown.router, prefix="/api/markitdown")
    return TestClient(app, raise_server_exceptions=False)


def test_convert_one_derives_output_and_rejects_escape(tmp_path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    source = input_root / "notes.txt"
    source.write_text("hello", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    client = make_client()

    ok = client.post("/api/markitdown/convert-one", json={
        "input_root": str(input_root),
        "input_file": str(source),
        "output_root": str(output_root),
    })
    escaped = client.post("/api/markitdown/convert-one", json={
        "input_root": str(input_root),
        "input_file": str(outside),
        "output_root": str(output_root),
    })

    assert ok.status_code == 200
    assert ok.json()["status"] == "converted"
    assert ok.json()["output_path"].endswith("notes.txt.md")
    assert escaped.status_code == 400
```

- [ ] **Step 2: Run tests to verify the new primitive and endpoint are absent**

Run:

```bash
python_service/.venv/bin/python -m pytest \
  python_service/tests/unit/test_markitdown_routes.py -q
```

Expected: failures report that `_convert_file_to_output` and `/convert-one` do not exist.

- [ ] **Step 3: Add typed outcomes and atomic writer**

In `python_service/httpserver/routes/markitdown.py`, add `os`, `uuid`, `dataclass`, and `Literal`, then define:

```python
import os
import uuid
from dataclasses import dataclass
from typing import List, Literal, Optional

ConversionStatus = Literal["converted", "skipped", "failed"]


@dataclass(frozen=True)
class FileConversionOutcome:
    status: ConversionStatus
    input_path: Path
    output_path: Optional[Path] = None
    output_size: int = 0
    error: str = ""


def _output_path_for(input_file: Path, input_root: Path, output_root: Path) -> Path:
    if input_root.is_symlink():
        raise ValueError(f"input_root must not be a symlink: {input_root}")
    resolved_root = input_root.resolve(strict=True)
    if input_file.is_symlink():
        raise ValueError(f"Input file must not be a symlink: {input_file}")
    resolved_input = input_file.resolve(strict=True)
    try:
        relative = resolved_input.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Input file is outside input_root: {input_file}") from exc
    if not resolved_input.is_file():
        raise ValueError(f"Input path is not a regular file: {input_file}")

    if output_root.is_symlink():
        raise ValueError(f"output_root must not be a symlink: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    current = output_root
    for part in relative.parent.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError(f"Output path contains a symlink: {current}")
        current.mkdir(exist_ok=True)
    final_path = current / f"{relative.name}.md"
    if final_path.is_symlink():
        raise ValueError(f"Output file must not be a symlink: {final_path}")
    return final_path


def _write_markdown_atomic(output_path: Path, markdown: str) -> int:
    temp_path = output_path.parent / (
        f".tracelens-textdump-tmp-{uuid.uuid4().hex}-{output_path.name}"
    )
    try:
        temp_path.write_text(markdown, encoding="utf-8")
        os.replace(temp_path, output_path)
        return output_path.stat().st_size
    finally:
        temp_path.unlink(missing_ok=True)
```

- [ ] **Step 4: Implement the shared conversion primitive**

Place this function below `_is_likely_binary()` and make both endpoint paths call it:

```python
async def _convert_file_to_output(
    file_path: Path, input_root: Path, output_root: Path
) -> FileConversionOutcome:
    try:
        output_path = _output_path_for(file_path, input_root, output_root)
    except (OSError, ValueError):
        raise

    locator = get_document_extractor_locator()
    extractor = locator.get_extractor(str(file_path))
    try:
        if extractor is not None:
            markdown = await extractor.extract_to_markdown(str(file_path))
        else:
            raw = file_path.read_bytes()
            if not raw or _is_likely_binary(raw):
                return FileConversionOutcome("skipped", file_path)
            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                text = raw.decode("latin-1", errors="replace")
            markdown = f"# {file_path.name}\n\n```\n{text}\n```\n"
    except Exception as exc:
        return FileConversionOutcome("failed", file_path, error=str(exc))

    if not markdown or not markdown.strip():
        return FileConversionOutcome("skipped", file_path)

    output_size = _write_markdown_atomic(output_path, markdown)
    return FileConversionOutcome(
        "converted", file_path, output_path=output_path, output_size=output_size
    )
```

An `OSError` from `_write_markdown_atomic` must propagate so the endpoint returns HTTP 500; extractor exceptions remain HTTP 200 `status=failed` outcomes.

- [ ] **Step 5: Add the `/convert-one` request and response contract**

Add these Pydantic models and route:

```python
class ConvertOneRequest(BaseModel):
    input_root: str = Field(..., description="Root containing extracted files")
    input_file: str = Field(..., description="One regular file beneath input_root")
    output_root: str = Field(..., description="Root for mirrored Markdown output")


class ConvertOneResponse(BaseModel):
    success: bool
    status: ConversionStatus
    input_path: str
    output_path: str = ""
    output_size: int = 0
    error: str = ""


@router.post("/convert-one", response_model=ConvertOneResponse)
async def convert_one(request: ConvertOneRequest):
    try:
        outcome = await _convert_file_to_output(
            Path(request.input_file),
            Path(request.input_root),
            Path(request.output_root),
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Output write failed: {exc}") from exc

    return ConvertOneResponse(
        success=outcome.status == "converted",
        status=outcome.status,
        input_path=str(outcome.input_path),
        output_path=str(outcome.output_path or ""),
        output_size=outcome.output_size,
        error=outcome.error,
    )
```

- [ ] **Step 6: Refactor batch conversion to reuse the primitive without changing its API**

Replace the body of `_convert_one()` with:

```python
async def _convert_one(file_path: Path, input_root: Path, output_root: Path,
                       sem: asyncio.Semaphore):
    async with sem:
        try:
            outcome = await _convert_file_to_output(
                file_path, input_root, output_root)
            detail = outcome.error or str(file_path.relative_to(input_root))
            return (outcome.status, detail)
        except Exception as exc:
            rel = file_path.relative_to(input_root)
            return ("failed", f"{rel}: {exc}")
```

Keep `BatchConvertResponse`, the semaphore value `4`, the 50-error response cap, and existing count field names unchanged. Correct the error-cap summary to use the true `failed` count:

```python
if len(errors) > 50:
    errors = errors[:50] + [f"... and {failed - 50} more failures"]
```

- [ ] **Step 7: Run focused and regression Python tests**

Run:

```bash
python_service/.venv/bin/python -m pytest \
  python_service/tests/unit/test_markitdown_routes.py \
  python_service/tests/unit/test_forensic_extractors.py -q
```

Expected: all selected tests pass and no `.tracelens-textdump-tmp-*` files remain in pytest temporary directories.

- [ ] **Step 8: Commit the Python conversion slice**

```bash
git add python_service/httpserver/routes/markitdown.py \
  python_service/tests/unit/test_markitdown_routes.py
git commit -m "feat(markitdown): convert one extracted file atomically"
```

---

### Task 3: Add the Typed C++ Single-File Markitdown Client

**Files:**
- Modify: `src/integration/LLMIntegration/MarkitdownProxy.h:21-77`
- Modify: `src/integration/LLMIntegration/MarkitdownProxy.cpp:8-138`
- Create: `tests/UnitTest/test_markitdown_proxy.cpp`
- Modify: `tests/CMakeLists.txt`

**Interfaces:**
- Consumes: Task 2's `POST /api/markitdown/convert-one` JSON response.
- Produces: `SingleConversionStatus`, `SingleConversionResult`, public injectable constructor, and `convertOneToMarkdown()` locked above.

- [ ] **Step 1: Write a local HTTP-server test for status mapping**

Create `tests/UnitTest/test_markitdown_proxy.cpp` with an in-process cpp-httplib server:

```cpp
#include <gtest/gtest.h>
#include <httplib.h>
#include <nlohmann/json.hpp>
#include <thread>
#include "LLMIntegration/MarkitdownProxy.h"

namespace {

class LocalServer {
public:
    explicit LocalServer(std::function<void(httplib::Server&)> configure) {
        configure(server_);
        port_ = server_.bind_to_any_port("127.0.0.1");
        thread_ = std::thread([this] { server_.listen_after_bind(); });
    }
    ~LocalServer() {
        server_.stop();
        if (thread_.joinable()) thread_.join();
    }
    std::string url() const {
        return "http://127.0.0.1:" + std::to_string(port_);
    }
private:
    httplib::Server server_;
    int port_ = -1;
    std::thread thread_;
};

using forensics::llm::MarkitdownProxy;
using forensics::llm::SingleConversionStatus;

TEST(MarkitdownProxyConvertOne, MapsConvertedResponse) {
    LocalServer server([](httplib::Server& app) {
        app.Post("/api/markitdown/convert-one",
            [](const httplib::Request& req, httplib::Response& res) {
                const auto body = nlohmann::json::parse(req.body);
                EXPECT_EQ(body["input_root"], "/in");
                EXPECT_EQ(body["input_file"], "/in/a.txt");
                EXPECT_EQ(body["output_root"], "/out");
                res.set_content(nlohmann::json({
                    {"success", true}, {"status", "converted"},
                    {"input_path", "/in/a.txt"},
                    {"output_path", "/out/a.txt.md"},
                    {"output_size", 17}, {"error", ""}
                }).dump(), "application/json");
            });
    });
    MarkitdownProxy proxy(server.url());
    const auto result = proxy.convertOneToMarkdown("/in", "/in/a.txt", "/out");
    EXPECT_EQ(result.status, SingleConversionStatus::Converted);
    EXPECT_EQ(result.output_path, "/out/a.txt.md");
    EXPECT_EQ(result.output_bytes, 17U);
}

TEST(MarkitdownProxyConvertOne, MapsPerFileAndServiceFailures) {
    LocalServer server([](httplib::Server& app) {
        app.Post("/api/markitdown/convert-one",
            [](const httplib::Request& req, httplib::Response& res) {
                if (req.body.find("skip.bin") != std::string::npos) {
                    res.set_content(R"({"success":false,"status":"skipped","input_path":"/in/skip.bin","output_path":"","output_size":0,"error":""})", "application/json");
                } else if (req.body.find("bad.evtx") != std::string::npos) {
                    res.status = 400;
                    res.set_content(R"({"detail":"unsafe path"})", "application/json");
                } else {
                    res.status = 500;
                    res.set_content(R"({"detail":"disk full"})", "application/json");
                }
            });
    });
    MarkitdownProxy proxy(server.url());
    EXPECT_EQ(proxy.convertOneToMarkdown("/in", "/in/skip.bin", "/out").status,
              SingleConversionStatus::Skipped);
    EXPECT_EQ(proxy.convertOneToMarkdown("/in", "/in/bad.evtx", "/out").status,
              SingleConversionStatus::Failed);
    EXPECT_EQ(proxy.convertOneToMarkdown("/in", "/in/write.txt", "/out").status,
              SingleConversionStatus::ServiceError);
}

} // namespace
```

- [ ] **Step 2: Register and run the target to verify the interface is missing**

Add to `tests/CMakeLists.txt`:

```cmake
add_executable(
  test_markitdown_proxy
  UnitTest/test_markitdown_proxy.cpp
  ../src/integration/LLMIntegration/MarkitdownProxy.cpp
  ../src/core/Logger/Logger.cpp
  ../src/core/ConfigManager/ConfigManager.cpp
  ../src/core/PathManager/PathManager.cpp)

target_include_directories(test_markitdown_proxy PRIVATE ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(
  test_markitdown_proxy ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES}
  nlohmann_json::nlohmann_json cpp_dotenv pthread)
add_test(NAME MarkitdownProxyTests COMMAND test_markitdown_proxy)
```

Run:

```bash
cmake -S . -B build
cmake --build build --target test_markitdown_proxy -j2
```

Expected: compilation fails because the constructor and single-file result types are not public/defined.

- [ ] **Step 3: Add result types and injectable construction**

In `MarkitdownProxy.h`, include `<cstdint>` and add the locked enum/struct before the class. Move this constructor into the public section while retaining the singleton:

```cpp
explicit MarkitdownProxy(std::string pythonServiceUrl);
```

Declare `convertOneToMarkdown()` exactly as specified in the locked interfaces. Remove the old private constructor declaration.

- [ ] **Step 4: Implement response classification**

In `MarkitdownProxy.cpp`, change construction to move the URL and implement:

```cpp
MarkitdownProxy::MarkitdownProxy(std::string pythonServiceUrl)
    : pythonServiceUrl_(std::move(pythonServiceUrl)) {}

SingleConversionResult MarkitdownProxy::convertOneToMarkdown(
        const std::string& inputRoot,
        const std::string& inputFile,
        const std::string& outputRoot) {
    SingleConversionResult result;
    try {
        httplib::Client cli(pythonServiceUrl_);
        cli.set_connection_timeout(10);
        cli.set_read_timeout(120);
        const nlohmann::json body = {
            {"input_root", inputRoot},
            {"input_file", inputFile},
            {"output_root", outputRoot},
        };
        auto res = cli.Post("/api/markitdown/convert-one",
                            body.dump(), "application/json");
        if (!res) {
            result.status = SingleConversionStatus::ServiceError;
            result.error = "Service unreachable at " + pythonServiceUrl_;
            return result;
        }
        if (res->status >= 500) {
            result.status = SingleConversionStatus::ServiceError;
            result.error = "HTTP " + std::to_string(res->status) + ": " + res->body;
            return result;
        }
        if (res->status >= 400) {
            result.status = SingleConversionStatus::Failed;
            result.error = "HTTP " + std::to_string(res->status) + ": " + res->body;
            return result;
        }

        const auto response = nlohmann::json::parse(res->body);
        const std::string status = response.value("status", "failed");
        if (status == "converted") {
            result.status = SingleConversionStatus::Converted;
        } else if (status == "skipped") {
            result.status = SingleConversionStatus::Skipped;
        } else {
            result.status = SingleConversionStatus::Failed;
        }
        result.output_path = response.value("output_path", "");
        result.output_bytes = response.value("output_size", uint64_t{0});
        result.error = response.value("error", "");
        return result;
    } catch (const std::exception& ex) {
        result.status = SingleConversionStatus::ServiceError;
        result.error = ex.what();
        return result;
    }
}
```

`previous_bytes` remains zero here; the production adapter in Task 6 reads the existing Markdown size before sending the request.

- [ ] **Step 5: Run focused tests**

```bash
cmake --build build --target test_markitdown_proxy -j2
ctest --test-dir build -R '^MarkitdownProxyTests$' --output-on-failure
```

Expected: all proxy tests pass.

- [ ] **Step 6: Commit the proxy slice**

```bash
git add src/integration/LLMIntegration/MarkitdownProxy.h \
  src/integration/LLMIntegration/MarkitdownProxy.cpp \
  tests/UnitTest/test_markitdown_proxy.cpp tests/CMakeLists.txt
git commit -m "feat(markitdown): add single-file C++ client"
```

---

### Task 4: Expose Deterministic and Atomic FileExtractor Operations

**Files:**
- Modify: `src/core/DatabaseManager/FileExtractor/FileExtractor.h:4-90`
- Modify: `src/core/DatabaseManager/FileExtractor/FileExtractor_Extract.cpp:15-407`
- Create: `tests/UnitTest/test_file_extractor_text_dump.cpp`
- Modify: `tests/CMakeLists.txt`

**Interfaces:**
- Consumes: existing `FileRecord`, `dbManager_->getDb()`, `generateOutputPath()`, and private `extractFile()`.
- Produces: the locked `AtomicExtractionStatus`, `AtomicExtractionResult`, ordered query methods, safe output resolver, and atomic extraction method.

- [ ] **Step 1: Write failing ordering and path-confinement tests**

Create `tests/UnitTest/test_file_extractor_text_dump.cpp`:

```cpp
#include <gtest/gtest.h>
#include <sqlite3.h>
#include <filesystem>
#include <fstream>
#include "DatabaseManager/FileExtractor/FileExtractor.h"

namespace fs = std::filesystem;

namespace {

class SQLiteFixture : public ::testing::Test {
protected:
    void SetUp() override {
        ASSERT_EQ(sqlite3_open(":memory:", &db_), SQLITE_OK);
        ASSERT_EQ(sqlite3_exec(db_, R"SQL(
            CREATE TABLE files (
                inode INTEGER, name TEXT, path TEXT, size INTEGER,
                mtime INTEGER, ctime INTEGER, type TEXT,
                is_deleted INTEGER, is_allocated INTEGER, md5 TEXT,
                partition_num INTEGER
            );
            INSERT INTO files VALUES
                (8, 'z', '/z.txt', 1, 0, 0, 'REG', 0, 1, '', 0),
                (9, 'a2', '/a.txt', 1, 0, 0, 'REG', 0, 1, '', 2),
                (3, 'a1', '/a.txt', 1, 0, 0, 'REG', 0, 1, '', 1),
                (2, 'deleted', '/b.txt', 1, 0, 0, 'REG', 1, 1, '', 0),
                (1, 'dir', '/c', 0, 0, 0, 'DIR', 0, 1, '', 0);
        )SQL", nullptr, nullptr, nullptr), SQLITE_OK);
    }
    void TearDown() override { sqlite3_close(db_); }
    sqlite3* db_ = nullptr;
};

TEST_F(SQLiteFixture, OrdersAllocatedRegularFilesDeterministically) {
    std::string error;
    const auto rows = FileExtractor::queryRegularFilesOrdered(db_, &error);
    ASSERT_TRUE(error.empty());
    ASSERT_EQ(rows.size(), 3U);
    EXPECT_EQ(rows[0].path, "/a.txt");
    EXPECT_EQ(rows[0].partitionNum, 1);
    EXPECT_EQ(rows[0].inode, 3);
    EXPECT_EQ(rows[1].partitionNum, 2);
    EXPECT_EQ(rows[2].path, "/z.txt");
}

TEST(FileExtractorTextDumpPath, ResolvesImagePathBeneathRoot) {
    const fs::path root = fs::temp_directory_path() / "tracelens-safe-path";
    fs::remove_all(root);
    fs::create_directories(root);
    std::string error;
    const auto result = FileExtractor::resolveSafeOutputPath(
        root, "/etc/auth.log", &error);
    ASSERT_TRUE(result.has_value());
    EXPECT_EQ(*result, root / "etc" / "auth.log");
    fs::remove_all(root);
}

TEST(FileExtractorTextDumpPath, RejectsTraversalAndSymlinkComponents) {
    const fs::path root = fs::temp_directory_path() / "tracelens-unsafe-path";
    const fs::path outside = fs::temp_directory_path() / "tracelens-outside";
    fs::remove_all(root);
    fs::remove_all(outside);
    fs::create_directories(root);
    fs::create_directories(outside);
    fs::create_directory_symlink(outside, root / "linked");
    std::string error;
    EXPECT_FALSE(FileExtractor::resolveSafeOutputPath(
        root, "../../escape", &error).has_value());
    error.clear();
    EXPECT_FALSE(FileExtractor::resolveSafeOutputPath(
        root, "/linked/file.txt", &error).has_value());
    fs::remove_all(root);
    fs::remove_all(outside);
}

} // namespace
```

- [ ] **Step 2: Register and run the target to verify the APIs are missing**

Add:

```cmake
add_executable(
  test_file_extractor_text_dump
  UnitTest/test_file_extractor_text_dump.cpp
  ../src/core/DatabaseManager/FileExtractor/FileExtractor.cpp
  ../src/core/DatabaseManager/FileExtractor/FileExtractor_Extract.cpp
  ../src/core/DatabaseManager/DatabaseManager.cpp
  ../src/analyzers/ImageAnalyzer/XFSHelper.cpp
  ../src/core/AuditLog/AuditLog.cpp)

target_include_directories(test_file_extractor_text_dump PRIVATE ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(
  test_file_extractor_text_dump ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES}
  sqlite3 tsk pthread)
add_test(NAME FileExtractorTextDumpTests COMMAND test_file_extractor_text_dump)
```

Run:

```bash
cmake -S . -B build
cmake --build build --target test_file_extractor_text_dump -j2
```

Expected: compilation fails because the ordered-query and safe-path APIs do not exist.

- [ ] **Step 3: Add locked public types and methods to `FileExtractor.h`**

Add `<filesystem>`, `<optional>`, and `<cstdint>`, then place the locked enum, result struct, and methods in the public section. Keep existing extraction methods source-compatible.

- [ ] **Step 4: Implement the deterministic SQLite query**

In `FileExtractor_Extract.cpp`, implement `queryRegularFilesOrdered()` with this SQL:

```cpp
const char* sql = R"SQL(
    SELECT inode, name, path, size, mtime, ctime, type, is_deleted, md5,
           COALESCE(partition_num, 0)
    FROM files
    WHERE type = 'REG'
      AND is_deleted = 0
      AND COALESCE(is_allocated, 1) = 1
    ORDER BY path COLLATE BINARY ASC,
             COALESCE(partition_num, 0) ASC,
             inode ASC
)SQL";
```

Populate all `FileRecord` fields in the same defensive manner as `searchFiles()`, finalize the statement on every path, and set `*error` from `sqlite3_errmsg(db)` when prepare or stepping fails. The instance method delegates to the static method:

```cpp
std::vector<FileRecord> FileExtractor::listRegularFilesOrdered(std::string* error) {
    if (!dbManager_ || !dbManager_->getDb()) {
        if (error) *error = "File extractor database is not initialized";
        return {};
    }
    return queryRegularFilesOrdered(dbManager_->getDb(), error);
}
```

- [ ] **Step 5: Implement path confinement without following symlinks**

Use lexical normalization, reject every `..` component, strip only the image path's root, and reject existing symlink components:

```cpp
std::optional<fs::path> FileExtractor::resolveSafeOutputPath(
        const fs::path& outputRoot,
        const std::string& imagePath,
        std::string* error) {
    std::error_code ec;
    fs::create_directories(outputRoot, ec);
    if (ec || fs::is_symlink(fs::symlink_status(outputRoot, ec))) {
        if (error) *error = "Output root is unavailable or is a symlink: " + outputRoot.string();
        return std::nullopt;
    }

    fs::path relative = fs::path(imagePath).relative_path().lexically_normal();
    if (relative.empty() || relative == ".") {
        if (error) *error = "Image path does not identify a file";
        return std::nullopt;
    }
    for (const auto& component : relative) {
        if (component == "..") {
            if (error) *error = "Image path escapes the output root: " + imagePath;
            return std::nullopt;
        }
    }

    fs::path current = outputRoot;
    for (const auto& component : relative.parent_path()) {
        current /= component;
        const auto status = fs::symlink_status(current, ec);
        if (!ec && fs::is_symlink(status)) {
            if (error) *error = "Output path contains a symlink: " + current.string();
            return std::nullopt;
        }
        ec.clear();
    }
    const fs::path result = outputRoot / relative;
    const auto finalStatus = fs::symlink_status(result, ec);
    if (!ec && fs::is_symlink(finalStatus)) {
        if (error) *error = "Output file is a symlink: " + result.string();
        return std::nullopt;
    }
    return result;
}
```

- [ ] **Step 6: Implement atomic extraction and reuse detection**

`extractRecordAtomically()` must:

1. call `resolveSafeOutputPath()`;
2. record an existing regular final file's size as `previous_bytes`;
3. return `Reused` when that size equals nonnegative `record.size`;
4. create the parent directory and a same-directory temp path beginning `.tracelens-textdump-tmp-`;
5. call private `extractFile(record, tempPath, true, nullptr)`;
6. remove the temp on failure;
7. atomically replace the final file (`std::filesystem::rename` on POSIX; `MoveFileExW(..., MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)` on Windows);
8. return actual final `file_size()` and never leave a temp file.

Use this result construction:

```cpp
AtomicExtractionResult result;
result.output_path = finalPath;
result.previous_bytes = previousBytes;
if (!extractFile(record, tempPath.string(), true, nullptr)) {
    fs::remove(tempPath, ec);
    result.status = AtomicExtractionStatus::Failed;
    result.error = "Failed to extract " + record.path;
    return result;
}
if (!atomicReplace(tempPath, finalPath, result.error)) {
    fs::remove(tempPath, ec);
    result.status = AtomicExtractionStatus::Failed;
    return result;
}
result.status = AtomicExtractionStatus::Extracted;
result.output_bytes = fs::file_size(finalPath, ec);
if (ec) {
    result.status = AtomicExtractionStatus::Failed;
    result.error = "Cannot stat extracted file: " + ec.message();
}
return result;
```

The temporary filename must include partition and inode plus a process-unique suffix so concurrent files cannot collide.

- [ ] **Step 7: Run focused tests and existing extraction-related regression tests**

```bash
cmake --build build --target test_file_extractor_text_dump -j2
ctest --test-dir build -R '^(FileExtractorTextDumpTests|SceneClassifierGTests)$' \
  --output-on-failure
```

Expected: both selected test registrations pass.

- [ ] **Step 8: Commit the FileExtractor slice**

```bash
git add src/core/DatabaseManager/FileExtractor/FileExtractor.h \
  src/core/DatabaseManager/FileExtractor/FileExtractor_Extract.cpp \
  tests/UnitTest/test_file_extractor_text_dump.cpp tests/CMakeLists.txt
git commit -m "feat(extractor): add ordered atomic text-dump extraction"
```

---

### Task 5: Implement and Unit-Test the Text Dump Policy Engine

**Files:**
- Create: `src/export/TextDumpExporter.h`
- Create: `src/export/TextDumpExporter.cpp`
- Create: `tests/UnitTest/test_text_dump_exporter.cpp`
- Modify: `tests/CMakeLists.txt`

**Interfaces:**
- Consumes: only `FileRecord`, `ITextDumpFileSource`, and `ITextDumpConverter`; tests use fakes.
- Produces: every locked `forensics::textdump` type and `TextDumpExporter` API used by Task 6.

- [ ] **Step 1: Create the locked header before writing tests**

Create `src/export/TextDumpExporter.h` with all locked interfaces from the File Structure section. Include:

```cpp
#pragma once
#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>
#include "DatabaseManager/DatabaseManagerDataTypes.h"
```

Do not include `FileExtractor.h` or `MarkitdownProxy.h`; the policy layer must remain independent of production adapters.

- [ ] **Step 2: Write fakes and the first failing soft-limit test**

Create `tests/UnitTest/test_text_dump_exporter.cpp`. Define fakes that write actual fixture files so accounting exercises `std::filesystem`:

```cpp
#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>
#include <map>
#include "export/TextDumpExporter.h"

namespace fs = std::filesystem;
using namespace forensics::textdump;

namespace {

void writeBytes(const fs::path& path, size_t size, char fill = 'x') {
    fs::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::binary);
    std::string bytes(size, fill);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

class FakeSource final : public ITextDumpFileSource {
public:
    bool available = true;
    std::vector<FileRecord> records;
    std::map<std::string, size_t> sizes;
    std::vector<std::string> started;

    bool initialize(std::string& error) override {
        if (!available) error = "source unavailable";
        return available;
    }
    std::vector<FileRecord> listRegularFilesOrdered(std::string&) override {
        return records;
    }
    FileDeltaResult extractOne(const FileRecord& record,
                               const fs::path& root) override {
        started.push_back(record.path);
        const fs::path output = root / fs::path(record.path).relative_path();
        const uint64_t before = fs::exists(output) ? fs::file_size(output) : 0;
        writeBytes(output, sizes.at(record.path), 'o');
        return {OriginalStatus::Extracted, output, before,
                static_cast<uint64_t>(sizes.at(record.path)), ""};
    }
    int extractAll(const fs::path& root, std::string&) override {
        for (const auto& record : records) extractOne(record, root);
        return static_cast<int>(records.size());
    }
};

class FakeConverter final : public ITextDumpConverter {
public:
    bool available = true;
    std::map<std::string, size_t> sizes;
    std::map<std::string, MarkdownStatus> statuses;
    std::vector<std::string> started;

    bool isAvailable() override { return available; }
    MarkdownDeltaResult convertOne(const fs::path& inputRoot,
                                   const fs::path& inputFile,
                                   const fs::path& outputRoot,
                                   bool) override {
        const auto rel = fs::relative(inputFile, inputRoot);
        started.push_back("/" + rel.generic_string());
        const fs::path output = outputRoot / (rel.string() + ".md");
        const uint64_t before = fs::exists(output) ? fs::file_size(output) : 0;
        const auto status = statuses.count(started.back())
            ? statuses.at(started.back()) : MarkdownStatus::Converted;
        if (status == MarkdownStatus::Converted) {
            writeBytes(output, sizes.at(started.back()), 'm');
            return {status, output, before,
                    static_cast<uint64_t>(sizes.at(started.back())), ""};
        }
        return {status, output, before, before,
                status == MarkdownStatus::ServiceError ? "service lost" : "conversion failed"};
    }
    BatchConversionResult convertBatch(const fs::path&, const fs::path&) override {
        return {true, 0, 0, 0, 0, ""};
    }
};

class TextDumpExporterTest : public ::testing::Test {
protected:
    void SetUp() override {
        root = fs::temp_directory_path() / "tracelens-text-dump-exporter";
        fs::remove_all(root);
        fs::create_directories(root);
    }
    void TearDown() override { fs::remove_all(root); }
    FileRecord record(const std::string& path, int64_t inode) {
        FileRecord value{};
        value.path = path;
        value.name = fs::path(path).filename().string();
        value.inode = inode;
        value.partitionNum = 0;
        value.type = "REG";
        value.isDeleted = 0;
        value.isAllocated = 1;
        return value;
    }
    fs::path root;
};

TEST_F(TextDumpExporterTest, CompletesActiveFileThenStopsBeforeNextFile) {
    FakeSource source;
    source.records = {record("/a.txt", 1), record("/b.txt", 2)};
    source.sizes = {{"/a.txt", 12}, {"/b.txt", 3}};
    FakeConverter converter;
    converter.sizes = {{"/a.txt", 5}, {"/b.txt", 2}};
    TextDumpExporter exporter(source, converter);

    const auto result = exporter.run({
        root / "originals", root / "markdown", uint64_t{10}});

    EXPECT_EQ(source.started, std::vector<std::string>({"/a.txt"}));
    EXPECT_EQ(converter.started, std::vector<std::string>({"/a.txt"}));
    EXPECT_EQ(result.final_bytes, 17U);
    EXPECT_TRUE(result.truncated);
    EXPECT_EQ(result.stop_reason, StopReason::SizeLimitReached);
}

} // namespace
```

- [ ] **Step 3: Register the exporter test and prove the implementation is missing**

```cmake
add_executable(
  test_text_dump_exporter
  UnitTest/test_text_dump_exporter.cpp
  ../src/export/TextDumpExporter.cpp)

target_include_directories(test_text_dump_exporter PRIVATE ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(test_text_dump_exporter ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)
add_test(NAME TextDumpExporterTests COMMAND test_text_dump_exporter)
```

Run:

```bash
cmake -S . -B build
cmake --build build --target test_text_dump_exporter -j2
```

Expected: linker or compile failure because `TextDumpExporter.cpp` has no implementation.

- [ ] **Step 4: Implement safe accounting and stale-temp cleanup first**

In `TextDumpExporter.cpp`, define:

```cpp
#include "TextDumpExporter.h"
#include <iomanip>
#include <sstream>

namespace fs = std::filesystem;
namespace forensics::textdump {
namespace {
constexpr std::string_view kTempPrefix = ".tracelens-textdump-tmp-";

bool prepareRoot(const fs::path& root, std::string& error) {
    std::error_code ec;
    if (fs::exists(root, ec) && fs::is_symlink(fs::symlink_status(root, ec))) {
        error = "Text dump root is a symlink: " + root.string();
        return false;
    }
    fs::create_directories(root, ec);
    if (ec || !fs::is_directory(root, ec)) {
        error = "Cannot prepare text dump root " + root.string() + ": " + ec.message();
        return false;
    }
    return true;
}

std::optional<uint64_t> scanRoot(const fs::path& root, std::string& error) {
    uint64_t total = 0;
    std::error_code ec;
    fs::recursive_directory_iterator it(
        root, fs::directory_options::skip_permission_denied, ec), end;
    if (ec) {
        error = "Cannot scan " + root.string() + ": " + ec.message();
        return std::nullopt;
    }
    for (; it != end; it.increment(ec)) {
        if (ec) {
            error = "Cannot continue scanning " + root.string() + ": " + ec.message();
            return std::nullopt;
        }
        const auto status = it->symlink_status(ec);
        if (ec) {
            error = "Cannot inspect " + it->path().string() + ": " + ec.message();
            return std::nullopt;
        }
        if (fs::is_symlink(status)) {
            if (fs::is_directory(status)) it.disable_recursion_pending();
            continue;
        }
        if (!fs::is_regular_file(status)) continue;
        if (it->path().filename().string().starts_with(kTempPrefix)) {
            fs::remove(it->path(), ec);
            if (ec) {
                error = "Cannot remove stale text-dump temp file: " + ec.message();
                return std::nullopt;
            }
            continue;
        }
        const uint64_t size = fs::file_size(it->path(), ec);
        if (ec || size > std::numeric_limits<uint64_t>::max() - total) {
            error = ec ? ec.message() : "Text dump usage overflows uint64_t";
            return std::nullopt;
        }
        total += size;
    }
    return total;
}

void applyDelta(uint64_t& usage, uint64_t before, uint64_t after) {
    usage -= std::min(usage, before);
    if (after > std::numeric_limits<uint64_t>::max() - usage) {
        throw std::overflow_error("Text dump usage overflows uint64_t");
    }
    usage += after;
}
} // namespace
```

`calculateUsage()` calls `prepareRoot()` for both roots, scans each, and checked-adds the totals. This implementation must use `symlink_status`, not `status`, to avoid following links.

- [ ] **Step 5: Implement unlimited behavior unchanged**

`run()` first checks `converter_.isAvailable()`. When `max_bytes` is absent:

```cpp
if (!options.max_bytes.has_value()) {
    std::string error;
    if (!source_.initialize(error)) {
        result.stop_reason = StopReason::OutputError;
        result.message = error;
        return result;
    }
    const int extracted = source_.extractAll(options.original_root, error);
    if (extracted < 0) {
        result.stop_reason = StopReason::OutputError;
        result.message = error;
        return result;
    }
    const auto batch = converter_.convertBatch(
        options.original_root, options.markdown_root);
    result.candidate_files = batch.total;
    result.processed_files = batch.total;
    result.originals_extracted = static_cast<size_t>(extracted);
    result.markdown_converted = batch.converted;
    result.markdown_skipped = batch.skipped;
    result.markdown_failed = batch.failed;
    if (!batch.ok) {
        result.stop_reason = StopReason::ServiceUnavailable;
        result.message = batch.error;
    }
    std::string usageError;
    const auto usage = calculateUsage(
        options.original_root, options.markdown_root, usageError);
    if (usage) result.initial_bytes = result.final_bytes = *usage;
    return result;
}
```

This path does not enumerate per-file records and does not call `convertOne()`.

- [ ] **Step 6: Implement limited per-file policy**

For `max_bytes.has_value()`:

1. prepare/account roots;
2. set `initial_bytes`, `final_bytes`, and `max_bytes`;
3. return `SizeLimitReached` immediately if initial usage is already at or above the limit;
4. initialize the source and obtain ordered records;
5. before each record, compare current usage with the limit;
6. call `extractOne()` and update original counters/delta;
7. when extraction is `Extracted`, call `convertOne()` even if Markdown exists so it is regenerated; when extraction is `Reused`, allow the converter adapter to reuse existing Markdown;
8. update Markdown counters/delta;
9. on `ServiceError`, stop immediately with `ServiceUnavailable`;
10. after the loop, mark `SizeLimitReached` if unprocessed candidates remain and usage is at/above the limit.

Use this status handling in the loop:

```cpp
for (const auto& record : records) {
    if (usage >= *options.max_bytes) {
        result.truncated = true;
        result.stop_reason = StopReason::SizeLimitReached;
        result.message = "size limit reached; completed files were preserved";
        break;
    }
    ++result.processed_files;
    const auto original = source_.extractOne(record, options.original_root);
    switch (original.status) {
        case OriginalStatus::Extracted: ++result.originals_extracted; break;
        case OriginalStatus::Reused: ++result.originals_reused; break;
        case OriginalStatus::Failed:
        case OriginalStatus::UnsafePath:
            ++result.originals_failed;
            continue;
    }
    applyDelta(usage, original.previous_bytes, original.output_bytes);

    const auto markdown = converter_.convertOne(
        options.original_root,
        original.output_path,
        options.markdown_root,
        original.status == OriginalStatus::Extracted);
    switch (markdown.status) {
        case MarkdownStatus::Converted: ++result.markdown_converted; break;
        case MarkdownStatus::Reused: ++result.markdown_reused; break;
        case MarkdownStatus::Skipped: ++result.markdown_skipped; break;
        case MarkdownStatus::Failed: ++result.markdown_failed; break;
        case MarkdownStatus::ServiceError:
            ++result.markdown_failed;
            applyDelta(usage, markdown.previous_bytes, markdown.output_bytes);
            result.final_bytes = usage;
            result.stop_reason = StopReason::ServiceUnavailable;
            result.message = markdown.error;
            return result;
    }
    applyDelta(usage, markdown.previous_bytes, markdown.output_bytes);
    result.final_bytes = usage;
}
```

Catch filesystem/overflow exceptions at the outer `run()` boundary, return `OutputError`, preserve `final_bytes`, and place the exception message in `result.message`.

- [ ] **Step 7: Add accounting, resume, and failure tests**

Extend `test_text_dump_exporter.cpp` with these concrete cases:

```cpp
TEST_F(TextDumpExporterTest, CountsBothTreesAndDoesNotFollowSymlinks) {
    writeBytes(root / "originals/a", 3);
    writeBytes(root / "markdown/a.md", 5);
    writeBytes(root / "outside/large", 100);
    fs::create_directory_symlink(root / "outside", root / "originals/link");
    writeBytes(root / "originals/.tracelens-textdump-tmp-stale", 50);
    std::string error;
    const auto usage = TextDumpExporter::calculateUsage(
        root / "originals", root / "markdown", error);
    ASSERT_TRUE(usage.has_value()) << error;
    EXPECT_EQ(*usage, 8U);
    EXPECT_FALSE(fs::exists(root / "originals/.tracelens-textdump-tmp-stale"));
}

TEST_F(TextDumpExporterTest, DoesNoWorkWhenExistingUsageMeetsLimit) {
    writeBytes(root / "originals/existing", 10);
    FakeSource source;
    source.records = {record("/a.txt", 1)};
    FakeConverter converter;
    TextDumpExporter exporter(source, converter);
    const auto result = exporter.run({
        root / "originals", root / "markdown", uint64_t{10}});
    EXPECT_TRUE(source.started.empty());
    EXPECT_EQ(result.stop_reason, StopReason::SizeLimitReached);
}

TEST_F(TextDumpExporterTest, ContinuesAfterPerFileConversionFailure) {
    FakeSource source;
    source.records = {record("/a.txt", 1), record("/b.txt", 2)};
    source.sizes = {{"/a.txt", 1}, {"/b.txt", 1}};
    FakeConverter converter;
    converter.sizes = {{"/b.txt", 1}};
    converter.statuses["/a.txt"] = MarkdownStatus::Failed;
    TextDumpExporter exporter(source, converter);
    const auto result = exporter.run({
        root / "originals", root / "markdown", uint64_t{100}});
    EXPECT_EQ(source.started.size(), 2U);
    EXPECT_EQ(result.markdown_failed, 1U);
    EXPECT_EQ(result.markdown_converted, 1U);
}

TEST_F(TextDumpExporterTest, StopsAfterServiceFailure) {
    FakeSource source;
    source.records = {record("/a.txt", 1), record("/b.txt", 2)};
    source.sizes = {{"/a.txt", 1}, {"/b.txt", 1}};
    FakeConverter converter;
    converter.statuses["/a.txt"] = MarkdownStatus::ServiceError;
    TextDumpExporter exporter(source, converter);
    const auto result = exporter.run({
        root / "originals", root / "markdown", uint64_t{100}});
    EXPECT_EQ(source.started, std::vector<std::string>({"/a.txt"}));
    EXPECT_EQ(result.stop_reason, StopReason::ServiceUnavailable);
}
```

Add a resume test where the fake reports `OriginalStatus::Reused` and `MarkdownStatus::Reused` with equal before/after sizes; assert `initial_bytes == final_bytes`, no duplicate accounting, and a larger limit permits the next candidate.

- [ ] **Step 8: Implement stable byte formatting and run tests**

`formatBytes()` chooses the largest binary unit and prints one decimal place:

```cpp
std::string TextDumpExporter::formatBytes(uint64_t bytes) {
    static constexpr const char* units[] = {"B", "KiB", "MiB", "GiB", "TiB"};
    double value = static_cast<double>(bytes);
    size_t unit = 0;
    while (value >= 1024.0 && unit < 4) {
        value /= 1024.0;
        ++unit;
    }
    std::ostringstream out;
    out << std::fixed << std::setprecision(unit == 0 ? 0 : 1)
        << value << ' ' << units[unit];
    return out.str();
}
```

Run:

```bash
cmake --build build --target test_text_dump_exporter -j2
ctest --test-dir build -R '^TextDumpExporterTests$' --output-on-failure
```

Expected: every exporter policy test passes.

- [ ] **Step 9: Commit the policy slice**

```bash
git add src/export/TextDumpExporter.h src/export/TextDumpExporter.cpp \
  tests/UnitTest/test_text_dump_exporter.cpp tests/CMakeLists.txt
git commit -m "feat(export): enforce per-file text dump soft limit"
```

---

### Task 6: Add Production Adapters and Wire the Orchestrator

**Files:**
- Create: `src/export/TextDumpAdapters.h`
- Create: `src/export/TextDumpAdapters.cpp`
- Modify: `src/AnalysisOrchestrator.cpp:15-20,347-430`
- Modify: `CMakeLists.txt:133-229,260-493`
- Modify: `tests/UnitTest/test_text_dump_exporter.cpp`

**Interfaces:**
- Consumes: Tasks 3–5 interfaces and existing `MarkitdownProxy::BatchResult`.
- Produces: `FileExtractorTextDumpSource`, `MarkitdownTextDumpConverter`, and the production `AnalysisOrchestrator` call path.

- [ ] **Step 1: Add an adapter mapping test before production classes**

 `test_text_dump_exporter.cpp`, add compile-time checks after including `export/TextDumpAdapters.h`:

```cpp
#include <type_traits>
#include "export/TextDumpAdapters.h"

static_assert(std::is_base_of_v<
    forensics::textdump::ITextDumpFileSource,
    forensics::textdump::FileExtractorTextDumpSource>);
static_assert(std::is_base_of_v<
    forensics::textdump::ITextDumpConverter,
    forensics::textdump::MarkitdownTextDumpConverter>);
```

Run the exporter target and expect compilation to fail because the adapter header does not exist.

- [ ] **Step 2: Declare focused production adapters**

Create `src/export/TextDumpAdapters.h`:

```cpp
#pragma once
#include <memory>
#include "TextDumpExporter.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "LLMIntegration/MarkitdownProxy.h"

namespace forensics::textdump {

class FileExtractorTextDumpSource final : public ITextDumpFileSource {
public:
    FileExtractorTextDumpSource(std::string imagePath, std::string databasePath);
    bool initialize(std::string& error) override;
    std::vector<FileRecord> listRegularFilesOrdered(std::string& error) override;
    FileDeltaResult extractOne(const FileRecord& record,
                               const std::filesystem::path& outputRoot) override;
    int extractAll(const std::filesystem::path& outputRoot,
                   std::string& error) override;
private:
    FileExtractor extractor_;
};

class MarkitdownTextDumpConverter final : public ITextDumpConverter {
public:
    explicit MarkitdownTextDumpConverter(forensics::llm::MarkitdownProxy& proxy);
    bool isAvailable() override;
    MarkdownDeltaResult convertOne(
        const std::filesystem::path& inputRoot,
        const std::filesystem::path& inputFile,
        const std::filesystem::path& outputRoot,
        bool force) override;
    BatchConversionResult convertBatch(
        const std::filesystem::path& inputRoot,
        const std::filesystem::path& outputRoot) override;
private:
    forensics::llm::MarkitdownProxy& proxy_;
};

} // namespace forensics::textdump
```

- [ ] **Step 3: Implement source result mapping**

In `TextDumpAdapters.cpp`, initialize the existing extractor, delegate ordering, map each atomic status one-for-one, and preserve actual before/after sizes:

```cpp
FileDeltaResult FileExtractorTextDumpSource::extractOne(
        const FileRecord& record, const fs::path& outputRoot) {
    const auto source = extractor_.extractRecordAtomically(record, outputRoot);
    OriginalStatus status = OriginalStatus::Failed;
    switch (source.status) {
        case AtomicExtractionStatus::Extracted: status = OriginalStatus::Extracted; break;
        case AtomicExtractionStatus::Reused: status = OriginalStatus::Reused; break;
        case AtomicExtractionStatus::UnsafePath: status = OriginalStatus::UnsafePath; break;
        case AtomicExtractionStatus::Failed: status = OriginalStatus::Failed; break;
    }
    return {status, source.output_path, source.previous_bytes,
            source.output_bytes, source.error};
}
```

`extractAll()` calls the existing unlimited method:

```cpp
return extractor_.extractAll(outputRoot.string(), false, false, nullptr);
```

- [ ] **Step 4: Implement converter reuse and proxy mapping**

Before calling Python, derive the expected Markdown path from `inputFile` relative to `inputRoot` and append `.md`. If it is an existing non-symlink regular file, return `MarkdownStatus::Reused` with identical before/after size. Otherwise call `convertOneToMarkdown()` and map statuses:

```cpp
const fs::path relative = fs::relative(inputFile, inputRoot);
const fs::path expected = outputRoot / (relative.string() + ".md");
std::error_code ec;
const auto status = fs::symlink_status(expected, ec);
if (!ec && fs::is_regular_file(status) && !fs::is_symlink(status)) {
    const auto bytes = fs::file_size(expected, ec);
    if (!ec) return {MarkdownStatus::Reused, expected, bytes, bytes, ""};
}
const uint64_t previous = (!ec && fs::is_regular_file(status))
    ? fs::file_size(expected, ec) : 0;
const auto converted = proxy_.convertOneToMarkdown(
    inputRoot.string(), inputFile.string(), outputRoot.string());
```

Map C++ proxy `Converted`, `Skipped`, `Failed`, and `ServiceError` to exporter statuses. Set `previous_bytes=previous`; use the proxy's `output_bytes` for converted output and `previous` for skipped/failed outputs that did not replace an existing valid file. When `force` is true, the old Markdown corresponds to a replaced original and is no longer valid: if conversion does not produce a replacement (`Skipped`, `Failed`, or `ServiceError`), remove the stale expected Markdown and report `output_bytes=0`. This ensures a later run cannot incorrectly reuse Markdown generated from the previous source content.

`convertBatch()` maps every field from `MarkitdownProxy::batchConvertToMarkdown()`.

- [ ] **Step 5: Honor forced regeneration after original replacement**

The locked converter interface already carries:

```cpp
bool force
```

The exporter passes `force=true` only for `OriginalStatus::Extracted` and `false` for `OriginalStatus::Reused`. Implement the adapter's reuse guard as:

```cpp
if (!force && !ec && fs::is_regular_file(status) && !fs::is_symlink(status)) {
    const auto bytes = fs::file_size(expected, ec);
    if (!ec) return {MarkdownStatus::Reused, expected, bytes, bytes, ""};
}
```

Ensure all fakes accept the fourth parameter (they may ignore it unless testing regeneration). Add a test with a pre-existing Markdown file and `OriginalStatus::Extracted`: assert the converter is called with `force=true` and the output changes. Add a second case with `OriginalStatus::Reused`: assert `force=false` allows Markdown reuse. This preserves resume performance while preventing mismatched originals from retaining stale Markdown.

Run:

```bash
cmake --build build --target test_text_dump_exporter -j2
ctest --test-dir build -R '^TextDumpExporterTests$' --output-on-failure
```

Expected: all exporter tests compile and pass.

- [ ] **Step 6: Replace the embedded orchestrator text-dump block**

Add:

```cpp
#include "export/TextDumpAdapters.h"
#include "export/TextDumpExporter.h"
```

Replace the current `if (args.dump_text)` body with:

```cpp
if (args.dump_text) {
    const fs::path originalRoot = prefix + baseName + "_extracted_files";
    const fs::path markdownRoot = prefix + baseName + "_extracted_text";
    textdump::FileExtractorTextDumpSource source(args.image_path, effectiveRawDb);
    textdump::MarkitdownTextDumpConverter converter(
        forensics::llm::MarkitdownProxy::instance());
    textdump::TextDumpExporter exporter(source, converter);
    const auto result = exporter.run({
        originalRoot, markdownRoot, args.dump_text_max_bytes});

    std::cout << "Text dump: " << result.processed_files << "/"
              << result.candidate_files << " files processed\n"
              << "  Extracted: " << result.originals_extracted << " new, "
              << result.originals_reused << " reused, "
              << result.originals_failed << " failed\n"
              << "  Markdown: " << result.markdown_converted << " converted, "
              << result.markdown_reused << " reused, "
              << result.markdown_skipped << " skipped, "
              << result.markdown_failed << " failed\n";
    if (result.max_bytes) {
        std::cout << "  Size: " << textdump::TextDumpExporter::formatBytes(result.final_bytes)
                  << " / " << textdump::TextDumpExporter::formatBytes(*result.max_bytes)
                  << " soft limit\n";
    } else {
        std::cout << "  Size: " << textdump::TextDumpExporter::formatBytes(result.final_bytes)
                  << " (unlimited)\n";
    }
    if (result.stop_reason != textdump::StopReason::Completed) {
        std::cerr << "Warning: Text dump stopped: " << result.message << "\n"
                  << "  Core forensic databases remain valid." << std::endl;
    } else {
        std::cout << "✓ Text dump complete -> " << markdownRoot << std::endl;
    }
    std::cout << std::endl;
}
```

Do not return a nonzero status for `SizeLimitReached`, `ServiceUnavailable`, or `OutputError`; the enclosing analysis remains successful unless an earlier core analysis step failed.

- [ ] **Step 7: Add production sources to CMake and build all affected targets**

Add `${CMAKE_SOURCE_DIR}/src/export` to include directories and these to `LIB_SOURCES`:

```cmake
src/export/TextDumpExporter.cpp
src/export/TextDumpAdapters.cpp
```

Add `TextDumpAdapters.cpp`, `FileExtractor.cpp`, `FileExtractor_Extract.cpp`, `DatabaseManager.cpp`, `XFSHelper.cpp`, `MarkitdownProxy.cpp`, `Logger.cpp`, `ConfigManager.cpp`, `PathManager.cpp`, and `AuditLog.cpp` to the `test_text_dump_exporter` target; link `sqlite3`, `tsk`, `nlohmann_json::nlohmann_json`, and `cpp_dotenv` in addition to GTest/pthread.

Run:

```bash
cmake -S . -B build
cmake --build build --target test_text_dump_exporter forensic_analyzer -j2
ctest --test-dir build -R \
  '^(TextDumpExporterTests|FileExtractorTextDumpTests|MarkitdownProxyTests|CommandLineParserTests)$' \
  --output-on-failure
```

Expected: the binary builds and all four feature test registrations pass.

- [ ] **Step 8: Confirm unlimited mode still selects batch conversion**

Add a test using the fakes where `max_bytes=std::nullopt`; assert:

```cpp
EXPECT_EQ(source.extract_all_calls, 1);
EXPECT_EQ(converter.batch_calls, 1);
EXPECT_TRUE(source.started.empty());       // no per-file extraction
EXPECT_TRUE(converter.started.empty());    // no per-file conversion
```

Add `extract_all_calls` and `batch_calls` counters to the fakes. Run `TextDumpExporterTests` and expect pass.

- [ ] **Step 9: Commit integration and wiring**

```bash
git add src/export/TextDumpAdapters.h src/export/TextDumpAdapters.cpp \
  src/export/TextDumpExporter.h src/export/TextDumpExporter.cpp \
  src/AnalysisOrchestrator.cpp CMakeLists.txt tests/CMakeLists.txt \
  tests/UnitTest/test_text_dump_exporter.cpp
git commit -m "feat(cli): wire limited text dump exporter"
```

---

### Task 7: Document and Verify the Complete Feature End to End

**Files:**
- Modify: `scripts/ONSITE_TEST_GUIDE.md:21-47,68-81,119-128`
- Modify only if verification exposes a defect: feature files from Tasks 1–6

**Interfaces:**
- Consumes: completed CLI binary and running Python service.
- Produces: operator documentation and observed acceptance evidence.

- [ ] **Step 1: Add the field-test command and semantics to the guide**

Under the disk-image examples in `scripts/ONSITE_TEST_GUIDE.md`, add:

```markdown
# 限制 --dump-text 的现场导出总量（原文件 + Markdown，二进制单位）
./build/forensic_analyzer /path/to/disk.E01 \
  --db-dir ./onsite-output \
  --linux-analyze \
  --no-ai \
  --dump-text-max-size 500M
```

Add these operational notes:

```markdown
- `--dump-text-max-size` 会自动启用 `--dump-text`，不要求 `--no-ai`。
- 仅统计 `<base>_extracted_files/` 与 `<base>_extracted_text/` 中的普通文件；三个核心数据库和 `--report` 不受限制。
- `K/M/G/T` 按 1024 进位，只接受正整数，例如 `500M`、`2G`。
- 上限是文件级软限制：已开始的原文件及其 Markdown 会完整保留，所以最终大小可能超过设置值；达到后不会开始下一个文件。
- 重跑时已有产物会计入额度并尽量复用；提高额度后可继续导出。
- 达到上限只会警告，主分析仍成功，核心取证数据库仍有效。
```

- [ ] **Step 2: Run parser rejection before creating analysis output**

Use a fresh path:

```bash
rm -rf build/invalid-size-output
set +e
./build/forensic_analyzer test_image.img \
  --db-dir build/invalid-size-output \
  --dump-text-max-size 1.5G
status=$?
set -e
test "$status" -eq 2
test ! -e build/invalid-size-output
```

Expected: CLI prints the strict syntax error, exits `2`, and the output directory does not exist.

- [ ] **Step 3: Run focused Python and C++ regression suites**

```bash
python_service/.venv/bin/python -m pytest \
  python_service/tests/unit/test_markitdown_routes.py \
  python_service/tests/unit/test_forensic_extractors.py -q

cmake --build build --target \
  test_command_line_parser test_markitdown_proxy \
  test_file_extractor_text_dump test_text_dump_exporter \
  forensic_analyzer -j2

ctest --test-dir build -R \
  '^(CommandLineParserTests|MarkitdownProxyTests|FileExtractorTextDumpTests|TextDumpExporterTests|SceneClassifierGTests)$' \
  --output-on-failure
```

Expected: all selected Python and C++ tests pass.

- [ ] **Step 4: Start the Python service and execute a constrained real dump**

Use the project `run` skill or start `./scripts/start_python_service.sh` as a harness-tracked background process, then wait until:

```bash
curl -fsS http://localhost:8090/api/markitdown/status
```

returns JSON containing `"available":true`.

Run:

```bash
rm -rf build/limited-output
./build/forensic_analyzer test_image.img \
  --db-dir build/limited-output \
  --no-ai \
  --dump-text-max-size 1M 2>&1 | tee build/limited-output-run.log
```

Expected:

- exit status is zero;
- `test_image_raw.db`, `test_image_events.db`, and `test_image_files.db` exist;
- both `test_image_extracted_files/` and `test_image_extracted_text/` contain complete regular files when the image has convertible content;
- summary prints `soft limit` and either `size limit reached` or a completed result if one final unit covers all candidates.

- [ ] **Step 5: Verify actual logical usage and absence of temporary files**

```bash
python3 - <<'PY'
from pathlib import Path
root = Path('build/limited-output')
roots = [root / 'test_image_extracted_files', root / 'test_image_extracted_text']
files = [p for r in roots if r.exists() for p in r.rglob('*') if p.is_file() and not p.is_symlink()]
temps = [p for p in files if p.name.startswith('.tracelens-textdump-tmp-')]
print('logical_bytes=', sum(p.stat().st_size for p in files))
print('regular_files=', len(files))
assert not temps, temps
assert (root / 'test_image_raw.db').is_file()
assert (root / 'test_image_events.db').is_file()
assert (root / 'test_image_files.db').is_file()
PY
```

Expected: no reserved temporary files remain and all core databases exist. Logical bytes may be greater than 1 MiB only because the last complete processing unit is allowed to overshoot.

- [ ] **Step 6: Verify deterministic stop and larger-limit resumption**

Capture the first run's regular-file list:

```bash
find build/limited-output/test_image_extracted_files \
     build/limited-output/test_image_extracted_text \
  -type f -printf '%p|%s\n' | sort > build/limited-first.lst

./build/forensic_analyzer test_image.img \
  --db-dir build/limited-output \
  --no-ai \
  --dump-text-max-size 1M > build/limited-rerun.log 2>&1

find build/limited-output/test_image_extracted_files \
     build/limited-output/test_image_extracted_text \
  -type f -printf '%p|%s\n' | sort > build/limited-second.lst
cmp build/limited-first.lst build/limited-second.lst
```

Expected: the same limit and existing state produce the same retained file list and sizes.

Then increase the limit:

```bash
./build/forensic_analyzer test_image.img \
  --db-dir build/limited-output \
  --no-ai \
  --dump-text-max-size 2M > build/limited-resume.log 2>&1
```

Expected: the summary reports reused outputs and processes later candidates when the previous final usage is below 2 MiB. Existing valid files are not regenerated.

- [ ] **Step 7: Verify legacy unlimited behavior**

Use a separate directory:

```bash
rm -rf build/unlimited-output
./build/forensic_analyzer test_image.img \
  --db-dir build/unlimited-output \
  --no-ai \
  --dump-text > build/unlimited-run.log 2>&1
grep -F 'unlimited' build/unlimited-run.log
```

Expected: command succeeds, invokes one batch conversion, and does not print a soft-limit stop message.

- [ ] **Step 8: Run the project verification skill and inspect the final diff**

Invoke `verify` because product source has changed. Exercise the constrained CLI flow rather than relying only on unit tests. Then run:

```bash
git diff --check
git status --short
git diff --stat
git diff -- src/CommandLineParser.h src/CommandLineParser.cpp src/main.cpp \
  src/core/DatabaseManager/FileExtractor \
  src/export src/integration/LLMIntegration/MarkitdownProxy.h \
  src/integration/LLMIntegration/MarkitdownProxy.cpp \
  src/AnalysisOrchestrator.cpp python_service/httpserver/routes/markitdown.py \
  scripts/ONSITE_TEST_GUIDE.md
```

Expected: no whitespace errors; every product change maps to the approved spec; no core database schema or web/HTTP task path changed.

- [ ] **Step 9: Commit documentation and any verification-only corrections**

```bash
git add scripts/ONSITE_TEST_GUIDE.md
# Add feature files here only when Step 8 required a verified correction.
git commit -m "docs: document constrained onsite text dumps"
```

- [ ] **Step 10: Request final code review before integration**

Invoke `superpowers:requesting-code-review`, provide the approved spec and this plan, and ask the reviewer to focus on:

- hard-vs-soft limit semantics;
- existing-file delta accounting;
- path traversal and symlink handling;
- temp-file cleanup and atomic replacement;
- distinction between per-file failure and service failure;
- preservation of unlimited behavior.

Apply only verified findings using `superpowers:receiving-code-review`, then rerun Steps 3–8 before claiming completion.

---

## Plan Self-Review Results

- **Spec coverage:** CLI grammar, implication, unlimited compatibility, two-tree accounting, existing files, symlink behavior, deterministic ordering, one-file sequencing, soft overshoot, resumption, atomic writes, Python status semantics, service-stop behavior, summaries, documentation, and end-to-end acceptance each map to an explicit task.
- **Scope:** The plan does not alter database schemas, reports, stdout quotas, HTTP-created tasks, or UI behavior.
- **Type consistency:** `dump_text_max_bytes`, `SingleConversionResult`, `AtomicExtractionResult`, exporter status names, `force`, and before/after byte fields are defined once and used consistently across adapters and tests.
- **Execution order:** Each task ends with an independently reviewable test cycle and commit. Task 6 is the first point at which all prior interfaces are wired into the product binary.
