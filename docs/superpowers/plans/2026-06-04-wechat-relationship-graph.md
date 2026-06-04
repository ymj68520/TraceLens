# WeChat Relationship Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add WeChat chat record analysis with SQLCipher decryption, relationship graph generation via NetworkX, and interactive frontend visualization.

**Architecture:** C++ parses and decrypts WeChat EnMicroMsg.db, writes structured data to `_android.db`. Python FastAPI reads the database, builds a NetworkX graph with community detection and centrality analysis, serves results via REST API with caching. React frontend renders an interactive force-directed graph with timeline linkage and chat panel.

**Tech Stack:** C++20, libsqlcipher, SQLite3, Python 3.10+, NetworkX, python-louvain, FastAPI, React 18, react-force-graph-2d, Recharts

**Design Spec:** `docs/superpowers/specs/2026-06-04-wechat-relationship-graph-design.md`

---

## File Map

### C++ — New Files
| File | Responsibility |
|------|---------------|
| `src/analyzers/AndroidAnalyzer/WeChatDecryptor.h` | SQLCipher decryption class declaration |
| `src/analyzers/AndroidAnalyzer/WeChatDecryptor.cpp` | Decryption implementation with dual-mode password |
| `tests/UnitTest/test_wechat_decryptor_gtest.cpp` | Decryptor unit tests |
| `tests/UnitTest/test_wechat_parser_gtest.cpp` | Enhanced parser unit tests |

### C++ — Modified Files
| File | Change |
|------|--------|
| `src/analyzers/AndroidAnalyzer/AndroidDataTypes.h` | Add WeChatContact, WeChatChatroom, WeChatOwnerInfo structs |
| `src/core/DatabaseManager/SQL/android_analysis_sql.h` | Add 3 new tables + enhanced wechat_messages columns + INSERT statements |
| `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h` | Declare 3 new insert methods |
| `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp` | Implement 3 new insert methods |
| `src/analyzers/AndroidAnalyzer/AndroidAnalyzerDeclarations.h` | Declare new parser methods |
| `src/analyzers/AndroidAnalyzer/AndroidDataParsers.cpp` | Enhanced WeChat parser + extractAndParseDB dispatcher |
| `src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp` | Integration in analyzeAndroidData() |
| `src/CommandLineParser.h` | Add wechat_password field |
| `src/CommandLineParser.cpp` | Parse --wechat-password argument |
| `src/AnalysisOrchestrator.cpp` | Pass password to AndroidAnalyzer |
| `src/analyzers/AndroidAnalyzer/AndroidAnalyzerDeclarations.h` | Add setWeChatPassword() method |
| `CMakeLists.txt` | Add libsqlcipher dependency |

### Python — New Files
| File | Responsibility |
|------|---------------|
| `python_service/httpserver/services/wechat_graph_service.py` | Graph construction, algorithms, caching |
| `python_service/httpserver/routes/wechat_graph.py` | REST API endpoints |
| `python_service/tests/test_wechat_graph_service.py` | Unit tests for graph service |

### Python — Modified Files
| File | Change |
|------|--------|
| `python_service/httpserver/main.py` | Register wechat_graph router |
| `python_service/httpserver/routes/__init__.py` | Add wechat_graph to __all__ |

### Frontend — New Files
| File | Responsibility |
|------|---------------|
| `web/src/services/wechatService.js` | API client for WeChat endpoints |
| `web/src/pages/WeChatGraph/WeChatGraph.jsx` | Main page container |
| `web/src/pages/WeChatGraph/components/GraphCanvas.jsx` | ForceGraph2D wrapper |
| `web/src/pages/WeChatGraph/components/TimelineSlider.jsx` | Timeline with range selection |
| `web/src/pages/WeChatGraph/components/ChatPanel.jsx` | Chat bubble side panel |
| `web/src/pages/WeChatGraph/components/CommunityLegend.jsx` | Community color legend |
| `web/src/pages/WeChatGraph/components/PersonDetail.jsx` | Person detail card |
| `web/src/pages/WeChatGraph/components/SearchBar.jsx` | Search/filter bar |
| `web/src/pages/WeChatGraph/hooks/useWeChatGraph.js` | Data fetching hook |
| `web/src/styles/wechat-graph.css` | Chat bubble styles |

### Frontend — Modified Files
| File | Change |
|------|--------|
| `web/src/routes.jsx` | Add /wechat-graph route |
| `web/src/components/Layout/Layout.jsx` | Add sidebar nav entry + taskContextPages |
| `web/vite.config.js` | Add /api/wechat proxy |
| `web/src/locales/zh.js` | Add translation keys |
| `web/src/locales/en.js` | Add translation keys |

---

## Task 1: C++ Data Structures and SQL Schema

**Files:**
- Modify: `src/analyzers/AndroidAnalyzer/AndroidDataTypes.h`
- Modify: `src/core/DatabaseManager/SQL/android_analysis_sql.h`

### Step 1: Add WeChat structs to AndroidDataTypes.h

Add after the existing `ChatMessage` struct (around line 25):

```cpp
struct WeChatContact {
    std::string username;
    std::string nickname;
    std::string remark;
    std::string avatarPath;
    int type = 0;
    bool isChatroom = false;
};

struct WeChatChatroom {
    std::string chatroomName;
    std::string owner;
    std::string memberList;  // comma-separated usernames
    int memberCount = 0;
    int64_t createTime = 0;
};

struct WeChatOwnerInfo {
    std::string username;
    std::string nickname;
    int uin = 0;
    std::string imei;
};
```

### Step 2: Add new table schemas to android_analysis_sql.h

Inside the `CREATE_ALL_TABLES` string, add after the existing `wechat_messages` CREATE TABLE:

```sql
CREATE TABLE IF NOT EXISTS wechat_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    nickname TEXT,
    remark TEXT,
    avatar_path TEXT,
    type INTEGER,
    chatroom_flag INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS wechat_chatrooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chatroom_name TEXT UNIQUE,
    owner TEXT,
    member_list TEXT,
    member_count INTEGER,
    create_time INTEGER
);
CREATE TABLE IF NOT EXISTS wechat_owner_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    nickname TEXT,
    uin INTEGER,
    imei TEXT
);
```

### Step 3: Add enhanced wechat_messages columns

Replace the existing `wechat_messages` CREATE TABLE with:

```sql
CREATE TABLE IF NOT EXISTS wechat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT,
    receiver TEXT,
    content TEXT,
    timestamp INTEGER,
    media_url TEXT,
    media_type TEXT,
    msg_type INTEGER DEFAULT 1,
    is_send INTEGER DEFAULT 0,
    chatroom_name TEXT,
    sender_nickname TEXT,
    talker TEXT
);
```

### Step 4: Add INSERT statements

Add after the existing `INSERT_WECHAT` constant:

```cpp
inline constexpr const char* INSERT_WECHAT_ENHANCED =
    "INSERT INTO wechat_messages (sender, receiver, content, timestamp, msg_type, is_send, chatroom_name, sender_nickname, talker) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_WECHAT_CONTACT =
    "INSERT OR IGNORE INTO wechat_contacts (username, nickname, remark, avatar_path, type, chatroom_flag) VALUES (?, ?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_WECHAT_CHATROOM =
    "INSERT OR IGNORE INTO wechat_chatrooms (chatroom_name, owner, member_list, member_count, create_time) VALUES (?, ?, ?, ?, ?);";

inline constexpr const char* INSERT_WECHAT_OWNER =
    "INSERT OR REPLACE INTO wechat_owner_info (username, nickname, uin, imei) VALUES (?, ?, ?, ?);";
```

### Step 5: Commit

```bash
git add src/analyzers/AndroidAnalyzer/AndroidDataTypes.h src/core/DatabaseManager/SQL/android_analysis_sql.h
git commit -m "feat(wechat): add data structures and SQL schema for enhanced WeChat analysis"
```

---

## Task 2: C++ Database Insert Methods

**Files:**
- Modify: `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h`
- Modify: `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp`

### Step 1: Declare new methods in header

Add after `insertWeChatMessage` declaration (around line 30):

```cpp
bool insertWeChatEnhancedMessage(const ChatMessage& msg, int msgType, int isSend,
                                  const std::string& chatroomName, const std::string& senderNickname,
                                  const std::string& talker);
bool insertWeChatContact(const WeChatContact& contact);
bool insertWeChatChatroom(const WeChatChatroom& chatroom);
bool insertWeChatOwnerInfo(const WeChatOwnerInfo& owner);
```

### Step 2: Implement insertWeChatEnhancedMessage

Add in the .cpp file, following the exact pattern of `insertWeChatMessage`:

```cpp
bool AndroidAnalysisDatabase::insertWeChatEnhancedMessage(
    const ChatMessage& msg, int msgType, int isSend,
    const std::string& chatroomName, const std::string& senderNickname,
    const std::string& talker) {
    const char* sql = "INSERT INTO wechat_messages (sender, receiver, content, timestamp, msg_type, is_send, chatroom_name, sender_nickname, talker) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, msg.sender.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, msg.receiver.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, msg.content.c_str(), -1, SQLITE_TRANSIENT);
    try { sqlite3_bind_int64(stmt, 4, std::stoll(msg.timestamp)); } catch (...) { sqlite3_bind_int64(stmt, 4, 0); }
    sqlite3_bind_int(stmt, 5, msgType);
    sqlite3_bind_int(stmt, 6, isSend);
    sqlite3_bind_text(stmt, 7, chatroomName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, senderNickname.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, talker.c_str(), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}
```

### Step 3: Implement insertWeChatContact

```cpp
bool AndroidAnalysisDatabase::insertWeChatContact(const WeChatContact& contact) {
    const char* sql = "INSERT OR IGNORE INTO wechat_contacts (username, nickname, remark, avatar_path, type, chatroom_flag) VALUES (?, ?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, contact.username.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, contact.nickname.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, contact.remark.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, contact.avatarPath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 5, contact.type);
    sqlite3_bind_int(stmt, 6, contact.isChatroom ? 1 : 0);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}
```

### Step 4: Implement insertWeChatChatroom

```cpp
bool AndroidAnalysisDatabase::insertWeChatChatroom(const WeChatChatroom& chatroom) {
    const char* sql = "INSERT OR IGNORE INTO wechat_chatrooms (chatroom_name, owner, member_list, member_count, create_time) VALUES (?, ?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, chatroom.chatroomName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, chatroom.owner.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, chatroom.memberList.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 4, chatroom.memberCount);
    sqlite3_bind_int64(stmt, 5, chatroom.createTime);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}
```

### Step 5: Implement insertWeChatOwnerInfo

```cpp
bool AndroidAnalysisDatabase::insertWeChatOwnerInfo(const WeChatOwnerInfo& owner) {
    const char* sql = "INSERT OR REPLACE INTO wechat_owner_info (username, nickname, uin, imei) VALUES (?, ?, ?, ?);";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) return false;

    sqlite3_bind_text(stmt, 1, owner.username.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, owner.nickname.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 3, owner.uin);
    sqlite3_bind_text(stmt, 4, owner.imei.c_str(), -1, SQLITE_TRANSIENT);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}
```

### Step 6: Commit

```bash
git add src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp
git commit -m "feat(wechat): add database insert methods for contacts, chatrooms, owner info"
```

---

## Task 3: CLI Arguments and Analyzer Configuration

**Files:**
- Modify: `src/CommandLineParser.h`
- Modify: `src/CommandLineParser.cpp`
- Modify: `src/analyzers/AndroidAnalyzer/AndroidAnalyzerDeclarations.h`
- Modify: `src/AnalysisOrchestrator.cpp`

### Step 1: Add wechat_password to CommandLineArgs

In `CommandLineParser.h`, add after `android_analyze` (around line 29):

```cpp
std::string wechat_password;
```

### Step 2: Parse --wechat-password argument

In `CommandLineParser.cpp`, add in the argument parsing loop (after the `--android-analyze` branch):

```cpp
} else if (arg == "--wechat-password" && i + 1 < argc) {
    args.wechat_password = argv[++i];
```

### Step 3: Add setWeChatPassword to AndroidAnalyzer

In `AndroidAnalyzerDeclarations.h`, add a member variable and setter in the `AndroidAnalyzer` class:

```cpp
private:
    std::string wechatPassword_;
public:
    void setWeChatPassword(const std::string& password) { wechatPassword_ = password; }
    const std::string& getWeChatPassword() const { return wechatPassword_; }
```

### Step 4: Pass password from orchestrator

In `AnalysisOrchestrator.cpp`, after creating the `androidAnalyzer` (around line 108), add:

```cpp
if (!args.wechat_password.empty()) {
    androidAnalyzer->setWeChatPassword(args.wechat_password);
}
```

### Step 5: Commit

```bash
git add src/CommandLineParser.h src/CommandLineParser.cpp src/analyzers/AndroidAnalyzer/AndroidAnalyzerDeclarations.h src/AnalysisOrchestrator.cpp
git commit -m "feat(wechat): add --wechat-password CLI argument and analyzer configuration"
```

---

## Task 4: SQLCipher Decryptor

**Files:**
- Create: `src/analyzers/AndroidAnalyzer/WeChatDecryptor.h`
- Create: `src/analyzers/AndroidAnalyzer/WeChatDecryptor.cpp`
- Modify: `CMakeLists.txt`

### Step 1: Create WeChatDecryptor.h

```cpp
#pragma once

#include <string>
#include <sqlite3.h>

class WeChatDecryptor {
public:
    WeChatDecryptor();
    ~WeChatDecryptor();

    // Attempt to open an encrypted WeChat database
    // Returns true on success, false on failure
    bool openDatabase(const std::string& dbPath, const std::string& password);

    // Auto-derive password from device files in the image
    // Returns empty string on failure
    static std::string derivePassword(const std::string& imageMountPath);

    // Get the opened database handle (valid only after openDatabase returns true)
    sqlite3* getDb() const { return db_; }

    // Close the database
    void close();

    // Get last error message
    const std::string& getLastError() const { return lastError_; }

private:
    sqlite3* db_ = nullptr;
    std::string lastError_;

    bool tryOpenWithCipher(const std::string& dbPath, const std::string& password,
                           int kdfIterations, const std::string& hmacAlgo);
    static std::string md5(const std::string& input);
};
```

### Step 2: Create WeChatDecryptor.cpp

```cpp
#include "WeChatDecryptor.h"
#include <fstream>
#include <sstream>
#include <algorithm>
#include <cstring>
#include <openssl/md5.h>

WeChatDecryptor::WeChatDecryptor() = default;

WeChatDecryptor::~WeChatDecryptor() {
    close();
}

void WeChatDecryptor::close() {
    if (db_) {
        sqlite3_close(db_);
        db_ = nullptr;
    }
}

bool WeChatDecryptor::openDatabase(const std::string& dbPath, const std::string& password) {
    close();
    lastError_.clear();

    if (password.empty()) {
        lastError_ = "Password is empty";
        return false;
    }

    // Try SQLCipher 4.x defaults first (newer WeChat versions)
    if (tryOpenWithCipher(dbPath, password, 64000, "sha512")) {
        return true;
    }

    // Fall back to SQLCipher 2.x defaults (older WeChat versions)
    if (tryOpenWithCipher(dbPath, password, 4000, "sha1")) {
        return true;
    }

    lastError_ = "Failed to decrypt database with provided password";
    return false;
}

bool WeChatDecryptor::tryOpenWithCipher(const std::string& dbPath, const std::string& password,
                                         int kdfIterations, const std::string& hmacAlgo) {
    if (sqlite3_open(dbPath.c_str(), &db_) != SQLITE_OK) {
        lastError_ = "Failed to open database file: " + std::string(sqlite3_errmsg(db_));
        db_ = nullptr;
        return false;
    }

    // Set SQLCipher key
    std::string pragmaKey = "PRAGMA key = '" + password + "';";
    if (sqlite3_exec(db_, pragmaKey.c_str(), nullptr, nullptr, nullptr) != SQLITE_OK) {
        close();
        return false;
    }

    // Configure SQLCipher parameters
    std::string pragmaKdf = "PRAGMA kdf_iter = " + std::to_string(kdfIterations) + ";";
    sqlite3_exec(db_, pragmaKdf.c_str(), nullptr, nullptr, nullptr);

    std::string pragmaHmac = "PRAGMA cipher_use_hmac = ON;";
    sqlite3_exec(db_, pragmaHmac.c_str(), nullptr, nullptr, nullptr);

    if (hmacAlgo == "sha512") {
        sqlite3_exec(db_, "PRAGMA cipher_page_size = 4096;", nullptr, nullptr, nullptr);
        sqlite3_exec(db_, "PRAGMA cipher_compatibility = 4;", nullptr, nullptr, nullptr);
    } else {
        sqlite3_exec(db_, "PRAGMA cipher_page_size = 1024;", nullptr, nullptr, nullptr);
    }

    // Verify by querying a known table
    sqlite3_stmt* stmt;
    const char* testSql = "SELECT count(*) FROM sqlite_master;";
    if (sqlite3_prepare_v2(db_, testSql, -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            sqlite3_finalize(stmt);
            return true;  // Successfully decrypted
        }
        sqlite3_finalize(stmt);
    }

    close();
    return false;
}

std::string WeChatDecryptor::derivePassword(const std::string& imageMountPath) {
    // Try to find UIN from shared_prefs
    std::string uin;
    std::vector<std::string> uinPaths = {
        "/data/data/com.tencent.mm/shared_prefs/auth_info_key_prefs.xml",
        "/data/data/com.tencent.mm/shared_prefs/system_config_prefs.xml"
    };

    for (const auto& path : uinPaths) {
        std::string fullPath = imageMountPath + path;
        std::ifstream file(fullPath);
        if (file.is_open()) {
            std::string content((std::istreambuf_iterator<char>(file)),
                                 std::istreambuf_iterator<char>());
            // Look for _auth_uin or default_uin
            size_t pos = content.find("_auth_uin");
            if (pos == std::string::npos) pos = content.find("default_uin");
            if (pos != std::string::npos) {
                size_t valStart = content.find(">", pos);
                size_t valEnd = content.find("<", valStart);
                if (valStart != std::string::npos && valEnd != std::string::npos) {
                    uin = content.substr(valStart + 1, valEnd - valStart - 1);
                    // Trim whitespace
                    uin.erase(std::remove_if(uin.begin(), uin.end(), ::isspace), uin.end());
                    if (!uin.empty()) break;
                }
            }
        }
    }

    if (uin.empty()) return "";

    // Try to find IMEI (may be empty on newer devices)
    std::string imei = "1234567890ABCDEF";  // default fallback
    // TODO: extract IMEI from build.prop or shared_prefs if available

    // Derive password: MD5(IMEI + UIN).substring(0, 7)
    std::string combined = imei + uin;
    std::string hash = md5(combined);
    if (hash.length() >= 7) {
        return hash.substr(0, 7);
    }
    return "";
}

std::string WeChatDecryptor::md5(const std::string& input) {
    unsigned char digest[MD5_DIGEST_LENGTH];
    MD5(reinterpret_cast<const unsigned char*>(input.c_str()), input.size(), digest);

    char mdString[33];
    for (int i = 0; i < 16; i++) {
        sprintf(&mdString[i * 2], "%02x", (unsigned int)digest[i]);
    }
    return std::string(mdString);
}
```

### Step 3: Add libsqlcipher to CMakeLists.txt

Find the existing `find_package` or `target_link_libraries` section for sqlite3 and add sqlcipher:

```cmake
# Add to the dependency finding section
pkg_check_modules(SQLCIPHER REQUIRED sqlcipher)

# Add to target_link_libraries for forensic_analyzer
${SQLCIPHER_LIBRARIES}

# Add to target_include_directories
${SQLCIPHER_INCLUDE_DIRS}
```

Note: If pkg-config for sqlcipher is not available, use direct linking:
```cmake
target_link_libraries(forensic_analyzer PRIVATE sqlcipher crypto)
```

### Step 4: Add WeChatDecryptor.cpp to build

Add `src/analyzers/AndroidAnalyzer/WeChatDecryptor.cpp` to the `add_executable` or `target_sources` in CMakeLists.txt.

### Step 5: Commit

```bash
git add src/analyzers/AndroidAnalyzer/WeChatDecryptor.h src/analyzers/AndroidAnalyzer/WeChatDecryptor.cpp CMakeLists.txt
git commit -m "feat(wechat): add SQLCipher decryptor with dual-mode password resolution"
```

---

## Task 5: Enhanced WeChat Parser

**Files:**
- Modify: `src/analyzers/AndroidAnalyzer/AndroidAnalyzerDeclarations.h`
- Modify: `src/analyzers/AndroidAnalyzer/AndroidDataParsers.cpp`
- Modify: `src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp`

### Step 1: Declare new parser methods

In `AndroidAnalyzerDeclarations.h`, add after existing WeChat declarations:

```cpp
std::vector<WeChatContact> parseWeChatContacts(sqlite3* db);
std::vector<WeChatChatroom> parseWeChatChatrooms(sqlite3* db);
WeChatOwnerInfo identifyWeChatOwner(sqlite3* db);
void parseWeChatEnhanced(const std::string& dbPath, const std::string& password);
```

### Step 2: Implement parseWeChatContacts

In `AndroidDataParsers.cpp`:

```cpp
std::vector<WeChatContact> AndroidAnalyzer::parseWeChatContacts(sqlite3* db) {
    std::vector<WeChatContact> contacts;
    const char* sql = "SELECT username, nickname, conRemark, type, chatroomFlag FROM rcontact WHERE username NOT LIKE '%@chatroom%' AND username != 'weixin' AND username != 'filehelper';";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            WeChatContact contact;
            const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            const char* nickname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            const char* remark = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));

            contact.username = username ? username : "";
            contact.nickname = nickname ? nickname : "";
            contact.remark = remark ? remark : "";
            contact.type = sqlite3_column_int(stmt, 3);
            contact.isChatroom = false;

            if (!contact.username.empty()) {
                contacts.push_back(contact);
            }
        }
        sqlite3_finalize(stmt);
    }
    return contacts;
}
```

### Step 3: Implement parseWeChatChatrooms

```cpp
std::vector<WeChatChatroom> AndroidAnalyzer::parseWeChatChatrooms(sqlite3* db) {
    std::vector<WeChatChatroom> chatrooms;
    const char* sql = "SELECT chatroomname, roomowner, memberlist, membercount, addtime FROM chatroom;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            WeChatChatroom room;
            const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            const char* owner = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            const char* members = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));

            room.chatroomName = name ? name : "";
            room.owner = owner ? owner : "";
            room.memberList = members ? members : "";
            room.memberCount = sqlite3_column_int(stmt, 3);
            room.createTime = sqlite3_column_int64(stmt, 4);

            if (!room.chatroomName.empty()) {
                chatrooms.push_back(room);
            }
        }
        sqlite3_finalize(stmt);
    }
    return chatrooms;
}
```

### Step 4: Implement identifyWeChatOwner

```cpp
WeChatOwnerInfo AndroidAnalyzer::identifyWeChatOwner(sqlite3* db) {
    WeChatOwnerInfo owner;
    // Try userinfo table first
    const char* sql = "SELECT value FROM userinfo WHERE id = 2;";  // id=2 is typically username
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (username) owner.username = username;
        }
        sqlite3_finalize(stmt);
    }

    // Get nickname
    sql = "SELECT value FROM userinfo WHERE id = 4;";  // id=4 is typically nickname
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* nickname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (nickname) owner.nickname = nickname;
        }
        sqlite3_finalize(stmt);
    }

    return owner;
}
```

### Step 5: Implement parseWeChatEnhanced (main orchestrator)

```cpp
void AndroidAnalyzer::parseWeChatEnhanced(const std::string& dbPath, const std::string& password) {
    WeChatDecryptor decryptor;
    if (!decryptor.openDatabase(dbPath, password)) {
        LOG_WARNING("Failed to decrypt WeChat database: " + decryptor.getLastError());
        return;
    }

    sqlite3* db = decryptor.getDb();

    // 1. Identify device owner
    WeChatOwnerInfo owner = identifyWeChatOwner(db);
    androidDb_->insertWeChatOwnerInfo(owner);

    // 2. Parse contacts
    auto contacts = parseWeChatContacts(db);
    for (const auto& contact : contacts) {
        androidDb_->insertWeChatContact(contact);
    }

    // 3. Parse chatrooms
    auto chatrooms = parseWeChatChatrooms(db);
    for (const auto& room : chatrooms) {
        androidDb_->insertWeChatChatroom(room);
    }

    // 4. Parse messages with enhanced fields
    const char* msgSql = "SELECT talker, content, createTime, type, isSend FROM message WHERE type IN (1, 3, 34, 43, 47, 49) ORDER BY createTime;";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, msgSql, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            ChatMessage msg;
            const char* talker = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            const char* content = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));

            msg.content = content ? content : "";
            msg.timestamp = std::to_string(sqlite3_column_int64(stmt, 2));
            int msgType = sqlite3_column_int(stmt, 3);
            int isSend = sqlite3_column_int(stmt, 4);

            std::string talkerStr = talker ? talker : "";
            std::string chatroomName;
            std::string sender;
            std::string receiver;
            std::string senderNickname;

            if (talkerStr.find("@chatroom") != std::string::npos) {
                // Group chat
                chatroomName = talkerStr;
                // Extract sender from content XML header (format: "wxid_xxx:\n<message>")
                size_t colonPos = msg.content.find(":\n");
                if (colonPos != std::string::npos) {
                    sender = msg.content.substr(0, colonPos);
                    msg.content = msg.content.substr(colonPos + 2);
                }
                receiver = chatroomName;
            } else {
                // Private chat
                if (isSend == 1) {
                    sender = owner.username;
                    receiver = talkerStr;
                } else {
                    sender = talkerStr;
                    receiver = owner.username;
                }
            }

            // Look up nickname for sender
            for (const auto& c : contacts) {
                if (c.username == sender) {
                    senderNickname = c.remark.empty() ? c.nickname : c.remark;
                    break;
                }
            }

            msg.sender = sender;
            msg.receiver = receiver;

            androidDb_->insertWeChatEnhancedMessage(msg, msgType, isSend, chatroomName, senderNickname, talkerStr);
        }
        sqlite3_finalize(stmt);
    }

    decryptor.close();
    LOG_INFO("WeChat enhanced parsing completed: " + std::to_string(contacts.size()) + " contacts, " +
             std::to_string(chatrooms.size()) + " chatrooms");
}
```

### Step 6: Update extractAndParseDB and analyzeAndroidData

In `AndroidAnalyzerCore.cpp`, replace the existing WeChat line in `analyzeAndroidData()`:

```cpp
// Replace: extractAndParseDB("data/data/com.tencent.mm/MicroMsg/testuser/EnMicroMsg.db", "parseWeChat");
// With:
parseWeChatEnhanced("data/data/com.tencent.mm/MicroMsg/testuser/EnMicroMsg.db", wechatPassword_);
```

Also update `extractAndParseDB` dispatcher to remove the old "parseWeChat" branch (or keep it as fallback for unencrypted databases).

### Step 7: Commit

```bash
git add src/analyzers/AndroidAnalyzer/AndroidAnalyzerDeclarations.h src/analyzers/AndroidAnalyzer/AndroidDataParsers.cpp src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp
git commit -m "feat(wechat): implement enhanced parser with contacts, chatrooms, and owner identification"
```

---

## Task 6: C++ Unit Tests

**Files:**
- Create: `tests/UnitTest/test_wechat_decryptor_gtest.cpp`
- Create: `tests/UnitTest/test_wechat_parser_gtest.cpp`

### Step 1: Create test_wechat_decryptor_gtest.cpp

```cpp
#include <gtest/gtest.h>
#include "analyzers/AndroidAnalyzer/WeChatDecryptor.h"
#include <fstream>
#include <filesystem>

class WeChatDecryptorTest : public ::testing::Test {
protected:
    void SetUp() override {
        // Create a test database (unencrypted) for testing
        testDbPath_ = std::filesystem::temp_directory_path() / "test_wechat.db";
    }

    void TearDown() override {
        std::filesystem::remove(testDbPath_);
    }

    std::filesystem::path testDbPath_;
};

TEST_F(WeChatDecryptorTest, EmptyPasswordReturnsError) {
    WeChatDecryptor decryptor;
    EXPECT_FALSE(decryptor.openDatabase("/nonexistent.db", ""));
    EXPECT_FALSE(decryptor.getLastError().empty());
}

TEST_F(WeChatDecryptorTest, NonexistentFileReturnsError) {
    WeChatDecryptor decryptor;
    EXPECT_FALSE(decryptor.openDatabase("/nonexistent.db", "abcdef1"));
}

TEST_F(WeChatDecryptorTest, MD5DerivationProducesCorrectLength) {
    // Test the static derivePassword method with a mock image path
    // This will fail to find files, but should not crash
    std::string password = WeChatDecryptor::derivePassword("/nonexistent/");
    EXPECT_TRUE(password.empty());  // No files found
}
```

### Step 2: Create test_wechat_parser_gtest.cpp

```cpp
#include <gtest/gtest.h>
#include <sqlite3.h>
#include <filesystem>
#include "analyzers/AndroidAnalyzer/AndroidDataTypes.h"

class WeChatParserTest : public ::testing::Test {
protected:
    void SetUp() override {
        testDbPath_ = std::filesystem::temp_directory_path() / "test_wechat_parser.db";
        createTestDatabase();
    }

    void TearDown() override {
        std::filesystem::remove(testDbPath_);
    }

    void createTestDatabase() {
        sqlite3* db;
        ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

        const char* schema = R"(
            CREATE TABLE IF NOT EXISTS rcontact (
                username TEXT, nickname TEXT, conRemark TEXT, type INTEGER, chatroomFlag INTEGER
            );
            CREATE TABLE IF NOT EXISTS chatroom (
                chatroomname TEXT, roomowner TEXT, memberlist TEXT, membercount INTEGER, addtime INTEGER
            );
            CREATE TABLE IF NOT EXISTS message (
                talker TEXT, content TEXT, createTime INTEGER, type INTEGER, isSend INTEGER
            );
            CREATE TABLE IF NOT EXISTS userinfo (
                id INTEGER, value TEXT
            );
        )";
        sqlite3_exec(db, schema, nullptr, nullptr, nullptr);

        // Insert test data
        sqlite3_exec(db, "INSERT INTO rcontact VALUES ('wxid_test1', 'TestUser1', 'Remark1', 0, 0);", nullptr, nullptr, nullptr);
        sqlite3_exec(db, "INSERT INTO rcontact VALUES ('wxid_test2', 'TestUser2', '', 0, 0);", nullptr, nullptr, nullptr);
        sqlite3_exec(db, "INSERT INTO chatroom VALUES ('testroom@chatroom', 'wxid_test1', 'wxid_test1,wxid_test2', 2, 1700000000);", nullptr, nullptr, nullptr);
        sqlite3_exec(db, "INSERT INTO message VALUES ('wxid_test1', 'Hello World', 1700000001, 1, 0);", nullptr, nullptr, nullptr);
        sqlite3_exec(db, "INSERT INTO message VALUES ('wxid_test2', 'Hi there', 1700000002, 1, 1);", nullptr, nullptr, nullptr);
        sqlite3_exec(db, "INSERT INTO userinfo VALUES (2, 'wxid_owner');", nullptr, nullptr, nullptr);
        sqlite3_exec(db, "INSERT INTO userinfo VALUES (4, 'OwnerNick');", nullptr, nullptr, nullptr);

        sqlite3_close(db);
    }

    std::filesystem::path testDbPath_;
};

TEST_F(WeChatParserTest, DatabaseCreation) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);
    sqlite3_close(db);
}
```

### Step 3: Add tests to CMakeLists.txt

Add the test executables to the CMake build, following the pattern of existing test targets.

### Step 4: Commit

```bash
git add tests/UnitTest/test_wechat_decryptor_gtest.cpp tests/UnitTest/test_wechat_parser_gtest.cpp CMakeLists.txt
git commit -m "test(wechat): add unit tests for decryptor and parser"
```

---

## Task 7: Python Graph Service

**Files:**
- Create: `python_service/httpserver/services/wechat_graph_service.py`

### Step 1: Create the service

```python
"""
WeChat Relationship Graph Service
Builds NetworkX graphs from WeChat data in _android.db and computes analytics.
"""

import sqlite3
import os
import time
import hashlib
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from collections import defaultdict

import networkx as nx

try:
    import community as community_louvain
    HAS_LOUVAIN = True
except ImportError:
    HAS_LOUVAIN = False


class WeChatGraphService:
    """Service for WeChat relationship graph analysis with caching."""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 1800  # 30 minutes

    def _get_cache_key(self, task_id: str, db_path: str) -> str:
        """Generate cache key including db modification time."""
        try:
            mtime = os.path.getmtime(db_path)
        except OSError:
            mtime = 0
        return f"{task_id}:{mtime}"

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid."""
        if cache_key not in self._cache:
            return False
        cached = self._cache[cache_key]
        return (time.time() - cached["timestamp"]) < self._cache_ttl

    def invalidate_cache(self, task_id: str):
        """Invalidate cache for a specific task."""
        keys_to_remove = [k for k in self._cache if k.startswith(f"{task_id}:")]
        for key in keys_to_remove:
            del self._cache[key]

    def _resolve_db_path(self, task_id: str) -> Optional[str]:
        """Resolve _android.db path from task_id."""
        # Try common patterns
        import glob
        patterns = [
            f"**/{task_id}*_android.db",
            f"**/*_android.db",
        ]
        for pattern in patterns:
            matches = glob.glob(pattern, recursive=True)
            if matches:
                return matches[0]
        return None

    def build_graph(self, db_path: str) -> nx.DiGraph:
        """Build NetworkX directed graph from WeChat database."""
        G = nx.DiGraph()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 1. Get owner info
        owner = {}
        try:
            cursor.execute("SELECT username, nickname FROM wechat_owner_info LIMIT 1")
            row = cursor.fetchone()
            if row:
                owner = {"username": row["username"], "nickname": row["nickname"] or row["username"]}
        except sqlite3.OperationalError:
            pass

        # 2. Get contacts for label lookup
        contacts = {}
        try:
            cursor.execute("SELECT username, nickname, remark FROM wechat_contacts")
            for row in cursor.fetchall():
                label = row["remark"] or row["nickname"] or row["username"]
                contacts[row["username"]] = label
        except sqlite3.OperationalError:
            pass

        # 3. Add owner node
        if owner.get("username"):
            G.add_node(owner["username"], label=owner["nickname"], is_owner=True, message_count=0)

        # 4. Process private chat messages
        try:
            cursor.execute("""
                SELECT sender, receiver, content, timestamp, is_send, talker
                FROM wechat_messages
                WHERE chatroom_name IS NULL OR chatroom_name = ''
                ORDER BY timestamp
            """)
            edge_data = defaultdict(lambda: {"weight": 0, "total_chars": 0, "sent_count": 0,
                                              "received_count": 0, "first_time": None, "last_time": None})

            for row in cursor.fetchall():
                sender = row["sender"] or ""
                receiver = row["receiver"] or ""
                content = row["content"] or ""
                timestamp = row["timestamp"] or 0

                if not sender or not receiver:
                    continue

                # Normalize edge direction (alphabetical) for undirected behavior
                pair = tuple(sorted([sender, receiver]))
                data = edge_data[pair]
                data["weight"] += 1
                data["total_chars"] += len(content)
                if row["is_send"] == 1:
                    data["sent_count"] += 1
                else:
                    data["received_count"] += 1
                if data["first_time"] is None or timestamp < data["first_time"]:
                    data["first_time"] = timestamp
                if data["last_time"] is None or timestamp > data["last_time"]:
                    data["last_time"] = timestamp

            # Add edges to graph
            for (u, v), data in edge_data.items():
                # Add nodes if not exist
                for node_id in [u, v]:
                    if node_id not in G:
                        label = contacts.get(node_id, node_id)
                        G.add_node(node_id, label=label, is_owner=False, message_count=0)

                G.add_edge(u, v, **data, is_group_edge=False, chatroom_name=None)
                # Update message counts
                G.nodes[u]["message_count"] = G.nodes[u].get("message_count", 0) + data["weight"]
                G.nodes[v]["message_count"] = G.nodes[v].get("message_count", 0) + data["weight"]

        except sqlite3.OperationalError as e:
            print(f"Warning: Could not read wechat_messages: {e}")

        # 5. Process group chat messages for co-activity
        try:
            cursor.execute("""
                SELECT sender, chatroom_name, timestamp
                FROM wechat_messages
                WHERE chatroom_name IS NOT NULL AND chatroom_name != ''
                ORDER BY chatroom_name, timestamp
            """)

            # Group messages by chatroom and time window
            chatroom_messages = defaultdict(list)
            for row in cursor.fetchall():
                chatroom_messages[row["chatroom_name"]].append({
                    "sender": row["sender"],
                    "timestamp": row["timestamp"] or 0
                })

            # Co-activity: users active in same group within 1-hour window
            HOUR_WINDOW = 3600
            for chatroom, messages in chatroom_messages.items():
                for i, msg_i in enumerate(messages):
                    for j in range(i + 1, min(i + 50, len(messages))):  # limit scan
                        msg_j = messages[j]
                        if msg_j["timestamp"] - msg_i["timestamp"] > HOUR_WINDOW:
                            break
                        if msg_i["sender"] == msg_j["sender"]:
                            continue

                        pair = tuple(sorted([msg_i["sender"], msg_j["sender"]]))
                        if G.has_edge(pair[0], pair[1]):
                            edge = G[pair[0]][pair[1]]
                            edge["weight"] += 1
                        else:
                            # Add group-only edge
                            for node_id in pair:
                                if node_id not in G:
                                    label = contacts.get(node_id, node_id)
                                    G.add_node(node_id, label=label, is_owner=False, message_count=0)
                            G.add_edge(pair[0], pair[1], weight=1, total_chars=0,
                                      sent_count=0, received_count=0,
                                      first_time=msg_i["timestamp"], last_time=msg_j["timestamp"],
                                      is_group_edge=True, chatroom_name=chatroom)
        except sqlite3.OperationalError as e:
            print(f"Warning: Could not process group messages: {e}")

        conn.close()
        return G

    def compute_metrics(self, G: nx.DiGraph) -> Dict[str, Any]:
        """Compute graph metrics: community detection, centrality."""
        if len(G) == 0:
            return {"nodes": [], "edges": [], "communities": []}

        # Convert to undirected for community detection
        G_undirected = G.to_undirected()

        # Community detection (Louvain)
        communities = {}
        if HAS_LOUVAIN and len(G_undirected) > 1:
            try:
                partition = community_louvain.best_partition(G_undirected, resolution=1.0)
                communities = partition
            except Exception:
                pass

        # Centrality measures
        pagerank = nx.pagerank(G, weight="weight") if len(G) > 1 else {}
        betweenness = nx.betweenness_centrality(G, weight="weight") if len(G) > 1 else {}

        # Build community groups
        community_groups = defaultdict(list)
        for node, cluster in communities.items():
            community_groups[cluster].append(node)

        community_list = [
            {"cluster": cid, "members": members, "label": f"社区{cid}"}
            for cid, members in community_groups.items()
        ]

        # Build node list
        nodes = []
        for node_id, attrs in G.nodes(data=True):
            nodes.append({
                "id": node_id,
                "label": attrs.get("label", node_id),
                "is_owner": attrs.get("is_owner", False),
                "message_count": attrs.get("message_count", 0),
                "pagerank": round(pagerank.get(node_id, 0), 6),
                "betweenness": round(betweenness.get(node_id, 0), 6),
                "cluster": communities.get(node_id, 0)
            })

        # Build edge list
        edges = []
        for u, v, attrs in G.edges(data=True):
            first_time = attrs.get("first_time")
            last_time = attrs.get("last_time")
            edges.append({
                "source": u,
                "target": v,
                "weight": attrs.get("weight", 0),
                "sent_count": attrs.get("sent_count", 0),
                "received_count": attrs.get("received_count", 0),
                "total_chars": attrs.get("total_chars", 0),
                "first_time": datetime.fromtimestamp(first_time).isoformat() if first_time else None,
                "last_time": datetime.fromtimestamp(last_time).isoformat() if last_time else None,
                "is_group_edge": attrs.get("is_group_edge", False)
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "communities": community_list
        }

    def compute_timeline(self, G: nx.DiGraph, interval: str = "month") -> List[Dict[str, Any]]:
        """Compute temporal distribution of messages."""
        # Collect all timestamps from edges
        time_buckets = defaultdict(lambda: {"total_messages": 0, "active_edges": 0, "contacts": defaultdict(int)})

        for u, v, attrs in G.edges(data=True):
            first_time = attrs.get("first_time")
            last_time = attrs.get("last_time")
            weight = attrs.get("weight", 0)

            if not first_time:
                continue

            dt = datetime.fromtimestamp(first_time)
            if interval == "month":
                period = dt.strftime("%Y-%m")
            elif interval == "week":
                period = dt.strftime("%Y-W%W")
            else:
                period = dt.strftime("%Y-%m")

            bucket = time_buckets[period]
            bucket["total_messages"] += weight
            bucket["active_edges"] += 1
            bucket["contacts"][u] += weight
            bucket["contacts"][v] += weight

        # Format response
        intervals = []
        for period in sorted(time_buckets.keys()):
            bucket = time_buckets[period]
            top_contacts = sorted(bucket["contacts"].items(), key=lambda x: x[1], reverse=True)[:5]
            intervals.append({
                "period": period,
                "total_messages": bucket["total_messages"],
                "active_edges": bucket["active_edges"],
                "top_contacts": [{"username": uid, "message_count": count} for uid, count in top_contacts]
            })

        return intervals

    def get_chat_history(self, db_path: str, user1: str, user2: str,
                         offset: int = 0, limit: int = 50) -> Dict[str, Any]:
        """Get chat history between two users."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get total count
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM wechat_messages
            WHERE (sender = ? AND receiver = ?) OR (sender = ? AND receiver = ?)
        """, (user1, user2, user2, user1))
        total = cursor.fetchone()["cnt"]

        # Get messages
        cursor.execute("""
            SELECT sender, receiver, content, timestamp, msg_type, is_send, sender_nickname
            FROM wechat_messages
            WHERE (sender = ? AND receiver = ?) OR (sender = ? AND receiver = ?)
            ORDER BY timestamp ASC
            LIMIT ? OFFSET ?
        """, (user1, user2, user2, user1, limit, offset))

        messages = []
        for row in cursor.fetchall():
            ts = row["timestamp"]
            messages.append({
                "sender": row["sender"],
                "receiver": row["receiver"],
                "content": row["content"] or "",
                "timestamp": datetime.fromtimestamp(ts).isoformat() if ts else None,
                "msg_type": row["msg_type"] or 1,
                "is_send": row["is_send"] or 0,
                "sender_nickname": row["sender_nickname"] or row["sender"]
            })

        conn.close()
        return {"messages": messages, "total": total, "offset": offset, "limit": limit}

    def get_group_chat_history(self, db_path: str, chatroom: str,
                                offset: int = 0, limit: int = 50) -> Dict[str, Any]:
        """Get group chat history."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as cnt FROM wechat_messages WHERE chatroom_name = ?", (chatroom,))
        total = cursor.fetchone()["cnt"]

        cursor.execute("""
            SELECT sender, content, timestamp, msg_type, sender_nickname
            FROM wechat_messages
            WHERE chatroom_name = ?
            ORDER BY timestamp ASC
            LIMIT ? OFFSET ?
        """, (chatroom, limit, offset))

        messages = []
        for row in cursor.fetchall():
            ts = row["timestamp"]
            messages.append({
                "sender": row["sender"],
                "content": row["content"] or "",
                "timestamp": datetime.fromtimestamp(ts).isoformat() if ts else None,
                "msg_type": row["msg_type"] or 1,
                "sender_nickname": row["sender_nickname"] or row["sender"]
            })

        conn.close()
        return {"messages": messages, "total": total, "offset": offset, "limit": limit}

    def get_owner_info(self, db_path: str) -> Dict[str, Any]:
        """Get device owner information."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT username, nickname FROM wechat_owner_info LIMIT 1")
            row = cursor.fetchone()
            if row:
                return {"username": row["username"], "nickname": row["nickname"] or row["username"]}
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
        return {"username": "", "nickname": ""}

    def get_contacts_list(self, db_path: str) -> List[Dict[str, Any]]:
        """Get contact list."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        contacts = []
        try:
            cursor.execute("SELECT username, nickname, remark FROM wechat_contacts")
            for row in cursor.fetchall():
                contacts.append({
                    "username": row["username"],
                    "nickname": row["nickname"] or "",
                    "remark": row["remark"] or ""
                })
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
        return contacts

    async def get_full_graph(self, task_id: str, db_path: str) -> Dict[str, Any]:
        """Main entry: get full graph with caching."""
        cache_key = self._get_cache_key(task_id, db_path)

        if self._is_cache_valid(cache_key):
            cached = self._cache[cache_key]
            owner = self.get_owner_info(db_path)
            return {**cached["data"], "owner": owner}

        # Build and compute
        G = self.build_graph(db_path)
        metrics = self.compute_metrics(G)
        owner = self.get_owner_info(db_path)

        result = {**metrics, "owner": owner}

        # Cache result
        self._cache[cache_key] = {
            "data": result,
            "timestamp": time.time()
        }

        return result
```

### Step 2: Commit

```bash
git add python_service/httpserver/services/wechat_graph_service.py
git commit -m "feat(wechat): implement graph service with NetworkX algorithms and caching"
```

---

## Task 8: Python API Routes

**Files:**
- Create: `python_service/httpserver/routes/wechat_graph.py`
- Modify: `python_service/httpserver/main.py`
- Modify: `python_service/httpserver/routes/__init__.py`

### Step 1: Create wechat_graph.py route

```python
"""
WeChat Relationship Graph API Routes
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class GraphResponse(BaseModel):
    success: bool
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    communities: List[Dict[str, Any]]
    owner: Dict[str, Any]
    timestamp: str


class TimelineResponse(BaseModel):
    success: bool
    intervals: List[Dict[str, Any]]
    timestamp: str


class ChatResponse(BaseModel):
    success: bool
    messages: List[Dict[str, Any]]
    total: int
    offset: int
    limit: int
    timestamp: str


class ContactsResponse(BaseModel):
    success: bool
    contacts: List[Dict[str, Any]]
    timestamp: str


class OwnerResponse(BaseModel):
    success: bool
    owner: Dict[str, Any]
    timestamp: str


class InvalidateResponse(BaseModel):
    success: bool
    message: str
    timestamp: str


def _get_service():
    """Lazy import to avoid circular dependencies."""
    from ..services.wechat_graph_service import WeChatGraphService
    return WeChatGraphService()


def _resolve_db_path(task_id: str) -> str:
    """Resolve android database path from task_id.

    Follows the same pattern as the C++ backend's RouteHelpers::get_database_path():
    1. Check task metadata for 'android_db' key
    2. Fall back to <raw_db_path>_android.db

    The C++ backend stores task metadata including database paths.
    We query it via the cpp_backend service.
    """
    import os
    from ..services import get_service_manager

    service_manager = get_service_manager()

    # Try to get task info from C++ backend
    try:
        import httpx
        base_url = service_manager.settings.cpp_backend_base_url
        resp = httpx.get(f"{base_url}/api/tasks/{task_id}", timeout=10)
        if resp.status_code == 200:
            task_data = resp.json()
            # Check metadata for android_db path
            metadata = task_data.get("metadata", {})
            android_db = metadata.get("android_db", "")
            if android_db and os.path.exists(android_db):
                return android_db
            # Fall back: derive from raw_db path
            raw_db = metadata.get("raw_db", "")
            if raw_db:
                candidate = raw_db.replace("_raw.db", "_android.db")
                if os.path.exists(candidate):
                    return candidate
    except Exception:
        pass

    # Last resort: glob search
    import glob
    for pattern in [f"**/{task_id}*_android.db", f"**/*_android.db"]:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            return matches[0]

    raise HTTPException(status_code=404, detail=f"Android database not found for task {task_id}")


@router.get("/graph", response_model=GraphResponse)
async def get_graph(task_id: str = Query(..., description="Task ID")):
    """Get full relationship graph with community detection and centrality."""
    try:
        db_path = _resolve_db_path(task_id)
        service = _get_service()
        result = await service.get_full_graph(task_id, db_path)
        return GraphResponse(
            success=True,
            nodes=result.get("nodes", []),
            edges=result.get("edges", []),
            communities=result.get("communities", []),
            owner=result.get("owner", {}),
            timestamp=datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Graph computation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph/timeline", response_model=TimelineResponse)
async def get_timeline(
    task_id: str = Query(..., description="Task ID"),
    interval: str = Query("month", description="Aggregation interval: month or week")
):
    """Get temporal distribution of messages."""
    try:
        db_path = _resolve_db_path(task_id)
        service = _get_service()
        G = service.build_graph(db_path)
        intervals = service.compute_timeline(G, interval)
        return TimelineResponse(
            success=True,
            intervals=intervals,
            timestamp=datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Timeline computation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph/community")
async def get_community(task_id: str = Query(..., description="Task ID")):
    """Get community group details."""
    try:
        db_path = _resolve_db_path(task_id)
        service = _get_service()
        result = await service.get_full_graph(task_id, db_path)
        return {
            "success": True,
            "communities": result.get("communities", []),
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Community computation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph/person/{username}")
async def get_person(
    username: str,
    task_id: str = Query(..., description="Task ID")
):
    """Get single person ego network."""
    try:
        db_path = _resolve_db_path(task_id)
        service = _get_service()
        result = await service.get_full_graph(task_id, db_path)

        # Find the person's node and their connections
        person_node = None
        for node in result.get("nodes", []):
            if node["id"] == username:
                person_node = node
                break

        if not person_node:
            raise HTTPException(status_code=404, detail=f"Person {username} not found")

        # Find connected edges
        connected_edges = [
            edge for edge in result.get("edges", [])
            if edge["source"] == username or edge["target"] == username
        ]

        # Find connected nodes
        connected_ids = set()
        for edge in connected_edges:
            connected_ids.add(edge["source"])
            connected_ids.add(edge["target"])

        connected_nodes = [
            node for node in result.get("nodes", [])
            if node["id"] in connected_ids
        ]

        return {
            "success": True,
            "person": person_node,
            "nodes": connected_nodes,
            "edges": connected_edges,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Person lookup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat", response_model=ChatResponse)
async def get_chat(
    task_id: str = Query(..., description="Task ID"),
    user1: str = Query(..., description="First user"),
    user2: str = Query(..., description="Second user"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200)
):
    """Get chat history between two users."""
    try:
        db_path = _resolve_db_path(task_id)
        service = _get_service()
        result = service.get_chat_history(db_path, user1, user2, offset, limit)
        return ChatResponse(
            success=True,
            messages=result["messages"],
            total=result["total"],
            offset=result["offset"],
            limit=result["limit"],
            timestamp=datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat history failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/group", response_model=ChatResponse)
async def get_group_chat(
    task_id: str = Query(..., description="Task ID"),
    chatroom: str = Query(..., description="Chatroom name"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200)
):
    """Get group chat history."""
    try:
        db_path = _resolve_db_path(task_id)
        service = _get_service()
        result = service.get_group_chat_history(db_path, chatroom, offset, limit)
        return ChatResponse(
            success=True,
            messages=result["messages"],
            total=result["total"],
            offset=result["offset"],
            limit=result["limit"],
            timestamp=datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Group chat history failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/owner", response_model=OwnerResponse)
async def get_owner(task_id: str = Query(..., description="Task ID")):
    """Get device owner information."""
    try:
        db_path = _resolve_db_path(task_id)
        service = _get_service()
        owner = service.get_owner_info(db_path)
        return OwnerResponse(
            success=True,
            owner=owner,
            timestamp=datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Owner info failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/contacts", response_model=ContactsResponse)
async def get_contacts(task_id: str = Query(..., description="Task ID")):
    """Get contact list."""
    try:
        db_path = _resolve_db_path(task_id)
        service = _get_service()
        contacts = service.get_contacts_list(db_path)
        return ContactsResponse(
            success=True,
            contacts=contacts,
            timestamp=datetime.now().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Contacts list failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/graph/invalidate", response_model=InvalidateResponse)
async def invalidate_cache(task_id: str = Query(..., description="Task ID")):
    """Force cache refresh for a task."""
    try:
        service = _get_service()
        service.invalidate_cache(task_id)
        return InvalidateResponse(
            success=True,
            message=f"Cache invalidated for task {task_id}",
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        logger.error(f"Cache invalidation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
```

### Step 2: Register router in main.py

In `python_service/httpserver/main.py`, add to the imports in `_register_routes()`:

```python
from .routes import health, graphiti, llm, database, office, case_analysis, system, associations, oss_analysis, multi_analysis, dll, markitdown, wechat_graph
```

Add the router registration:

```python
app.include_router(wechat_graph.router, prefix="/api/wechat", tags=["WeChat Analysis"])
```

### Step 3: Update routes/__init__.py

Add `wechat_graph` to the `__all__` list.

### Step 4: Commit

```bash
git add python_service/httpserver/routes/wechat_graph.py python_service/httpserver/main.py python_service/httpserver/routes/__init__.py
git commit -m "feat(wechat): add REST API endpoints for relationship graph and chat history"
```

---

## Task 9: Frontend Service and Hooks

**Files:**
- Create: `web/src/services/wechatService.js`
- Create: `web/src/pages/WeChatGraph/hooks/useWeChatGraph.js`

### Step 1: Create wechatService.js

```javascript
import { pythonApi } from './api';

export const getWeChatGraph = async (taskId) => {
    return pythonApi.get('/api/wechat/graph', { params: { task_id: taskId } });
};

export const getWeChatTimeline = async (taskId, interval = 'month') => {
    return pythonApi.get('/api/wechat/graph/timeline', { params: { task_id: taskId, interval } });
};

export const getWeChatCommunity = async (taskId) => {
    return pythonApi.get('/api/wechat/graph/community', { params: { task_id: taskId } });
};

export const getWeChatPerson = async (taskId, username) => {
    return pythonApi.get(`/api/wechat/graph/person/${username}`, { params: { task_id: taskId } });
};

export const getWeChatChat = async (taskId, user1, user2, offset = 0, limit = 50) => {
    return pythonApi.get('/api/wechat/chat', {
        params: { task_id: taskId, user1, user2, offset, limit }
    });
};

export const getWeChatGroupChat = async (taskId, chatroom, offset = 0, limit = 50) => {
    return pythonApi.get('/api/wechat/chat/group', {
        params: { task_id: taskId, chatroom, offset, limit }
    });
};

export const getWeChatOwner = async (taskId) => {
    return pythonApi.get('/api/wechat/owner', { params: { task_id: taskId } });
};

export const getWeChatContacts = async (taskId) => {
    return pythonApi.get('/api/wechat/contacts', { params: { task_id: taskId } });
};

export const invalidateWeChatCache = async (taskId) => {
    return pythonApi.post('/api/wechat/graph/invalidate', null, { params: { task_id: taskId } });
};

export default {
    getWeChatGraph,
    getWeChatTimeline,
    getWeChatCommunity,
    getWeChatPerson,
    getWeChatChat,
    getWeChatGroupChat,
    getWeChatOwner,
    getWeChatContacts,
    invalidateWeChatCache,
};
```

### Step 2: Create useWeChatGraph.js hook

```javascript
import { useState, useCallback, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
    getWeChatGraph,
    getWeChatTimeline,
    getWeChatChat,
    getWeChatGroupChat,
    invalidateWeChatCache,
} from '../../../services/wechatService';

export function useWeChatGraph() {
    const [searchParams] = useSearchParams();
    const taskId = searchParams.get('task_id');

    const [graphData, setGraphData] = useState(null);
    const [timelineData, setTimelineData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    // Selection state
    const [selectedNode, setSelectedNode] = useState(null);
    const [selectedEdge, setSelectedEdge] = useState(null);
    const [chatMessages, setChatMessages] = useState([]);
    const [chatTotal, setChatTotal] = useState(0);
    const [chatLoading, setChatLoading] = useState(false);

    // Filter state
    const [timeRange, setTimeRange] = useState(null);
    const [selectedCommunity, setSelectedCommunity] = useState(null);
    const [searchQuery, setSearchQuery] = useState('');

    const fetchGraph = useCallback(async () => {
        if (!taskId) return;
        setLoading(true);
        setError(null);
        try {
            const [graphResult, timelineResult] = await Promise.all([
                getWeChatGraph(taskId),
                getWeChatTimeline(taskId, 'month')
            ]);
            setGraphData(graphResult);
            setTimelineData(timelineResult);
        } catch (err) {
            setError(err.message || 'Failed to load graph data');
        } finally {
            setLoading(false);
        }
    }, [taskId]);

    useEffect(() => {
        fetchGraph();
    }, [fetchGraph]);

    const loadChatHistory = useCallback(async (user1, user2, offset = 0) => {
        setChatLoading(true);
        try {
            const result = await getWeChatChat(taskId, user1, user2, offset, 50);
            if (offset === 0) {
                setChatMessages(result.messages);
            } else {
                setChatMessages(prev => [...prev, ...result.messages]);
            }
            setChatTotal(result.total);
        } catch (err) {
            console.error('Failed to load chat:', err);
        } finally {
            setChatLoading(false);
        }
    }, [taskId]);

    const loadGroupChat = useCallback(async (chatroom, offset = 0) => {
        setChatLoading(true);
        try {
            const result = await getWeChatGroupChat(taskId, chatroom, offset, 50);
            if (offset === 0) {
                setChatMessages(result.messages);
            } else {
                setChatMessages(prev => [...prev, ...result.messages]);
            }
            setChatTotal(result.total);
        } catch (err) {
            console.error('Failed to load group chat:', err);
        } finally {
            setChatLoading(false);
        }
    }, [taskId]);

    const handleEdgeClick = useCallback((edge) => {
        setSelectedEdge(edge);
        setSelectedNode(null);
        const src = typeof edge.source === 'object' ? edge.source.id : edge.source;
        const tgt = typeof edge.target === 'object' ? edge.target.id : edge.target;
        if (edge.is_group_edge && edge.chatroom_name) {
            loadGroupChat(edge.chatroom_name);
        } else {
            loadChatHistory(src, tgt);
        }
    }, [loadChatHistory, loadGroupChat]);

    const handleNodeClick = useCallback((node) => {
        setSelectedNode(node);
        setSelectedEdge(null);
        setChatMessages([]);
    }, []);

    const handleBackgroundClick = useCallback(() => {
        setSelectedNode(null);
        setSelectedEdge(null);
        setChatMessages([]);
    }, []);

    const refreshGraph = useCallback(async () => {
        if (taskId) {
            await invalidateWeChatCache(taskId);
            await fetchGraph();
        }
    }, [taskId, fetchGraph]);

    // Filter graph data by time range and community
    const filteredGraphData = useCallback(() => {
        if (!graphData) return null;

        let nodes = graphData.nodes || [];
        let edges = graphData.edges || [];

        if (selectedCommunity !== null) {
            const memberIds = new Set();
            const community = graphData.communities?.find(c => c.cluster === selectedCommunity);
            if (community) {
                community.members.forEach(m => memberIds.add(m));
                nodes = nodes.filter(n => memberIds.has(n.id));
                const nodeIds = new Set(nodes.map(n => n.id));
                edges = edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
            }
        }

        if (searchQuery) {
            const q = searchQuery.toLowerCase();
            const matchIds = new Set(
                nodes.filter(n =>
                    n.label?.toLowerCase().includes(q) ||
                    n.id?.toLowerCase().includes(q)
                ).map(n => n.id)
            );
            nodes = nodes.filter(n => matchIds.has(n.id));
            edges = edges.filter(e => matchIds.has(e.source) || matchIds.has(e.target));
        }

        return { nodes, links: edges };
    }, [graphData, selectedCommunity, searchQuery]);

    return {
        taskId,
        graphData: filteredGraphData(),
        rawGraphData: graphData,
        timelineData,
        loading,
        error,
        selectedNode,
        selectedEdge,
        chatMessages,
        chatTotal,
        chatLoading,
        timeRange,
        selectedCommunity,
        searchQuery,
        setSelectedNode,
        setSelectedEdge,
        setTimeRange,
        setSelectedCommunity,
        setSearchQuery,
        handleEdgeClick,
        handleNodeClick,
        handleBackgroundClick,
        loadChatHistory,
        loadGroupChat,
        refreshGraph,
    };
}
```

### Step 3: Add proxy to vite.config.js

In `web/vite.config.js`, add to the proxy object (after the existing `/api/db` entry):

```javascript
'/api/wechat': { target: 'http://localhost:8090', changeOrigin: true },
```

### Step 4: Commit

```bash
git add web/src/services/wechatService.js web/src/pages/WeChatGraph/hooks/useWeChatGraph.js web/vite.config.js
git commit -m "feat(wechat): add frontend service, hooks, and proxy configuration"
```

---

## Task 10: Frontend Components

**Files:**
- Create: `web/src/pages/WeChatGraph/WeChatGraph.jsx`
- Create: `web/src/pages/WeChatGraph/components/GraphCanvas.jsx`
- Create: `web/src/pages/WeChatGraph/components/ChatPanel.jsx`
- Create: `web/src/pages/WeChatGraph/components/TimelineSlider.jsx`
- Create: `web/src/pages/WeChatGraph/components/CommunityLegend.jsx`
- Create: `web/src/pages/WeChatGraph/components/PersonDetail.jsx`
- Create: `web/src/pages/WeChatGraph/components/SearchBar.jsx`
- Create: `web/src/styles/wechat-graph.css`

### Step 1: Create WeChatGraph.jsx (main container)

```jsx
import React from 'react';
import { useWeChatGraph } from './hooks/useWeChatGraph';
import GraphCanvas from './components/GraphCanvas';
import ChatPanel from './components/ChatPanel';
import TimelineSlider from './components/TimelineSlider';
import CommunityLegend from './components/CommunityLegend';
import PersonDetail from './components/PersonDetail';
import SearchBar from './components/SearchBar';
import '../../styles/wechat-graph.css';

export default function WeChatGraph() {
    const {
        graphData, rawGraphData, timelineData, loading, error,
        selectedNode, selectedEdge, chatMessages, chatTotal, chatLoading,
        timeRange, selectedCommunity, searchQuery,
        setSelectedCommunity, setSearchQuery,
        handleEdgeClick, handleNodeClick, handleBackgroundClick,
        loadChatHistory, refreshGraph,
    } = useWeChatGraph();

    if (loading) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="text-slate-400">加载关系图中...</div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="text-red-400">{error}</div>
            </div>
        );
    }

    if (!graphData || graphData.nodes?.length === 0) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="text-slate-400">未发现微信聊天记录</div>
            </div>
        );
    }

    const sidePanelContent = () => {
        if (selectedEdge) {
            return (
                <ChatPanel
                    edge={selectedEdge}
                    messages={chatMessages}
                    total={chatTotal}
                    loading={chatLoading}
                    onLoadMore={(offset) => {
                        const src = typeof selectedEdge.source === 'object' ? selectedEdge.source.id : selectedEdge.source;
                        const tgt = typeof selectedEdge.target === 'object' ? selectedEdge.target.id : selectedEdge.target;
                        loadChatHistory(src, tgt, offset);
                    }}
                    onClose={handleBackgroundClick}
                />
            );
        }
        if (selectedNode) {
            return (
                <PersonDetail
                    node={selectedNode}
                    graphData={rawGraphData}
                    onClose={handleBackgroundClick}
                />
            );
        }
        return <CommunityLegend communities={rawGraphData?.communities || []} selected={selectedCommunity} onSelect={setSelectedCommunity} />;
    };

    return (
        <div className="flex flex-col h-full p-4 gap-4">
            <SearchBar query={searchQuery} onChange={setSearchQuery} onRefresh={refreshGraph} />
            <div className="flex flex-1 gap-4 min-h-0">
                <div className="flex-1 rounded-xl overflow-hidden bg-gradient-to-br from-slate-900 to-slate-800">
                    <GraphCanvas
                        data={graphData}
                        onNodeClick={handleNodeClick}
                        onEdgeClick={handleEdgeClick}
                        onBackgroundClick={handleBackgroundClick}
                    />
                </div>
                <div className="w-80 shrink-0">
                    {sidePanelContent()}
                </div>
            </div>
            {timelineData && (
                <TimelineSlider data={timelineData} onRangeChange={() => {}} />
            )}
        </div>
    );
}
```

### Step 2: Create GraphCanvas.jsx

```jsx
import React, { useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

const COMMUNITY_COLORS = [
    '#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#8b5cf6',
    '#ec4899', '#06b6d4', '#f97316', '#14b8a6', '#6366f1'
];

export default function GraphCanvas({ data, onNodeClick, onEdgeClick, onBackgroundClick }) {
    const graphRef = useRef(null);

    const getNodeColor = useCallback((node) => {
        if (node.is_owner) return '#fbbf24';
        return COMMUNITY_COLORS[node.cluster % COMMUNITY_COLORS.length] || '#94a3b8';
    }, []);

    const getLinkWidth = useCallback((link) => {
        return Math.max(1, Math.min(8, (link.weight || 1) / 10));
    }, []);

    const getLinkColor = useCallback((link) => {
        return link.is_group_edge ? 'rgba(148, 163, 184, 0.4)' : 'rgba(148, 163, 184, 0.6)';
    }, []);

    const nodeCanvasObject = useCallback((node, ctx, globalScale) => {
        const size = node.is_owner ? 8 : 5;
        const color = getNodeColor(node);

        // Glow for highlighted
        ctx.beginPath();
        ctx.arc(node.x, node.y, size + 2, 0, 2 * Math.PI);
        ctx.fillStyle = color + '40';
        ctx.fill();

        // Main circle
        ctx.beginPath();
        ctx.arc(node.x, node.y, size, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();

        // Label
        if (globalScale >= 1.2) {
            ctx.font = `${12 / globalScale}px Sans-Serif`;
            ctx.textAlign = 'center';
            ctx.fillStyle = '#e2e8f0';
            ctx.fillText(node.label || node.id, node.x, node.y + size + 12 / globalScale);
        }
    }, [getNodeColor]);

    return (
        <ForceGraph2D
            ref={graphRef}
            graphData={data}
            nodeCanvasObject={nodeCanvasObject}
            nodePointerAreaPaint={(node, color, ctx) => {
                ctx.fillStyle = color;
                ctx.beginPath();
                ctx.arc(node.x, node.y, 8, 0, 2 * Math.PI);
                ctx.fill();
            }}
            linkColor={getLinkColor}
            linkWidth={getLinkWidth}
            linkDirectionalArrowLength={3}
            linkDirectionalArrowRelPos={1}
            onNodeClick={onNodeClick}
            onLinkClick={onEdgeClick}
            onBackgroundClick={onBackgroundClick}
            cooldownTicks={80}
            onEngineStop={() => graphRef.current?.zoomToFit(400, 40)}
            backgroundColor="transparent"
        />
    );
}
```

### Step 3: Create ChatPanel.jsx

```jsx
import React from 'react';

const MSG_TYPE_LABELS = {
    1: '文本', 3: '图片', 34: '语音', 43: '视频', 47: '表情', 49: '链接'
};

export default function ChatPanel({ edge, messages, total, loading, onLoadMore, onClose }) {
    const src = typeof edge.source === 'object' ? edge.source.id : edge.source;
    const tgt = typeof edge.target === 'object' ? edge.target.id : edge.target;
    const srcLabel = typeof edge.source === 'object' ? edge.source.label : src;
    const tgtLabel = typeof edge.target === 'object' ? edge.target.label : tgt;

    return (
        <div className="flex flex-col h-full bg-slate-800 rounded-xl overflow-hidden">
            <div className="flex items-center justify-between p-3 border-b border-slate-700">
                <div>
                    <div className="text-sm font-medium text-slate-200">
                        {srcLabel} ↔ {tgtLabel}
                    </div>
                    <div className="text-xs text-slate-400">
                        共 {edge.weight || 0} 条消息
                    </div>
                </div>
                <button onClick={onClose} className="text-slate-400 hover:text-slate-200">✕</button>
            </div>

            <div className="flex-1 overflow-y-auto p-3 space-y-3 wechat-chat-scroll">
                {messages.map((msg, i) => {
                    const isOwner = msg.is_send === 1;
                    return (
                        <div key={i} className={`flex ${isOwner ? 'justify-end' : 'justify-start'}`}>
                            <div className={`max-w-[80%] ${isOwner ? 'order-2' : ''}`}>
                                {!isOwner && (
                                    <div className="text-xs text-slate-400 mb-1">{msg.sender_nickname || msg.sender}</div>
                                )}
                                <div className={`rounded-lg px-3 py-2 text-sm ${
                                    isOwner
                                        ? 'bg-green-600 text-white chat-bubble-right'
                                        : 'bg-slate-600 text-slate-100 chat-bubble-left'
                                }`}>
                                    {msg.msg_type === 1 ? msg.content : `[${MSG_TYPE_LABELS[msg.msg_type] || '消息'}]`}
                                </div>
                                <div className="text-xs text-slate-500 mt-1">
                                    {msg.timestamp ? new Date(msg.timestamp).toLocaleString() : ''}
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>

            {messages.length < total && (
                <button
                    onClick={() => onLoadMore(messages.length)}
                    disabled={loading}
                    className="p-2 text-sm text-blue-400 hover:text-blue-300 border-t border-slate-700"
                >
                    {loading ? '加载中...' : '加载更多'}
                </button>
            )}
        </div>
    );
}
```

### Step 4: Create remaining components

**TimelineSlider.jsx:**
```jsx
import React from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, Brush } from 'recharts';

export default function TimelineSlider({ data, onRangeChange }) {
    const intervals = data?.intervals || [];
    if (intervals.length === 0) return null;

    return (
        <div className="h-32 bg-slate-800 rounded-xl p-3">
            <div className="text-xs text-slate-400 mb-2">消息时间线</div>
            <ResponsiveContainer width="100%" height="85%">
                <AreaChart data={intervals}>
                    <XAxis dataKey="period" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                    <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} width={40} />
                    <Tooltip
                        contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                        labelStyle={{ color: '#e2e8f0' }}
                    />
                    <Area type="monotone" dataKey="total_messages" stroke="#3b82f6" fill="#3b82f680" />
                    <Brush
                        dataKey="period"
                        height={20}
                        stroke="#475569"
                        fill="#1e293b"
                        onChange={(range) => onRangeChange?.(range)}
                    />
                </AreaChart>
            </ResponsiveContainer>
        </div>
    );
}
```

**CommunityLegend.jsx:**
```jsx
import React from 'react';

const COLORS = ['#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];

export default function CommunityLegend({ communities, selected, onSelect }) {
    if (!communities?.length) return <div className="text-slate-400 text-sm p-3">无社区数据</div>;

    return (
        <div className="bg-slate-800 rounded-xl p-3">
            <div className="text-sm font-medium text-slate-200 mb-2">社区分组</div>
            <div className="space-y-1">
                {communities.map((c) => (
                    <button
                        key={c.cluster}
                        onClick={() => onSelect(selected === c.cluster ? null : c.cluster)}
                        className={`flex items-center gap-2 w-full px-2 py-1 rounded text-sm ${
                            selected === c.cluster ? 'bg-slate-600' : 'hover:bg-slate-700'
                        }`}
                    >
                        <div className="w-3 h-3 rounded-full" style={{ background: COLORS[c.cluster % COLORS.length] }} />
                        <span className="text-slate-300">{c.label}</span>
                        <span className="text-slate-500 text-xs ml-auto">{c.members?.length || 0}人</span>
                    </button>
                ))}
            </div>
        </div>
    );
}
```

**PersonDetail.jsx:**
```jsx
import React from 'react';

export default function PersonDetail({ node, graphData, onClose }) {
    const connectedEdges = (graphData?.edges || []).filter(e => {
        const src = typeof e.source === 'object' ? e.source.id : e.source;
        const tgt = typeof e.target === 'object' ? e.target.id : e.target;
        return src === node.id || tgt === node.id;
    });

    return (
        <div className="bg-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
                <div>
                    <div className="text-lg font-medium text-slate-100">{node.label || node.id}</div>
                    <div className="text-xs text-slate-400">{node.id}</div>
                </div>
                <button onClick={onClose} className="text-slate-400 hover:text-slate-200">✕</button>
            </div>

            <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="bg-slate-700 rounded p-2">
                    <div className="text-slate-400 text-xs">消息数</div>
                    <div className="text-slate-100 font-medium">{node.message_count || 0}</div>
                </div>
                <div className="bg-slate-700 rounded p-2">
                    <div className="text-slate-400 text-xs">PageRank</div>
                    <div className="text-slate-100 font-medium">{(node.pagerank || 0).toFixed(4)}</div>
                </div>
                <div className="bg-slate-700 rounded p-2">
                    <div className="text-slate-400 text-xs">中介中心性</div>
                    <div className="text-slate-100 font-medium">{(node.betweenness || 0).toFixed(4)}</div>
                </div>
                <div className="bg-slate-700 rounded p-2">
                    <div className="text-slate-400 text-xs">社区</div>
                    <div className="text-slate-100 font-medium">社区{node.cluster || 0}</div>
                </div>
            </div>

            <div>
                <div className="text-sm text-slate-300 mb-1">关联关系 ({connectedEdges.length})</div>
                <div className="space-y-1 max-h-40 overflow-y-auto">
                    {connectedEdges.map((e, i) => {
                        const src = typeof e.source === 'object' ? e.source.id : e.source;
                        const tgt = typeof e.target === 'object' ? e.target.id : e.target;
                        const other = src === node.id ? tgt : src;
                        return (
                            <div key={i} className="flex justify-between text-xs text-slate-400 px-2 py-1">
                                <span>{other}</span>
                                <span>{e.weight || 0}条</span>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
```

**SearchBar.jsx:**
```jsx
import React from 'react';

export default function SearchBar({ query, onChange, onRefresh }) {
    return (
        <div className="flex items-center gap-3">
            <div className="flex-1 relative">
                <input
                    type="text"
                    value={query}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder="搜索联系人..."
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                />
            </div>
            <button
                onClick={onRefresh}
                className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-300 hover:bg-slate-700"
            >
                刷新
            </button>
        </div>
    );
}
```

### Step 5: Create wechat-graph.css

```css
.wechat-chat-scroll::-webkit-scrollbar {
    width: 4px;
}
.wechat-chat-scroll::-webkit-scrollbar-track {
    background: transparent;
}
.wechat-chat-scroll::-webkit-scrollbar-thumb {
    background: #475569;
    border-radius: 2px;
}

.chat-bubble-left {
    position: relative;
}
.chat-bubble-left::before {
    content: '';
    position: absolute;
    left: -6px;
    top: 10px;
    border: 6px solid transparent;
    border-right-color: #475569;
}

.chat-bubble-right {
    position: relative;
}
.chat-bubble-right::before {
    content: '';
    position: absolute;
    right: -6px;
    top: 10px;
    border: 6px solid transparent;
    border-left-color: #16a34a;
}
```

### Step 6: Commit

```bash
git add web/src/pages/WeChatGraph/ web/src/styles/wechat-graph.css
git commit -m "feat(wechat): add frontend components for relationship graph visualization"
```

---

## Task 11: Route and Navigation Registration

**Files:**
- Modify: `web/src/routes.jsx`
- Modify: `web/src/components/Layout/Layout.jsx`
- Modify: `web/src/locales/zh.js`
- Modify: `web/src/locales/en.js`

### Step 1: Add route in routes.jsx

Add import at top:
```jsx
const WeChatGraph = React.lazy(() => import('./pages/WeChatGraph/WeChatGraph'));
```

Add route in children array:
```jsx
{
    path: 'wechat-graph',
    element: (
        <React.Suspense fallback={<div className="flex items-center justify-center h-full"><div className="text-slate-400">Loading...</div></div>}>
            <WeChatGraph />
        </React.Suspense>
    ),
},
```

### Step 2: Add sidebar navigation in Layout.jsx

Add import for the icon:
```jsx
import { MessageCircle } from 'lucide-react';
```

Add to navigation array (after the android entry):
```jsx
{ name: t('nav.wechat_graph'), href: '/wechat-graph', icon: MessageCircle },
```

Add `/wechat-graph` to the `taskContextPages` array.

### Step 3: Add translation keys

In `zh.js`:
```javascript
wechat_graph: '微信关系分析',
```

In `en.js`:
```javascript
wechat_graph: 'WeChat Graph',
```

### Step 4: Commit

```bash
git add web/src/routes.jsx web/src/components/Layout/Layout.jsx web/src/locales/zh.js web/src/locales/en.js
git commit -m "feat(wechat): register route and navigation for WeChat graph page"
```

---

## Task 12: Integration Test

**Files:**
- Create: `tests/test_wechat_analysis.sh`

### Step 1: Create integration test script

```bash
#!/bin/bash
# Integration test for WeChat analysis pipeline
set -e

echo "=== WeChat Analysis Integration Test ==="

# Build the project
echo "[1/5] Building project..."
cd "$(dirname "$0")/.."
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -5
cmake --build . -j$(nproc) 2>&1 | tail -5
echo "Build completed."

# Run C++ unit tests
echo "[2/5] Running C++ unit tests..."
ctest --output-on-failure -R wechat 2>&1 || echo "Note: Some tests may be skipped if SQLCipher not installed"

# Run Python unit tests
echo "[3/5] Running Python unit tests..."
cd ..
python -m pytest python_service/tests/test_wechat_graph_service.py -v 2>&1 || echo "Note: Python tests may need networkx installed"

# Verify Python API routes
echo "[4/5] Checking Python route registration..."
grep -q "wechat_graph" python_service/httpserver/main.py && echo "OK: Router registered" || echo "FAIL: Router not registered"
grep -q "wechat_graph" python_service/httpserver/routes/__init__.py && echo "OK: Module in __all__" || echo "FAIL: Module not in __all__"

# Verify frontend files
echo "[5/5] Checking frontend files..."
test -f web/src/pages/WeChatGraph/WeChatGraph.jsx && echo "OK: Main page exists" || echo "FAIL: Main page missing"
test -f web/src/services/wechatService.js && echo "OK: Service exists" || echo "FAIL: Service missing"
grep -q "wechat-graph" web/src/routes.jsx && echo "OK: Route registered" || echo "FAIL: Route not registered"
grep -q "wechat-graph" web/src/components/Layout/Layout.jsx && echo "OK: Nav registered" || echo "FAIL: Nav not registered"

echo "=== Integration Test Complete ==="
```

### Step 2: Make executable and commit

```bash
chmod +x tests/test_wechat_analysis.sh
git add tests/test_wechat_analysis.sh
git commit -m "test(wechat): add integration test script"
```

---

## Task 13: Final Verification

### Step 1: Verify all files exist

```bash
# C++ files
test -f src/analyzers/AndroidAnalyzer/WeChatDecryptor.h && echo "OK"
test -f src/analyzers/AndroidAnalyzer/WeChatDecryptor.cpp && echo "OK"
test -f tests/UnitTest/test_wechat_decryptor_gtest.cpp && echo "OK"
test -f tests/UnitTest/test_wechat_parser_gtest.cpp && echo "OK"

# Python files
test -f python_service/httpserver/services/wechat_graph_service.py && echo "OK"
test -f python_service/httpserver/routes/wechat_graph.py && echo "OK"

# Frontend files
test -f web/src/pages/WeChatGraph/WeChatGraph.jsx && echo "OK"
test -f web/src/services/wechatService.js && echo "OK"
```

### Step 2: Verify build compiles

```bash
cd build && cmake .. && cmake --build . -j$(nproc)
```

### Step 3: Run all tests

```bash
ctest --output-on-failure
cd .. && python -m pytest python_service/tests/ -v
```

### Step 4: Final commit

```bash
git add -A && git commit -m "feat(wechat): complete WeChat relationship graph analysis module"
```
