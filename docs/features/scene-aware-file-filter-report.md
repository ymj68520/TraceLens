# 场景特化文件过滤系统 — 技术集成报告

> **文档版本**: 1.0
> **生成日期**: 2026-06-13
> **适用产品**: Digital Forensics Image Analyzer
> **模块版本**: FileFilter v1.0.0 / FilterProfiles v1.0.0

---

## 一、概述

### 1.1 背景

在电子取证实战中，不同案件类型关注的数据范围差异显著。电信诈骗案件需要聚焦通讯录与即时通讯记录，数据泄露案件需要追踪文档与数据库，病毒入侵案件则重点关注可执行文件与持久化机制。对磁盘镜像执行全量分析不仅浪费时间，还会引入大量无关噪声，干扰调查人员的判断。

场景特化文件过滤系统（Scenario-Aware File Filter）正是为解决这一问题而设计。系统在分析管线中介于图像解析（ImageAnalyzer）与下游处理（EventExtractor / FileClassifier / PlatformAnalyzer）之间，根据预设场景配置对原始文件集进行智能过滤，仅保留与当前案件类型相关度高的文件进入后续分析。

### 1.2 设计目标

| 目标 | 说明 |
|------|------|
| **精准聚焦** | 按案件类型预定义包含/排除规则，显著缩小分析范围 |
| **无损可控** | 过滤产生独立数据库副本，原始 `_raw.db` 始终完整保留 |
| **可扩展** | 支持通过 API 动态创建自定义过滤配置，不限于内置方案 |
| **管线透明** | 过滤结果自动传递至事件提取、文件分类、平台分析等全部下游环节 |
| **可审计** | 每次过滤操作生成审计日志，记录过滤配置名称、过滤前后文件数量 |

### 1.3 适用场景一览

系统当前内置 4 套场景配置：

| 配置名称 | 适用案件类型 | 典型文件范围 | 文件尺寸限制 |
|----------|-------------|-------------|-------------|
| `general_forensics` | 通用取证 | 全部文件（仅排除虚拟文件系统） | 无 |
| `data_breach` | 数据泄露调查 | 文档、数据库、归档、证书、云存储路径 | 无 |
| `telecom_fraud` | 电信诈骗调查 | 通讯记录、社交应用、支付数据、浏览器记录 | 100 MB |
| `virus_intrusion` | 病毒入侵调查 | 可执行文件、脚本、系统配置、持久化机制 | 500 MB |

---

## 二、系统架构

### 2.1 管线中的位置

文件过滤模块位于核心 4 步分析管线的 Step 1.5（介于图像分析与事件提取之间），是整个分析管线的"漏斗"——所有下游处理器的输入数据都经过该模块的筛选。

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│ 1. 图像分析   │────▶│ 1.5 文件过滤  │────▶│ 2. 事件提取       │
│ ImageAnalyzer │     │ FileFilter   │     │ EventExtractor   │
│ → _raw.db    │     │ → _filtered.db│     │ → _events.db     │
└──────────────┘     └──────┬───────┘     └────────┬─────────┘
                            │                       │
                     过滤后数据库(effectiveRawDb)      │
                            │                       │
                     ┌──────▼───────┐     ┌────────▼────────┐
                     │ 3. 文件分类   │     │ 4. 平台特化分析   │
                     │ FileClassifier│     │ Android/Windows/ │
                     │ → _files.db  │     │ Linux Analyzer   │
                     └──────────────┘     └─────────────────┘
```

**关键设计**：过滤成功后，系统将 `effectiveRawDb` 变量指向 `_filtered.db`，后续所有处理器均使用该变量，而非原始 `_raw.db`。这一机制确保过滤效果完整穿透至管线末端。

### 2.2 过滤逻辑

#### 2.2.1 双条件模型

每个过滤配置由 **Include（包含条件）** 和 **Exclude（排除条件）** 两部分组成，各包含以下维度：

| 维度 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `extensions` | 字符串数组 | 按文件扩展名匹配（大小写不敏感） | `[".pdf", ".docx"]` |
| `path_patterns` | 字符串数组 | 按路径模式匹配（支持 `*` 和 `?` 通配符） | `["*/Documents/*", "*/.ssh/*"]` |
| `filename_patterns` | 字符串数组 | 按文件名模式匹配（支持通配符） | `["password*", "*.bak"]` |
| `min_size` | 整数 | 文件最小字节数（0 表示不限制） | `0` |
| `max_size` | 整数 | 文件最大字节数（0 表示不限制） | `104857600` |
| `include_deleted` | 布尔值 | 是否包含已删除文件 | `true` |
| `include_allocated` | 布尔值 | 是否包含已分配文件 | `true` |

#### 2.2.2 组合模式（Combine Mode）

当 Include 和 Exclude 条件同时生效时，系统支持三种组合策略：

| 模式 | 行为 | 适用场景 |
|------|------|----------|
| `exclude_wins`（默认） | 排除优先：若文件命中排除条件则直接排除，否则检查包含条件 | 保守取证，宁可遗漏也不误收 |
| `include_wins` | 包含优先：若文件命中包含条件则直接保留，否则检查排除条件 | 宽松取证，宁可多收也不遗漏 |
| `include_only` | 仅使用包含条件，忽略排除规则 | 精确指定目标文件集 |

**内置配置全部采用 `exclude_wins` 模式**，这是取证领域最安全的默认策略——避免因过度包含而引入污染数据。

#### 2.2.3 匹配逻辑细节

以默认的 `exclude_wins` 模式为例，单个文件的处理流程为：

```
1. 排除条件检查
   ├── 命中 → 文件被排除 ✗
   └── 未命中 → 进入步骤 2

2. 包含条件检查
   ├── 命中 → 文件被保留 ✓
   └── 未命中 → 文件被排除 ✗
```

其中，每个条件的匹配规则为：

- **extensions**：提取文件扩展名（含点号，转小写），逐一比对列表
- **path_patterns**：路径标准化（`\` → `/`），先将通配符模式转为正则表达式匹配；若模式含 `*`，同时提取通配符之间的"核心部分"进行子串匹配，确保 `*/com.tencent.mm/*` 这类模式可匹配深层路径
- **filename_patterns**：对文件名进行通配符-正则转换后匹配
- **min_size / max_size**：数值比较，0 表示不限制
- **include_deleted / include_allocated**：布尔开关

当 Include 条件中 `extensions`、`path_patterns`、`filename_patterns` 均为空时，视为"无内容过滤"，该条件维度默认匹配所有文件（但仍受 size / deleted / allocated 约束）。

---

## 三、内置场景配置详解

### 3.1 通用取证（general_forensics）

| 属性 | 值 |
|------|-----|
| 配置名称 | `general_forensics` |
| 适用案件 | 无明确案件类型指向的全量取证、初步勘查 |
| 组合模式 | `exclude_wins` |

**设计理念**：最大程度保留数据，仅排除对取证无意义的虚拟文件系统路径。

**包含条件**：

| 维度 | 值 | 说明 |
|------|-----|------|
| extensions | 空 | 不限制扩展名 |
| path_patterns | 空 | 不限制路径 |
| filename_patterns | 空 | 不限制文件名 |
| min_size | 0 | 不限制 |
| max_size | 0 | 不限制 |
| include_deleted | true | 包含已删除文件 |
| include_allocated | true | 包含已分配文件 |

**排除条件**：

| 维度 | 值 | 说明 |
|------|-----|------|
| path_patterns | `/proc/*`, `/sys/*`, `/dev/*`, `/run/*` | Linux 虚拟文件系统，无取证价值 |

**使用建议**：当案件类型尚未明确、或需要全量数据支撑后续深入分析时使用。该配置对分析性能的提升有限，但确保不遗漏任何潜在证据。

---

### 3.2 数据泄露调查（data_breach）

| 属性 | 值 |
|------|-----|
| 配置名称 | `data_breach` |
| 适用案件 | 企业数据泄露、内部信息外传、知识产权侵权 |
| 组合模式 | `exclude_wins` |

**设计理念**：聚焦可能被泄露或外传的"数据资产"——文档、数据库、归档、证书文件、邮件及云同步目录。

**包含条件**：

| 维度 | 值 |
|------|-----|
| extensions | `.doc/.docx/.xls/.xlsx/.ppt/.pptx`（Office 文档）<br>`.pdf/.rtf/.odt/.ods/.odp`（跨平台文档）<br>`.csv/.tsv`（表格数据）<br>`.db/.db3/.sqlite/.sqlite3/.mdb/.accdb/.sql/.bak`（数据库）<br>`.zip/.rar/.7z/.tar/.gz/.bz2/.xz`（归档文件）<br>`.txt/.log/.json/.xml/.yaml/.yml`（文本/配置）<br>`.eml/.msg/.pst/.ost`（邮件数据）<br>`.key/.pem/.crt/.p12/.pfx`（证书/密钥）<br>`.vmdk/.vhd/.vhdx/.qcow2`（虚拟磁盘）<br>`.iso/.img`（镜像文件） |
| path_patterns | `*/documents/*`, `*/Documents/*` — 用户文档目录<br>`*/downloads/*`, `*/Downloads/*` — 下载目录<br>`*/desktop/*`, `*/Desktop/*` — 桌面<br>`*/email/*`, `*/mail/*`, `*/thunderbird/*`, `*/outlook/*` — 邮件目录<br>`*/database/*`, `*/backup/*`, `*/Backup/*` — 数据库与备份<br>`*/share/*`, `*/shared/*`, `*/ftp/*`, `*/sftp/*` — 共享与传输<br>`*/network/*`, `*/vpn/*` — 网络与VPN配置<br>`/var/log/*`, `/etc/ssh/*`, `/etc/samba/*` — 服务器日志与配置<br>`/var/lib/mysql/*`, `/var/lib/postgresql/*` — 数据库存储<br>`*/.ssh/*`, `*/.gnupg/*` — SSH密钥与加密密钥<br>`*/onedrive/*`, `*/dropbox/*`, `*/google.drive/*` — 云同步目录 |
| filename_patterns | `*.sql`, `*.dump`, `*.bak` — 数据导出与备份<br>`database*`, `backup*` — 数据库/备份命名文件<br>`*.pst`, `*.ost`, `*.mbox` — 邮件归档<br>`password*`, `credential*`, `secret*` — 凭证文件 |
| min_size / max_size | 0 / 0（不限制） |
| include_deleted / include_allocated | true / true |

**排除条件**：

| 维度 | 值 |
|------|-----|
| extensions | `.o/.obj/.so/.dll/.dylib`（编译产物）<br>`.class/.pyc`（字节码）<br>`.tmp/.temp/.swp`（临时文件）<br>`.cache`（缓存） |
| path_patterns | `/proc/*`, `/sys/*`, `/dev/*`, `/run/*`（虚拟文件系统）<br>`*/node_modules/*`, `*/__pycache__/*`（开发依赖）<br>`*/.git/objects/*`, `*/cache/*`（版本控制与缓存） |
| filename_patterns | `*.tmp`, `*.temp`, `.DS_Store`, `Thumbs.db`（临时/系统文件） |

**数据量估算**：对于 500 GB 磁盘镜像，典型企业工作站中该配置可过滤至约 15-30% 文件量，显著缩短事件提取与文件分类的处理时间。

---

### 3.3 电信诈骗调查（telecom_fraud）

| 属性 | 值 |
|------|-----|
| 配置名称 | `telecom_fraud` |
| 适用案件 | 电信诈骗、社交工程攻击、资金追踪 |
| 组合模式 | `exclude_wins` |
| 文件尺寸上限 | **100 MB** |

**设计理念**：聚焦通讯记录、社交应用数据、支付交易记录与浏览器活动，覆盖中国大陆主流社交/支付应用的路径特征。文件尺寸限制为 100 MB，排除大体积视频/安装包，加速分析。

**包含条件**：

| 维度 | 值 |
|------|-----|
| extensions | `.db/.db3/.sqlite/.sqlite3`（通讯/联系人数据库）<br>`.jpg/.jpeg/.png/.gif/.bmp/.webp`（聊天图片/截图）<br>`.mp3/.wav/.aac/.amr/.ogg/.m4a`（语音记录）<br>`.mp4/.avi/.mkv/.mov/.3gp/.flv`（视频记录）<br>`.pdf/.doc/.docx/.xls/.xlsx/.ppt/.pptx`（文档）<br>`.txt/.csv/.json/.xml/.html/.htm`（文本/网页）<br>`.vcf/.vcard`（电子名片）<br>`.eml/.msg`（邮件）<br>`.log`（日志）<br>`.apk/.ipa`（移动应用）<br>`.db-wal/.db-shm/.db-journal`（SQLite WAL文件，含未提交事务） |
| path_patterns | `*/com.tencent.mm/*` — 微信<br>`*/com.tencent.mobileqq/*` — QQ<br>`*/com.whatsapp/*` — WhatsApp<br>`*/com.telegram.*/*` — Telegram<br>`*/com.ss.android.ugc.aweme/*` — 抖音<br>`*/com.eg.android.AlipayGphone/*` — 支付宝<br>`*/com.tencent.tmgp.*/*` — 腾讯游戏<br>`*/sms/*`, `*/mms/*` — 短信/彩信<br>`*/contacts/*`, `*/calllog/*` — 联系人/通话记录<br>`*/downloads/*`, `*/dcim/*`, `*/camera/*` — 下载/相机<br>`*/pictures/*`, `*/videos/*`, `*/music/*` — 多媒体<br>`*/documents/*` — 文档<br>`*/browser/*`, `*/chrome/*`, `*/firefox/*` — 浏览器<br>`*/wechat/*`, `*/qq/*` — 微信/QQ（非安卓路径）<br>`*/alipay/*`, `*/unionpay/*` — 支付/银联<br>`*/banks/*`, `*/payment*/*` — 银行/支付<br>`/var/log/*` — 系统日志<br>`/home/*/.bash_history`, `/home/*/.ssh/*` — Shell历史/SSH<br>`*/recent*/*` — 最近文件 |
| filename_patterns | `*.db`, `*.sqlite*`, `*.vcf` — 数据库与联系人<br>`contacts*`, `calllog*`, `sms*`, `mms*` — 通讯数据文件<br>`*.bak`, `*.backup` — 备份文件 |
| min_size | 0 |
| max_size | **104857600**（100 MB） |
| include_deleted / include_allocated | true / true |

**排除条件**：

| 维度 | 值 |
|------|-----|
| extensions | `.o/.obj/.so/.dll/.dylib`（编译产物）<br>`.class/.pyc/.pyo`（字节码）<br>`.tmp/.temp/.swp/.swo`（临时文件）<br>`.cache`（缓存） |
| path_patterns | `/proc/*`, `/sys/*`, `/dev/*`, `/run/*`（虚拟文件系统）<br>`*/node_modules/*`, `*/__pycache__/*`（开发依赖）<br>`*/.git/*`, `*/.svn/*`（版本控制）<br>`*/cache/*`, `*/Cache/*`（缓存目录）<br>`*/tmp/*`, `*/temp/*`（临时目录） |
| filename_patterns | `*.tmp`, `*.temp`, `*.swap`（临时文件）<br>`.DS_Store`, `Thumbs.db`, `desktop.ini`（系统文件） |

**特殊说明**：

- **SQLite WAL 文件**（`.db-wal`, `.db-shm`, `.db-journal`）：这些是 SQLite 的预写日志文件，可能包含尚未写入主数据库的最新通讯记录，对电信诈骗调查具有极高价值。
- **应用包名路径匹配**：配置使用 Android 应用包名（如 `com.tencent.mm`）作为路径匹配模式，可覆盖非标准安装路径下的应用数据。
- **100 MB 文件尺寸限制**：诈骗案件关注的多为文本、图片、音频等小型文件；超大文件（如电影、大型安装包）对调查无直接帮助，过滤后可显著减少处理时间。

---

### 3.4 病毒入侵调查（virus_intrusion）

| 属性 | 值 |
|------|-----|
| 配置名称 | `virus_intrusion` |
| 适用案件 | 勒索软件、木马植入、APT攻击、后门检测 |
| 组合模式 | `exclude_wins` |
| 文件尺寸上限 | **500 MB** |

**设计理念**：覆盖攻击者可能使用的全部文件类型——可执行文件、脚本、配置文件、日志，以及攻击者常利用的持久化机制路径。同时包含 Office 文档与 PDF，因为钓鱼邮件附件是常见初始入侵载体。

**包含条件**：

| 维度 | 值 |
|------|-----|
| extensions | `.exe/.dll/.sys/.drv/.com/.scr/.bat/.cmd`（Windows 可执行/脚本）<br>`.ps1/.psm1/.psd1/.vbs/.vbe/.js/.jse/.wsf`（Windows 脚本）<br>`.msi/.msp/.mst/.cpl/.hta/.inf/.reg`（Windows 安装/配置）<br>`.sh/.bash/.py/.rb/.pl/.php/.cgi`（Unix 脚本）<br>`.elf/.so/.ko/.bin`（Linux 可执行/内核模块）<br>`.jar/.class/.war`（Java 可执行）<br>`.doc/.docx/.xls/.xlsx/.pdf/.rtf`（文档/钓鱼载体）<br>`.html/.htm/.js/.css`（网页/注入脚本）<br>`.log/.txt/.conf/.cfg/.ini/.yaml/.yml`（日志/配置）<br>`.json/.xml`（数据/配置）<br>`.db/.sqlite/.sqlite3`（数据库）<br>`.key/.pem/.crt/.cer/.p12/.pfx/.jks`（证书/密钥）<br>`.dat/.bak`（数据/备份）<br>`.lnk/.url`（快捷方式/URL） |
| path_patterns | `/etc/*`, `/etc/init.d/*`, `/etc/cron*/*`, `/etc/systemd/*`（系统配置/定时任务/服务）<br>`/etc/ssh/*`, `/etc/sudoers*`（SSH/提权配置）<br>`/var/log/*`, `/var/tmp/*`, `/var/spool/*`（日志/临时/队列）<br>`/tmp/*`, `/dev/shm/*`（临时目录/内存文件系统）<br>`/root/*`, `/home/*`（用户主目录）<br>`*/.ssh/*`, `*/.gnupg/*`（SSH密钥/加密密钥）<br>`*/autorun*`, `*/startup*`, `*/Startup/*`（自启动项）<br>`*/Windows/System32/*`, `*/Windows/SysWOW64/*`（Windows 系统目录）<br>`*/Windows/Temp/*`, `*/Windows/Prefetch/*`（Windows 临时/预取）<br>`*/AppData/Local/Temp/*`（用户临时目录）<br>`*/AppData/Roaming/Microsoft/Windows/Start Menu/*`（用户启动项）<br>`*/ProgramData/*`（全局程序数据）<br>`*/.bash_history`, `*/.zsh_history`（Shell 历史）<br>`*/.bashrc`, `*/.profile`, `*/.zshrc`（Shell 配置）<br>`*/crontab*`, `*/cron.d/*`（定时任务）<br>`*/.config/autostart/*`（XDG 自启动） |
| filename_patterns | `autorun.inf`, `desktop.ini`（自动运行/桌面配置）<br>`*.vbs`, `*.vbe`, `*.js`, `*.jse`（脚本文件）<br>`*.ps1`, `*.bat`, `*.cmd`（命令脚本）<br>`crontab*`, `*.service`, `*.timer`（定时任务/服务）<br>`id_rsa*`, `id_ed25519*`, `authorized_keys`（SSH 密钥）<br>`.htaccess`, `.htpasswd`（Web 认证）<br>`*.key`, `*.pem`（密钥文件） |
| min_size | 0 |
| max_size | **524288000**（500 MB） |
| include_deleted / include_allocated | true / true |

**排除条件**：

| 维度 | 值 |
|------|-----|
| extensions | 空（不按扩展名排除） |
| path_patterns | `/proc/*`, `/sys/*`, `/dev/*`, `/run/*`（虚拟文件系统）<br>`*/node_modules/*`, `*/__pycache__/*`（开发依赖）<br>`*/.git/objects/*`（版本控制对象） |
| filename_patterns | 空（不按文件名排除） |

**特殊说明**：

- **排除条件宽松**：病毒入侵场景下，攻击者可能利用任何文件类型，因此排除条件仅限于明确无取证价值的路径。
- **500 MB 文件尺寸限制**：恶意可执行文件通常较小；该上限兼顾了某些大型恶意样本（如含载荷的 PE 文件）的分析需求。
- **跨平台覆盖**：同时包含 Windows（.exe, .bat, .ps1, System32, Prefetch）和 Linux（.elf, .sh, /etc, crontab）的攻击路径特征，适用于混合环境入侵调查。
- **持久化机制全覆盖**：配置涵盖 Windows 注册表启动项路径、Linux crontab、systemd 服务、XDG autostart 等常见持久化位置。

---

## 四、集成路径分析

### 4.1 集成路径总览

场景过滤配置通过三个入口集成至主数据流：

```
                    config/filter_profiles/*.json
                              │
                              ▼
                 ┌──────────────────────────┐
                 │    FileFilter 核心引擎     │
                 │  loadProfile()            │
                 │  applyFilter()            │
                 │  applyFilterByName()      │
                 └─────┬──────────┬─────────┘
                       │          │
          ┌────────────▼──┐  ┌───▼──────────────┐
          │  CLI 入口      │  │  HTTP API 入口     │
          │  --filter-profile │  FilterRoutes      │
          │                │  │  TaskCRUDRoutes    │
          └──────┬─────────┘  └────┬──────────────┘
                 │                  │
                 ▼                  ▼
           raw.db ──过滤──▶ _filtered.db
                               │
                               ▼  effectiveRawDb
                 ┌─────────────┼──────────────┐
                 ▼             ▼              ▼
           EventExtractor  FileClassifier  PlatformAnalyzer
           → _events.db    → _files.db     → _android.db / _windows.db / _linux.db
```

### 4.2 CLI 入口

通过命令行参数 `--filter-profile <name>` 激活：

```bash
./forensic_analyzer suspect_image.dd --filter-profile telecom_fraud --android-analyze
```

**集成代码**（`src/AnalysisOrchestrator.cpp:70-91`）：

1. 检测 `args.filter_profile` 是否非空
2. 调用 `FileFilter::applyFilterByName()` 加载配置并过滤
3. 生成 `{baseName}_filtered.db`
4. 将 `effectiveRawDb` 指向过滤后数据库
5. 若过滤后文件数为 0，回退至原始数据库并输出警告
6. 若过滤过程异常，同样回退至原始数据库

**回退机制**：确保即使过滤配置有误，分析流程也不会中断，而是自动使用未过滤数据继续执行。

### 4.3 HTTP API 入口

#### 4.3.1 任务创建时集成

在创建分析任务时通过 `filter_profile` 字段指定：

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/evidence/suspect.dd",
    "scenarios": ["android"],
    "filter_profile": "telecom_fraud",
    "llm_analyze": true
  }'
```

**集成代码**（`src/network/HTTPServer/TaskManager.cpp:612-647`）：

1. 任务执行时检测 `task.filter_profile` 是否非空
2. 自动调用 `FileFilter::applyFilterByName()` 执行过滤
3. 更新 `task.output_raw_db` 为过滤后数据库路径
4. 后续所有阶段（事件提取、文件分类、平台分析）均使用 `effectiveRawDb`

#### 4.3.2 独立过滤端点

系统提供独立的过滤 API，可在任务运行后追加过滤操作：

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/filter/profiles` | GET | 列出所有可用过滤配置 |
| `/api/filter/profiles/{name}` | GET | 获取指定配置的详细规则 |
| `/api/filter/profiles` | POST | 创建或更新自定义过滤配置 |
| `/api/filter/profiles/{name}` | DELETE | 删除自定义配置（内置配置受保护） |
| `/api/filter/apply` | POST | 对已完成任务的数据库应用过滤 |

**内置配置保护**：`general_forensics`、`telecom_fraud`、`data_breach`、`virus_intrusion` 四个内置配置不允许被覆盖或删除，确保核心场景配置的一致性。

**独立应用过滤示例**：

```bash
curl -X POST http://localhost:8080/api/filter/apply \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task-abc123", "profile_name": "data_breach"}'
```

响应：

```json
{
  "status": "success",
  "data": {
    "task_id": "task-abc123",
    "profile_name": "data_breach",
    "filtered_db": "/output/task-abc123/Server_filtered.db",
    "total_files": 284731,
    "included_files": 42819,
    "excluded_files": 241912
  }
}
```

### 4.4 数据流穿透验证

过滤结果在管线中的传递路径：

| 管线阶段 | 使用的数据源 | 变量 |
|----------|-------------|------|
| 1.5 文件过滤 | `_raw.db` → `_filtered.db` | `effectiveRawDb` |
| 2. 事件提取 | `effectiveRawDb` | `EventExtractor(effectiveRawDb, ...)` |
| 3. 文件分类 | `effectiveRawDb` | `FileClassifier(effectiveRawDb, ...)` |
| 4. Android 分析 | `effectiveRawDb` | `DatabaseManager(effectiveRawDb)` |
| 4. Windows 分析 | `effectiveRawDb` | `DatabaseManager(effectiveRawDb)` |
| 4. Linux 分析 | `effectiveRawDb` | `DatabaseManager(effectiveRawDb)` |

**验证结论**：`effectiveRawDb` 变量贯穿全部分析阶段，场景过滤效果完整传递至管线末端，不存在数据穿透断裂。

### 4.5 配置文件发现机制

系统通过 `PathManager` 在以下候选路径中搜索 `config/filter_profiles/` 目录：

| 优先级 | 候选路径 | 说明 |
|--------|---------|------|
| 1 | `{ProjectRoot}/config/filter_profiles` | 项目根目录下 |
| 2 | `{ExeDir}/config/filter_profiles` | 可执行文件同级目录 |
| 3 | `{ProjectRoot}/../config/filter_profiles` | 项目根目录上级 |
| 4 | `config/filter_profiles` | 当前工作目录 |
| 5 | `../config/filter_profiles` | 上级目录 |
| 6 | `../../config/filter_profiles` | 上两级目录 |

此多路径搜索机制确保无论产品部署在何种目录结构下，均可正确发现配置文件。

---

## 五、自定义过滤配置

### 5.1 通过 API 创建

用户可通过 REST API 创建专属过滤配置，满足特殊案件需求：

```bash
curl -X POST http://localhost:8080/api/filter/profiles \
  -H "Content-Type: application/json" \
  -d '{
    "name": "insider_trading",
    "description": "Insider trading investigation - focuses on trading records, communications, financial documents",
    "version": "1.0",
    "combine_mode": "exclude_wins",
    "include": {
      "extensions": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".eml", ".msg", ".db", ".sqlite"],
      "path_patterns": ["*/trading/*", "*/broker/*", "*/email/*", "*/documents/*"],
      "filename_patterns": ["trade*", "transaction*", "portfolio*"],
      "min_size": 0,
      "max_size": 0,
      "include_deleted": true,
      "include_allocated": true
    },
    "exclude": {
      "extensions": [".tmp", ".cache"],
      "path_patterns": ["/proc/*", "/sys/*"],
      "filename_patterns": []
    }
  }'
```

### 5.2 通过文件创建

在 `config/filter_profiles/` 目录下创建 JSON 文件，系统会自动发现：

```bash
vi config/filter_profiles/insider_trading.json
```

### 5.3 安全约束

- **路径遍历防护**：配置名称不允许包含 `..`、`/`、`\`、空字符
- **内置配置保护**：4 个内置配置不可被覆盖或删除
- **JSON 格式校验**：无效 JSON 会被拒绝并返回解析错误

---

## 六、性能影响分析

### 6.1 过滤操作本身

过滤操作对 `_raw.db` 执行全表扫描，逐条匹配过滤规则。由于采用 SQLite 批量事务（BEGIN / COMMIT）写入 `_filtered.db`，性能开销主要取决于源数据库文件数量：

| 文件数量 | 预估过滤耗时 | 说明 |
|----------|-------------|------|
| < 10,000 | < 1 秒 | 基本无感 |
| 10,000 - 100,000 | 1 - 5 秒 | 可接受 |
| 100,000 - 1,000,000 | 5 - 30 秒 | 建议使用过滤 |
| > 1,000,000 | 30 秒以上 | 强烈建议使用过滤 |

### 6.2 下游管线加速

过滤的核心收益不在过滤操作本身，而在于下游管线的加速：

| 管线阶段 | 加速原理 | 预估加速比（data_breach 场景） |
|----------|---------|------|
| 事件提取 | 仅对保留文件生成事件 | 3-5x |
| 文件分类 | 仅对保留文件进行分类 | 3-5x |
| 文件提取 | 仅提取保留文件内容 | 5-10x |
| LLM 分析 | 仅对保留文件生成描述 | 5-10x |
| 全文索引 | 仅索引保留文件内容 | 3-7x |

### 6.3 存储开销

过滤生成独立的 `_filtered.db` 数据库副本。其大小取决于过滤后的文件数量，通常为原始 `_raw.db` 的 10-40%（视场景配置而定）。原始 `_raw.db` 始终完整保留，不影响取证完整性。

---

## 七、审计与合规

### 7.1 审计日志

每次过滤操作自动写入审计日志（AuditLog），包含以下信息：

- 过滤配置名称（profile name）
- 过滤前文件总数（total_files）
- 过滤后保留文件数（included_files）
- 排除文件数（excluded_files）

日志格式示例：

```
[AUDIT] SYSTEM | FILE_FILTER | Profile: telecom_fraud, Total: 284731, Included: 42819, Excluded: 241912
```

### 7.2 数据完整性保证

| 保证项 | 实现方式 |
|--------|---------|
| 原始数据不可变 | `_raw.db` 仅读取，过滤结果写入独立 `_filtered.db` |
| 过滤可回溯 | 审计日志记录每次过滤的配置名称与统计信息 |
| 过滤可逆 | 随时可对原始 `_raw.db` 重新应用不同配置，或直接使用未过滤数据 |
| 内置配置防篡改 | 四个内置配置受保护，不可覆盖/删除 |
| 任务元数据记录 | HTTP 任务中 `output_raw_db` 字段反映实际使用的数据库路径 |

---

## 八、使用示例

### 8.1 典型工作流：电信诈骗案件

```bash
# Step 1: 创建分析任务，指定场景过滤 + Android 分析
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/evidence/suspect_phone.dd",
    "scenarios": ["android"],
    "filter_profile": "telecom_fraud",
    "llm_analyze": true,
    "llm_mode": "smart"
  }'

# Step 2: 系统自动执行以下管线
#   图像分析 → telecom_fraud 过滤 → 事件提取 → 文件分类 → Android 分析 → LLM 分析

# Step 3: 查看过滤效果
curl http://localhost:8080/api/tasks/{task_id}
# 响应中 output_raw_db 字段将指向 _filtered.db
```

### 8.2 典型工作流：病毒入侵应急响应

```bash
# 使用 CLI 模式
./forensic_analyzer compromised_server.dd \
  --filter-profile virus_intrusion \
  --linux-analyze

# 使用 HTTP 模式
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/evidence/compromised_server.dd",
    "scenarios": ["linux"],
    "filter_profile": "virus_intrusion"
  }'
```

### 8.3 典型工作流：数据泄露调查（事后追加过滤）

```bash
# 任务已在运行或已完成，追加过滤
curl -X POST http://localhost:8080/api/filter/apply \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task-existing", "profile_name": "data_breach"}'

# 查看可用配置
curl http://localhost:8080/api/filter/profiles

# 查看具体配置规则
curl http://localhost:8080/api/filter/profiles/data_breach
```

---

## 九、技术实现参考

### 9.1 核心源代码清单

| 文件 | 功能 |
|------|------|
| `src/core/FileFilter/FileFilter.h` | 过滤引擎头文件，定义 FilterProfile / FilterCondition / FilterCombineMode 等数据结构 |
| `src/core/FileFilter/FileFilter.cpp` | 过滤引擎实现，包含配置加载、模式匹配、数据库过滤逻辑 |
| `src/network/HTTPServer/routes/FilterRoutes.h` | 过滤 REST API 路由声明 |
| `src/network/HTTPServer/routes/FilterRoutes.cpp` | 过滤 REST API 实现，5 个端点 |
| `src/network/HTTPServer/HTTPServerDataTypes.h` | AnalysisTask.filter_profile 字段定义 |
| `src/network/HTTPServer/TaskManager.cpp` | HTTP 任务管线中的过滤集成 |
| `src/AnalysisOrchestrator.cpp` | CLI 管线中的过滤集成 |
| `src/CommandLineParser.h/cpp` | --filter-profile 命令行参数解析 |
| `src/network/HTTPServer/TaskSerialization.cpp` | filter_profile JSON 序列化/反序列化 |

### 9.2 配置文件清单

| 文件 | 场景 |
|------|------|
| `config/filter_profiles/general_forensics.json` | 通用取证 |
| `config/filter_profiles/data_breach.json` | 数据泄露 |
| `config/filter_profiles/telecom_fraud.json` | 电信诈骗 |
| `config/filter_profiles/virus_intrusion.json` | 病毒入侵 |

### 9.3 数据结构

```
FilterProfile
├── name: string                    // 配置名称
├── description: string             // 描述
├── version: string                 // 版本号
├── combine_mode: FilterCombineMode // 组合模式
├── include: FilterCondition        // 包含条件
│   ├── extensions: vector<string>
│   ├── path_patterns: vector<string>
│   ├── filename_patterns: vector<string>
│   ├── min_size: int64
│   ├── max_size: int64
│   ├── include_deleted: bool
│   └── include_allocated: bool
└── exclude: FilterCondition        // 排除条件
    ├── extensions: vector<string>
    ├── path_patterns: vector<string>
    ├── filename_patterns: vector<string>
    ├── min_size: int64
    ├── max_size: int64
    ├── include_deleted: bool
    └── include_allocated: bool
```

---

## 十、已知限制与后续规划

### 10.1 当前限制

| 限制项 | 说明 | 影响 |
|--------|------|------|
| Python 服务未集成 | Python FastAPI 服务不直接调用文件过滤功能 | Python 端无法独立过滤；但若 C++ 管线已过滤，Python 读取的是过滤后数据，间接生效 |
| 正则性能 | 路径/文件名匹配使用 std::regex，大文件集下性能有限 | 百万级文件集下过滤耗时可能超过 30 秒 |
| 不支持内容过滤 | 当前仅基于元数据（扩展名、路径、文件名、大小）过滤，不读取文件内容 | 无法基于文件内容关键词进行过滤 |
| 单次单配置 | 一个任务只能应用一个过滤配置 | 无法组合多个配置的规则 |

### 10.2 后续规划

| 规划项 | 说明 | 预期时间 |
|--------|------|---------|
| Python 端集成 | 在 Python 服务中增加过滤配置读取与数据库过滤能力 | 后续迭代 |
| 配置组合 | 支持多个配置的 AND/OR 组合 | 后续迭代 |
| 内容感知过滤 | 集成全文索引，支持基于文件内容的过滤规则 | 后续迭代 |
| 统计反馈增强 | 过滤后生成详细统计报告（按扩展名/路径/类别的保留/排除分布） | 后续迭代 |
| 性能优化 | 预编译正则表达式，批量模式匹配 | 后续迭代 |

---

## 附录 A：REST API 速查

### 过滤配置管理

```
GET    /api/filter/profiles            列出所有可用配置
GET    /api/filter/profiles/{name}     获取配置详情
POST   /api/filter/profiles            创建/更新自定义配置
DELETE /api/filter/profiles/{name}     删除自定义配置
POST   /api/filter/apply               对任务应用过滤
```

### 任务创建时指定过滤

```
POST   /api/tasks
Body:  { "image_path": "...", "filter_profile": "telecom_fraud", ... }
```

### 命令行

```bash
./forensic_analyzer image.dd --filter-profile <profile_name>
```

---

*— 报告结束 —*
