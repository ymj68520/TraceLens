# 数据流架构

## 1. 概述

本文档详细描述 ForensicsProject 中的数据流架构，包括取证分析管道、HTTP 服务数据流、知识图谱集成和 LLM 分析流程。

---

## 2. 核心取证分析管道

### 2.1 四步分析管道

```mermaid
flowchart LR
    A[磁盘镜像<br/>E01/DD/RAW] --> B[步骤1: 镜像分析<br/>ImageAnalyzer]
    B --> C[_raw.db<br/>原始元数据]

    C --> D[步骤2: 事件提取<br/>EventExtractor]
    D --> E[_events.db<br/>时间线]

    C --> F[步骤3: 文件分类<br/>FileClassifier]
    F --> G[_files.db<br/>分类文件]

    G --> H[步骤4: 平台分析<br/>PlatformAnalyzers]
    H --> I[_android.db<br/>_windows.db<br/>_linux.db]

    G --> J[LLM 分析<br/>LLMIntegration]
    I --> J

    style A fill:#ffebee
    style C fill:#e8f5e9
    style E fill:#fff3e0
    style G fill:#e3f2fd
    style I fill:#f3e5f5
```

### 2.2 详细数据流图

```mermaid
sequenceDiagram
    participant User
    participant Main
    participant ImageAnalyzer
    participant TSK
    participant DBManager
    participant EventExtractor
    participant FileClassifier
    participant AndroidAnalyzer
    participant LLMService

    User->>Main: ./forensic_analyzer evidence.E01

    rect rgb(200, 230, 201)
        Note over ImageAnalyzer,DBManager: 步骤1: 镜像分析
        Main->>ImageAnalyzer: analyze(evidence.E01)
        ImageAnalyzer->>TSK: tsk_img_open(image_path)
        TSK-->>ImageAnalyzer: Image Handle
        loop 遍历文件系统
            ImageAnalyzer->>TSK: tsk_fs_file_open(meta)
            TSK-->>ImageAnalyzer: File Metadata
            ImageAnalyzer->>DBManager: INSERT INTO files
        end
        ImageAnalyzer-->>Main: _raw.db 生成完成
    end

    rect rgb(255, 243, 224)
        Note over EventExtractor,DBManager: 步骤2: 事件提取
        Main->>EventExtractor: extract_events(_raw.db)
        EventExtractor->>DBManager: SELECT * FROM files
        loop 遍历文件
            EventExtractor->>EventExtractor: analyze_timestamps()
            EventExtractor->>DBManager: INSERT INTO events
        end
        EventExtractor-->>Main: _events.db 生成完成
    end

    rect rgb(227, 242, 253)
        Note over FileClassifier,DBManager: 步骤3: 文件分类
        Main->>FileClassifier: classify(_raw.db)
        FileClassifier->>DBManager: SELECT * FROM files
        loop 遍历文件
            FileClassifier->>FileClassifier: determine_category(extension)
            FileClassifier->>DBManager: INSERT INTO {category}_table
        end
        FileClassifier-->>Main: _files.db 生成完成
    end

    rect rgb(243, 229, 245)
        Note over AndroidAnalyzer,DBManager: 步骤4a: Android 分析
        Main->>AndroidAnalyzer: analyze_android(_files.db)
        AndroidAnalyzer->>DBManager: SELECT * FROM documents WHERE ext='.db'
        loop 解析 Android 数据库
            AndroidAnalyzer->>AndroidAnalyzer: parse_sms_database()
            AndroidAnalyzer->>DBManager: INSERT INTO android.sms
            AndroidAnalyzer->>AndroidAnalyzer: parse_contacts_database()
            AndroidAnalyzer->>DBManager: INSERT INTO android.contacts
        end
        AndroidAnalyzer-->>Main: _android.db 生成完成
    end

    rect rgb(255, 224, 178)
        Note over LLMService,DBManager: 步骤4b: LLM 分析
        Main->>LLMService: batch_analyze(_files.db)
        LLMService->>DBManager: SELECT * FROM documents WHERE llm_analyzed_at IS NULL
        loop 分析文件
            LLMService->>LLMService: extract_content(file_path)
            LLMService->>LLMService: call_llm_api(content)
            LLMService-->>LLMService: summary, description, keywords
            LLMService->>DBManager: UPDATE documents SET llm_summary=...
        end
        LLMService-->>Main: LLM 分析完成
    end

    Main-->>User: 分析完成，生成 5 个数据库
```

---

## 3. 镜像分析数据流

### 3.1 ImageAnalyzer 流程

```mermaid
flowchart TD
    Start([开始]) --> Open[打开磁盘镜像]
    Open --> CheckFormat{检查格式}

    CheckFormat -->|E01| EWF[libewf 处理]
    CheckFormat -->|DD/RAW| RAW[直接读取]
    CheckFormat -->|其他| Error[错误: 不支持]

    EWF --> OpenImg[tsk_img_open]
    RAW --> OpenImg

    OpenImg --> GetVol[获取卷列表]
    GetVol --> LoopVol{遍历卷}

    LoopVol -->|下一个卷| OpenFs[tsk_fs_open]
    OpenFs --> CheckFS{文件系统?}

    CheckFS -->|NTFS| NTFS[NTFS 解析]
    CheckFS -->|FAT| FAT[FAT 解析]
    CheckFS -->|EXT| EXT[EXT 解析]
    CheckFS -->|XFS| XFS[XFS 解析]

    NTFS --> WalkRoot[遍历根目录]
    FAT --> WalkRoot
    EXT --> WalkRoot
    XFS --> WalkRoot

    WalkRoot --> WalkDir{遍历目录}

    WalkDir -->|子目录| Recurse[递归遍历]
    Recurse --> WalkDir

    WalkDir -->|文件| GetMeta[获取元数据]
    GetMeta --> InsertDB[插入数据库]
    InsertDB --> WalkDir

    WalkDir -->|完成| LoopVol

    LoopVol -->|所有卷| Close[关闭句柄]
    Close --> End([结束])

    style Start fill:#c8e6c9
    style End fill:#ffcdd2
    style OpenImg fill:#bbdefb
    style InsertDB fill:#fff9c4
```

### 3.2 元数据提取流程

```mermaid
flowchart LR
    A[TSK 文件元数据] --> B[提取基本属性]
    A --> C[提取时间戳]
    A --> D[提取文件类型]
    A --> E[提取删除状态]

    B --> F[文件名/路径<br/>大小/权限<br/>UID/GID<br/>inode 号]

    C --> G[访问时间 atime<br/>修改时间 mtime<br/>变更时间 ctime<br/>创建时间 crtime]

    D --> H[文件类型<br/>mode_t 标志]

    E --> I[删除标志<br/>未分配标志]

    F --> J[构建 FileRecord]
    G --> J
    H --> J
    I --> J

    J --> K[插入 _raw.db<br/>files 表]

    style A fill:#e3f2fd
    style J fill:#fff9c4
    style K fill:#c8e6c9
```

---

## 4. 事件提取数据流

### 4.1 EventExtractor 转换逻辑

```mermaid
flowchart TD
    A[从 _raw.db<br/>读取文件] --> B{分析时间戳}

    B --> C[创建时间检测<br/>crtime > 0<br/>且 != mtime]
    B --> D[修改时间检测<br/>mtime 存在]
    B --> E[访问时间检测<br/>atime 存在<br/>且 != mtime]
    B --> G[删除事件检测<br/>deleted=true]

    C --> F[生成 CREATED 事件]
    D --> H[生成 MODIFIED 事件]
    E --> I[生成 ACCESSED 事件]
    G --> J[生成 DELETED 事件]

    F --> K[插入 events 表]
    H --> K
    I --> K
    J --> K

    K --> L[插入专用表<br/>creation_events<br/>modification_events<br/>access_events<br/>deletion_events]

    style A fill:#e3f2fd
    style K fill:#fff9c4
    style L fill:#c8e6c9
```

### 4.2 事件数据结构

**原始文件元数据 (_raw.db/files)**：
```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    size INTEGER,
    type TEXT,
    deleted INTEGER DEFAULT 0,
    atime INTEGER,  -- 访问时间
    mtime INTEGER,  -- 修改时间
    ctime INTEGER,  -- 变更时间
    crtime INTEGER  -- 创建时间
);
```

**时间线事件 (_events.db/events)**：
```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    timestamp INTEGER NOT NULL,
    event_type TEXT NOT NULL,  -- CREATED/MODIFIED/ACCESSED/DELETED
    file_id INTEGER,
    description TEXT,
    source_type TEXT,  -- filesystem/android/windows/linux
    metadata TEXT
);
```

**事件转换示例**：
```json
// 输入：原始文件
{
  "id": 1,
  "path": "/Users/john/Documents/report.docx",
  "name": "report.docx",
  "size": 1048576,
  "deleted": 0,
  "atime": 1705388400,  // 2024-01-15 10:00:00
  "mtime": 1705388400,
  "ctime": 1705388400,
  "crtime": 1705380000  // 2024-01-15 08:00:00
}

// 输出：时间线事件（3 个事件）
[
  {
    "timestamp": 1705380000,
    "event_type": "CREATED",
    "file_id": 1,
    "description": "Created report.docx",
    "source_type": "filesystem"
  },
  {
    "timestamp": 1705388400,
    "event_type": "MODIFIED",
    "file_id": 1,
    "description": "Modified report.docx",
    "source_type": "filesystem"
  },
  {
    "timestamp": 1705388400,
    "event_type": "ACCESSED",
    "file_id": 1,
    "description": "Accessed report.docx",
    "source_type": "filesystem"
  }
]
```

---

## 5. 文件分类数据流

### 5.1 FileClassifier 逻辑

```mermaid
flowchart TD
    A[从 _raw.db<br/>读取文件] --> B[获取扩展名]

    B --> C{扩展名<br/>映射}

    C -->|图片| D[images<br/>.jpg/.png/.gif/.bmp]
    C -->|视频| E[videos<br/>.mp4/.avi/.mkv/.mov]
    C -->|音频| F[audio_files<br/>.mp3/.wav/.aac/.flac]
    C -->|文档| G[documents<br/>.pdf/.doc/.docx/.txt/.rtf]
    C -->|压缩包| H[archives<br/>.zip/.tar/.gz/.7z/.rar]
    C -->|可执行文件| I[executables<br/>.exe/.dll/.so/.dylib/.app]
    C -->|数据库| J[databases<br/>.db/.sqlite/.mdb/.accdb]
    C -->|源代码| K[source_code<br/>.c/.cpp/.h/.py/.js/.java]
    C -->|Web 文件| L[web_files<br/>.html/.css/.js/.php/.asp]
    C -->|邮件| M[email_files<br/>.eml/.msg/.pst/.ost]
    C -->|系统文件| N[system_files<br/>.sys/.dll/.ini/.cfg]
    C -->|加密文件| O[encrypted_files<br/>.gpg/.pgp/.enc]
    C -->|其他| P[unknown_files]

    D --> Q[插入对应表]
    E --> Q
    F --> Q
    G --> Q
    H --> Q
    I --> Q
    J --> Q
    K --> Q
    L --> Q
    M --> Q
    N --> Q
    O --> Q
    P --> Q

    style A fill:#e3f2fd
    style C fill:#fff9c4
    style Q fill:#c8e6c9
```

### 5.2 扩展名映射表

| 类别 | 扩展名 | 表名 |
|------|--------|------|
| **图片** | .jpg, .jpeg, .png, .gif, .bmp, .tiff, .webp, .svg | images |
| **视频** | .mp4, .avi, .mkv, .mov, .wmv, .flv, .webm | videos |
| **音频** | .mp3, .wav, .aac, .flac, .ogg, .wma | audio_files |
| **文档** | .pdf, .doc, .docx, .xls, .xlsx, .ppt, .pptx, .txt, .rtf, .odt | documents |
| **压缩包** | .zip, .tar, .gz, .7z, .rar, .bz2, .xz | archives |
| **可执行文件** | .exe, .dll, .so, .dylib, .app, .elf | executables |
| **数据库** | .db, .sqlite, .sqlite3, .mdb, .accdb | databases |
| **源代码** | .c, .cpp, .h, .hpp, .py, .js, .java, .go, .rs | source_code |
| **Web 文件** | .html, .htm, .css, .js, .php, .asp, .jsp | web_files |
| **邮件** | .eml, .msg, .pst, .ost, .mbox | email_files |
| **系统文件** | .sys, .dll, .ini, .cfg, .conf, .log | system_files |
| **加密文件** | .gpg, .pgp, .enc, .encrypted | encrypted_files |
| **其他** | 所有其他扩展名 | unknown_files |

---

## 6. 平台分析数据流

### 6.1 Android 分析流程

```mermaid
flowchart TD
    A[从 _files.db<br/>读取文档] --> B{查找 Android<br/>数据库文件}

    B --> C[contacts2.db<br/>联系人]
    B --> D[mmssms.db<br/>短信/MMS]
    B --> E[calllog.db<br/>通话记录]
    B --> F[usage stat.db<br/>应用使用]

    C --> C1[解析 contacts<br/>data 表]
    C1 --> C2[插入 _android.db<br/>contacts 表]

    D --> D1[解析 sms<br/>address/body/date]
    D1 --> D2[插入 _android.db<br/>sms 表]

    E --> E1[解析 calls<br/>number/duration/date]
    E1 --> E2[插入 _android.db<br/>call_logs 表]

    F --> F1[解析 usage stats<br/>package_name/foreground_time]
    F1 --> F2[插入 _android.db<br/>app_usage 表]

    style A fill:#e3f2fd
    style B fill:#fff9c4
    style C fill:#fce4ec
    style D fill:#e1bee7
    style E fill:#f8bbd0
    style F fill:#e6ee9c
```

**Android 数据库路径映射**：
| 数据库类型 | 典型路径 | 表名 |
|-----------|---------|------|
| 联系人 | `/data/data/com.android.providers.contacts/databases/contacts2.db` | contacts |
| 短信/MMS | `/data/data/com.android.providers.telephony/databases/mmssms.db` | sms, mms |
| 通话记录 | `/data/data/com.android.providers.contacts/databases/calllog.db` | call_logs |
| 应用使用 | `/data/system/usagestats/` | app_usage |

### 6.2 Windows 分析流程

```mermaid
flowchart TD
    A[从 _files.db<br/>读取文件] --> B{查找 Windows<br/>工件文件}

    B --> C[注册表配置单元<br/>.SAM/.SYSTEM/.SOFTWARE]
    B --> D[事件日志<br/>.evtx 文件]
    B --> E[浏览器历史<br/>.sqlite/.dat]
    B --> F[预读取<br/>.pf]
    B --> G[跳列表<br/>.lnk/.customDestinations-ms]
    B --> H[SRUM<br/>.sdb]
    B --> I[Amcache<br/>.hive]

    C --> C1[使用 libhivex<br/>解析注册表]
    C1 --> C2[插入 _windows.db<br/>registry_keys/values]

    D --> D1[使用 libevtx<br/>解析事件日志]
    D1 --> D2[插入 _windows.db<br/>event_logs]

    E --> E1[解析浏览器<br/>历史记录]
    E1 --> E2[插入 _windows.db<br/>browser_history]

    F --> F1[解析预读取<br/>元数据]
    F1 --> F2[插入 _windows.db<br/>prefetch]

    G --> G1[解析跳列表<br/>.lnk 文件]
    G1 --> G2[插入 _windows.db<br/>jump_lists]

    H --> H1[解析 SRUM<br/>数据库]
    H1 --> H2[插入 _windows.db<br/>srum_data]

    I --> I1[解析 Amcache<br/>注册表]
    I1 --> I2[插入 _windows.db<br/>amcache]

    style A fill:#e3f2fd
    style B fill:#fff9c4
    style C fill:#c8e6c9
    style D fill:#ffcdd2
    style E fill:#ffccbc
```

**Windows 工件路径映射**：
| 工件类型 | 典型路径 | 解析库 |
|---------|---------|--------|
| 注册表 SAM | `C:/Windows/System32/config/SAM` | libhivex |
| 注册表 SYSTEM | `C:/Windows/System32/config/SYSTEM` | libhivex |
| 注册表 SOFTWARE | `C:/Windows/System32/config/SOFTWARE` | libhivex |
| 注册表 NTUSER | `C:/Users/{user}/NTUSER.DAT` | libhivex |
| 事件日志 | `C:/Windows/System32/winevt/Logs/*.evtx` | libevtx |
| Chrome 历史 | `C:/Users/{user}/AppData/Local/Google/Chrome/User Data/Default/History` | SQLite |
| Firefox 历史 | `C:/Users/{user}/AppData/Roaming/Mozilla/Firefox/Profiles/*.default/places.sqlite` | SQLite |
| 预读取 | `C:/Windows/Prefetch/*.pf` | 自定义解析器 |
| 跳列表 | `C:/Users/{user}/AppData/Roaming/Microsoft/Windows/Recent/*.lnk` | 自定义解析器 |
| SRUM | `C:/Windows/System32/sru/SRUDB.dat` | 自定义解析器 |
| Amcache | `C:/Windows/AppCompat/Programs/Amcache.hve` | libhivex |

### 6.3 Linux 分析流程

```mermaid
flowchart TD
    A[从 _files.db<br/>读取文件] --> B{查找 Linux<br/>工件文件}

    B --> C[系统日志<br/>/var/log/*]
    B --> D[用户账户<br/>/etc/passwd,/etc/shadow]
    B --> E[Shell 历史<br/>/.bash_history,/.zsh_history]
    B --> F[认证日志<br/>/var/log/auth.log]
    B --> G[Cron 任务<br/>/etc/crontab,/var/spool/cron/*]

    C --> C1[解析 syslog<br/>格式日志]
    C1 --> C2[插入 _linux.db<br/>system_logs]

    D --> D1[解析用户账户<br/>/etc/passwd 格式]
    D1 --> D2[插入 _linux.db<br/>user_accounts]

    E --> E1[解析 Shell<br/>历史命令]
    E1 --> E2[插入 _linux.db<br/>shell_history]

    F --> F1[解析认证<br/>事件日志]
    F1 --> F2[插入 _linux.db<br/>auth_data]

    G --> G1[解析 Cron<br/>任务配置]
    G1 --> G2[插入 _linux.db<br/>cron_jobs]

    style A fill:#e3f2fd
    style B fill:#fff9c4
    style C fill:#c8e6c9
    style D fill:#ffcdd2
    style E fill:#ffccbc
```

---

## 7. LLM 分析数据流

### 7.1 批量分析流程

```mermaid
sequenceDiagram
    participant Main
    participant LLMService
    participant FileExtractor
    participant LLMClient
    participant LMStudio
    participant DBManager

    Main->>LLMService: batch_analyze(task_id, "documents")

    LLMService->>DBManager: SELECT * FROM documents WHERE llm_analyzed_at IS NULL LIMIT 100

    loop 批量处理文件
        DBManager-->>LLMService: 文件列表

        par 并行提取（5 个线程）
            LLMService->>FileExtractor: extract_content(file1)
            FileExtractor-->>LLMService: 文本内容
        and
            LLMService->>FileExtractor: extract_content(file2)
            FileExtractor-->>LLMService: 文本内容
        and
            LLMService->>FileExtractor: extract_content(file3)
            FileExtractor-->>LLMService: 文本内容
        end

        LLMService->>LLMClient: analyze(file1_content, "document.pdf")
        LLMClient->>LMStudio: POST /v1/chat/completions
        LMStudio-->>LLMClient: {"summary": "...", "description": "...", "keywords": [...]}
        LLMClient-->>LLMService: 分析结果

        LLMService->>DBManager: UPDATE documents SET llm_summary=..., llm_analyzed_at=... WHERE id=1
    end

    LLMService-->>Main: 批量分析完成，已处理 100 个文件
```

### 7.2 LLM 分析数据结构

**分析请求**：
```json
{
  "content": "这是一份保密协议，甲方与乙方同意...",
  "max_tokens": 1000,
  "model_type": "text",
  "extract": {
    "summary": true,
    "description": true,
    "keywords": true
  }
}
```

**分析响应**：
```json
{
  "success": true,
  "summary": "保密协议文档",
  "description": "这是一份甲方与乙方的保密协议，规定了双方在合作期间的保密义务...",
  "keywords": ["保密", "协议", "合同", "法律责任"],
  "model_used": "qwen2.5:7b",
  "tokens_used": 500,
  "analyzed_at": "2024-01-16T10:00:00Z"
}
```

**数据库更新**：
```sql
UPDATE documents
SET
    llm_summary = '保密协议文档',
    llm_description = '这是一份甲方与乙方的保密协议...',
    llm_keywords = '保密,协议,合同,法律责任',
    llm_analyzed_at = 1705388400,
    llm_model_used = 'qwen2.5:7b'
WHERE id = 1;
```

---

## 8. 知识图谱集成数据流

### 8.1 Graphiti 数据摄取流程

```mermaid
sequenceDiagram
    participant PythonClient
    participant GraphitiIngestor
    participant DatabaseReader
    participant SQLite
    participant TOONTransformer
    participant LLMClient
    participant Neo4j

    PythonClient->>GraphitiIngestor: ingest(task_id, include_llm=true)

    GraphitiIngestor->>DatabaseReader: get_file_reader(task_id)
    DatabaseReader->>SQLite: ATTACH DATABASE _files.db
    DatabaseReader-->>GraphitiIngestor: FilesDatabaseReader

    loop 批量读取文件
        GraphitiIngestor->>DatabaseReader: read_batch(batch_size=50)
        DatabaseReader->>SQLite: SELECT * FROM documents LIMIT 50 OFFSET 0
        SQLite-->>DatabaseReader: 文件记录
        DatabaseReader-->>GraphitiIngestor: List[FileRecord]

        GraphitiIngestor->>TOONTransformer: to_episode_data(FileRecord)
        TOONTransformer->>LLMClient: generate_summary(FileRecord)
        LLMClient-->>TOONTransformer: summary
        TOONTransformer-->>GraphitiIngestor: EpisodeData

        GraphitiIngestor->>GraphitiIngestor: add_episode(EpisodeData)
    end

    GraphitiIngestor->>Neo4j: 批量写入实体和关系
    Neo4j-->>GraphitiIngestor: 写入完成

    GraphitiIngestor-->>PythonClient: 摄取完成，200 个实体，400 个关系
```

### 8.2 数据转换流程

**FileRecord → EpisodeData**：
```json
// 输入：FileRecord
{
  "id": 1,
  "name": "contract.pdf",
  "path": "/Users/john/Documents/contract.pdf",
  "size": 1048576,
  "category": "documents",
  "llm_summary": "法律合同文档",
  "llm_description": "甲方与乙方的服务合同...",
  "llm_keywords": ["合同", "法律", "服务"],
  "mtime": 1705388400
}

// 输出：EpisodeData
{
  "episode_id": "ep-1",
  "name": "contract.pdf",
  "summary": "法律合同文档",
  "summary_embedding": [0.1, 0.2, ...],
  "source": "ForensicsProject",
  "source_description": "Digital forensics analysis",
  "valid_at": 1705388400,
  "created_at": 1705400000,
  "observations": [
    {
      "name": "contract.pdf",
      "entity_type": "FILE",
      "attributes": {
        "file_path": "/Users/john/Documents/contract.pdf",
        "size": 1048576,
        "category": "documents"
      }
    },
    {
      "name": "/Users/john/Documents",
      "entity_type": "LOCATION",
      "attributes": {
        "directory": true
      }
    },
    {
      "name": "法律",
      "entity_type": "KEYWORD",
      "attributes": {}
    }
  ],
  "relationships": [
    {
      "source": "contract.pdf",
      "target": "/Users/john/Documents",
      "type": "LOCATED_AT",
      "attributes": {
        "confidence": 1.0
      }
    },
    {
      "source": "contract.pdf",
      "target": "法律",
      "type": "HAS_KEYWORD",
      "attributes": {
        "confidence": 0.95
      }
    }
  ]
}
```

### 8.3 Neo4j 图谱模式

```mermaid
graph TD
    subgraph "实体类型 Entity Types"
        FILE[FILE<br/>文件]
        LOCATION[LOCATION<br/>位置]
        KEYWORD[KEYWORD<br/>关键词]
        PERSON[PERSON<br/>人物]
        DATE[DATE<br/>日期]
    end

    subgraph "关系类型 Relationship Types"
        LOCATED_AT[LOCATED_AT<br/>位于]
        HAS_KEYWORD[HAS_KEYWORD<br/>包含关键词]
        CREATED_BY[CREATED_BY<br/>创建者]
        MODIFIED_ON[MODIFIED_ON<br/>修改日期]
        REFERENCES[REFERENCES<br/>引用]
    end

    FILE --> LOCATED_AT --> LOCATION
    FILE --> HAS_KEYWORD --> KEYWORD
    FILE --> CREATED_BY --> PERSON
    FILE --> MODIFIED_ON --> DATE

    style FILE fill:#e3f2fd
    style LOCATION fill:#fff9c4
    style KEYWORD fill:#ffcdd2
    style PERSON fill:#c8e6c9
    style DATE fill:#ffccbc
```

---

## 9. HTTP 服务数据流

### 9.1 C++ 服务请求处理

```mermaid
sequenceDiagram
    participant Client
    participant CrowServer
    participant Router
    participant TaskManager
    participant ThreadPool
    participant Worker
    participant DBManager

    Client->>CrowServer: POST /tasks (创建任务)
    CrowServer->>Router: 路由解析
    Router->>TaskManager: handle_create_task(request)

    TaskManager->>TaskManager: 生成 task_id
    TaskManager->>DBManager: INSERT INTO tasks

    TaskManager->>ThreadPool: submit(analysis_job)
    ThreadPool->>Worker: 分配工作线程

    par 异步执行分析
        Worker->>Worker: ImageAnalyzer::analyze()
        Worker->>Worker: EventExtractor::extract()
        Worker->>Worker: FileClassifier::classify()
        Worker->>DBManager: 更新任务状态
    end

    TaskManager-->>CrowServer: {"task_id": "task_123"}
    CrowServer-->>Client: HTTP 201 Created

    Note over Client,Worker: 后台任务继续执行...

    Client->>CrowServer: GET /api/tasks/task_123/progress
    CrowServer->>TaskManager: get_progress(task_123)
    TaskManager-->>CrowServer: {"progress": 45, "phase": "FILE_CLASSIFICATION"}
    CrowServer-->>Client: {"progress": 45, "phase": "FILE_CLASSIFICATION"}
```

### 9.2 Python 服务请求处理

```mermaid
sequenceDiagram
    participant Client
    participant FastAPI
    participant ServiceManager
    participant GraphitiService
    participant CppBackend
    participant Neo4j

    Client->>FastAPI: POST /api/graphiti/ingest
    FastAPI->>ServiceManager: get_service_manager()
    ServiceManager-->>FastAPI: ServiceManager 实例

    FastAPI->>GraphitiService: ingest(task_id)
    GraphitiService->>CppBackend: GET /api/system/databases?task_id=xxx
    CppBackend-->>GraphitiService: 数据库列表

    GraphitiService->>GraphitiService: 创建 GraphitiIngestor

    loop 批量摄取
        GraphitiService->>GraphitiService: 读取文件批次
        GraphitiService->>GraphitiService: 调用本地 LLM
        GraphitiService->>Neo4j: 写入实体和关系
    end

    GraphitiService-->>FastAPI: {"job_id": "job_123", "status": "running"}
    FastAPI-->>Client: HTTP 202 Accepted
```

### 9.3 服务间通信

```mermaid
flowchart LR
    A[客户端请求] --> B{请求类型}

    B -->|任务管理| C[C++ Server<br/>:8080]
    B -->|取证分析| C
    B -->|全文搜索| C
    B -->|系统监控| C

    B -->|知识图谱| D[Python Server<br/>:8090]
    B -->|LLM 分析| D
    B -->|数据库导出| D

    C --> E[(SQLite<br/>取证数据库)]
    D --> E
    D --> F[(Neo4j<br/>知识图谱)]

    C -.后台同步.-> D
    D -.HTTP 调用.-> C

    style A fill:#e1f5fe
    style C fill:#c8e6c9
    style D fill:#ffccbc
    style E fill:#fff9c4
    style F fill:#f8bbd0
```

---

## 10. 数据导出流

### 10.1 TOON 格式导出

```mermaid
flowchart LR
    A[数据库查询] --> B[FileReader<br/>读取记录]
    B --> C[TOONTransformer<br/>转换为 TOON]
    C --> D[TOONExporter<br/>格式化输出]

    D --> E{输出目标}

    E -->|HTTP 响应| F[JSON 响应<br/>带 toon 字段]
    E -->|文件导出| G[.toon 文件]

    F --> H[客户端接收]
    G --> I[磁盘存储]

    style A fill:#e3f2fd
    style C fill:#fff9c4
    style F fill:#c8e6c9
    style G fill:#ffccbc
```

**TOON 格式示例**：
```
TOON.schema: name | path | category | size | mtime | llm_summary | llm_keywords
# records[2]
contract.pdf | /docs/contract.pdf | documents | 1048576 | 1705388400 | 法律合同 | 合同,法律
report.docx | /docs/report.docx | documents | 2048576 | 1705390000 | 年度报告 | 报告,年度
```

### 10.2 JSON 格式导出

```json
{
  "success": true,
  "format": "json",
  "data": [
    {
      "name": "contract.pdf",
      "path": "/docs/contract.pdf",
      "category": "documents",
      "size": 1048576,
      "mtime": 1705388400,
      "llm_summary": "法律合同",
      "llm_keywords": ["合同", "法律"]
    }
  ],
  "count": 1
}
```

---

## 相关文档

- **[架构总览](./Overview.md)** - 系统整体架构
- **[数据库模式](./DatabaseSchema.md)** - 数据库表结构
- **[LLM 集成](../modules/cpp/integration/LLMIntegration.md)** - LLM 服务集成
- **[知识图谱集成](../modules/python/graphiti_integration/GraphitiIngestor.md)** - Graphiti 数据摄取

---

**最后更新**: 2026-03-11
**维护者**: ymj68520
