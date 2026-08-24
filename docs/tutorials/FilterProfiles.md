# 过滤画像（Filter Profiles）完全指南

> **目标读者**：需要在大镜像上"先收窄再分析"的取证分析师，以及要为特定案情编写自定义画像的工程师。
> **事实来源**：`config/filter_profiles/*.json`（四个内置画像原文）、`src/core/FileFilter/FileFilter.cpp`（全部匹配语义）、`src/network/HTTPServer/TaskManagerAnalysis.cpp:227-298`（管线位置与回退）、`src/network/HTTPServer/routes/FilterRoutes.cpp`（HTTP 面）。
> **一句话**：过滤画像把 TSK 全量清单 `_raw.db` 裁剪成 `_filtered.db` 子集，后续分类/事件提取/LLM 分析全部只看子集——它是"零成本提速"的第一旋钮（见 [PerformanceTuning](../ops/PerformanceTuning.md) §5.2）。

---

## 1. 画像在管线中的位置与 `_filtered.db` 副本机制

分析管线（HTTP 任务，TaskManagerAnalysis.cpp:200-330）：

```text
TSK 解析 ──► raw.db（全量文件表）
              │
              ├─ 1.4b SceneDetector（只读探测，必须在过滤之前，见 §6.2）
              │
              └─ 1.5 FileFilter（task.filter_profile 非空时）
                    │  applyFilterByName(raw, filtered, profile)
                    ▼
                 _filtered.db（全新 SQLite 库，非视图非删行）
                    │ included_files > 0 → effectiveRawDb = filtered
                    │ included_files = 0 / 抛异常 → 回退 raw.db 继续全量
                    ▼
              事件提取 + 文件分类 + LLM（都吃 effectiveRawDb）
```

副本机制的三个要点（FileFilter.cpp:317-501）：

1. **源库只读**：过滤是对 raw.db 做 `SELECT ... FROM files` 逐行判定，把命中行 `INSERT` 进新建的 filtered 库；raw.db 一个字节都不改——重跑不同画像互不污染，"`_raw.db` 是证据，`_filtered.db` 是工作副本"。
2. **路径推导**：`rawDbPath.rfind("_raw.db")` 命中则替换为 `_filtered.db`，否则追加 `.filtered`（TaskManagerAnalysis.cpp:269-275；HTTP 任务目录布局下 raw 库叫 `raw.db`，因此产物是 `raw.db.filtered`；CLI 布局下是 `<镜像stem>_raw.db` → `<镜像stem>_filtered.db`）。
3. **表结构等价**：filtered 库重建同名 `files` 表（含 inode/name/path/size/四时间戳/type/md5/is_deleted/is_allocated/permissions/uid/gid/partition_num）并建 5 个索引（inode/path/type/is_deleted/partition_num），写入用 WAL + synchronous=NORMAL + 单事务批量提交，完成后向审计库写一条 `FILE_FILTER` 动作（含 Total/Included/Excluded 计数）。

每次 `POST /api/filter/apply` 或带 `filter_profile` 的任务运行都会**重建**（覆盖）同名 filtered 库——它随时可以从 raw.db 重生，删除无风险。

---

## 2. 四个内置画像逐一拆解

目录 `config/filter_profiles/`，加载顺序见 `FileFilter::findProfilesDirectory()`（:507-530，按 projectRoot → exeDir → CWD 相对回退）。四个画像 `version` 均为 `1.0.0`、`combine_mode` 均为 `exclude_wins`、`include.include_deleted/include_allocated` 均为 `true`。

### 2.1 general_forensics（默认）

```json
"include": { "extensions": [], "path_patterns": [], "filename_patterns": [],
             "min_size": 0, "max_size": 0 },
"exclude": { "path_patterns": ["/proc/*", "/sys/*", "/dev/*", "/run/*"] },
"combine_mode": "exclude_wins"
```

解读：include 三个内容过滤器全空 → **匹配条件恒真**（§3.3 的"无内容过滤默认放行"）；实际语义是"除了伪文件系统外全要"。它是 CLI 分析管线的默认画像（AnalysisOrchestrator.cpp:228-245）。用途：不确定案情时的第一遍全量摸底，或小镜像直接跑。

### 2.2 telecom_fraud（电信诈骗）

- **include**（摘要）：扩展名 40+ 种——通信数据库（`.db/.db3/.sqlite/.sqlite3/.db-wal/.db-shm/.db-journal`）、图片、音视频、办公文档、通讯录（`.vcf/.vcard`）、邮件（`.eml/.msg`）、安装包（`.apk/.ipa`）、`.log`；路径命中即时通讯（`*/com.tencent.mm/*`、`*/com.whatsapp/*`、`*/com.telegram.*/*`）、支付宝、短信/联系人/通话记录（`*/sms/*`、`*/calllog/*`）、DCIM/下载、浏览器、`/home/*/.bash_history`、`/home/*/.ssh/*`；文件名 `*.db`、`contacts*`、`calllog*`、`sms*`、`*.bak` 等；**`max_size: 104857600`（100 MiB）**——四个画像里唯一在 include 上限尺寸的。
- **exclude**：编译产物（`.o/.so/.dll/.class/.pyc`）、临时文件、`*/node_modules/*`、`*/.git/*`、`*/cache/*`、`Thumbs.db` 等噪声。
- 解读：面向手机备份/涉诈终端——只要"人产生的数据"（聊天、转账、照片、文档），砍掉代码与缓存；100 MiB 上限防巨型视频拖慢 LLM。

### 2.3 data_breach（数据泄露）

- **include**：文档全套（Office/PDF/ODF/RTF）、数据导出（`.csv/.tsv/.sql/.bak`）、数据库（含 `.mdb/.accdb`）、压缩包（`.zip/.rar/.7z/.tar/.gz/...`）、邮件存档（`.eml/.msg/.pst/.ost`）、**密钥材料（`.key/.pem/.crt/.p12/.pfx`）**、虚拟磁盘（`.vmdk/.vhd/.vhdx/.qcow2`）、`.iso/.img`；路径命中 `*/documents/*`、`*/downloads/*`、`*/email/*`、`*/database/*`、`*/backup/*`、共享/传输目录（`*/ftp/*`、`*/sftp/*`、`*/share/*`）、`/etc/ssh/*`、`/var/lib/mysql|postgresql/*`、云同步（`*/onedrive/*`、`*/dropbox/*`）；文件名 `*.sql`、`*.dump`、`database*`、`backup*`、**`password*`、`credential*`、`secret*`**。
- **exclude**：编译产物 + `*/.git/objects/*` 等；`max_size: 0`（不限）——虚拟磁盘/压缩包就是要的大件。
- 解读：回答"什么数据被拿走了/放哪了"——按"文档价值"而非"用户行为"圈证据，密钥与凭证文件名单列。

### 2.4 virus_intrusion（病毒/入侵）

- **include**：可执行与脚本全家桶（Windows：`.exe/.dll/.sys/.com/.scr/.bat/.ps1/.vbs/.js/.hta/.msi`；Linux：`.sh/.py/.elf/.so/.ko`；Java：`.jar/.class/.war`）、诱饵文档（`.doc/.xls/.pdf`）、配置（`.conf/.ini/.yaml`）、日志、密钥、**持久化指针（`.lnk/.url`）**；路径几乎覆盖所有持久化位置：`/etc/cron*/*`、`/etc/systemd/*`、`/var/spool/*`、`/tmp/*`、`/dev/shm/*`、`*/Windows/System32/*`、`*/Windows/Prefetch/*`、`*/AppData/Roaming/Microsoft/Windows/Start Menu/*`、`*/.config/autostart/*`、shell 历史与 rc 文件；文件名含 `autorun.inf`、`crontab*`、`*.service`、`*.timer`、`id_rsa*`、`authorized_keys`、`.htaccess`；**`max_size: 524288000`（500 MiB）**。
- **exclude**：仅伪文件系统 + `*/node_modules/*` + `*/__pycache__/*` + `*/.git/objects/*`（注意：**没有**排 `.exe/.dll` 之外的系统噪声——恶意样本可能伪装成任意类型）。
- 解读：按"攻击者会碰的地方"圈——可执行物 + 持久化位置 + 日志；500 MiB 上限容纳大体积样本又不至于被备份镜像淹没。

四个画像的 `min_size` 全部为 0（不设下限）。

---

## 3. 画像 JSON 字段全解（对照 FileFilter.cpp 实现）

### 3.1 顶层字段

| 字段 | 类型 | 语义 |
|---|---|---|
| `profile_name` | string | 画像名；`applyFilterByName` 按 `<目录>/<name>.json` 寻址；HTTP 校验拒绝空名/`..`/`/`/`\`（FilterRoutes.cpp:17-24） |
| `description` | string | 说明，仅展示（`GET /api/filter/profiles` 回显） |
| `version` | string | 版本号，仅元数据，不参与匹配 |
| `include` / `exclude` | object | 两个条件块（FilterCondition），字段见 3.3 |
| `combine_mode` | string | `exclude_wins`（默认）/ `include_wins` / `include_only`，见 §4 |

### 3.2 模式匹配的三套引擎（大小写一律不敏感）

- **extensions**：取文件名**最后一个 `.` 起的尾段**小写后与清单条目小写**全等**比较（`getExtension`/`matchExtensions`，:211-235）。无扩展名文件永远不命中；`.db-wal` 这类"复合扩展名"是合法条目（整体全等）。
- **path_patterns**：**glob 全匹配 + 子串双语义**（`matchPathPatterns`，:167-197）。先把双方 `\` 归一为 `/`，然后任一命中即匹配：
  1. glob 转 regex 后 `regex_match` 整路径全匹配——`*`→`.*`、`?`→任意单字符，`.()` 等正则元字符被转义（`matchGlob`，:122-165；`std::regex::icase`）；regex 构造失败时退化为"原文包含"。
  2. **子串兜底**：若 pattern 含 `*`，把 `*` 全部剥掉得到核心串（如 `*/com.tencent.mm/*` → `/com.tencent.mm/`），路径中**包含**该核心串即命中——这是为"深层嵌套路径 glob 拼不全"设计的，代价是**任何位置**的子串都会命中（见 §6.3 陷阱）。
- **filename_patterns**：纯 glob 全匹配文件名（不含路径），**没有**子串兜底（`matchFilenamePatterns`，:199-209）。`contacts*` 只匹配以 contacts 开头的文件名。

### 3.3 条件块（FilterCondition）内字段与判定顺序

`matchesCondition`（:241-269）按固定顺序短路判定，任何一步不过即整体不匹配：

| 顺序 | 字段 | 语义 |
|---|---|---|
| 1 | `include_deleted`（默认 true） | false 时已删除文件（is_deleted=1）一律不匹配 |
| 2 | `include_allocated`（默认 true） | false 时未分配（is_allocated=0，即已删除盘上空间）不匹配 |
| 3 | `min_size`（默认 0） | **>0 才生效**；size < min_size 不匹配 |
| 4 | `max_size`（默认 0） | **>0 才生效**；size > max_size 不匹配；0 = 不限 |
| 5 | 内容过滤器 | `extensions`/`path_patterns`/`filename_patterns` **三者全空 → 默认放行**；任一非空则三者之间是 **OR**（命中任意一组即匹配） |

注意：`min_size/max_size/include_deleted/include_allocated` 也存在于 exclude 块的解析路径（:81-84），但内置画像只在 include 块使用它们；`POST /api/filter/profiles` 创建画像时 exclude 块只持久化三个内容过滤字段（FilterRoutes.cpp:280-293），手工写 JSON 文件则不受此限。

---

## 4. combine_mode：三种合成模式与 include_wins 的非对称分支

对每个文件，`applyFilter`（:413-448）先分别算 included/excluded 两个布尔，再按模式合成：

| 模式 | 合成逻辑 | 行为特点 |
|---|---|---|
| `exclude_wins`（缺省，四个内置画像全用它） | exclude 条件命中 → 排除；否则看 include 条件，命中才收 | 经典"白名单 + 黑名单压顶" |
| `include_only` | 只看 include 条件 | exclude 块被完全忽略；适合"只要这几类，别的不碰" |
| `include_wins` | ① include 命中 → 收；② include 未命中但 exclude 也未命中 → **仅当 include 的三个内容过滤器至少一个非空**才收；③ include 未命中且 exclude 命中 → 排除 | **非对称**：include 命中能压过 exclude；但"两边都没提"的文件是否兜底收录，取决于 include 是否写了内容过滤器——include 全空时 `include_wins` 会退化为"只收 exclude 未命中的"（等价黑名单模式），这是最容易写错的分支 |

推导示例（include 有内容过滤器时）：文件 F 命中 exclude 不命中 include → `exclude_wins` 排除、`include_only` 排除、`include_wins` 排除（走分支③？不——include 未命中但 exclude 命中，落 ③ 排除）。文件 G 两边都不命中 → `exclude_wins` 排除（include 未命中）、`include_only` 排除、`include_wins` **收录**（分支②）。也就是说 `include_wins` 是三个模式里最"宽松"的：只要画像写过 include 规则，没被点名排除的就都进。

---

## 5. 编写自定义画像实战

### 5.1 从案情到画像的映射方法

写画像前先用四句话描述案情，逐句翻译成字段：

1. **"我们要找什么类型的东西"** → `include.extensions` + `include.filename_patterns`（类型视角）；
2. **"这些东西通常放在哪"** → `include.path_patterns`（位置视角，记得带 `*/` 前后缀或用核心串）；
3. **"什么东西肯定不用看"** → `exclude.*`（噪声：缓存/包管理器/虚拟化目录——抄内置画像的 exclude 即可起步）；
4. **"太大/太小的算噪声吗"** → `min_size/max_size`（取证上常见的 1 KiB 下限过滤纯空文件，max 防 LLM 超时）。

写完后用 §7 的 `POST /api/filter/apply` 在已有任务上**试跑**，看 `included_files/total_files` 比例——目标通常落在 5%-30%；低于 1% 检查是不是模式写死（子串没命中），高于 80% 检查是不是 include 全空成了全量。

### 5.2 完整示例一：内部泄密排查（insider_leak）

案情：离职员工被疑将设计文档拷入私人 U 盘/网盘，需圈定"文档 + 压缩外带 + 云同步 + U 盘痕迹"。

```json
{
    "profile_name": "insider_leak",
    "description": "Insider exfiltration - docs, archives, cloud-sync, USB traces",
    "version": "1.0.0",
    "include": {
        "extensions": [".doc",".docx",".xls",".xlsx",".ppt",".pptx",".pdf",".rtf",
                       ".zip",".rar",".7z",".tar",".gz",
                       ".txt",".csv",".log",".json",".eml",".msg"],
        "path_patterns": ["*/Documents/*","*/Desktop/*","*/Downloads/*",
                          "*/onedrive/*","*/dropbox/*","*/google.drive/*",
                          "*/usb/*","*/udisk/*","*/mnt/*",
                          "*/Users/*/Recent/*","/var/log/*"],
        "filename_patterns": ["*.docx","*.xlsx","*.pdf","*.zip",
                              "recent*","usb*","mounts*"],
        "min_size": 1024,
        "max_size": 0,
        "include_deleted": true,
        "include_allocated": true
    },
    "exclude": {
        "extensions": [".o",".obj",".so",".dll",".pyc",".tmp",".cache"],
        "path_patterns": ["/proc/*","/sys/*","/dev/*","/run/*",
                          "*/node_modules/*","*/__pycache__/*","*/.git/*"],
        "filename_patterns": ["Thumbs.db","desktop.ini",".DS_Store"]
    },
    "combine_mode": "exclude_wins"
}
```

要点：`min_size: 1024` 砍掉空文件/快捷方式残骸；`*/mnt/*` 借子串语义覆盖 Linux 挂载点下的 U 盘内容；`Recent`/`usb*` 文件名从使用痕迹侧补漏。

### 5.3 完整示例二：挖矿木马（crypto_miner）

案情：服务器疑似植入挖矿木马，需要可执行物 + 持久化 + 矿池配置 + 排除"CPU 高但合法"的重负载程序目录。

```json
{
    "profile_name": "crypto_miner",
    "description": "Cryptomining malware - ELF/scripts, persistence, pool configs",
    "version": "1.0.0",
    "include": {
        "extensions": [".elf",".so",".ko",".bin",".sh",".py",".pl",
                       ".conf",".cfg",".ini",".yaml",".yml",".json",
                       ".log",".txt",".service",".timer"],
        "path_patterns": ["/tmp/*","/dev/shm/*","/var/tmp/*",
                          "/etc/cron*/*","/etc/systemd/*","/var/spool/cron/*",
                          "/root/*","/home/*/.config/*","/home/*/.*history",
                          "/var/log/*","*/docker/*"],
        "filename_patterns": ["cron*","*.service","*.timer","config*","pool*",
                              "miner*","xmrig*","stratum*","watchdog*"],
        "min_size": 0,
        "max_size": 104857600,
        "include_deleted": true,
        "include_allocated": true
    },
    "exclude": {
        "extensions": [],
        "path_patterns": ["/proc/*","/sys/*","/dev/*","/run/*",
                          "*/node_modules/*","*/__pycache__/*","*/.git/*",
                          "*/maven/*","*/gradle/*","*/.cargo/registry/*"],
        "filename_patterns": []
    },
    "combine_mode": "exclude_wins"
}
```

要点：挖矿负载常借 Docker 逃逸/容器落地，故保留 `*/docker/*`；矿池地址多藏在 `config*.json`/`pool*`；排除 `*/maven/*` 等合法构建缓存避免 Java 工程机器上误爆量。

### 5.4 落盘方式

两种：① 直接写 `config/filter_profiles/<name>.json`（字段最全）；② `POST /api/filter/profiles`（body 的 `name/description/version/combine_mode/include/exclude`，include 七字段全持久化、exclude 只留三个内容过滤字段）。内置四名（general_forensics/telecom_fraud/data_breach/virus_intrusion）被 403 保护，不可覆盖或删除。

---

## 6. 陷阱清单

1. **include 全灭 → 静默回退全量**：`filterStats.included_files == 0` 时只打 warning `Filter excluded all files`，`effectiveRawDb` 保持 raw.db 继续跑（TaskManagerAnalysis.cpp:278-289）；画像 JSON 写错（如 extensions 全部拼错）不报错、任务照常完成，但 LLM 分析文件数会远超预期——**验收动作**：任务目录出现 `_filtered.db`/`raw.db.filtered` 且行数明显小于 raw.db，审计库 `FILE_FILTER` 动作的 Included 计数 > 0。
2. **SceneDetector 必须在过滤之前**：场景探测靠 raw.db 里的系统噪声路径（`%/data/data/com.android.%`、`%/Windows/Prefetch/%` 等，SceneDetector.cpp:35-61），而画像恰恰把这些当噪声排除；管线固定先探测（1.4b）后过滤（1.5）。自定义画像若手工对 raw 库单独执行 `POST /api/filter/apply`，不影响已完成的任务，但**别指望**在 filtered 库上再跑场景探测。
3. **path_patterns 子串兜底的误伤面**：`*/logs/*` 的核心串是 `/logs/`，路径里任何一段叫 logs（含 `*/changelogs/*/`）都命中。要收紧就写更长的核心串，或接受"宁多勿漏"。
4. **`max_size: 0` 是"不限"不是"零字节"**：判定是 `max_size > 0 && size > max_size` 才排除（:249-250）。同理 `min_size: 0` 不设下限。
5. **extensions 是"最后一个点号全等"**：`myfile.tar.gz` 的扩展名是 `.gz` 不是 `.tar.gz`；要匹配双后缀请把 `.tar.gz` 写进清单（整体全等可行）。
6. **大小写与路径分隔符已被归一**：glob 匹配 `icase`、路径 `\`→`/`（:159,172-177），画像里不必为 Windows 盘符路径单写反斜杠版本。
7. **画像名即文件名**：`applyFilterByName` 抛 `Filter profile not found` 时整个过滤步骤失败→回退全量（同陷阱 1 的表现）。

---

## 7. 使用入口速查

```bash
# CLI：分析管线内过滤（默认 general_forensics）
./build/forensic_analyzer image.dd --db-dir ./out --filter-profile telecom_fraud

# HTTP：创建任务时指定（任务字段 filter_profile）
curl -X POST http://localhost:8666/api/tasks -H "Content-Type: application/json" \
  -d '{"image_path":"/abs/image.dd","filter_profile":"virus_intrusion"}'

# HTTP：对已完成任务补跑过滤（不重跑分析，只产 _filtered.db + 统计）
curl -X POST http://localhost:8666/api/filter/apply -H "Content-Type: application/json" \
  -d '{"task_id":"task_aaa","profile_name":"insider_leak"}'
# → {"filtered_db":"..._filtered.db","total_files":N,"included_files":M,"excluded_files":K}

# 画像 CRUD
curl http://localhost:8666/api/filter/profiles            # 列出（文件名+名称+描述）
curl http://localhost:8666/api/filter/profiles/telecom_fraud   # 单个完整规则
curl -X POST http://localhost:8666/api/filter/profiles ... # 创建/更新自定义（内置 403）
```

注意 `POST /api/filter/apply` 只生成 filtered 库，**不会**改写该任务已产出的 events/files 库；要让后续分析吃子集，应在创建任务时就带 `filter_profile`。

## 相关文档

- [CLI 参考 §3/§13](../reference/CLI.md)（`--filter-profile` 与 `_filtered.db` 产物）
- [性能调优 §5.2](../ops/PerformanceTuning.md)（"过滤画像先行"策略）
- [服务契约 §8](../reference/ServiceContracts.md)（任务目录与库后缀发现）
- [Linux 入侵教程](LinuxIntrusion.md)（画像+场景+smart LLM 的组合实战）

---


## 练习与扩展实验

- [ ] 练习 1：逐字段读一遍 general_forensics.json，标注每个条件的实际匹配语义（glob/子串）。
- [ ] 练习 2：复制 telecom_fraud 为自定义画像，删掉三类扩展名，量化 included_files 变化。
- [ ] 练习 3：构造一个 include 全灭的画像，验证"回退全量+警告"行为。
- [ ] 扩展实验 A：写"内部泄密排查"画像（文档/源码/压缩包 + 排除系统目录），跑真实镜像验证。
- [ ] 扩展实验 B：用 POST /api/filter/apply 对已完成任务的 raw.db 现场过滤，对比 REST 创建与 apply 两条路径的产物差异。
- [ ] 思考题：为什么 SceneDetector 必须在画像之前？构造一个反例画像证明它。
- [ ] 思考题：画像能过滤掉的时间线事件会消失吗？（提示：事件提取读的是 effectiveRawDb。）
**最后更新**: 2026-08-24（新建）
