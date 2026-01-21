# FileCarving - 文件雕刻与数据恢复模块

## 1. 模块概述 (Overview)

**FileCarving**(文件雕刻)是数字取证中最具价值的技术之一,能够从磁盘的未分配空间中恢复已被删除的文件。当用户删除文件或格式化磁盘时,文件系统通常会移除文件的元数据(如文件名、目录位置),但文件的原始数据可能仍然保留在磁盘上,直到被新数据覆盖。FileCarving模块通过识别文件的特征字节签名(文件头和文件尾),直接从原始磁盘数据中重建完整文件,无需依赖文件系统元数据。

该模块为客户解决"关键文件被删除后能否恢复"的紧急需求,广泛应用于数据泄露调查、电子取证、误删恢复等场景。无论文件是因用户误操作、恶意软件破坏,还是嫌疑人故意删除,FileCarving都能为您提供最后的挽救机会。

**核心业务价值:**
- **深度数据恢复**:无需文件系统元数据,直接从原始扇区数据中重建文件
- **高成功率**:支持30+种文件格式,覆盖常见办公文档、图片、视频、压缩包等
- **智能防重复**:自动追踪已雕刻区域,避免重复提取同一文件
- **完整证据链**:所有恢复文件均记录来源偏移和验证状态,满足司法取证要求
- **灵活可扩展**:支持自定义文件签名,可适应特殊文件格式需求

---

## 2. 核心功能列表 (Key Features)

- **多格式文件支持**
  - **图片格式**:JPEG、PNG、GIF、BMP、WebP、TIFF、ICO等
  - **文档格式**:PDF、Office文档(部分支持)
  - **压缩文件**:ZIP、RAR、7Z、GZIP、BZIP2、XZ、TAR等
  - **音频文件**:MP3、WAV、FLAC、OGG、AAC、M4A等
  - **视频文件**:MP4、AVI、MKV、FLV、MOV、WMV等
  - **数据库**:SQLite、DBF等
  - **可执行文件**:Windows EXE、Linux ELF、DEX(Android)等
  - **邮件文件**:PST、OST、MBOX等

- **智能雕刻算法**
  - **文件头识别**:扫描磁盘数据寻找已知文件格式的起始字节标记
  - **文件尾定位**:从文件头开始查找文件结束标记,精确定位文件边界
  - **最大长度限制**:防止将无关数据误判为文件内容,支持设置文件大小上限
  - **偏移量修正**:支持文件头与实际数据存在偏移的特殊格式

- **文件验证机制**
  - **JPEG验证**:检查文件结构完整性,验证SOF、EOC标记
  - **PNG验证**:验证IHDR块和IEND块完整性
  - **PDF验证**:检查PDF版本号和%%EOF标记
  - **ZIP验证**:验证中央目录记录和文件完整性
  - **可选验证**:可启用/禁用验证以提高处理速度

- **进度跟踪与统计**
  - **实时进度回调**:支持UI集成,实时显示雕刻进度
  - **详细统计信息**:恢复文件数、总字节数、各类型文件数量
  - **验证结果统计**:有效文件数、无效文件数、错误计数
  - **执行时间统计**:记录雕刻耗时,用于性能评估

- **数据库日志记录**
  - **完整审计跟踪**:将所有恢复文件记录到SQLite数据库
  - **来源追踪**:记录每个文件的原始偏移地址和数据块信息
  - **验证状态**:标记文件是否通过验证,便于后续筛选
  - **可搜索索引**:支持按文件类型、大小、位置等条件查询

- **高级功能**
  - **自定义签名**:支持添加自定义文件头/文件尾签名
  - **分区偏移处理**:支持分析特定分区的未分配空间
  - **未分配空间扫描**:仅扫描未分配数据块,跳过已占用区域
  - **重复区域检测**:避免重复提取已被雕刻的磁盘区域

---

## 3. 业务流程/使用场景 (Use Cases)

### 场景一:员工离职前的数据销毁调查

**背景**:某公司关键员工在离职前删除了大量工作文档,公司需要恢复这些文件以评估知识产权泄露风险。

**业务流程**:
1. **镜像制作**:IT部门对员工电脑硬盘制作E01格式镜像,确保现场数据不被篡改
2. **初步分析**:使用ImageAnalyzer快速扫描文件系统,发现大量文件被删除
3. **文件雕刻**:启动FileCarving模块,对整个磁盘进行深度扫描
4. **进度监控**:系统实时显示扫描进度,已发现并恢复1200+个文件
5. **结果筛选**:通过数据库查询,筛选出删除时间在离职前一周的Office文档
6. **重点验证**:对恢复的PDF、Word、Excel文件进行验证,确认文件完整性
7. **证据固定**:将恢复的文件保存至证据服务器,生成司法鉴定报告

**价值体现**:成功恢复85%的被删文档,包括关键的设计图纸和客户清单,为公司维权提供核心证据。

### 场景二:网络攻击中的恶意软件取证

**背景**:某服务器遭勒索软件攻击,管理员删除了部分可疑文件,需要恢复分析攻击手法。

**业务流程**:
1. **紧急响应**:安全团队立即下线服务器并制作磁盘镜像
2. **目标雕刻**:针对可执行文件格式(PE、ELF、脚本)进行雕刻
3. **时间线关联**:结合文件系统元数据,定位恶意文件被删除的时间点
4. **恶意代码分析**:对恢复的可疑文件进行沙箱测试和行为分析
5. **IOC提取**:提取恶意软件的IOC指标(域名、IP、文件哈希)
6. **溯源追踪**:通过恢复的临时文件和日志,追溯攻击者行为轨迹

**价值体现**:成功恢复被删除的勒索软件样本和配置文件,帮助安全团队识别攻击手法并加强防护。

---

## 4. 部署与配置要求 (Deployment & Configuration)

### 环境依赖

**操作系统支持:**
- Linux:Ubuntu 18.04+、CentOS 7+、Debian 9+(推荐环境)
- Windows:Windows 10/11、Windows Server 2016+
- macOS:macOS 10.15+(部分功能受限)

**必需的外部库:**
- The Sleuth Kit (TSK) 4.14.0+:提供磁盘镜像访问和未分配块遍历
- SQLite 3.x:可选,用于数据库日志记录

**硬件要求建议:**
- **内存**:最低4GB,推荐8GB以上(大镜像处理)
- **存储**:至少2倍于待分析镜像的可用空间
- **CPU**:多核处理器可加速扫描(模块支持多线程)

### 关键配置项

**命令行参数:**
```bash
# 基本雕刻命令
forensic_analyzer disk_image.dd --carve

# 指定输出目录
forensic_analyzer disk_image.dd --carve --carve-out /recovery/path

# 指定分区偏移(仅分析特定分区)
forensic_analyzer disk.dd --carve --partition-offset 1048576
```

**编程接口配置:**
```cpp
FileCarver carver;

// 设置进度回调(用于UI集成)
carver.setProgressCallback([](uint64_t current, uint64_t total, const std::string& file) {
    double percent = 100.0 * current / total;
    std::cout << "进度: " << percent << "% - " << file << std::endl;
});

// 启用数据库日志
carver.setDatabasePath("carving_log.db");

// 禁用文件验证(提高速度)
carver.setValidationEnabled(false);

// 添加自定义文件签名
CarvingSignature customSig;
customSig.name = "专有格式";
customSig.extension = "xyz";
customSig.header = {0x12, 0x34, 0x56, 0x78};
customSig.footer = {0xAB, 0xCD};
customSig.maxSize = 50 * 1024 * 1024; // 50MB
carver.addSignature(customSig);
```

### 性能优化建议

**加速雕刻处理:**
- 使用SSD存储镜像文件(对比HDD可提速3-5倍)
- 增加系统内存到16GB或更高,减少磁盘I/O
- 禁用文件验证(仅用于快速筛选,后续再验证)
- 针对特定文件类型雕刻,跳过不需要的格式

**大镜像处理策略:**
- 先进行文件系统分析,定位重点区域
- 分区雕刻:逐个分区处理,避免单次处理过大镜像
- 分段处理:将大镜像拆分为多个小段并行处理

---

## 5. 接口与集成说明 (API & Integration)

### 命令行接口(CLI)

```bash
# 完整示例:雕刻并记录到数据库
forensic_analyzer evidence.E01 --carve --carve-out ./recovered --db-path carving.db

# 仅雕刻图片文件
forensic_analyzer disk.dd --carve --signatures jpg,png,gif,bmp

# 查看雕刻统计
forensic_analyzer disk.dd --carve --stats-only
```

### C++ 编程接口

```cpp
#include "FileCarving/FileCarver.h"

// 创建文件雕刻器
FileCarver carver;

// 配置雕刻参数
carver.setProgressCallback(myProgressCallback);
carver.setDatabasePath("evidence_carving.db");
carver.setValidationEnabled(true);

// 执行雕刻
int recoveredCount = carver.carve("suspect_disk.dd", "./recovered_files/");

// 获取雕刻结果
const auto& stats = carver.getStatistics();
std::cout << "恢复文件数: " << stats.totalFilesCarved << std::endl;
std::cout << "总字节数: " << stats.totalBytesCarved << std::endl;
std::cout << "有效文件: " << stats.validFiles << std::endl;

// 遍历恢复的文件列表
for (const auto& file : carver.getCarvedFiles()) {
    if (file.validated) {
        std::cout << "✓ " << file.path << " (" << file.signatureName << ")" << std::endl;
    } else {
        std::cout << "✗ " << file.path << " - " << file.validationMessage << std::endl;
    }
}
```

### 数据库查询接口

雕刻完成后,可通过SQL查询分析结果:

```sql
-- 查看所有恢复的图片文件
SELECT * FROM carved_files WHERE extension IN ('jpg','png','gif');

-- 查看恢复的大文件(>10MB)
SELECT * FROM carved_files WHERE size > 10485760 ORDER BY size DESC;

-- 按文件类型统计
SELECT signature_name, COUNT(*) as count, SUM(size) as total_bytes
FROM carved_files GROUP BY signature_name;

-- 查找特定偏移范围的文件
SELECT * FROM carved_files
WHERE source_offset BETWEEN 1073741824 AND 2147483648;
```

### REST API 集成

通过HTTPServer模块提供的API:
- `POST /api/carve` - 启动雕刻任务
- `GET /api/carve/{task_id}/progress` - 查询雕刻进度
- `GET /api/carve/{task_id}/results` - 获取雕刻结果列表
- `GET /api/carve/{task_id}/statistics` - 获取统计信息

---

## 6. 常见问题 (FAQ)

**Q1:文件雕刻的成功率有多高?哪些因素影响恢复效果?**

A:雕刻成功率取决于多个因素:
- **文件覆盖程度**:如果新数据已覆盖原文件,无法恢复
- **文件类型**:结构化的文件(如JPEG、PDF)成功率较高
- **磁盘使用率**:磁盘使用率越高,文件被覆盖的风险越大
- **删除时间**:删除后立即进行雕刻,成功率接近90%;使用数月后的磁盘,成功率可能降至50%以下

**建议**:
- 发现数据丢失后,立即停止使用该磁盘
- 尽快制作镜像进行雕刻,避免继续写入数据
- 对重要区域进行多次扫描,部分工具可恢复部分覆盖的文件

---

**Q2:雕刻出的文件打不开或损坏,怎么办?**

A:雕刻出的文件可能因以下原因损坏:
- **文件被部分覆盖**:只恢复了部分内容
- **文件头/尾识别错误**:误将非文件数据当作文件内容
- **碎片化文件**:文件被分散存储在多个不连续的区域

**处理方法**:
1. 检查验证结果,优先处理"已验证"的文件
2. 尝试用专业修复工具打开(如JPEG Repair Toolbox)
3. 对于部分损坏的文件,使用十六进制编辑器手动修复
4. 对于碎片化文件,考虑使用专业碎片重组工具(如Foremost、Scalpel)

---

**Q3:雕刻过程需要多长时间?大文件如何处理?**

A:雕刻时间主要取决于:
- **磁盘大小**:1TB硬盘通常需要4-12小时
- **文件数量**:文件碎片化程度影响扫描速度
- **CPU性能**:文件验证步骤需要CPU密集计算

**加速建议**:
- 使用SSD存储镜像文件
- 禁用文件验证(初次快速扫描)
- 针对特定时间段或特定区域进行雕刻
- 分布式处理:将大镜像切分到多台机器并行雕刻

**时间参考**:
- 500GB硬盘,SSD存储,约2-4小时
- 1TB硬盘,HDD存储,约8-15小时
- 可通过进度回调实时监控剩余时间

---

**Q4:能否雕刻加密的文件系统(如BitLocker、LUKS)?**

A:FileCarving模块本身不支持解密,需要先解密磁盘镜像。

**处理流程**:
1. 使用BitLocker/LUKS恢复工具解密镜像
2. 将解密后的数据保存为DD/RAW格式
3. 使用FileCarving对解密后的镜像进行雕刻

**注意**:
- 加密文件系统的未分配空间通常是加密的,解密前无法雕刻
- 如果有密码或恢复密钥,可以使用:`libbde`(BitLocker)或`cryptsetup`(LUKS)解密

---
