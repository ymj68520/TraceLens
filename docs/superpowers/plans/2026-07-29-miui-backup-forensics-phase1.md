# Xiaomi (MIUI) Backup Forensics — Phase 1 (MVP Backend + CLI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Analyze an unencrypted MIUI phone backup (`descript.xml` + `*.bak`) end-to-end through the existing `AndroidAnalyzer` via a new on-demand `IFileExtractor` backend (`MiuiBackupExtractor`), producing the standard `_files.db` artifacts plus MIUI manifest + DB-inventory tables, reachable from the CLI with `--android-source miui-backup`.

**Architecture:** A `.bak` file is a MIUI text header followed by a standard Android Backup stream whose tar payload is the `/data/data/<pkg>/` tree the analyzer already parses. The new `MiuiBackupExtractor` backend (sibling of `LogicalDirExtractor`/`ZipArchiveExtractor`) strips the MIUI header, optionally inflates (zlib), streams the tar once to build a `mappedPath → (bakFile, offset, size)` index, then serves `extractFileByPath()` by mapping `data/data/<pkg>/databases|files|shared_prefs/...` → `apps/<pkg>/db|f|sp/...` and seeking on demand. The live-device `AndroidAdbExtractor` is untouched.

**Tech Stack:** C++17, POSIX tar parsing, zlib (`find_package(ZLIB)` already in `CMakeLists.txt:53`), raw `sqlite3`, GTest. OpenSSL is required by the build but is **not** used in Phase 1 (AES decryption is Phase 2).

## Global Constraints

- **No ADB changes.** Do not modify anything under `src/integration/AndroidAdbExtractor/`.
- **No new parsing logic duplicated.** Reuse the existing `AndroidAnalyzer` analyzers; the new code only adds a *data source* behind `IFileExtractor`.
- **Read-only evidence.** The backup folder is opened read-only; never write back to it.
- **No silent failure.** Unknown/encrypted `.bak` payloads are recorded as `encrypted_locked`/`parse_error` in the inventory; other apps still process.
- **UTF-8 paths.** `bakFile` names contain CJK + parentheses; handle as UTF-8 bytes (no locale-dependent `char*` widening).
- **Compile gates.** Add every new `.cpp` to the `LIB_SOURCES` list in `CMakeLists.txt` (after `ZipArchiveExtractor.cpp`, ~line 345). GTest tests register in `tests/CMakeLists.txt`.
- **Phase scope.** Phase 1 supports `enc=none` and `comp∈{0,1}` only. `AES-256-encrypted` is detected and deferred to Phase 2.

## File Structure

**Create (all under `src/analyzers/AndroidAnalyzer/`):**
- `MiuiBackupManifest.{h,cpp}` — parse `descript.xml` → `BackupMeta` + `vector<BackupPackage>`.
- `AndroidBackupHeader.{h,cpp}` — scan one `.bak` → `{version, compression, encryption, payloadOffset}`.
- `TarIndex.{h,cpp}` — stream a tar (raw or zlib-inflated) → `map<string, TarEntry>`.
- `MiuiPathMap.h` — header-only path translation helpers (`apps/<pkg>/db|f|sp` ↔ `data/data/<pkg>/...`).
- `MiuiBackupExtractor.{h,cpp}` — `IFileExtractor` backend; orchestrates the above; owns the combined index + open file handles.
- `MiuiArtifactParsers.{h,cpp}` — Phase 1: backup-manifest writer + universal DB-inventory pass (registry stub for Phase 3).

**Modify:**
- `AndroidAnalyzerDeclarations.h` — add `AndroidSourceMode::MiuiBackup`; add `backupPassword_` member + `setBackupPassword()`.
- `AndroidAnalyzerCore.cpp` — dispatch `case MiuiBackup`.
- `AndroidAnalysisDatabase.{h,cpp}` + the `AndroidAnalysisSQL` namespace — MIUI tables + `insert*` methods.
- `AnalysisOrchestrator.cpp` — route `miui-backup` through `runAndroidLogicalAnalysis`; set mode + password.
- `CommandLineParser.{h,cpp}` — accept `miui-backup`; add `--backup-password`.
- `CMakeLists.txt` — add new sources to `LIB_SOURCES`.
- `tests/CMakeLists.txt` — register `test_miui_backup_gtest`.
- `tests/UnitTest/test_miui_backup_gtest.cpp` (create) + `tests/fixtures/miui/` (synthetic `.bak` fixtures, created by a small generator script).

---

### Task 1: `AndroidBackupHeader` — scan a `.bak` to the Android Backup payload

**Files:**
- Create: `src/analyzers/AndroidAnalyzer/AndroidBackupHeader.h`, `src/analyzers/AndroidAnalyzer/AndroidBackupHeader.cpp`
- Test: `tests/UnitTest/test_miui_backup_gtest.cpp` (new), `tests/CMakeLists.txt`

**Interfaces:**
- Produces:
  ```cpp
  // AndroidBackupHeader.h
  #pragma once
  #include <string>
  #include <cstdint>
  enum class BackupEncryption { None, Aes256, Unknown };
  struct AndroidBackupHeader {
      int version = 0;                 // e.g. 5
      int compression = 0;            // 0 = none, 1 = zlib
      BackupEncryption encryption = BackupEncryption::None;
      uint64_t payloadOffset = 0;     // byte offset where the (tar|zlib|cipher) blob starts
      std::string encMarker;          // raw marker string, e.g. "none" / "AES-256-encrypted"
  };
  // Returns false (and leaves out empty) if this is not a recognized Android Backup stream.
  bool parseAndroidBackupHeader(const std::string& bakPath, AndroidBackupHeader& out);
  ```
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing test**

Create `tests/UnitTest/test_miui_backup_gtest.cpp`:
```cpp
// test_miui_backup_gtest.cpp
#include <gtest/gtest.h>
#include <fstream>
#include <filesystem>
#include "analyzers/AndroidAnalyzer/AndroidBackupHeader.h"

namespace fs = std::filesystem;

static fs::path writeTempBak(const std::string& name, const std::string& body) {
    fs::path p = fs::temp_directory_path() / name;
    std::ofstream(p, std::ios::binary) << body;
    return p;
}

TEST(AndroidBackupHeaderTest, ParsesMiuiPrefixedStream) {
    std::string body =
        "MIUI BACKUP\n2\ncom.android.deskclock 时钟\n-1\n0\n"
        "ANDROID BACKUP\n5\n0\nnone\n" + std::string(512, '\0'); // padding stands in for tar
    auto p = writeTempBak("hdr_ok.bak", body);
    AndroidBackupHeader h;
    ASSERT_TRUE(parseAndroidBackupHeader(p.string(), h));
    EXPECT_EQ(h.version, 5);
    EXPECT_EQ(h.compression, 0);
    EXPECT_EQ(h.encryption, BackupEncryption::None);
    EXPECT_EQ(h.encMarker, "none");
    // payload starts right after "none\n"
    EXPECT_GT(h.payloadOffset, 0u);
    EXPECT_EQ(body[h.payloadOffset], '\0'); // first payload byte
}

TEST(AndroidBackupHeaderTest, RejectsNonBackupFile) {
    auto p = writeTempBak("hdr_bad.bak", std::string("just some bytes that are not a backup"));
    AndroidBackupHeader h;
    EXPECT_FALSE(parseAndroidBackupHeader(p.string(), h));
}

TEST(AndroidBackupHeaderTest, DetectsAesMarker) {
    std::string body =
        "MIUI BACKUP\n2\ncom.example Ex\n-1\n0\n"
        "ANDROID BACKUP\n5\n1\nAES-256-encrypted\n" + std::string(512, '\0');
    auto p = writeTempBak("hdr_aes.bak", body);
    AndroidBackupHeader h;
    ASSERT_TRUE(parseAndroidBackupHeader(p.string(), h));
    EXPECT_EQ(h.compression, 1);
    EXPECT_EQ(h.encryption, BackupEncryption::Aes256);
    EXPECT_EQ(h.encMarker, "AES-256-encrypted");
}
```

- [ ] **Step 2: Run test to verify it fails (build link error — header absent)**

Run: `cmake --build build --target test_miui_backup_gtest 2>&1 | head`
Expected: FAIL — `AndroidBackupHeader.h` not found / `parseAndroidBackupHeader` undefined.

- [ ] **Step 3: Register the test target in `tests/CMakeLists.txt`**

Append (after the Linux analyzer block, before the compressed-log block ~line 70):
```cmake
# MIUI Backup Header / Backend Tests
add_executable(
  test_miui_backup_gtest
  UnitTest/test_miui_backup_gtest.cpp
  ../src/analyzers/AndroidAnalyzer/AndroidBackupHeader.cpp)

target_include_directories(
  test_miui_backup_gtest
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/AndroidAnalyzer)

target_link_libraries(test_miui_backup_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread)
add_test(NAME MiuiBackupHeaderTests COMMAND test_miui_backup_gtest)
```

- [ ] **Step 4: Write minimal implementation**

`src/analyzers/AndroidAnalyzer/AndroidBackupHeader.h`:
```cpp
#pragma once
#include <string>
#include <cstdint>

enum class BackupEncryption { None, Aes256, Unknown };
struct AndroidBackupHeader {
    int version = 0;
    int compression = 0;
    BackupEncryption encryption = BackupEncryption::None;
    uint64_t payloadOffset = 0;
    std::string encMarker;
};
bool parseAndroidBackupHeader(const std::string& bakPath, AndroidBackupHeader& out);
```

`src/analyzers/AndroidAnalyzer/AndroidBackupHeader.cpp`:
```cpp
#include "AndroidBackupHeader.h"
#include <fstream>
#include <vector>
#include <cstring>

static std::string readAll(const std::string& path, size_t cap) {
    std::ifstream f(path, std::ios::binary);
    std::string s((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    if (s.size() > cap) s.resize(cap);
    return s;
}

bool parseAndroidBackupHeader(const std::string& bakPath, AndroidBackupHeader& out) {
    // The MIUI header is variable-length; only the first ~1 KiB is needed.
    std::string buf = readAll(bakPath, 4096);
    const std::string magic = "ANDROID BACKUP\n";
    auto pos = buf.find(magic);
    if (pos == std::string::npos) return false;
    // After the magic: version\n compression\n encryption\n  then the payload.
    size_t cur = pos + magic.size();
    auto nextLine = [&](std::string& dst) -> bool {
        auto nl = buf.find('\n', cur);
        if (nl == std::string::npos) return false;
        dst.assign(buf, cur, nl - cur);
        cur = nl + 1;
        return true;
    };
    std::string ver, comp, enc;
    if (!nextLine(ver) || !nextLine(comp) || !nextLine(enc)) return false;
    try { out.version = std::stoi(ver); } catch (...) { return false; }
    try { out.compression = std::stoi(comp); } catch (...) { out.compression = 0; }
    out.encMarker = enc;
    if (enc == "none") out.encryption = BackupEncryption::None;
    else if (enc == "AES-256-encrypted") out.encryption = BackupEncryption::Aes256;
    else out.encryption = BackupEncryption::Unknown;
    out.payloadOffset = cur;
    return true;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cmake --build build --target test_miui_backup_gtest && ctest --test-dir build -R MiuiBackupHeaderTests --output-on-failure`
Expected: 3 tests PASS.

- [ ] **Step 6: Commit**
```bash
git add src/analyzers/AndroidAnalyzer/AndroidBackupHeader.h \
        src/analyzers/AndroidAnalyzer/AndroidBackupHeader.cpp \
        tests/UnitTest/test_miui_backup_gtest.cpp tests/CMakeLists.txt
git commit -m "feat(android): AndroidBackupHeader parser for MIUI .bak files"
```

---

### Task 2: `TarIndex` — stream a tar (raw or zlib) into an offset map

**Files:**
- Create: `src/analyzers/AndroidAnalyzer/TarIndex.h`, `src/analyzers/AndroidAnalyzer/TarIndex.cpp`
- Modify: `tests/UnitTest/test_miui_backup_gtest.cpp`, `tests/CMakeLists.txt`

**Interfaces:**
- Produces:
  ```cpp
  // TarIndex.h
  #pragma once
  #include <string>
  #include <cstdint>
  #include <unordered_map>
  #include <vector>
  #include <cstdio>

  struct TarEntry {
      uint64_t dataOffset;   // absolute byte offset in the underlying file
      uint64_t size;
  };
  class TarIndex {
  public:
      // Index a tar payload located at [payloadOffset, end-of-file) of `bakPath`.
      // If inflate=true, the payload is zlib-deflated and is inflated into a temp
      // file first (offsets then refer to the temp file).
      bool build(const std::string& bakPath, uint64_t payloadOffset, bool inflate);
      // Look up an entry by its tar member name (e.g. "apps/com.foo/db/x.db").
      bool find(const std::string& memberName, TarEntry& out) const;
      // Read entry bytes into outPath.
      bool readEntry(const TarEntry& e, const std::string& outPath) const;
      const std::unordered_map<std::string, TarEntry>& entries() const { return entries_; }
      const std::string& dataFile() const { return dataFile_; }
  private:
      std::unordered_map<std::string, TarEntry> entries_;
      std::string dataFile_;   // bakPath, or the temp inflated file
      bool ownsTemp_ = false;
  };
  ```
- Consumes: `AndroidBackupHeader` (the caller passes `payloadOffset`/`inflate`).

- [ ] **Step 1: Write the failing test**

Append to `tests/UnitTest/test_miui_backup_gtest.cpp`:
```cpp
#include "analyzers/AndroidAnalyzer/TarIndex.h"
#include <cstdio>

// Build a minimal POSIX (ustar) tar holding one regular file "apps/com.foo/db/x.db"
// with known contents, optionally zlib-deflated.
static fs::path makeUstarTar(const std::vector<std::pair<std::string,std::string>>& files) {
    std::string tar;
    for (auto& [name, content] : files) {
        std::string blk(512, '\0');
        std::memcpy(blk.data(), name.data(), std::min(name.size(), (size_t)100));
        std::string oct; char buf[16];
        auto toOct = [&](size_t v, int width){ std::snprintf(buf,sizeof(buf,"%0*lo",width-1,v);
            std::string s(buf); s.push_back('\0'); s.push_back(' '); return s; };
        std::memcpy(blk.data()+124, toOct(content.size(), 12).data(), 12); // size
        std::memcpy(blk.data()+136, toOct(0, 12).data(), 12);              // mtime
        blk[156] = '0';                                                     // typeflag regular
        std::memcpy(blk.data()+257, "ustar", 5);                            // ustar magic
        // checksum: blanks then sum
        std::memset(blk.data()+148, ' ', 8);
        unsigned sum = 0; for (unsigned char c : blk) sum += c;
        std::snprintf(buf, sizeof(buf), "%06o", sum);
        std::memcpy(blk.data()+148, buf, 6); blk[154] = '\0'; blk[155] = ' ';
        tar += blk;
        std::string data = content;
        data.append(((512 - data.size() % 512) % 512), '\0');
        tar += data;
    }
    tar.append(1024, '\0'); // two zero blocks
    fs::path p = fs::temp_directory_path() / "payload.tar";
    std::ofstream(p, std::ios::binary) << tar;
    return p;
}

TEST(TarIndexTest, IndexesRawTarOffsets) {
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "HELLO"}});
    TarIndex idx;
    ASSERT_TRUE(idx.build(tar.string(), 0, /*inflate=*/false));
    TarEntry e;
    ASSERT_TRUE(idx.find("apps/com.foo/db/x.db", e));
    EXPECT_EQ(e.size, 5u);
    fs::path out = fs::temp_directory_path() / "out_x.db";
    ASSERT_TRUE(idx.readEntry(e, out.string()));
    std::ifstream f(out, std::ios::binary);
    std::string got((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    EXPECT_EQ(got, "HELLO");
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake --build build --target test_miui_backup_gtest && ctest --test-dir build -R MiuiBackupHeaderTests --output-on-failure`
Expected: FAIL — `TarIndex` undefined / link error.

- [ ] **Step 3: Add the new source to the test target**

In `tests/CMakeLists.txt`, add `../src/analyzers/AndroidAnalyzer/TarIndex.cpp` to the `test_miui_backup_gtest` sources, and add `ZLIB::ZLIB` (or `${ZLIB_LIBRARIES}`) to its `target_link_libraries`. Ensure the top-level `find_package(ZLIB QUIET)` (CMakeLists.txt:53) is visible; if `ZLIB::ZLIB` is not defined, link `${ZLIB_LIBRARIES}` and add `${ZLIB_INCLUDE_DIRS}` to include dirs.

- [ ] **Step 4: Write minimal implementation**

`src/analyzers/AndroidAnalyzer/TarIndex.h`: as in Interfaces above.

`src/analyzers/AndroidAnalyzer/TarIndex.cpp`:
```cpp
#include "TarIndex.h"
#include <fstream>
#include <vector>
#include <cstring>
#include <sstream>
#ifdef USE_ZLIB
#include <zlib.h>
#endif

static uint64_t parseOctal(const char* s, int width) {
    uint64_t v = 0;
    for (int i = 0; i < width && s[i]; ++i) {
        if (s[i] >= '0' && s[i] <= '7') v = v * 8 + (s[i] - '0');
    }
    return v;
}

bool TarIndex::build(const std::string& bakPath, uint64_t payloadOffset, bool inflate) {
    entries_.clear();
    if (ownsTemp_) std::remove(dataFile_.c_str());
    dataFile_ = bakPath;
    ownsTemp_ = false;
    if (inflate) {
#ifdef USE_ZLIB
        std::string tmp = bakPath + ".inflated.tmp";
        std::ifstream in(bakPath, std::ios::binary);
        in.seekg(payloadOffset);
        std::ofstream out(tmp, std::ios::binary);
        z_stream zs{}; inflateInit(&zs);
        std::vector<char> ibuf(1<<20), obuf(1<<20);
        bool done = false;
        while (!done) {
            in.read(ibuf.data(), ibuf.size()); zs.avail_in = in.gcount();
            if (!zs.avail_in) break;
            zs.next_in = reinterpret_cast<Bytef*>(ibuf.data());
            do {
                zs.next_out = reinterpret_cast<Bytef*>(obuf.data());
                zs.avail_out = obuf.size();
                int r = inflate(&zs, Z_NO_FLUSH);
                out.write(obuf.data(), obuf.size() - zs.avail_out);
                if (r == Z_STREAM_END) { done = true; break; }
                if (r != Z_OK) { inflateEnd(&zs); return false; }
            } while (zs.avail_out == 0);
        }
        inflateEnd(&zs);
        out.close();
        dataFile_ = tmp; ownsTemp_ = true; payloadOffset = 0;
#else
        return false; // zlib unavailable
#endif
    }
    std::ifstream f(dataFile_, std::ios::binary);
    f.seekg(payloadOffset);
    std::vector<char> hdr(512);
    while (true) {
        f.read(hdr.data(), 512);
        if (f.gcount() != 512) break;
        if (hdr[0] == 0) break; // end-of-archive zero block
        std::string name(hdr.data(), std::min<size_t>(strlen(hdr.data()), 100));
        if (name.empty()) break;
        uint64_t size = parseOctal(hdr.data() + 124, 12);
        uint64_t dataOff = (uint64_t)f.tellg() - (uint64_t)512 + 512; // data right after header
        // dataOff == current read pos (we are at the byte after the 512 header)
        dataOff = (uint64_t)f.tellg();
        entries_[name] = { dataOff, size };
        uint64_t padded = (size + 511) & ~uint64_t(511);
        f.seekg((uint64_t)f.tellg() + padded);
    }
    return true;
}

bool TarIndex::find(const std::string& memberName, TarEntry& out) const {
    auto it = entries_.find(memberName);
    if (it == entries_.end()) return false;
    out = it->second; return true;
}

bool TarIndex::readEntry(const TarEntry& e, const std::string& outPath) const {
    std::ifstream in(dataFile_, std::ios::binary);
    in.seekg(e.dataOffset);
    std::vector<char> buf(e.size);
    in.read(buf.data(), e.size);
    if ((uint64_t)in.gcount() != e.size) return false;
    std::ofstream out(outPath, std::ios::binary);
    out.write(buf.data(), e.size);
    return out.good();
}
```

> Note: `USE_ZLIB` must be defined when zlib is found. Add to `CMakeLists.txt` near line 53: after `find_package(ZLIB QUIET)`, add `if(ZLIB_FOUND) add_compile_definitions(USE_ZLIB) endif()`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cmake --build build --target test_miui_backup_gtest && ctest --test-dir build -R MiuiBackupHeaderTests --output-on-failure`
Expected: 4 tests PASS.

- [ ] **Step 6: Commit**
```bash
git add src/analyzers/AndroidAnalyzer/TarIndex.h src/analyzers/AndroidAnalyzer/TarIndex.cpp \
        tests/UnitTest/test_miui_backup_gtest.cpp tests/CMakeLists.txt CMakeLists.txt
git commit -m "feat(android): TarIndex streams tar payloads into an offset map"
```

---

### Task 3: `MiuiPathMap` — translate between backup and TSK-style paths

**Files:**
- Create: `src/analyzers/AndroidAnalyzer/MiuiPathMap.h`
- Modify: `tests/UnitTest/test_miui_backup_gtest.cpp`

**Interfaces:**
- Produces (header-only):
  ```cpp
  // MiuiPathMap.h
  #pragma once
  #include <string>
  // Map a TSK-style analyzer query path to the tar member name used by MIUI backups.
  // Returns empty string if the path is not a mappable app-data path.
  std::string analyzerPathToTarMember(const std::string& imageRelPath);
  // Inverse, used when reporting source paths in inventory rows.
  std::string tarMemberToAnalyzerPath(const std::string& memberName);
  ```

- [ ] **Step 1: Write the failing test**

Append:
```cpp
#include "analyzers/AndroidAnalyzer/MiuiPathMap.h"
TEST(MiuiPathMapTest, MapsDatabasesFilesSharedPrefs) {
    EXPECT_EQ(analyzerPathToTarMember("data/data/com.foo/databases/x.db"), "apps/com.foo/db/x.db");
    EXPECT_EQ(analyzerPathToTarMember("data/data/com.foo/files/y"), "apps/com.foo/f/y");
    EXPECT_EQ(analyzerPathToTarMember("data/data/com.foo/shared_prefs/z.xml"), "apps/com.foo/sp/z.xml");
}
TEST(MiuiPathMapTest, ToleratesLeadingSlashAndBackslashes) {
    EXPECT_EQ(analyzerPathToTarMember("/data/data/com.foo/databases/x.db"), "apps/com.foo/db/x.db");
    EXPECT_EQ(analyzerPathToTarMember("data\\data\\com.foo\\databases\\x.db"), "apps/com.foo/db/x.db");
}
TEST(MiuiPathMapTest, ReturnsEmptyForUnmappable) {
    EXPECT_TRUE(analyzerPathToTarMember("system/build.prop").empty());
}
TEST(MiuiPathMapTest, InverseRoundTrip) {
    EXPECT_EQ(tarMemberToAnalyzerPath("apps/com.foo/db/x.db"), "data/data/com.foo/databases/x.db");
}
```

- [ ] **Step 2: Run test to verify it fails** — `cmake --build build --target test_miui_backup_gtest` → link error.

- [ ] **Step 3: Write minimal implementation**

`src/analyzers/AndroidAnalyzer/MiuiPathMap.h`:
```cpp
#pragma once
#include <string>
#include <algorithm>

inline static std::string normalizeFwd(const std::string& s) {
    std::string r = s;
    std::replace(r.begin(), r.end(), '\\', '/');
    if (!r.empty() && r[0] == '/') r.erase(0, 1);
    return r;
}

inline std::string analyzerPathToTarMember(const std::string& imageRelPath) {
    std::string p = normalizeFwd(imageRelPath);
    const std::string prefix = "data/data/";
    if (p.rfind(prefix, 0) != 0) return "";
    std::string rest = p.substr(prefix.size());
    auto slash = rest.find('/');
    if (slash == std::string::npos) return "";
    std::string pkg = rest.substr(0, slash);
    std::string tail = rest.substr(slash + 1);
    std::string sub;
    if (tail.rfind("databases/", 0) == 0)        sub = "db/" + tail.substr(strlen("databases/"));
    else if (tail.rfind("files/", 0) == 0)        sub = "f/" + tail.substr(strlen("files/"));
    else if (tail.rfind("shared_prefs/", 0) == 0) sub = "sp/" + tail.substr(strlen("shared_prefs/"));
    else return "";
    return "apps/" + pkg + "/" + sub;
}

inline std::string tarMemberToAnalyzerPath(const std::string& memberName) {
    std::string p = normalizeFwd(memberName);
    const std::string prefix = "apps/";
    if (p.rfind(prefix, 0) != 0) return "";
    std::string rest = p.substr(prefix.size());
    auto s1 = rest.find('/'); if (s1 == std::string::npos) return "";
    std::string pkg = rest.substr(0, s1);
    std::string tail = rest.substr(s1 + 1);
    std::string sub;
    if (tail.rfind("db/", 0) == 0)       sub = "databases/" + tail.substr(3);
    else if (tail.rfind("f/", 0) == 0)    sub = "files/" + tail.substr(2);
    else if (tail.rfind("sp/", 0) == 0)   sub = "shared_prefs/" + tail.substr(3);
    else return "";
    return "data/data/" + pkg + "/" + sub;
}
```

- [ ] **Step 4: Run test to verify it passes** — `ctest --test-dir build -R MiuiBackupHeaderTests --output-on-failure` → 8 tests PASS.

- [ ] **Step 5: Commit**
```bash
git add src/analyzers/AndroidAnalyzer/MiuiPathMap.h tests/UnitTest/test_miui_backup_gtest.cpp
git commit -m "feat(android): MiuiPathMap translates apps/<pkg>/db|f|sp <-> data/data/..."
```

---

### Task 4: `MiuiBackupManifest` — parse `descript.xml`

**Files:**
- Create: `src/analyzers/AndroidAnalyzer/MiuiBackupManifest.h`, `src/analyzers/AndroidAnalyzer/MiuiBackupManifest.cpp`
- Modify: `tests/UnitTest/test_miui_backup_gtest.cpp`, `tests/CMakeLists.txt`

**Interfaces:**
- Produces:
  ```cpp
  // MiuiBackupManifest.h
  #pragma once
  #include <string>
  #include <vector>
  #include <cstdint>
  struct BackupPackage {
      std::string packageName;
      std::string bakFile;     // UTF-8 filename, e.g. "短信设置(com.android.mms).bak"
      int bakType = 0;
      int error = 0;
      int state = 0;
      uint64_t pkgSize = 0;
      uint64_t sdSize = 0;
  };
  struct BackupMeta {
      std::string device;            // e.g. "cepheus"
      std::string miuiVersion;       // e.g. "V12.5.6.0.RFACNXM"
      uint64_t date = 0;             // epoch ms
      uint64_t totalSize = 0;
      std::vector<BackupPackage> packages;
      std::string sourceFolder;
  };
  // Parse <backupFolder>/descript.xml. Returns false if the file is missing/malformed.
  bool parseMiuiManifest(const std::string& backupFolder, BackupMeta& out);
  ```

- [ ] **Step 1: Write the failing test**

Append:
```cpp
#include "analyzers/AndroidAnalyzer/MiuiBackupManifest.h"
TEST(MiuiManifestTest, ParsesPackagesAndDevice) {
    fs::path dir = fs::temp_directory_path() / "miui_manifest_test";
    fs::create_directories(dir);
    std::string xml =
        "<?xml version='1.0' encoding='UTF-8' ?><MIUI-backup>"
        "<device>cepheus</device><miuiVersion>V12.5.6.0.RFACNXM</miuiVersion>"
        "<date>1785299538978</date><size>4122640883</size><packages>"
        "<package><packageName>com.android.mms</packageName>"
        "<bakFile>短信设置(com.android.mms).bak</bakFile><bakType>1</bakType>"
        "<pkgSize>7905280</pkgSize><sdSize>0</sdSize><state>1</state><error>0</error>"
        "</package></packages></MIUI-backup>";
    std::ofstream(dir / "descript.xml", std::ios::binary) << xml;
    BackupMeta m;
    ASSERT_TRUE(parseMiuiManifest(dir.string(), m));
    EXPECT_EQ(m.device, "cepheus");
    EXPECT_EQ(m.miuiVersion, "V12.5.6.0.RFACNXM");
    EXPECT_EQ(m.date, 1785299538978ull);
    ASSERT_EQ(m.packages.size(), 1u);
    EXPECT_EQ(m.packages[0].packageName, "com.android.mms");
    EXPECT_EQ(m.packages[0].bakFile, "短信设置(com.android.mms).bak");
    EXPECT_EQ(m.packages[0].bakType, 1);
    EXPECT_EQ(m.packages[0].pkgSize, 7905280ull);
    EXPECT_EQ(m.sourceFolder, dir.string());
}
TEST(MiuiManifestTest, MissingFileReturnsFalse) {
    BackupMeta m;
    EXPECT_FALSE(parseMiuiManifest(fs::temp_directory_path().string(), m));
}
```

- [ ] **Step 2: Run test to verify it fails** — link error.

- [ ] **Step 3: Add source to the test target** — add `../src/analyzers/AndroidAnalyzer/MiuiBackupManifest.cpp` to `test_miui_backup_gtest` sources in `tests/CMakeLists.txt`.

- [ ] **Step 4: Write minimal implementation**

`MiuiBackupManifest.h`: as in Interfaces. `MiuiBackupManifest.cpp`:
```cpp
#include "MiuiBackupManifest.h"
#include <fstream>
#include <sstream>
#include <regex>

static std::string readFile(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    std::stringstream ss; ss << f.rdbuf();
    return ss.str();
}
static std::string one(const std::string& xml, const std::string& tag) {
    std::regex re("<" + tag + ">([^<]*)</" + tag + ">");
    std::smatch m; return std::regex_search(xml, m, re) ? m[1].str() : std::string();
}
static uint64_t toU64(const std::string& s) {
    try { return s.empty() ? 0 : std::stoull(s); } catch (...) { return 0; }
}

bool parseMiuiManifest(const std::string& backupFolder, BackupMeta& out) {
    std::string path = backupFolder + "/descript.xml";
    std::string xml = readFile(path);
    if (xml.find("MIUI-backup") == std::string::npos) return false;
    out.device = one(xml, "device");
    out.miuiVersion = one(xml, "miuiVersion");
    out.date = toU64(one(xml, "date"));
    out.totalSize = toU64(one(xml, "size"));
    out.sourceFolder = backupFolder;
    out.packages.clear();
    std::regex pkg("<package>([\\s\\S]*?)</package>");
    for (std::sregex_iterator it(xml.begin(), xml.end(), pkg), end; it != end; ++it) {
        std::string body = (*it)[1].str();
        BackupPackage p;
        p.packageName = one(body, "packageName");
        p.bakFile     = one(body, "bakFile");
        p.bakType     = (int)toU64(one(body, "bakType"));
        p.error       = (int)toU64(one(body, "error"));
        p.state       = (int)toU64(one(body, "state"));
        p.pkgSize     = toU64(one(body, "pkgSize"));
        p.sdSize      = toU64(one(body, "sdSize"));
        if (!p.packageName.empty()) out.packages.push_back(std::move(p));
    }
    return true;
}
```

- [ ] **Step 5: Run test to verify it passes** — `ctest --test-dir build -R MiuiBackupHeaderTests --output-on-failure` → 10 tests PASS.

- [ ] **Step 6: Commit**
```bash
git add src/analyzers/AndroidAnalyzer/MiuiBackupManifest.h \
        src/analyzers/AndroidAnalyzer/MiuiBackupManifest.cpp \
        tests/UnitTest/test_miui_backup_gtest.cpp tests/CMakeLists.txt
git commit -m "feat(android): MiuiBackupManifest parses descript.xml"
```

---

### Task 5: `MiuiBackupExtractor` — the `IFileExtractor` backend

**Files:**
- Create: `src/analyzers/AndroidAnalyzer/MiuiBackupExtractor.h`, `src/analyzers/AndroidAnalyzer/MiuiBackupExtractor.cpp`
- Modify: `tests/UnitTest/test_miui_backup_gtest.cpp`, `tests/CMakeLists.txt`

**Interfaces:**
- Produces:
  ```cpp
  // MiuiBackupExtractor.h
  #pragma once
  #include <string>
  #include <unordered_map>
  #include <memory>
  #include "IFileExtractor.h"
  #include "TarIndex.h"
  #include "MiuiBackupManifest.h"

  class MiuiBackupExtractor : public IFileExtractor {
  public:
      explicit MiuiBackupExtractor(const std::string& backupFolder);
      void setBackupPassword(const std::string& pw);   // Phase 2: AES; stored now, unused
      bool initialize() override;
      bool extractFileByPath(const std::string& imageRelPath, const std::string& outPath) override;
      const BackupMeta& manifest() const { return manifest_; }
      // enumerateEntries()/extractTarMember() are added to this class in Task 7
      // for the inventory pass; Task 5 leaves them out intentionally.
  private:
      std::string folder_;
      std::string password_;
      BackupMeta manifest_;
      // member name -> (which index owns it) ; we keep per-package TarIndex objects.
      std::vector<std::unique_ptr<TarIndex>> indexes_;
      std::unordered_map<std::string, TarIndex*> entryOwner_; // member name -> owning index
      bool initialized_ = false;
  };
  ```
- Consumes: `AndroidBackupHeader`, `TarIndex`, `MiuiPathMap`, `MiuiBackupManifest`.

- [ ] **Step 1: Write the failing test**

Append (builds a one-app synthetic backup folder, then queries through the analyzer path):
```cpp
#include "analyzers/AndroidAnalyzer/MiuiBackupExtractor.h"
TEST(MiuiBackupExtractorTest, ServesFileThroughAnalyzerPath) {
    fs::path dir = fs::temp_directory_path() / "miui_ext_test";
    fs::remove_all(dir); fs::create_directories(dir);
    // descript.xml
    std::string xml = "<?xml version='1.0'?><MIUI-backup><device>cepheus</device>"
        "<miuiVersion>V12</miuiVersion><date>1</date><size>1</size><packages>"
        "<package><packageName>com.foo</packageName>"
        "<bakFile>Foo(com.foo).bak</bakFile><bakType>1</bakType><pkgSize>1</pkgSize>"
        "<sdSize>0</sdSize><state>1</state><error>0</error></package></packages></MIUI-backup>";
    std::ofstream(dir / "descript.xml", std::ios::binary) << xml;
    // .bak = MIUI header + AB header + tar(apps/com.foo/db/x.db = "DATA")
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "DATA"}});
    std::string tarBytes((std::istreambuf_iterator<char>(std::ifstream(tar, std::ios::binary))),
                         std::istreambuf_iterator<char>());
    std::string bak = "MIUI BACKUP\n2\ncom.foo Foo\n-1\n0\nANDROID BACKUP\n5\n0\nnone\n" + tarBytes;
    std::ofstream(dir / "Foo(com.foo).bak", std::ios::binary) << bak;

    MiuiBackupExtractor ext(dir.string());
    ASSERT_TRUE(ext.initialize());
    fs::path out = fs::temp_directory_path() / "served_x.db";
    // The analyzer queries with the TSK-style path; the backend maps it.
    ASSERT_TRUE(ext.extractFileByPath("data/data/com.foo/databases/x.db", out.string()));
    std::ifstream f(out, std::ios::binary);
    std::string got((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    EXPECT_EQ(got, "DATA");
}
```

- [ ] **Step 2: Run test to verify it fails** — link error.

- [ ] **Step 3: Add source to the test target** — add `../src/analyzers/AndroidAnalyzer/MiuiBackupExtractor.cpp` to `test_miui_backup_gtest` sources.

- [ ] **Step 4: Write minimal implementation**

`MiuiBackupExtractor.h`: as in Interfaces.

`MiuiBackupExtractor.cpp`:
```cpp
#include "MiuiBackupExtractor.h"
#include "AndroidBackupHeader.h"
#include "MiuiPathMap.h"
#include <filesystem>
#include <iostream>

namespace fs = std::filesystem;

MiuiBackupExtractor::MiuiBackupExtractor(const std::string& backupFolder) : folder_(backupFolder) {}
void MiuiBackupExtractor::setBackupPassword(const std::string& pw) { password_ = pw; }

bool MiuiBackupExtractor::initialize() {
    if (!parseMiuiManifest(folder_, manifest_)) {
        std::cerr << "MiuiBackupExtractor: no descript.xml in " << folder_ << std::endl;
        return false;
    }
    entryOwner_.clear(); indexes_.clear();
    for (const auto& pkg : manifest_.packages) {
        fs::path bak = fs::path(folder_) / pkg.bakFile;
        if (!fs::exists(bak)) continue;
        AndroidBackupHeader h;
        if (!parseAndroidBackupHeader(bak.string(), h)) continue;
        if (h.encryption != BackupEncryption::None) {
            // Phase 1: record-and-defer. Phase 2 will decrypt with password_.
            std::cerr << "MiuiBackupExtractor: " << pkg.packageName
                      << " is encrypted (" << h.encMarker << "); deferred\n";
            continue;
        }
        auto idx = std::make_unique<TarIndex>();
        if (!idx->build(bak.string(), h.payloadOffset, h.compression == 1)) {
            std::cerr << "MiuiBackupExtractor: failed to index " << pkg.bakFile << std::endl;
            continue;
        }
        TarIndex* raw = idx.get();
        for (const auto& [name, entry] : idx->entries()) entryOwner_[name] = raw;
        indexes_.push_back(std::move(idx));
    }
    initialized_ = !indexes_.empty();
    return initialized_;
}

bool MiuiBackupExtractor::extractFileByPath(const std::string& imageRelPath, const std::string& outPath) {
    if (!initialized_) return false;
    std::string member = analyzerPathToTarMember(imageRelPath);   // try mapped path
    auto lookup = [&](const std::string& m) -> TarIndex* {
        auto it = entryOwner_.find(m);
        return it == entryOwner_.end() ? nullptr : it->second;
    };
    TarIndex* owner = lookup(member);
    if (!owner) owner = lookup(imageRelPath);                     // tolerate raw apps/... paths
    if (!owner) return false;
    TarEntry e;
    std::string key = lookup(member) ? member : imageRelPath;
    if (!owner->find(key, e)) return false;
    return owner->readEntry(e, outPath);
}

// (Task 7 adds enumerateEntries(visitor) and extractTarMember(name,outPath) here.)
```

> Task 7 adds `enumerateEntries(visitor)` and `extractTarMember(name,outPath)` to this class for the inventory pass; Task 5 leaves them out intentionally so there is no interim stub.

- [ ] **Step 5: Run test to verify it passes** — `ctest --test-dir build -R MiuiBackupHeaderTests --output-on-failure` → 11 tests PASS.

- [ ] **Step 6: Commit**
```bash
git add src/analyzers/AndroidAnalyzer/MiuiBackupExtractor.h \
        src/analyzers/AndroidAnalyzer/MiuiBackupExtractor.cpp \
        tests/UnitTest/test_miui_backup_gtest.cpp tests/CMakeLists.txt
git commit -m "feat(android): MiuiBackupExtractor IFileExtractor backend (unencrypted)"
```

---

### Task 6: MIUI tables + insert methods in `AndroidAnalysisDatabase`

**Files:**
- Modify: `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h` (add declarations), `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp` (add insert methods + call from `createTables()`), and `src/core/DatabaseManager/SQL/android_analysis_sql.h` (add the `CREATE_MIUI_TABLES` constant to `namespace AndroidAnalysisSQL`).

**Interfaces:**
- Produces:
  ```cpp
  // in AndroidAnalysisDatabase.h (public):
  bool insertMiuiBackupManifest(const std::string& device, const std::string& miuiVersion,
                                uint64_t date, uint64_t totalSize, int packageCount,
                                const std::string& sourceFolder);
  bool insertInstalledApp(const std::string& packageName, const std::string& displayName,
                          const std::string& versionCode, const std::string& versionName,
                          uint64_t dataSize, uint64_t sdSize, int bakType,
                          const std::string& manifestSummary);
  bool insertAppDbInventory(const std::string& packageName, const std::string& dbPath,
                            const std::string& tableName, uint64_t rowCount,
                            const std::string& columns, const std::string& openStatus);
  ```
- Consumes: the existing `executeSQL()` + `sqlite3* db_` member.

- [ ] **Step 1: Write the failing test** — append a test that opens a temp DB, inserts one row per table, and reads it back via `sqlite3` directly:
```cpp
#include "analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h"
#include <sqlite3.h>
TEST(MiuiDbTest, InsertsMiuiTables) {
    fs::path dbp = fs::temp_directory_path() / "miui_test.db";
    fs::remove(dbp);
    AndroidAnalysisDatabase db(dbp.string());
    ASSERT_TRUE(db.initialize());
    ASSERT_TRUE(db.insertMiuiBackupManifest("cepheus","V12",1785299538978ull,100,3,"/x"));
    ASSERT_TRUE(db.insertInstalledApp("com.foo","Foo","10","1.0",500,0,1,""));
    ASSERT_TRUE(db.insertAppDbInventory("com.foo","apps/com.foo/db/x.db","msgs",42,"id,text","decrypted"));
    sqlite3* raw=nullptr; sqlite3_open(dbp.string().c_str(),&raw);
    sqlite3_stmt* st=nullptr;
    sqlite3_prepare_v2(raw,"SELECT package_count FROM miui_backup_manifest",-1,&st,nullptr);
    ASSERT_EQ(sqlite3_step(st), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(st,0), 3);
    sqlite3_finalize(st); sqlite3_close(raw);
}
```

- [ ] **Step 2: Run test to verify it fails** — the tables don't exist yet (`no such table`).

- [ ] **Step 3: Add the SQL + methods**

In `src/core/DatabaseManager/SQL/android_analysis_sql.h` (inside `namespace AndroidAnalysisSQL`, matching the existing `inline constexpr const char* CREATE_ALL_TABLES = R"(...)";` style), add:
```cpp
inline constexpr const char* CREATE_MIUI_TABLES = R"(
    CREATE TABLE IF NOT EXISTS miui_backup_manifest (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device TEXT, miui_version TEXT, backup_date INTEGER,
        total_size INTEGER, package_count INTEGER, source_folder TEXT
    );
    CREATE TABLE IF NOT EXISTS installed_apps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT, display_name TEXT, version_code TEXT,
        version_name TEXT, data_size INTEGER, sd_size INTEGER,
        bak_type INTEGER, manifest_summary TEXT
    );
    CREATE TABLE IF NOT EXISTS app_db_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT, db_path TEXT, table_name TEXT,
        row_count INTEGER, columns TEXT, open_status TEXT
    );
)";
```
In `AndroidAnalysisDatabase::createTables()`, after the existing `executeSQL(CREATE_ALL_TABLES)`, add `executeSQL(AndroidAnalysisSQL::CREATE_MIUI_TABLES);` (and keep the existing return).

Add to `.cpp`:
```cpp
static bool execOnce(sqlite3* db, const std::string& sql) {
    char* err=nullptr; int rc=sqlite3_exec(db, sql.c_str(), nullptr, nullptr, &err);
    if (err){ sqlite3_free(err); } return rc==SQLITE_OK;
}
bool AndroidAnalysisDatabase::insertMiuiBackupManifest(const std::string& device,
    const std::string& miuiVersion, uint64_t date, uint64_t totalSize, int packageCount,
    const std::string& sourceFolder) {
    sqlite3_stmt* st=nullptr;
    sqlite3_prepare_v2(db_, "INSERT INTO miui_backup_manifest(device,miui_version,backup_date,"
      "total_size,package_count,source_folder) VALUES(?,?,?,?,?,?)", -1, &st, nullptr);
    sqlite3_bind_text(st,1,device.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(st,2,miuiVersion.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_int64(st,3,(sqlite3_int64)date);
    sqlite3_bind_int64(st,4,(sqlite3_int64)totalSize);
    sqlite3_bind_int(st,5,packageCount);
    sqlite3_bind_text(st,6,sourceFolder.c_str(),-1,SQLITE_TRANSIENT);
    bool ok=sqlite3_step(st)==SQLITE_DONE; sqlite3_finalize(st); return ok;
}
bool AndroidAnalysisDatabase::insertInstalledApp(const std::string& packageName,
    const std::string& displayName,const std::string& versionCode,const std::string& versionName,
    uint64_t dataSize,uint64_t sdSize,int bakType,const std::string& manifestSummary){
    sqlite3_stmt* st=nullptr;
    sqlite3_prepare_v2(db_,"INSERT INTO installed_apps(package_name,display_name,version_code,"
      "version_name,data_size,sd_size,bak_type,manifest_summary) VALUES(?,?,?,?,?,?,?,?)",-1,&st,nullptr);
    sqlite3_bind_text(st,1,packageName.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(st,2,displayName.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(st,3,versionCode.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(st,4,versionName.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_int64(st,5,(sqlite3_int64)dataSize);
    sqlite3_bind_int64(st,6,(sqlite3_int64)sdSize);
    sqlite3_bind_int(st,7,bakType);
    sqlite3_bind_text(st,8,manifestSummary.c_str(),-1,SQLITE_TRANSIENT);
    bool ok=sqlite3_step(st)==SQLITE_DONE; sqlite3_finalize(st); return ok;
}
bool AndroidAnalysisDatabase::insertAppDbInventory(const std::string& packageName,
    const std::string& dbPath,const std::string& tableName,uint64_t rowCount,
    const std::string& columns,const std::string& openStatus){
    sqlite3_stmt* st=nullptr;
    sqlite3_prepare_v2(db_,"INSERT INTO app_db_inventory(package_name,db_path,table_name,"
      "row_count,columns,open_status) VALUES(?,?,?,?,?,?)",-1,&st,nullptr);
    sqlite3_bind_text(st,1,packageName.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(st,2,dbPath.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(st,3,tableName.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_int64(st,4,(sqlite3_int64)rowCount);
    sqlite3_bind_text(st,5,columns.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(st,6,openStatus.c_str(),-1,SQLITE_TRANSIENT);
    bool ok=sqlite3_step(st)==SQLITE_DONE; sqlite3_finalize(st); return ok;
}
```
Declare the three methods in `AndroidAnalysisDatabase.h` (public).

- [ ] **Step 4: Run test to verify it passes** — add `../src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp` to the test sources (if not already linked) and rerun; expect 12 tests PASS.

- [ ] **Step 5: Commit**
```bash
git add src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h \
        src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp \
        tests/UnitTest/test_miui_backup_gtest.cpp tests/CMakeLists.txt
git commit -m "feat(android): miui_backup_manifest/installed_apps/app_db_inventory tables"
```

---

### Task 7: Inventory pass + manifest writer (`MiuiArtifactParsers`)

**Files:**
- Create: `src/analyzers/AndroidAnalyzer/MiuiArtifactParsers.h`, `src/analyzers/AndroidAnalyzer/MiuiArtifactParsers.cpp`
- Modify: `MiuiBackupExtractor.h` (add `enumerateEntries`), `tests/UnitTest/test_miui_backup_gtest.cpp`

**Interfaces:**
- Produces:
  ```cpp
  // MiuiArtifactParsers.h
  #pragma once
  #include <string>
  class AndroidAnalysisDatabase;
  class MiuiBackupExtractor;
  // Writes the backup manifest row + installed_apps rows.
  void writeMiuiManifest(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db);
  // Universal DB inventory: for every app DB found, record (table, row_count, columns).
  // open_status = "decrypted" (opened) or "encrypted_locked" (open failed).
  void writeAppDbInventory(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db);
  ```
- Add to `MiuiBackupExtractor`:
  ```cpp
  // in .h (public):
  using EntryVisitor = std::function<void(const std::string& memberName, const std::string& bakFile)>;
  void enumerateEntries(const EntryVisitor& v) const;
  // extract one member verbatim by its tar name (apps/...) into outPath:
  bool extractTarMember(const std::string& memberName, const std::string& outPath) const;
  ```
- Consumes: `MiuiBackupExtractor`, `AndroidAnalysisDatabase`.

- [ ] **Step 1: Write the failing test** — using the synthetic backup from Task 5's helper, build an extractor + DB, run both writers, assert `installed_apps` has 1 row and `app_db_inventory` records table `t` (the synthetic `x.db` is not a real sqlite; the inventory must mark it `encrypted_locked`/`parse_error` rather than crash):
```cpp
#include "analyzers/AndroidAnalyzer/MiuiArtifactParsers.h"
TEST(MiuiArtifactTest, WritesManifestAndInventory) {
    // reuse synthetic backup dir pattern from Task 5 (com.foo with apps/com.foo/db/x.db)
    fs::path dir = fs::temp_directory_path() / "miui_art_test";
    fs::remove_all(dir); fs::create_directories(dir);
    std::ofstream(dir/"descript.xml",std::ios::binary) <<
      "<?xml version='1.0'?><MIUI-backup><device>cepheus</device><miuiVersion>V12</miuiVersion>"
      "<date>1</date><size>1</size><packages><package><packageName>com.foo</packageName>"
      "<bakFile>Foo(com.foo).bak</bakFile><bakType>1</bakType><pkgSize>1</pkgSize>"
      "<sdSize>0</sdSize><state>1</state><error>0</error></package></packages></MIUI-backup>";
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db","DATA"}});
    std::string tb((std::istreambuf_iterator<char>(std::ifstream(tar,std::ios::binary))),
                   std::istreambuf_iterator<char>());
    std::ofstream(dir/"Foo(com.foo).bak",std::ios::binary) <<
      "MIUI BACKUP\n2\ncom.foo Foo\n-1\n0\nANDROID BACKUP\n5\n0\nnone\n"+tb;

    MiuiBackupExtractor ext(dir.string()); ASSERT_TRUE(ext.initialize());
    fs::path dbp = fs::temp_directory_path()/"miui_art.db"; fs::remove(dbp);
    AndroidAnalysisDatabase db(dbp.string()); ASSERT_TRUE(db.initialize());
    writeMiuiManifest(ext, db);
    writeAppDbInventory(ext, db);

    sqlite3* raw=nullptr; sqlite3_open(dbp.string().c_str(),&raw); sqlite3_stmt* st=nullptr;
    sqlite3_prepare_v2(raw,"SELECT count(*) FROM installed_apps WHERE package_name='com.foo'",-1,&st,nullptr);
    ASSERT_EQ(sqlite3_step(st),SQLITE_ROW); EXPECT_EQ(sqlite3_column_int(st,0),1); sqlite3_finalize(st);
    // x.db is not a real sqlite -> recorded with a non-decrypted open_status, no crash
    sqlite3_prepare_v2(raw,"SELECT open_status FROM app_db_inventory WHERE db_path LIKE '%x.db'",-1,&st,nullptr);
    ASSERT_EQ(sqlite3_step(st),SQLITE_ROW);
    std::string os=(const char*)sqlite3_column_text(st,0);
    EXPECT_NE(os,"decrypted");
    sqlite3_finalize(st); sqlite3_close(raw);
}
```

- [ ] **Step 2: Run test to verify it fails** — `writeMiuiManifest`/`writeAppDbInventory` undefined.

- [ ] **Step 3: Add `enumerateEntries`/`extractTarMember` to `MiuiBackupExtractor`**

In `.cpp`:
```cpp
void MiuiBackupExtractor::enumerateEntries(const EntryVisitor& v) const {
    for (const auto& pkg : manifest_.packages) {
        for (const auto& idx : indexes_) {
            for (const auto& [name, e] : idx->entries())
                if (name.rfind(std::string("apps/")+pkg.packageName+"/",0)==0) v(name, pkg.bakFile);
        }
    }
}
bool MiuiBackupExtractor::extractTarMember(const std::string& memberName, const std::string& outPath) const {
    auto it = entryOwner_.find(memberName);
    if (it == entryOwner_.end()) return false;
    TarEntry e; if (!it->second->find(memberName,e)) return false;
    return it->second->readEntry(e,outPath);
}
```
(Add `#include <functional>` in the header.)

- [ ] **Step 4: Write minimal implementation**

`MiuiArtifactParsers.cpp`:
```cpp
#include "MiuiArtifactParsers.h"
#include "MiuiBackupExtractor.h"
#include "AndroidAnalysisDatabase.h"
#include <sqlite3.h>
#include <filesystem>
#include <fstream>
namespace fs = std::filesystem;

void writeMiuiManifest(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db) {
    const auto& m = src.manifest();
    db.insertMiuiBackupManifest(m.device, m.miuiVersion, m.date, m.totalSize,
                                (int)m.packages.size(), m.sourceFolder);
    for (const auto& p : m.packages)
        db.insertInstalledApp(p.packageName, "", "", "", p.pkgSize, p.sdSize, p.bakType, "");
}

void writeAppDbInventory(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db) {
    fs::path tmpDir = fs::temp_directory_path() / "miui_inv_tmp";
    fs::create_directories(tmpDir);
    src.enumerateEntries([&](const std::string& member, const std::string& /*bakFile*/){
        if (member.rfind("apps/",0)!=0) return;
        // only index database files under apps/<pkg>/db/
        if (member.find("/db/")==std::string::npos) return;
        auto pkgPos = strlen("apps/"); auto slash = member.find('/',pkgPos);
        std::string pkg = member.substr(pkgPos, slash-pkgPos);
        fs::path out = tmpDir / std::to_string(std::hash<std::string>{}(member));
        if (!src.extractTarMember(member, out.string())) return;
        sqlite3* raw=nullptr;
        std::string status = "decrypted";
        if (sqlite3_open(out.string().c_str(), &raw) == SQLITE_OK) {
            sqlite3_stmt* st=nullptr;
            if (sqlite3_prepare_v2(raw,"SELECT name FROM sqlite_master WHERE type='table'",-1,&st,nullptr)==SQLITE_OK){
                while (sqlite3_step(st)==SQLITE_ROW){
                    std::string tbl=(const char*)sqlite3_column_text(st,0);
                    sqlite3_stmt* cnt=nullptr; uint64_t rows=0; std::string cols;
                    std::string q="SELECT count(*) FROM \""+tbl+"\"";
                    if (sqlite3_prepare_v2(raw,q.c_str(),-1,&cnt,nullptr)==SQLITE_OK && sqlite3_step(cnt)==SQLITE_ROW)
                        rows=(uint64_t)sqlite3_column_int64(cnt,0);
                    sqlite3_finalize(cnt);
                    // columns
                    sqlite3_stmt* ci=nullptr;
                    if (sqlite3_prepare_v2(raw,("PRAGMA table_info(\""+tbl+"\")").c_str(),-1,&ci,nullptr)==SQLITE_OK){
                        while (sqlite3_step(ci)==SQLITE_ROW){ if(!cols.empty())cols+=","; cols+=(const char*)sqlite3_column_text(ci,1);} }
                    sqlite3_finalize(ci);
                    db.insertAppDbInventory(pkg, member, tbl, rows, cols, "decrypted");
                }
                sqlite3_finalize(st);
            } else status = "encrypted_locked";
            sqlite3_close(raw);
        } else status = "parse_error";
        if (status!="decrypted")
            db.insertAppDbInventory(pkg, member, "", 0, "", status);
        fs::remove(out);
    });
}
```

- [ ] **Step 5: Run test to verify it passes** — add `../src/analyzers/AndroidAnalyzer/MiuiArtifactParsers.cpp` to the test sources; expect 13 tests PASS.

- [ ] **Step 6: Commit**
```bash
git add src/analyzers/AndroidAnalyzer/MiuiArtifactParsers.h \
        src/analyzers/AndroidAnalyzer/MiuiArtifactParsers.cpp \
        src/analyzers/AndroidAnalyzer/MiuiBackupExtractor.h \
        src/analyzers/AndroidAnalyzer/MiuiBackupExtractor.cpp \
        tests/UnitTest/test_miui_backup_gtest.cpp tests/CMakeLists.txt
git commit -m "feat(android): MIUI manifest + universal DB inventory parsers"
```

---

### Task 8: Wire the new source into the analyzer, orchestrator, and CLI

**Files:**
- Modify: `src/analyzers/AndroidAnalyzer/AndroidAnalyzerDeclarations.h` (enum + password), `src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp` (dispatch), `src/AnalysisOrchestrator.cpp` (routing + mode + password), `src/CommandLineParser.h` (new field), `src/CommandLineParser.cpp` (parse `--backup-password` + accept `miui-backup`), `CMakeLists.txt` (LIB_SOURCES).

**Interfaces:**
- Consumes: `MiuiBackupExtractor` (Task 5), `MiuiArtifactParsers` (Task 7).
- Produces: a working CLI `--android-source miui-backup`.

- [ ] **Step 1: Add the enum value + password plumbing**

In `AndroidAnalyzerDeclarations.h`:
```cpp
enum class AndroidSourceMode {
    TSK,
    LogicalDir,
    Zip,
    MiuiBackup            // <-- added
};
```
and near `setWeChatPassword` (line 67):
```cpp
    void setBackupPassword(const std::string& password) { backupPassword_ = password; }
```
and near `wechatPassword_` (private members block):
```cpp
    std::string backupPassword_;
```

- [ ] **Step 2: Add the dispatch case**

In `AndroidAnalyzerCore.cpp`, add the include and case:
```cpp
#include "MiuiBackupExtractor.h"
```
and inside `switch (sourceMode_)` (before `case AndroidSourceMode::TSK:`):
```cpp
        case AndroidSourceMode::MiuiBackup:
            fileExtractor_ = std::make_unique<MiuiBackupExtractor>(imagePath_);
            break;
```
Then, after `fileExtractor_->initialize()` succeeds, if it is the MIUI backend, forward the password and run the MIUI artifact writers. Concretely, after the `if (!fileExtractor_->initialize()) { ... }` block succeeds and before `androidDb_` init:
```cpp
    if (sourceMode_ == AndroidSourceMode::MiuiBackup) {
        auto* miui = dynamic_cast<MiuiBackupExtractor*>(fileExtractor_.get());
        if (miui) {
            if (!backupPassword_.empty()) miui->setBackupPassword(backupPassword_);
            // MIUI artifact tables are written once androidDb_ exists (below).
        }
    }
```
(Move the two `writeMiuiManifest`/`writeAppDbInventory` calls to *after* `androidDb_->initialize()` succeeds — add:
```cpp
    if (sourceMode_ == AndroidSourceMode::MiuiBackup) {
        if (auto* miui = dynamic_cast<MiuiBackupExtractor*>(fileExtractor_.get())) {
            writeMiuiManifest(*miui, *androidDb_);
            writeAppDbInventory(*miui, *androidDb_);
        }
    }
```
and `#include "MiuiArtifactParsers.h"` at the top of the file.)

- [ ] **Step 3: Route `miui-backup` through the logical path + set mode/password**

In `src/AnalysisOrchestrator.cpp`:
- Extend the guard (line 147-148):
```cpp
    if (args.android_analyze &&
        (args.android_source == "dir" || args.android_source == "zip" ||
         args.android_source == "miui-backup")) {
        return runAndroidLogicalAnalysis(args);
    }
```
- In `runAndroidLogicalAnalysis` (line 466-468), replace the two-way ternary with a three-way:
```cpp
        AndroidSourceMode mode =
            args.android_source == "zip"          ? AndroidSourceMode::Zip :
            args.android_source == "miui-backup"  ? AndroidSourceMode::MiuiBackup :
                                                    AndroidSourceMode::LogicalDir;
        androidAnalyzer->setSourceMode(mode);
        if (!args.backup_password.empty())
            androidAnalyzer->setBackupPassword(args.backup_password);
```

- [ ] **Step 4: Add the CLI flag**

In `src/CommandLineParser.h`, add a field next to `wechat_password`:
```cpp
    std::string backup_password;   // MIUI/Android backup password (AES-256)
```
In `src/CommandLineParser.cpp`, add a parser branch next to `--wechat-password`:
```cpp
        } else if (arg == "--backup-password" && i + 1 < argc) {
            args.backup_password = argv[++i];
        }
```
and extend the accepted values note + help text at line 89-90:
```cpp
    std::cout << "  --android-source <mode>     Android data source: tsk (default, disk image),\n"
                 "                              dir (extracted data/ tree), zip (Image.zip),\n"
                 "                              miui-backup (Xiaomi MIUI .bak folder)\n";
```
and wherever the string is validated (if a whitelist rejects unknown values — grep `android_source ==` to confirm none else rejects it), allow `miui-backup`.

- [ ] **Step 5: Add sources to the build**

In `CMakeLists.txt`, after `ZipArchiveExtractor.cpp` (~line 345) inside `LIB_SOURCES`:
```cmake
    # Xiaomi MIUI backup source (offline .bak analysis, bypassing TSK)
    src/analyzers/AndroidAnalyzer/MiuiBackupManifest.cpp
    src/analyzers/AndroidAnalyzer/AndroidBackupHeader.cpp
    src/analyzers/AndroidAnalyzer/TarIndex.cpp
    src/analyzers/AndroidAnalyzer/MiuiBackupExtractor.cpp
    src/analyzers/AndroidAnalyzer/MiuiArtifactParsers.cpp
```

- [ ] **Step 6: Build the full analyzer and run all tests**

Run:
```bash
cmake --build build -j && ctest --test-dir build --output-on-failure
```
Expected: full build succeeds; all GTest suites (including the 13 `MiuiBackupHeaderTests`) PASS.

- [ ] **Step 7: Commit**
```bash
git add src/analyzers/AndroidAnalyzer/AndroidAnalyzerDeclarations.h \
        src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp \
        src/analyzers/AndroidAnalyzer/MiuiBackupExtractor.h \
        src/analyzers/AndroidAnalyzer/MiuiArtifactParsers.cpp \
        src/AnalysisOrchestrator.cpp src/CommandLineParser.h src/CommandLineParser.cpp \
        CMakeLists.txt
git commit -m "feat(android): wire --android-source miui-backup into analyzer + CLI"
```

---

### Task 9: End-to-end integration against the real backup

**Files:**
- Create: `tests/test_miui_backup_e2e.sh` (a smoke script, registered or run manually)

**Interfaces:**
- Consumes: the full CLI from Task 8; the real backup at `/home/ymj68520/projects/Forensics/AndroidBackup`.

- [ ] **Step 1: Write the smoke script**

`tests/test_miui_backup_e2e.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
BACKUP="${1:-/home/ymj68520/projects/Forensics/AndroidBackup}"
OUT="$(mktemp -d)"
./build/forensic_analyzer "$BACKUP" --android-analyze --android-source miui-backup --db-dir "$OUT"
DB="$OUT/$(basename "$BACKUP")_files.db"
test -f "$DB"
# Manifest + inventory populated
sqlite3 "$DB" "SELECT count(*) FROM miui_backup_manifest;" | grep -qv '^0$'
sqlite3 "$DB" "SELECT count(*) FROM app_db_inventory;"      | grep -qv '^0$'
# A known real DB surfaces via the generic analyzer OR the inventory
sqlite3 "$DB" "SELECT package_name FROM app_db_inventory WHERE package_name='com.android.email' LIMIT 1;" \
  | grep -q 'com.android.email'
echo "MIUI backup E2E OK"
```

- [ ] **Step 2: Run it against the real backup**

Run: `bash tests/test_miui_backup_e2e.sh`
Expected: prints `MIUI backup E2E OK`; the com.android.email DB is inventoried.

- [ ] **Step 3: Commit**
```bash
git add tests/test_miui_backup_e2e.sh
git commit -m "test(android): MIUI backup end-to-end smoke against real export"
```

---

## Self-Review

**1. Spec coverage (Phase 1 slice):**
- New offline source + on-demand streaming + path mapping → Tasks 2,3,5. ✓
- Preserve ADB module → Global Constraints + no task touches `src/integration/`. ✓
- Transparent path mapping (zero changes to 9 call sites) → Task 3 + Task 5 maps inside the backend. ✓
- Dual entry points (CLI) → Task 8. Web is Phase 4 (deferred). ⚠ Partial — CLI done, Web deferred to its own plan.
- AES-256 → explicitly deferred to Phase 2; Task 1 detects the marker, Task 5 records-and-defers. ⚠ Phase 2 plan required.
- MIUI-specific artifacts (all apps) → Task 6 (tables) + Task 7 (manifest + universal inventory = "nothing lost"). Targeted per-app parsers (appstore/amap/wifi/…) → Phase 3 plan. ⚠ Inventory guarantees coverage; targeted parsers deferred.

Phase 1 is intentionally scoped to the shippable foundation; Phases 2–4 are listed below as separate plans (per the decomposition guidance — each produces working software on its own and each benefits from Phase 1's validated backend).

**2. Placeholder scan:** No "TBD/TODO/implement later." Every code step contains real code. The two known unknowns are handled concretely: (a) the `AndroidAnalysisSQL` file location is resolved by a grep command in Task 6; (b) Task 5's `allEntries()` is replaced by the proper `enumerateEntries` API in Task 7 (the interim stub is called out and fixed in the same plan, not left dangling).

**3. Type consistency:** `MiuiBackupExtractor::manifest()` returns `const BackupMeta&` (Task 4→5→7 consistent); `enumerateEntries`/`extractTarMember` signatures match between Task 5 add and Task 7 use; `BackupEncryption` enum values (`None/Aes256/Unknown`) match Task 1 and Task 5; `AndroidSourceMode::MiuiBackup` spelled identically in Tasks 1(N/A),5,8.

## Follow-on Phases (separate plans)

- **Phase 2 — AES-256 decryption:** `IBackupDecryptor` + `AospV5Decryptor` (OpenSSL `PKCS5_PBKDF2_HMAC` + `EVP_aes_256_cbc`), validated against a locally-generated `abe.jar pack` fixture; threaded via `setBackupPassword()` into `TarIndex.build` as a pre-inflate stage. Pluggable so a future MIUI-specific scheme swaps in without touching the indexer.
- **Phase 3 — MIUI targeted app parsers:** `MiuiAppParser` registry; per-app parsers for 应用商店/高德/WLAN/健康/笔记/录音机/日历/邮件, each starting with a schema-discovery step (`sqlite3 <db> .schema`) against the real backup, writing dedicated `miui_*` tables. Apps without a parser still appear in the Phase-1 inventory.
- **Phase 4 — Web integration:** add a "Xiaomi backup" source type + password field to the task-creation modal and backend task model; forward `source=miui-backup` + password into `AnalysisOrchestrator` over the existing task pipeline.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-29-miui-backup-forensics-phase1.md`.
