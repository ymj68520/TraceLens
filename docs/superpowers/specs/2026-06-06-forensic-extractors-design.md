# Forensic File Type Extractors Design Spec

**Date:** 2026-06-06
**Status:** Draft
**Scope:** Add 15 new Python extractor classes for forensically common file types

## Problem Statement

The ForensicsProject LLM analysis pipeline requires all files to be converted to text/markdown before sending to the AI model. The existing Python extractor plugin system covers common document formats (PDF, DOCX, XLSX, etc.) and database formats (SQLite, LevelDB, Redis, BSON), but lacks support for many forensically critical file types:

- Email evidence (EML, MSG, MBOX, PST/OST)
- Windows system artifacts (EVTX event logs, Registry hives, LNK shortcuts, Jump Lists)
- Browser history databases (Chrome, Firefox)
- Linux system logs (journald, auth.log, wtmp/utmp)
- Android backup files (AB format)
- Forensic disk image metadata (E01)

## Goals

1. Add Python extractor classes for 15 forensically common file types
2. Follow existing `BaseExtractor` + `extract_to_markdown()` plugin architecture exactly
3. Output markdown consistent with existing extractors (ArchiveExtractor, SQLiteExtractor style)
4. Use pure Python libraries where possible, minimize system-level dependencies
5. Each extractor handles errors gracefully and returns meaningful error messages
6. Register all new extractors in `extractor_mapping.json`

## Non-Goals

- C++ side changes (C++ uses MarkitdownProxy to call Python service)
- Modifying existing extractors
- Adding new API endpoints (existing case_analysis pipeline handles routing)
- Full PST/OST parsing (complex format, best-effort only)

## Architecture

### Plugin System Integration

All new extractors follow the existing pattern:

```python
from .base import BaseExtractor, register_extractor

@register_extractor
class NewExtractor(BaseExtractor):
    async def extract_to_markdown(self, file_path: str) -> str:
        # ... extraction logic ...
        return markdown_string
```

Registration in `extractor_mapping.json`:

```json
{
    "EmlExtractor": [".eml"],
    "MsgExtractor": [".msg"],
    ...
}
```

### File Organization

```
python_service/httpserver/services/extractors/
├── __init__.py              # (existing) dynamic loader
├── base.py                  # (existing) BaseExtractor ABC
├── markitdown_extractor.py  # (existing)
├── office.py                # (existing)
├── relational_db.py         # (existing)
├── nosql_db.py              # (existing)
├── archives.py              # (existing)
├── email.py                 # NEW: EmlExtractor, MsgExtractor, MboxExtractor, PstExtractor
├── windows_evtx.py          # NEW: EvtxExtractor
├── windows_registry.py      # NEW: RegistryExtractor
├── windows_lnk.py           # NEW: LnkExtractor, JumplistExtractor
├── browser_history.py       # NEW: ChromeHistoryExtractor, FirefoxHistoryExtractor
├── linux_journal.py         # NEW: JournalExtractor, AuthLogExtractor, WtmpExtractor
├── android_backup.py        # NEW: AndroidBackupExtractor
└── disk_image.py            # NEW: E01MetadataExtractor
```

## Extractor Specifications

### 1. Email Extractors (`email.py`)

#### EmlExtractor

- **File types:** `.eml`
- **Library:** `email` (Python standard library)
- **Parsing approach:**
  - Use `email.message_from_file()` to parse RFC 822 format
  - Extract headers: From, To, CC, BCC, Date, Subject, Message-ID, X-Mailer
  - Extract body: prefer text/plain, fallback to text/html
  - List attachments with filename, content-type, size
- **Markdown output:**
  ```
  # Email Summary: `filename.eml`
  **From:** ...
  **To:** ...
  **Date:** ...
  **Subject:** ...

  ## Headers
  | Header | Value |
  | --- | --- |
  | Message-ID | ... |
  | X-Mailer | ... |

  ## Body
  (plain text body content)

  ## Attachments (N)
  1. `file.pdf` (application/pdf, 1.2 MB)
  ```
- **Edge cases:** Multipart messages, base64-encoded bodies, malformed headers

#### MsgExtractor

- **File types:** `.msg`
- **Library:** `olefile` (pure Python OLE2 parser)
- **Parsing approach:**
  - Open OLE2 compound document with `olefile`
  - Read properties from `\x01Version`, `\x01CompObj` streams
  - Extract named properties: Subject, SenderName, SenderEmailAddress, DisplayTo, DeliveryTime
  - Read body from `\x01Body` stream (plain text) or `\x01HTMLBody` stream
  - Enumerate attachments from `attach` subdirectories
- **Markdown output:** Same structure as EmlExtractor
- **Edge cases:** Encrypted MSG, embedded OLE objects, RTF bodies

#### MboxExtractor

- **File types:** `.mbox`
- **Library:** `mailbox` (Python standard library)
- **Parsing approach:**
  - Use `mailbox.mbox(file_path)` to iterate messages
  - For each message, extract same fields as EmlExtractor
  - Sample first N messages (default 100) to prevent context overflow
  - Provide summary statistics (total count, date range)
- **Markdown output:**
  ```
  # Mbox Summary: `filename.mbox`
  **Total Messages:** 1,234
  **Date Range:** 2024-01-01 ~ 2024-01-15

  ## Message Sample (First 100)
  ### Message 1
  **From:** ... **Date:** ... **Subject:** ...
  Body preview (first 500 chars)...

  ### Message 2
  ...
  ```
- **Edge cases:** Very large mbox files (GB+), malformed messages

#### PstExtractor

- **File types:** `.pst`, `.ost`
- **Library:** `libpff` via subprocess (if available), fallback to header-only parsing
- **Parsing approach:**
  - Try `pffexport` CLI tool (from libpff) for full extraction
  - Fallback: read PST header magic bytes, extract basic metadata (version, encryption type)
  - Report format limitations if libpff not available
- **Markdown output:**
  ```
  # PST/OST File Summary: `outlook.pst`
  **Format:** PST (Personal Storage Table)
  **Version:** Unicode (32-bit)
  **Encryption:** Compressible

  ## Extraction Status
  (Full extraction requires libpff tools)

  ## Basic Metadata
  (Header-level information only)
  ```
- **Note:** PST is a complex binary format; full parsing requires external tools

### 2. Windows Event Log Extractor (`windows_evtx.py`)

#### EvtxExtractor

- **File types:** `.evtx`
- **Library:** `python-evtx` (pure Python EVTX parser)
- **Parsing approach:**
  - Parse EVTX file header for metadata (computer name, channel, record count)
  - Iterate event records, extract EventID, Level, TimeCreated, Provider, EventData
  - Build event distribution summary (by EventID count)
  - Sample recent N events (default 100)
  - Map EventID to human-readable descriptions for common IDs
- **Markdown output:**
  ```
  # Windows Event Log Summary: `System.evtx`
  **Channel:** System
  **Computer:** DESKTOP-ABC123
  **Total Records:** 1,234
  **Time Range:** 2024-01-01 ~ 2024-01-15

  ## Event Distribution (Top 20)
  | Event ID | Count | Level | Description |
  | --- | --- | --- | --- |
  | 7036 | 156 | Info | Service state change |
  | 4624 | 89 | Info | Logon success |
  | 1074 | 23 | Info | System shutdown |

  ## Recent Events (Last 100)
  | Time | ID | Level | Provider | Message |
  | --- | --- | --- | --- | --- |
  | 2024-01-15 10:30 | 7036 | Info | Service Control Manager | ... |
  ```
- **Common EventID map:** Include descriptions for top 50 forensic-relevant EventIDs (logon/logoff, service changes, process creation, policy changes, etc.)
- **Edge cases:** Corrupted records, fragmented EVTX files, very large files (1GB+)

### 3. Windows Registry Extractor (`windows_registry.py`)

#### RegistryExtractor

- **File types:** `.reg`, `.hiv` (Registry hive files) + specific `.dat` files (SAM, SYSTEM, SOFTWARE, SECURITY, DEFAULT, NTUSER.DAT, UsrClass.dat)
- **Library:** `python-registry` (pure Python registry parser)
- **Routing note:** Since `.dat` is a generic extension, the extractor checks file magic bytes (REGF header = `0x72656766`) before parsing. If the file is not a registry hive, it returns an error message. For the `_filename_routes` mapping, SAM, SYSTEM, SOFTWARE, SECURITY, DEFAULT, NTUSER.DAT, UsrClass.dat are mapped by filename.
- **Parsing approach:**
  - Check file magic bytes first (REGF header = `0x72656766` for registry hives)
  - Open registry hive with `Registry.Registry(file_path)`
  - Walk key tree, collect key count and depth statistics
  - Focus on forensically important keys:
    - `SAM\Domains\Account\Users` (user accounts)
    - `SYSTEM\Select` (current control set)
    - `SOFTWARE\Microsoft\Windows\CurrentVersion\Run` (autostart)
    - `NTUSER.DAT\Software\Microsoft\Windows\CurrentVersion\Explorer\RecentDocs` (recent files)
    - `NTUSER.DAT\Software\Microsoft\Internet Explorer` (IE history)
  - Extract values from important keys
  - Sample other keys (first N)
- **Markdown output:**
  ```
  # Windows Registry Summary: `SAM`
  **Hive Type:** SAM
  **Root Key:** CMI-CreateHive{...}
  **Total Keys:** 1,234

  ## Forensically Important Keys

  ### User Accounts (SAM\Domains\Account\Users)
  | RID | Username | Full Name | Last Login |
  | --- | --- | --- | --- |
  | 0x1F4 | Administrator | | 2024-01-15 |
  | 0x3E8 | john | John Doe | 2024-01-14 |

  ### Autostart Entries (Run keys)
  | Key Path | Value Name | Data |
  | --- | --- | --- |
  | ...\Run | SecurityHealth | %ProgramFiles%\Windows Defender\...

  ## Key Tree (Sample)
  ```
- **Edge cases:** Corrupted hives, encrypted values (DPAPI), very large hives

### 4. Windows LNK & Jump List Extractors (`windows_lnk.py`)

#### LnkExtractor

- **File types:** `.lnk`
- **Library:** Manual binary parsing (LNK format is well-documented)
- **Parsing approach:**
  - Parse LNK binary format: Header, LinkInfo, StringData, ExtraData
  - Extract: target path, working directory, command line arguments, icon location
  - Extract timestamps: creation time, access time, modification time (FILETIME)
  - Extract MAC address from MachineID in ExtraData (if present)
  - Extract volume serial number, drive type
- **Markdown output:**
  ```
  # Windows Shortcut Analysis: `document.lnk`
  **Target Path:** C:\Users\john\Documents\report.docx
  **Working Directory:** C:\Users\john\Documents
  **Arguments:** (none)
  **Description:** Microsoft Word Document

  ## Timestamps
  | Type | Timestamp |
  | --- | --- |
  | Created | 2024-01-10 09:15:30 |
  | Modified | 2024-01-14 16:45:22 |
  | Accessed | 2024-01-15 10:30:00 |

  ## Target Information
  **Volume:** C:\ (Fixed Drive)
  **Volume Serial:** ABCD-1234

  ## Machine Info
  **Machine ID:** DESKTOP-ABC123
  **MAC Address:** AA:BB:CC:DD:EE:FF
  ```
- **Edge cases:** Network LNK targets, special folder targets, malformed LNK files

#### JumplistExtractor

- **File types:** `.automaticDestinations-ms`, `.customDestinations-ms`
- **Library:** `olefile` + manual LNK parsing
- **Parsing approach:**
  - Automatic Destinations: OLE2 compound documents containing LNK streams
  - Custom Destinations: Binary format with embedded LNK entries
  - Parse each embedded LNK entry using LnkExtractor logic
  - Extract application ID and destination list
- **Markdown output:**
  ```
  # Jump List Analysis: `b39a4a3e6e8f9b12.automaticDestinations-ms`
  **Application ID:** b39a4a3e6e8f9b12
  **Application:** Microsoft Word (identified from AppID)
  **Type:** Automatic Destination
  **Entry Count:** 15

  ## Recent Documents
  | # | Target Path | Last Modified |
  | --- | --- | --- |
  | 1 | C:\Users\john\report.docx | 2024-01-15 10:30 |
  | 2 | C:\Users\john\data.xlsx | 2024-01-14 16:45 |
  ```
- **Edge cases:** Corrupted Jump Lists, unknown AppIDs

### 5. Browser History Extractors (`browser_history.py`)

#### ChromeHistoryExtractor

- **File types:** `chrome_history` (directory containing `History` SQLite DB)
- **Library:** `sqlite3` (standard library)
- **Parsing approach:**
  - Open `History` database in read-only mode
  - Query `urls` table: url, title, visit_count, last_visit_time
  - Query `downloads` table: target_path, start_time, total_bytes
  - Chrome timestamps are WebKit format (microseconds since 1601-01-01), convert to Unix
  - Sample first N entries (default 200)
- **Markdown output:**
  ```
  # Chrome Browser History Summary
  **Total URLs:** 5,678
  **Total Downloads:** 23
  **Time Range:** 2024-01-01 ~ 2024-01-15

  ## Top Sites (by visit count)
  | URL | Title | Visits | Last Visit |
  | --- | --- | --- | --- |
  | https://google.com | Google | 156 | 2024-01-15 |
  | https://github.com | GitHub | 89 | 2024-01-14 |

  ## Recent Downloads
  | File | URL | Time | Size |
  | --- | --- | --- | --- |
  | report.pdf | https://example.com/report.pdf | 2024-01-15 10:30 | 1.2 MB |
  ```
- **Edge cases:** Locked database (Chrome running), corrupted History, empty history

#### FirefoxHistoryExtractor

- **File types:** `firefox_history` (directory containing `places.sqlite`)
- **Library:** `sqlite3` (standard library)
- **Parsing approach:**
  - Open `places.sqlite` in read-only mode
  - Query `moz_places` + `moz_historyvisits` for URL history
  - Query `moz_bookmarks` for bookmarks
  - Firefox timestamps are Unix epoch microseconds
  - Sample first N entries (default 200)
- **Markdown output:** Similar to ChromeHistoryExtractor
- **Edge cases:** WAL journal files, locked database, profiles with no history

### 6. Linux System Log Extractors (`linux_journal.py`)

#### JournalExtractor

- **File types:** `.journal` (systemd journal binary files)
- **Library:** Manual parsing or `python-systemd` (if available)
- **Parsing approach:**
  - Systemd journal files have a custom binary format
  - Parse journal header for metadata (file ID, machine ID, boot ID)
  - Iterate journal entries, extract timestamp, priority, message, unit
  - If `python-systemd` not available, attempt basic header parsing
  - Sample recent N entries (default 200)
- **Markdown output:**
  ```
  # Systemd Journal Summary: `system.journal`
  **Machine ID:** abc123def456
  **Boot ID:** 789ghi012jkl
  **Total Entries:** 12,345
  **Time Range:** 2024-01-01 ~ 2024-01-15

  ## Entry Distribution by Priority
  | Priority | Count | Description |
  | --- | --- | --- |
  | 0 (Emergency) | 2 | System is unusable |
  | 3 (Error) | 156 | Error conditions |
  | 6 (Info) | 10,000 | Informational |

  ## Recent Entries (Last 200)
  | Time | Priority | Unit | Message |
  | --- | --- | --- | --- |
  | 2024-01-15 10:30:00 | 6 | sshd | Accepted publickey for user |
  ```
- **Edge cases:** Compressed journals (lz4/zstd), sealed journals, very large journal directories

#### AuthLogExtractor

- **File types:** `.log` files matching auth.log pattern
- **Library:** Standard text parsing (regex)
- **Parsing approach:**
  - Parse syslog-format lines: `timestamp hostname process[pid]: message`
  - Focus on authentication events: SSH logins, sudo, su, PAM
  - Extract IP addresses, usernames, success/failure status
  - Build summary statistics
- **Markdown output:**
  ```
  # Authentication Log Summary: `auth.log`
  **Total Entries:** 2,345
  **Time Range:** 2024-01-01 ~ 2024-01-15

  ## Authentication Statistics
  | Event Type | Count |
  | --- | --- |
  | SSH Login Success | 89 |
  | SSH Login Failure | 156 |
  | Sudo Usage | 45 |
  | Su Usage | 12 |

  ## Login Attempts
  | Time | User | Source IP | Status | Service |
  | --- | --- | --- | --- | --- |
  | 2024-01-15 10:30 | john | 192.168.1.100 | SUCCESS | sshd |
  | 2024-01-15 10:31 | admin | 10.0.0.50 | FAILURE | sshd |
  ```
- **Note:** Since `.log` extension conflicts with TextExtractor, this extractor should be registered for specific filenames or patterns, not the generic `.log` extension. The extractor_mapping.json can map specific filenames.

#### WtmpExtractor

- **File types:** `wtmp`, `utmp`, `btmp` (binary login records)
- **Library:** `struct` (standard library) for binary parsing
- **Parsing approach:**
  - Parse utmp binary format (384 bytes per record on Linux)
  - Record types: EMPTY(0), RUN_LVL(1), BOOT_TIME(2), NEW_TIME(3), OLD_TIME(4), INIT_PROCESS(5), LOGIN_PROCESS(6), USER_PROCESS(7), DEAD_PROCESS(8), ACCOUNTING(9)
  - Extract: username, device, hostname, timestamp, PID
  - Filter for USER_PROCESS and LOGIN_PROCESS entries
- **Markdown output:**
  ```
  # Login Records Summary: `wtmp`
  **Total Records:** 567
  **Time Range:** 2024-01-01 ~ 2024-01-15

  ## Login Statistics
  | Type | Count |
  | --- | --- |
  | User Logins | 234 |
  | System Boots | 12 |
  | Dead Processes | 321 |

  ## User Login History
  | Time | User | Terminal | Host | PID |
  | --- | --- | --- | --- | --- |
  | 2024-01-15 10:30 | john | pts/0 | 192.168.1.100 | 1234 |
  | 2024-01-14 09:15 | root | pts/1 | :0 | 5678 |
  ```
- **Edge cases:** Corrupted records, different architectures (32-bit vs 64-bit utmp)

### 7. Android Backup Extractor (`android_backup.py`)

#### AndroidBackupExtractor

- **File types:** `.ab` (Android backup)
- **Library:** `zlib` + `tarfile` (standard library)
- **Parsing approach:**
  - Read Android backup header (24 bytes: magic, version, compression, encryption)
  - If not encrypted: decompress with zlib, parse inner tar archive
  - List files in backup with sizes
  - Identify important Android databases (contacts, SMS, call logs, apps)
  - If encrypted: report encryption status, cannot extract content
- **Markdown output:**
  ```
  # Android Backup Summary: `backup.ab`
  **Version:** 5
  **Compression:** zlib
  **Encryption:** None
  **Total Files:** 156

  ## Important Android Artifacts
  | Path | Size | Type |
  | --- | --- | --- |
  | apps/com.android.providers.contacts/db/contacts2.db | 45 KB | Contacts DB |
  | apps/com.android.providers.telephony/db/mmssms.db | 120 KB | SMS DB |
  | apps/com.android.providers.contacts/db/calllog.db | 8 KB | Call Log DB |

  ## File Listing (First 50)
  | Path | Size |
  | --- | --- |
  | apps/com.example.app/f1 | 1.2 MB |
  ```
- **Edge cases:** Encrypted backups (AES-256), corrupted headers, non-standard formats

### 8. E01 Metadata Extractor (`disk_image.py`)

#### E01MetadataExtractor

- **File types:** `.e01` (EnCase Evidence File)
- **Library:** `pyewf` (if available), fallback to header parsing
- **Parsing approach:**
  - Try `pyewf` for full metadata extraction
  - Extract: case number, evidence number, examiner, description, acquisition date
  - Extract: segment count, total size, compression method, hash values (MD5, SHA1)
  - Fallback: read E01 header magic bytes and parse basic fields
- **Markdown output:**
  ```
  # E01 Forensic Image Metadata: `evidence.E01`
  **Case Number:** 2024-001
  **Evidence Number:** HDD-001
  **Examiner:** John Smith
  **Description:** Suspect laptop hard drive

  ## Acquisition Details
  | Field | Value |
  | --- | --- |
  | Date | 2024-01-15 10:30:00 |
  | Platform | Windows |
  | Compression | Deflate |
  | Segments | 15 |

  ## Integrity Hashes
  | Algorithm | Hash |
  | --- | --- |
  | MD5 | abc123def456... |
  | SHA1 | 789ghi012jkl... |

  ## Image Statistics
  | Field | Value |
  | --- | --- |
  | Total Size | 500 GB |
  | Acquired Size | 480 GB |
  ```
- **Note:** This extractor reads metadata only, not file system content (that's the C++ ImageAnalyzer's job)

## Dependency Management

### New Dependencies (add to requirements.txt)

```python
# Forensic Format Parsing
python-evtx>=0.8.0        # Windows Event Log (.evtx)
python-registry>=1.3.0    # Windows Registry hives
olefile>=0.47             # OLE2 format (.msg, .jump lists)
# pyewf-python is optional, only needed for E01 metadata
```

### Standard Library Dependencies (no install needed)

- `email` - EML parsing
- `mailbox` - MBOX parsing
- `sqlite3` - Browser history databases
- `struct` - Binary format parsing (wtmp, LNK)
- `zlib` - Android backup decompression
- `tarfile` - Android backup inner archive
- `re` - Log file parsing
- `datetime` - Timestamp conversion

### Optional Dependencies

- `python-systemd` - Enhanced journal parsing (fallback to manual parsing)
- `pyewf` - Full E01 metadata (fallback to header-only parsing)
- `libpff` CLI tools - Full PST extraction (fallback to header parsing)

## Routing Mechanism Extension

The current `extractor_mapping.json` uses extension-based routing (e.g., `".pdf"` -> `PDFExtractor`). However, some forensic extractors need filename-based or directory-based routing (e.g., `auth.log`, `wtmp`, Chrome `History` database).

### Solution: Extend `__init__.py` loader

Add a new `"filename_routes"` section to `extractor_mapping.json`:

```json
{
    "MarkitdownExtractor": { ... },
    "EmlExtractor": [".eml"],
    "MsgExtractor": [".msg"],
    "MboxExtractor": [".mbox"],
    "PstExtractor": [".pst", ".ost"],
    "EvtxExtractor": [".evtx"],
    "RegistryExtractor": [".reg", ".dat", ".hiv"],
    "LnkExtractor": [".lnk"],
    "JumplistExtractor": [".automaticDestinations-ms", ".customDestinations-ms"],
    "JournalExtractor": [".journal"],
    "AndroidBackupExtractor": [".ab"],
    "E01MetadataExtractor": [".e01"],
    "_filename_routes": {
        "auth.log": "AuthLogExtractor",
        "auth.log.1": "AuthLogExtractor",
        "wtmp": "WtmpExtractor",
        "utmp": "WtmpExtractor",
        "btmp": "WtmpExtractor",
        "History": "ChromeHistoryExtractor",
        "places.sqlite": "FirefoxHistoryExtractor",
        "SAM": "RegistryExtractor",
        "SYSTEM": "RegistryExtractor",
        "SOFTWARE": "RegistryExtractor",
        "SECURITY": "RegistryExtractor",
        "DEFAULT": "RegistryExtractor",
        "NTUSER.DAT": "RegistryExtractor",
        "UsrClass.dat": "RegistryExtractor"
    }
}
```

### Changes to `__init__.py`

1. Add a `filename_extractor_registry` dict alongside `extractor_registry`
2. In `load_plugins()`, read `"_filename_routes"` and populate `filename_extractor_registry`
3. Add `get_extractor_by_filename(filename: str)` function
4. In the case_analysis pipeline (`file_analyzer.py`), try `get_extractor_by_filename()` first, then fall back to `get_extractor(extension)`

### Alternative: Extension-based for Browser History

For Chrome/Firefox history, the pipeline can detect the directory structure and extract the `History`/`places.sqlite` file, then route based on the known filename pattern. This keeps the extension-based system clean.

## Testing Strategy

Each extractor should have:
1. **Unit test** with sample file (if available) or mock data
2. **Error handling test** for missing/corrupted files
3. **Edge case test** for empty files, oversized files

Test files to create or obtain:
- Sample EML file (can generate with Python)
- Sample EVTX file (Windows system export)
- Sample Registry hive (Windows export)
- Sample LNK file (Windows shortcut)
- Sample wtmp file (Linux `/var/log/wtmp` copy)
- Sample Chrome History SQLite database

## Implementation Order

**Phase 1 - Email (highest forensic value, pure Python):**
1. EmlExtractor (standard library, simplest)
2. MsgExtractor (olefile dependency)
3. MboxExtractor (standard library)

**Phase 2 - Windows Artifacts (high value, requires libraries):**
4. EvtxExtractor (python-evtx)
5. RegistryExtractor (python-registry)
6. LnkExtractor (manual parsing)
7. JumplistExtractor (olefile + manual)

**Phase 3 - Browser & Linux:**
8. ChromeHistoryExtractor (sqlite3)
9. FirefoxHistoryExtractor (sqlite3)
10. AuthLogExtractor (text parsing)
11. WtmpExtractor (struct)
12. JournalExtractor (manual/subprocess)

**Phase 4 - Remaining:**
13. AndroidBackupExtractor (zlib + tar)
14. E01MetadataExtractor (pyewf optional)
15. PstExtractor (libpff optional)

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| python-evtx parsing errors on malformed EVTX | Medium | Wrap in try/catch, return partial results |
| MSG format complexity (OLE2 nested structures) | Medium | Use olefile's robust OLE2 parser, handle missing streams |
| PST format too complex for pure Python | Low | Document limitation, recommend pffexport CLI |
| Browser history DB locked by running browser | Medium | Use read-only URI mode, copy file if needed |
| Large files causing memory issues | High | Implement streaming/chunked parsing, enforce sample limits |
| Extension conflicts (.dat could be many things) | Medium | Check file magic bytes before parsing, fallback gracefully |
