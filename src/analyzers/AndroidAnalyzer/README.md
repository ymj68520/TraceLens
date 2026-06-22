# AndroidAnalyzer - Android 移动设备取证分析模块

## 1. 模块概述 (Overview)

**AndroidAnalyzer** 是专门针对 Android 智能移动设备的深度取证分析模块,能够从 Android 设备镜像或提取的数据中恢复和解析各类用户行为痕迹。随着移动设备在犯罪活动、内部违规事件中的角色日益重要,该模块为客户提供"一站式"的 Android 数据提取与分析能力,解决了传统移动取证工具功能分散、数据解读困难的问题。

该模块直接解析 Android 系统的核心数据库文件和应用数据,无需依赖厂商提供的专用工具,即可提取通信记录、社交活动、位置信息、应用使用情况等关键证据。无论是刑事侦查、企业内部调查,还是数字证据鉴定,AndroidAnalyzer 都能为您提供专业、可靠的移动取证支持。

**核心业务价值:**
- **深度数据提取**:直接访问 SQLite 数据库底层,绕过应用层限制获取完整数据
- **智能数据关联**:自动关联联系人、通话、短信等多维度数据,还原完整社交网络
- **应用覆盖广泛**:支持原生应用及主流第三方应用的数据库解析
- **证据链完整**:所有提取数据均包含时间戳和来源路径,满足司法取证要求

---

## 2. 核心功能列表 (Key Features)

- **通信记录分析**
  - **短信/彩信提取**:解析系统短信数据库(mmssms.db),提取收发内容、收件人、时间戳
  - **通话记录重建**:提取通话日志(calllog.db),记录呼入/呼出、通话时长、联系人信息
  - **联系人管理**:提取通讯录(contacts2.db),含姓名、电话号码、邮箱、社交账号关联

- **应用使用追踪**
  - **应用使用频率**:统计各应用的启动次数、使用时长、最后使用时间
  - **应用安装记录**:记录应用安装、卸载、更新历史
  - **通知历史**:提取系统通知记录,了解用户接收的信息类型

- **多媒体文件分析**
  - **图片元数据**:提取相机照片的拍摄时间、GPS 位置、设备型号等信息
  - **视频分析**:解析视频文件的编码信息、时长、缩略图
  - **音频文件**:识别录音文件、语音备忘录等多媒体内容
  - **下载记录**:追踪浏览器下载文件和应用商店下载历史

- **设备信息采集**
  - **硬件信息**:设备型号、序列号、IMEI、MAC 地址等唯一标识
  - **系统信息**:Android 版本、安全补丁级别、内核版本
  - **网络配置**:WiFi 连接历史、蓝牙配对记录、移动网络信息
  - **存储统计**:内部存储和 SD 卡使用情况

- **逻辑提取专有解析 (Logical-Extraction Artifacts, Phase 2)**
  - **设备标识符**:从 `data/system/users/<uid>/settings_ssaid.xml` 提取 Android 8+ 的每应用 SSAID(即"Android ID")及设备级 `userkey` 种子,写入 `device_identifiers` 表
  - **笔记应用内容**:通用解析常见笔记 App 的明文数据库(如 `NotePal.db` / `notevault.db`),按含 `note`/`memo` 的表自动匹配 `title`/`content`/`tags` 列,结果写入 `app_notes` 表
  - **加密应用库清单**:对 SQLCipher 加密的 App 库(如 `social_chat.db`、`hidden_notes.db`)建立 `encrypted_db_inventory`,记录发现的密钥/口令提示(取自 `app_flutter/files/password.json`,支持 base64 raw-key、JSON `key`/`password` 字段及裸口令三种形态)与打开状态
  - **通用 SQLCipher 助手**:从 `WeChatDecryptor` 抽出 `SqlCipherDatabase`,支持口令、raw-key(hex)两种模式及 SQLCipher v1-v4 参数自动重试,供任意加密库复用

- **位置与活动追踪**
  - **GPS 历史位置**:提取系统位置缓存和 Google 位置历史
  - **WiFi 定位**:通过 WiFi 扫描记录估算设备移动轨迹
  - **基站定位**:提取蜂窝网络连接记录,定位大致区域
  - **运动传感器数据**:解析加速度计、陀螺仪数据(部分设备)

- **浏览器与网络活动**
  - **浏览历史**:Chrome、Firefox 等主流浏览器的历史记录
  - **书签与同步**:提取浏览器书签和同步账户信息
  - **搜索记录**:Google 搜索、百度搜索等搜索引擎历史
  - **Cookie 缓存**:提取网站登录凭证和浏览偏好

- **社交应用解析(部分支持)**
  - **微信**:提取聊天记录、联系人、朋友圈数据(需 root 权限)
  - **QQ**:提取聊天记录、群组信息、文件传输记录
  - **WhatsApp**:消息数据库解析(基于应用备份)
  - **Telegram**:聊天记录和媒体文件提取

- **数据源支持 (Data Sources)**

  AndroidAnalyzer 通过 `IFileExtractor` 抽象层访问取证数据,支持三种后端,所有解析器逻辑对后端透明:

  | 模式 | CLI 参数 | 输入 | 说明 |
  |------|----------|------|------|
  | TSK 磁盘镜像 | (默认) | E01 / DD 块级镜像 | 经 The Sleuth Kit 打开,依赖 `_raw.db` 的 path→inode 映射 |
  | 逻辑提取目录 | `--android-source dir` | 已解压的 `data/` 目录树 | ADB 逻辑/文件系统提取,无需 TSK、无需 `_raw.db` |
  | 逻辑提取压缩包 | `--android-source zip` | 打包的 `Image.zip` | 通过 libzip 按需读取归档内文件,无需解压整个压缩包(需 libzip) |

  逻辑提取模式专为移动取证工具导出的 ADB 提取设计(例如打包为 `Image.zip` 的 `data/data/<包名>/databases/*.db` 文件树)。这类数据**不是块级磁盘镜像**,无法被 TSK 打开,因此 `dir`/`zip` 模式会绕过 TSK 流水线直接分析数据源。

  ```bash
  # 分析已解压的逻辑提取目录
  ./forensic_analyzer /path/to/extracted --android-analyze --android-source dir

  # 直接分析打包的 Image.zip(按需读取,不落地解压)
  ./forensic_analyzer /path/to/Image.zip --android-analyze --android-source zip
  ```

  > **实现说明**:DuckX 静态链接了第三方 kuba-zip 库,它也导出 `zip_open`/`zip_close` 符号并遮蔽了 libzip 的同名符号。为避免符号冲突,`ZipArchiveExtractor` 改用 libzip 独有的 `zip_source_file_create` + `zip_open_from_source` 打开归档,并用 `zip_discard` 释放只读句柄。

  > **加密库的局限性**:许多笔记/通联类 App(如 `social_chat`、`hidden_notes`)把数据库密钥/口令以明文存于 `password.json`,但对存储值再施加 App 自有的 KDF(迭代哈希)后才用作 SQLCipher 密钥。`encrypted_db_inventory` 表会忠实记录所发现的密钥提示(`key_hint_value`,这通常就是题目"数据库密码"的答案)与 `open_status`(成功为 `decrypted`,无法用标准参数还原则为 `encrypted_locked`)。对于 `encrypted_locked` 的库,需结合 App 的 `libapp.so` 进一步逆向其 KDF,或通过 `SqlCipherDatabase` 提供的口令/raw-key 接口手动尝试。

---

## 3. 业务流程/使用场景 (Use Cases)

### 场景一:网络诈骗案件侦查

**背景**:某网络诈骗团伙通过手机即时通讯工具实施诈骗,侦查机关需要提取嫌疑人的手机证据。

**业务流程**:
1. 技术人员使用取证工具对嫌疑人手机制作完整镜像(含物理提取)
2. 将镜像文件输入 AndroidAnalyzer 进行全面扫描
3. 系统自动定位关键数据库路径:
   - `/data/data/com.android.providers.contacts/databases/contacts2.db` (通讯录)
   - `/data/data/com.android.providers.telephony/databases/mmssms.db` (短信)
   - `/data/data/com.android.providers.contacts/databases/calllog.db` (通话记录)
4. 提取诈骗相关的通讯内容、转账记录、收款人信息
5. 通过应用使用频率分析,发现嫌疑人频繁使用某虚拟货币钱包应用
6. 导出关键数据生成司法鉴定报告,包含时间线、证据完整性校验

**价值体现**:快速提取多维度证据,通过数据关联揭示犯罪网络,为定罪提供坚实证据链。

### 场景二:企业员工违规使用公司资源调查

**背景**:某公司怀疑离职员工通过个人手机窃取公司机密数据,需要取证其手机中的文件传输记录。

**业务流程**:
1. HR 部门配合取证人员对员工手机进行镜像备份
2. AndroidAnalyzer 扫描即时通讯应用(微信、钉钉)的文件传输记录
3. 提取发送给联系人的文件列表、传输时间、文件大小
4. 通过浏览器下载记录发现曾访问公司内部网盘
5. 分析应用使用时间线,发现异常活动集中在离职前一周
6. 生成完整的行为报告,用于法律诉讼证据

**价值体现**:通过多应用数据交叉验证,还原完整的违规行为时间线,为企业维权提供证据支持。

---

## 4. 部署与配置要求 (Deployment & Configuration)

### 环境依赖

**操作系统支持:**
- Linux:Ubuntu 18.04+、CentOS 7+、Debian 9+(推荐环境)
- Windows:Windows 10/11、Windows Server 2016+
- macOS:macOS 10.15+(部分功能受限)

**必需的外部库:**
- SQLite 3.x:用于读取 Android 数据库文件
- The Sleuth Kit (TSK):用于文件系统遍历
- JSON 解析库:用于解析应用配置文件

**可选依赖:**
- ADB(Android Debug Bridge):用于实时设备连接(需要 AndroidAdbExtractor 模块配合)
- Root 权限工具:用于访问受保护的应用数据目录

### 关键配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `--android-db-path` | Android 数据库文件路径 | 自动检测 |
| `--include-apps` | 需要分析的第三方应用列表 | 全部应用 |
| `--output-format` | 输出格式(html/json/报告) | SQLite 数据库 |
| `--timezone` | 时间戳时区设置 | 系统本地时区 |

**Android 数据库典型路径:**
```
/data/data/com.android.providers.contacts/databases/contacts2.db
/data/data/com.android.providers.telephony/databases/mmssms.db
/data/data/com.android.providers.contacts/databases/calllog.db
/data/data/com.android.chrome/app_chrome/Default/History
```

---

## 5. 接口与集成说明 (API & Integration)

### 命令行接口(CLI)

```bash
# 分析 Android 镜像文件
forensic_analyzer android_image.img --android-analyze

# 指定数据库输出路径
forensic_analyzer android.img --android-analyze --db-dir /path/to/output

# 只分析特定应用数据
forensic_analyzer android.img --android-analyze --include-apps com.tencent.mm,com.alibaba.android.rimet
```

### 数据库输出

分析完成后生成 `镜像名_android.db`,包含以下数据表:
- `sms`:短信/彩信记录
- `contacts`:通讯录联系人
- `call_logs`:通话记录
- `app_usage`:应用使用统计
- `device_info`:设备硬件与系统信息
- `media_analysis`:多媒体文件分析结果

### C++ 编程接口

```cpp
#include "AndroidAnalyzerCore.h"

// 创建 Android 分析器
AndroidAnalyzer analyzer;

// 配置分析选项
AndroidAnalyzer::Config config;
config.includeApps = {"com.tencent.mm", "com.alibaba.android.rimet"};
config.outputPath = "/path/to/output.db";

// 执行分析
analyzer.analyze("android_image.img", config);

// 访问分析结果
auto smsRecords = analyzer.getSMSRecords();
auto contacts = analyzer.getContacts();
auto callLogs = analyzer.getCallLogs();
```

### 与 ADB 集成

对于实时设备连接,可配合 AndroidAdbExtractor 模块使用:

```bash
# 通过 ADB 连接设备并提取数据
adb-shell pull /data/data/... /local/path
forensic_analyzer --android-analyze --source-dir /local/path
```

---

## 6. 常见问题 (FAQ)

**Q1:为什么某些应用的数据无法提取?**

A:这通常由以下原因导致:
- **加密数据库**:应用使用了 SQLCipher 或其他加密方式
- **Root 权限限制**:未获取 root 权限,无法访问 `/data/data` 目录
- **应用版本差异**:不同版本的应用数据库结构可能不同

**解决方法**:
- 使用已 root 的设备或镜像
- 针对特定应用开发自定义解析器
- 提取应用备份文件(如 WhatsApp 备份)进行分析

---

**Q2:提取的短信显示乱码?**

A:这通常是字符编码问题。

**解决方法**:
- 检查原始数据库的字符集(通常为 UTF-8)
- 转换编码:`iconv -f GB2312 -t UTF-8 input.txt`
- 某些特殊字符(emoji)可能需要特殊处理

---

**Q3:如何判断手机数据是否被篡改?**

A:可以通过以下方法识别篡改痕迹:
- **时间线逻辑错误**:短信发送时间晚于手机关机时间
- **数据库完整性**:检查 SQLite 数据库的完整性校验和
- **文件系统异常**:删除文件的时间戳不连续
- **应用版本不符**:应用数据库结构与声明版本不匹配

**建议**:
- 交叉验证多个数据源(如短信内容与通话记录的一致性)
- 检查系统日志中的异常行为
- 使用时间线分析工具识别异常时间点

---

**Q4:能否分析已恢复的删除数据?**

A:可以,但需要满足特定条件:
- 删除的数据库文件尚未被覆盖
- 使用文件雕刻(FileCarving)模块先恢复数据库文件
- SQLite 数据库的未分配空间可能包含历史记录

**建议流程**:
1. 先使用 FileCarving 恢复 `.db` 和 `.db-wal` 文件
2. 将恢复的文件输入 AndroidAnalyzer
3. 使用 SQLite 专用的"未分配空间扫描"工具

---
