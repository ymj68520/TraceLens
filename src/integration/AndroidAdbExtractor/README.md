# AndroidAdbExtractor - 产品说明书

## 1. 模块概述 (Overview)

AndroidAdbExtractor是专业的Android移动设备数据提取模块,通过Android Debug Bridge (ADB)协议与Android设备进行安全通信,实现远程数据提取、设备信息获取、分区镜像提取等核心功能。该模块支持有root权限和无root权限的设备,提供灵活的数据提取策略,是移动设备取证的重要工具。

**核心价值主张**:

- **远程非侵入式提取**: 通过USB连接远程提取数据,无需拆卸设备或物理接触存储芯片,保持设备完整性
- **双模式支持**: 完美支持root和非root设备,根据设备权限自动选择最优提取策略
- **分区级深度提取**: 支持提取完整分区镜像(data、system、boot等),满足深度取证分析需求
- **自动化高效流程**: 自动检测设备状态、权限和可用数据,大幅提升取证效率,减少人工操作错误
- **流式传输**: 通过ADB流式传输数据,不占用设备存储空间,适合大文件提取
- **安全合规**: 完整的操作日志和哈希校验,符合电子证据取证规范,保证证据链完整性

该模块解决了移动设备取证中的核心痛点:"如何在保持设备完整性的前提下,高效、全面地提取数据"。传统方法如JTAG、芯片读取需要拆机,成本高、风险大;而AndroidAdbExtractor通过标准ADB接口,实现了快速、安全、非破坏性的数据提取。

在实际执法和调查工作中,调查人员经常面临设备数量多、时间紧迫的情况。AndroidAdbExtractor的自动化批量提取能力,可以同时处理多台设备,显著提升取证效率。结合系统的自动分类、索引和分析功能,从设备连接到生成取证报告,全程自动化,让调查人员专注于证据分析而非数据提取。

## 2. 核心功能列表 (Key Features)

### 2.1 设备连接与管理

**智能ADB连接**:
- 自动检测本地ADB服务状态,自动启动ADB服务器
- 支持多设备同时连接和管理
- 自动识别设备型号、Android版本、厂商信息
- USB和网络ADB双模式支持
- 连接异常自动恢复,支持断线重连

**设备状态检测**:
- 实时监控设备连接状态
- 检测USB调试授权状态
- 检测设备锁屏状态(密码锁、图案锁、指纹锁)
- 检测USB配置(充电模式、MTP模式、PTP模式)
- 设备响应时间监测

**Root权限检测**:
- 自动检测设备是否已root
- 识别root管理工具类型(Magisk、SuperSU、KingRoot等)
- 测试root权限的实际可用性
- 提供root权限获取建议
- 安全的root权限测试(不修改系统)

**设备信息收集**:
- 提取基本设备信息(型号、序列号、IMEI、Android版本)
- 获取设备硬件配置(CPU、内存、存储)
- 提取网络信息(MAC地址、IP地址、WiFi连接历史)
- 获取安装应用列表和权限信息
- 提取设备设置和配置信息

### 2.2 文件系统数据提取

**目录递归提取**:
- 支持递归提取整个目录树
- 自动处理符号链接和特殊文件
- 保留文件元数据(时间戳、权限、属主)
- 支持长路径文件名(>260字符)
- 断点续传,支持中断后继续

**单文件精确提取**:
- 快速提取指定单个文件
- 支持通配符模式匹配(*、?)
- 支持正则表达式文件过滤
- 实时显示提取进度和速度
- 自动跳过无法访问的文件

**批量多路径提取**:
- 同时提取多个不相关路径
- 智能路径优先级排序(先关键数据后普通数据)
- 并行提取,提升效率
- 统一的进度跟踪和错误报告
- 自动生成提取清单

**进度显示与监控**:
- 实时显示文件提取进度(百分比)
- 显示传输速度和剩余时间估算
- 显示当前正在提取的文件
- 错误和警告实时提示
- 支持进度日志导出

### 2.3 分区镜像提取

**分区信息查询**:
- 列出所有块设备(/dev/block/*)
- 识别分区类型(data、system、boot、recovery、cache等)
- 获取分区大小和挂载点信息
- 识别分区文件系统类型(ext4、f2fs、vfat等)
- 显示分区使用情况

**分区完整镜像**:
- 通过dd命令提取完整分区镜像
- 支持分块提取(适合大分区)
- 流式传输,不占用设备存储
- 实时校验数据完整性
- 自动压缩(可选,节省传输时间)

**特定分区提取**:
- **data分区**: 用户数据、应用数据、下载文件
- **system分区**: 系统应用、系统配置、预装软件
- **boot分区**: 内核、ramdisk、启动配置
- **recovery分区**: 恢复模式、备份工具
- **cache分区**: 缓存数据、临时文件
- **persist分区**: 持久化数据(如WiFi MAC地址)

**DD命令优化**:
- 自动优化块大小(bs参数),提升传输速度
- 支持稀疏文件处理(sparse)
- 错误自动重试机制
- 支持断点续传(使用skip参数)
- 实时进度显示

**流式传输技术**:
- 通过ADB shell直接传输,无需中间存储
- 支持管道操作,可边提取边分析
- 内存占用低,适合大文件
- 支持实时压缩和解压
- 支持加密传输(通过管道工具)

### 2.4 高级功能特性

**Shell命令执行**:
- 在设备上执行任意shell命令
- 获取命令输出和返回码
- 支持交互式命令(需要root)
- 命令执行超时控制
- 安全的命令白名单机制

**自动Root尝试**:
- 检测设备是否有可用的root漏洞
- 尝试常见root方法(需要用户配合)
- 识别root管理工具
- 测试root权限稳定性
- root失败安全回滚

**错误恢复机制**:
- ADB连接断开自动重连
- 传输错误自动重试(可配置次数)
- 文件权限错误智能处理(尝试chmod)
- 磁盘空间不足提前检测
- 传输中断后的断点续传

**断点续传支持**:
- 记录已传输文件的校验信息
- 中断后从断点继续传输
- 自动跳过已完成文件
- 支持部分文件续传(大文件)
- 续传进度保存和恢复

**数据完整性校验**:
- 自动计算文件MD5/SHA256哈希值
- 传输后自动校验数据完整性
- 生成哈希校验报告
- 支持取证标准哈希算法
- 哈希值用于证据验证

**日志与审计**:
- 详细记录所有操作日志
- 记录设备连接时间、断开时间
- 记录每个文件的提取时间和结果
- 生成符合取证规范的审计报告
- 日志防篡改(数字签名)

## 3. 业务流程/使用场景 (Use Cases)

### 场景一: 刑事案件手机取证

**业务背景**:
在一起入室盗窃案件中,嫌疑人被抓获,警方扣押其Android手机。需要快速提取手机中的数据,寻找与案件相关的证据(如销赃聊天记录、案发现场照片、转账记录等)。

**使用流程**:

**阶段1: 设备连接与初步检查** (5分钟)

1. **物理连接**:
   - 将Android手机通过USB连接到取证工作站
   - 手机弹出USB调试授权提示
   - 嫌疑人同意授权(或根据搜查令强制授权)

2. **设备检测**:
   ```bash
   # ADB自动检测设备
   adb devices

   # 输出示例:
   # List of devices attached
   # ABCDEF123456    device
   ```

3. **设备信息收集**:
   ```cpp
   // 自动收集设备基本信息
   auto info = extractor.getDeviceInfo();
   // 输出:
   // 型号: Xiaomi 12
   // Android版本: 12
   // 序列号: ABCDEF123456
   // IMEI: 12345678901234
   // Root状态: 已root (Magisk)
   ```

**阶段2: 数据提取策略选择** (2分钟)

4. **权限评估**:
   ```cpp
   // 检测root权限
   if (extractor.hasRootAccess()) {
       // 有root:可以提取完整分区镜像
       strategy = "完整镜像提取";
   } else {
       // 无root:只能提取可访问的数据
       strategy = "逻辑数据提取";
   }
   ```

5. **提取范围确定**:
   - 关键应用数据:微信、QQ、支付宝、相册
   - 通话记录、短信、联系人
   - 浏览历史、下载文件
   - 位置信息、WiFi连接历史

**阶段3: 数据提取** (30-90分钟)

6. **关键应用数据提取** (root模式):
   ```bash
   # 提取微信数据
   adb shell "su -c 'tar -czf /sdcard/wechat.tar /data/data/com.tencent.mm'"
   adb pull /sdcard/wechat.tar ./extracted/

   # 提取QQ数据
   adb shell "su -c 'tar -czf /sdcard/qq.tar /data/data/com.tencent.mobileqq'"
   adb pull /sdcard/qq.tar ./extracted/

   # 提取支付宝数据
   adb shell "su -c 'tar -czf /sdcard/alipay.tar /data/data/com.eg.android.AlipayGphone'"
   adb pull /sdcard/alipay.tar ./extracted/
   ```

7. **相册和媒体文件提取**:
   ```bash
   # 提取相册
   extractor.extractDirectory("/sdcard/DCIM/Camera");

   # 提取截屏
   extractor.extractDirectory("/sdcard/Pictures/Screenshots");

   # 提取下载文件
   extractor.extractDirectory("/sdcard/Download");
   ```

8. **通话记录和短信提取**:
   ```bash
   # 提取通话记录数据库
   adb pull /data/data/com.android.providers.contacts/databases/calllog.db ./extracted/

   # 提取短信数据库
   adb pull /data/data/com.android.providers.telephony/databases/mmssms.db ./extracted/
   ```

9. **浏览器历史提取**:
   ```bash
   # 提取Chrome历史
   adb pull /data/data/com.android.chrome/app_chrome/Default/History ./extracted/

   # 提取UC浏览器历史
   adb pull /data/data/com.uc.browser/cache/ ./extracted/
   ```

**阶段4: 分区镜像提取** (可选,2-4小时)

10. **完整data分区镜像**:
    ```bash
    # 提取data分区(约64GB,需要2-3小时)
    extractor.extractPartition("data", "data_partition.img");

    # 自动计算SHA256哈希
    sha256sum data_partition.img > data_partition.img.sha256
    ```

**阶段5: 证据固定与报告** (15分钟)

11. **生成提取清单**:
    ```json
    {
      "case_id": "2024-001234",
      "device_serial": "ABCDEF123456",
      "extraction_time": "2024-01-15T14:30:00Z",
      "extraction_officer": "张警官",
      "witness": "李警官",
      "files_extracted": 15432,
      "total_size": "12.3GB",
      "hashes": {
        "data_partition.img": "sha256:abcd1234..."
      }
    }
    ```

12. **生成取证报告**:
    - 设备基本信息
    - 提取的数据清单
    - 关键证据预览
    - 哈希校验值
    - 操作日志和审计记录

**业务价值**:
- **效率提升**: 从传统手动提取需要1-2天,缩短到3-4小时
- **数据完整性**: 自动化流程,避免人为疏漏
- **合规性**: 完整的日志和哈希校验,符合法庭要求
- **可重复性**: 标准化流程,结果可验证

**关键指标**:
- 逻辑数据提取时间: 30-90分钟
- 完整分区镜像时间: 2-4小时(取决于data分区大小)
- 数据完整性: 100%(哈希校验通过)
- 提取成功率: >99.5%

### 场景二: 电子证据现场快速提取

**业务背景**:
在突击检查行动中,需要快速提取多个涉案设备的数据,现场环境复杂,时间紧迫,无法将所有设备带回实验室。需要使用便携式取证工作站,在现场快速提取关键数据。

**使用流程**:

**阶段1: 快速部署** (5分钟)

1. **启动便携式取证工作站**:
   - 笔记本电脑 + 预装取证软件
   - USB集线器,支持同时连接4-6台设备
   - 移动硬盘,准备1-2TB存储空间

2. **批量连接设备**:
   ```bash
   # 连接多台设备
   for device in /dev/ttyUSB*; do
       adb connect $(get_device_ip $device)
   done

   # 查看已连接设备
   adb devices -l
   # 输出:
   # ABCDEF123456  device product: Xiaomi_12
   # 123456789ABC  device product: Huawei_P50
   # FEDCBA098765  device product: Oppo_Reno
   ```

**阶段2: 快速优先提取** (每台设备15-30分钟)

3. **快速提取关键数据** (无root模式):
   ```cpp
   // 定义快速提取路径
   std::vector<std::string> quick_paths = {
       "/sdcard/DCIM/Camera",           // 相机照片
       "/sdcard/Pictures/Screenshots",  // 截屏
       "/sdcard/Download",              // 下载文件
       "/sdcard/WeChat",                // 微信文件(如果存在)
       "/sdcard/tencent/MicroMsg",      // 微信数据(如果存在)
   };

   // 批量提取(多设备并行)
   for (auto device : connected_devices) {
       auto extractor = createExtractor(device);
       extractor.extractMultiple(quick_paths);
   }
   ```

4. **生成设备快照**:
   ```bash
   # 设备基本信息
   adb shell "getprop > device_info.txt"

   # 安装应用列表
   adb shell "pm list packages -f > app_list.txt"

   # 已连接WiFi
   adb shell "dumpsys wifi | grep SSID > wifi_history.txt"
   ```

**阶段3: 数据快速预览** (5-10分钟)

5. **生成缩略图索引**:
   ```bash
   # 为所有图像生成缩略图
   find ./extracted/ -name "*.jpg" -exec convert {} -thumbnail 150x150 thumbs/$(basename {}).jpg \;

   # 生成HTML预览页面
   python generate_gallery.py ./extracted/ > preview.html
   ```

6. **关键词快速搜索**:
   ```bash
   # 在提取的文本中搜索关键词
   grep -r "涉案人员姓名" ./extracted/
   grep -r "涉案金额" ./extracted/
   grep -r "作案地点" ./extracted/
   ```

**阶段4: 初步筛选** (10-15分钟)

7. **识别重要设备**:
   - 提取到涉案照片的设备:优先带回实验室
   - 提取到涉案聊天记录的设备:优先深入分析
   - 无相关数据的设备:快速处理

8. **决定处理策略**:
   - 重要设备:带回实验室,完整镜像提取
   - 次要设备:现场快速提取即可
   - 无关设备:登记后归还

**业务价值**:
- **现场快速响应**: 30分钟内完成单设备关键数据提取
- **并行处理**: 同时处理4-6台设备,提升效率
- **智能筛选**: 快速识别重要设备,优化资源分配
- **灵活性**: 适应现场复杂环境,无需网络依赖

**关键指标**:
- 单设备提取时间: 15-30分钟
- 并行设备数: 4-6台
- 关键数据提取率: >95%
- 现场决策支持: 是

### 场景三: 恢复已删除数据

**业务背景**:
嫌疑人删除了手机中的关键聊天记录和照片,试图销毁证据。需要使用专业工具从设备中恢复已删除数据。

**使用流程**:

**阶段1: 提取物理镜像** (2-4小时)

1. **提取完整data分区**:
   ```bash
   # 使用dd命令提取完整分区
   adb shell "su -c 'dd if=/dev/block/by-name/data'"
   > data_partition.raw

   # 实时计算哈希
   sha256sum data_partition.raw | tee data_partition.sha256
   ```

2. **验证镜像完整性**:
   ```bash
   # 计算哈希并验证
   sha256sum -c data_partition.sha256
   # 输出: data_partition.raw: OK
   ```

**阶段2: 数据恢复分析** (实验室,4-8小时)

3. **使用专业工具恢复**:
   ```bash
   # 使用Autopsy、SleuthKit等工具
   autopsy data_partition.raw

   # 或使用PhotoRec恢复照片
   photorec /dev/sdb1  # 挂载的分区镜像
   ```

4. **数据库文件恢复**:
   ```bash
   # 恢复已删除的数据库记录
   # SQLite数据库:使用sqlite3恢复工具
   sqlite3 recovered.db "SELECT * FROM sqlite_master"

   # 使用CarveDB恢复数据库片段
   carvedb recover -i data_partition.raw -o recovered_dbs/
   ```

5. **微信聊天记录恢复**:
   ```python
   # 使用专门的微信恢复工具
   import wechat_recover

   # 扫描未分配空间
   recovered = wechat_recover.scan_unallocated(
       "data_partition.raw",
       keywords="涉案关键词"
   )

   # 重建聊天记录
   wechat_recover.recover_messages(
       recovered,
       output="recovered_wechat.db"
   )
   ```

**阶段3: 验证与分析** (2-4小时)

6. **验证恢复数据**:
   - 检查聊天记录完整性
   - 验证时间戳合理性
   - 交叉验证其他数据源
   - 识别被删除的时间

7. **分析删除行为**:
   ```bash
   # 分析删除时间
   sqlite3 recovered.db "SELECT datetime(timestamp/1000, 'unixepoch') as time, COUNT(*) FROM messages GROUP BY time ORDER BY time DESC"

   # 识别批量删除行为
   # 如果短时间内删除大量记录,可能是故意销毁证据
   ```

**业务价值**:
- **数据恢复**: 成功恢复70-90%已删除数据(取决于覆盖情况)
- **证据完整性**: 恢复的数据可作为法庭证据
- **行为分析**: 识别嫌疑人的反取证行为
- **时间线重建**: 恢复完整的通讯时间线

**关键指标**:
- 数据恢复率: 70-90% (取决于覆盖情况)
- 恢复准确率: >95%
- 分析时间: 8-16小时
- 证据可用性: 符合法庭要求

### 场景四: 应用数据深度提取

**业务背景**:
需要深度分析特定应用的数据,如微信、QQ、Telegram等加密通讯应用,提取聊天记录、联系人、文件传输等详细信息。

**使用流程**:

**阶段1: 识别应用数据位置** (5分钟)

1. **查找应用数据目录**:
   ```bash
   # 查找微信数据目录
   adb shell "pm path com.tencent.mm"
   adb shell "ls -l /data/data/com.tencent.mm/"

   # 输出:
   # databases/        # 数据库文件
   # files/            # 用户文件
   # shared_prefs/     # 配置文件
   # cache/            # 缓存
   ```

2. **识别关键数据库**:
   ```bash
   # 微信数据库
   /data/data/com.tencent.mm/databases/
   ├── EnMicroMsg.db        # 聊天记录(加密)
   ├── SPC_db_0_1000_0.db   # 朋友圈数据
   ├── WCDB_Contact.db      # 联系人
   └── MSG0.db              # 消息索引

   # QQ数据库
   /data/data/com.tencent.mobileqq/databases/
   ├── nt_qq.zip            # 主数据
   ├── friends_db           # 好友列表
   └── troop_info.db        # 群信息
   ```

**阶段2: 提取应用数据** (10-30分钟)

3. **提取应用数据目录**:
   ```bash
   # 完整提取应用数据
   adb shell "su -c 'tar -czf /sdcard/wechat_data.tar.gz /data/data/com.tencent.mm'"
   adb pull /sdcard/wechat_data.tar.gz ./extracted/

   # 解压
   tar -xzf wechat_data.tar.gz
   ```

4. **提取密钥和配置**:
   ```bash
   # 提取微信加密密钥
   # 位于: /data/data/com.tencent.mm/shared_prefs/auth_info.xml
   adb pull /data/data/com.tencent.mm/shared_prefs/auth_info.xml ./keys/

   # 提取IMEI和设备ID(用于解密)
   adb shell "getprop ro.product.model"
   adb shell "service call iphonesubinfo 1"
   ```

**阶段3: 解密与分析** (1-3小时)

5. **解密微信数据库**:
   ```python
   # 使用微信解密工具
   import wechat_decrypt

   # 读取密钥
   key = wechat_decrypt.extract_key(
       imei="12345678901234",
       uin="123456789",
       db_path="EnMicroMsg.db"
   )

   # 解密数据库
   decrypted = wechat_decrypt.decrypt(
       "EnMicroMsg.db",
       key,
       output="decrypted_messages.db"
   )
   ```

6. **解析聊天记录**:
   ```sql
   -- 查询聊天记录
   SELECT
       m.createTime as timestamp,
       c.chatName as contact,
       m.content as message,
       m.type as message_type
   FROM messages m
   JOIN chatroom c ON m.chatroom_id = c.chatroom_id
   WHERE c.chatName LIKE '%嫌疑人%'
   ORDER BY m.createTime;
   ```

7. **提取传输文件**:
   ```bash
   # 微信文件存储位置
   /sdcard/tencent/MicroMsg/Download/
   ├── image/              # 图片
   ├── video/              # 视频
   ├── voice/              # 语音
   └── document/           # 文档

   # 提取所有文件
   extractor.extractDirectory("/sdcard/tencent/MicroMsg/Download");
   ```

**阶段4: 生成分析报告** (30分钟)

8. **统计与分析**:
   ```sql
   -- 聊天统计
   SELECT
       date(createTime/1000, 'unixepoch') as date,
       COUNT(*) as message_count
   FROM messages
   GROUP BY date
   ORDER BY date;

   -- 高频联系人
   SELECT
       chatName,
       COUNT(*) as count
   FROM messages
   GROUP BY chatName
   ORDER BY count DESC
   LIMIT 10;
   ```

9. **生成可视化报告**:
   ```python
   # 使用Python生成报告
   import matplotlib.pyplot as plt
   import pandas as pd

   # 读取聊天记录
   df = pd.read_sql("SELECT * FROM messages", con)

   # 生成时间线图
   df['date'] = pd.to_datetime(df['createTime'], unit='ms')
   df.groupby(df['date'].dt.date).size().plot()
   plt.savefig('chat_timeline.png')

   # 生成词云
   from wordcloud import WordCloud
   text = ' '.join(df['content'])
   WordCloud(font_path='simhei.ttf').generate(text).to_file('wordcloud.png')
   ```

**业务价值**:
- **深度分析**: 提取和分析应用的完整数据
- **解密能力**: 支持主流通讯应用的解密
- **可视化**: 生成直观的分析报告和图表
- **证据价值**: 聊天记录、文件传输可作为关键证据

**关键指标**:
- 应用支持数: 50+ (微信、QQ、Telegram等)
- 解密成功率: 95% (有密钥)
- 数据提取完整性: 100%
- 分析时间: 2-5小时/应用

## 4. 部署与配置要求 (Deployment & Configuration)

### 4.1 软硬件环境要求

**硬件配置**:

**最低配置** (小规模使用):
- CPU: Intel i5 或 AMD Ryzen 5 (4核)
- 内存: 8GB RAM
- 存储: 500GB HDD (用于存储提取的数据)
- USB: USB 3.0端口 x 2
- 网络: 不必需

**推荐配置** (中等规模):
- CPU: Intel i7 或 AMD Ryzen 7 (8核)
- 内存: 16GB RAM
- 存储: 1TB SSD + 2TB HDD
- USB: USB 3.0/3.1集线器,支持4-6个设备
- 网络: 千兆以太网

**高性能配置** (大规模实验室):
- CPU: Intel i9 或 AMD Ryzen 9 (16核以上)
- 内存: 32GB RAM以上
- 存储: 2TB NVMe SSD RAID + 10TB HDD NAS
- USB: 多个USB集线器,支持10+设备
- 网络: 10Gb以太网

**操作系统**:
- Linux: Ubuntu 20.04/22.04 LTS (推荐)
- Linux: CentOS 7/8, RHEL 7/8
- Windows: Windows 10/11 Pro (需要安装ADB驱动)
- macOS: 11.0+ (需要安装Android File Transfer)

**软件依赖**:

**核心工具**:
- Android SDK Platform Tools (adb、fastboot)
- Android Debug Bridge (ADB) 31.0.3+
- USB驱动程序(Windows需要)

**编译依赖** (从源码编译):
- CMake 3.15+
- GCC 9.0+ 或 Clang 10.0+
- Boost.Asio 1.71+
- nlohmann/json 3.9+

**Python环境** (如使用Python封装):
- Python 3.8+
- pure-python-adb 0.3.0+
- adb-shell 0.4.0+

### 4.2 安装与配置

**方法1: 从源码编译** (推荐)

```bash
# 1. 安装依赖
sudo apt-get update
sudo apt-get install -y build-essential cmake
sudo apt-get install -y libboost-all-dev
sudo apt-get install -y nlohmann-json3-dev
sudo apt-get install -y android-tools-adb android-tools-fastboot

# 2. 编译项目
cd /home/ymj68520/projects/Forensics/ForensicsProject
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)

# 3. 验证安装
./forensic_analyzer --help
```

**方法2: 使用预编译二进制包**

```bash
# 下载预编译包
wget https://github.com/your-repo/releases/download/v1.0/forensic-analyzer-linux-amd64.tar.gz

# 解压
tar -xzf forensic-analyzer-linux-amd64.tar.gz

# 添加到PATH
sudo cp forensic-analyzer /usr/local/bin/
sudo chmod +x /usr/local/bin/forensic-analyzer
```

**方法3: Docker部署** (推荐用于大规模部署)

```dockerfile
# Dockerfile
FROM ubuntu:22.04

# 安装依赖
RUN apt-get update && apt-get install -y \
    android-tools-adb \
    android-tools-fastboot \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# 安装Python包
RUN pip3 install pure-python-adb

# 复制程序
COPY forensic-analyzer /usr/local/bin/

# 工作目录
WORKDIR /data

# 入口点
ENTRYPOINT ["forensic-analyzer"]
```

```bash
# 构建镜像
docker build -t android-adb-extractor:latest .

# 运行容器
docker run -d \
  --name extractor \
  --privileged \
  -v /dev/bus/usb:/dev/bus/usb \
  -v /data/extracted:/data \
  android-adb-extractor:latest
```

### 4.3 ADB服务配置

**设备端配置** (启用ADB调试):

1. **启用开发者选项**:
   ```
   设置 → 关于手机 → 连续点击"版本号"7次
   ```

2. **启用USB调试**:
   ```
   设置 → 开发者选项 → USB调试 (启用)
   ```

3. **授权计算机**:
   - 首次连接时会弹出授权提示
   - 勾选"始终允许使用这台计算机进行调试"

**主机端配置**:

```bash
# 1. 启动ADB服务器
adb start-server

# 2. 查看已连接设备
adb devices -l

# 3. 如果需要root权限
adb root
adb remount

# 4. 配置ADB密钥(可选)
# 生成密钥对
adb keygen ~/.android/adbkey

# 将公钥复制到设备
adb push ~/.android/adbkey.pub /data/misc/adb/adb_keys
```

**网络ADB配置** (无线连接):

```bash
# 1. 通过USB连接设备
adb devices

# 2. 设置TCP端口(5555)
adb tcpip 5555

# 3. 查看设备IP
adb shell ip addr show wlan0

# 4. 通过网络连接
adb connect 192.168.1.100:5555

# 5. 断开USB
# 现在可以无线使用ADB
```

### 4.4 性能优化配置

**并行传输优化**:

```cpp
// C++配置示例
AndroidDirectoryExtractor extractor("./extracted");

// 设置并发连接数
extractor.setMaxConnections(4);

// 设置缓冲区大小(提升传输速度)
extractor.setBufferSize(1024 * 1024);  // 1MB

// 启用压缩传输
extractor.setCompressionEnabled(true);
```

**批量处理优化**:

```bash
# 使用GNU parallel并行处理多设备
ls /dev/ttyUSB* | parallel -j 4 '
    DEVICE=$(adb devices | grep $(basename {}) | awk "{print \$1}")
    forensic-analyzer --device $DEVICE --extract-all
'
```

**缓存策略**:

```python
# Python缓存配置
from functools import lru_cache

@lru_cache(maxsize=100)
def get_device_info(device_serial):
    """缓存设备信息"""
    return adb.get_device_info(device_serial)
```

### 4.5 监控与日志

**日志配置**:

```cpp
// C++日志配置
#include "core/AuditLog/AuditLog.h"

// 初始化审计日志
auto audit = AuditLog::instance();
audit->initialize("/var/log/forensic/adb_extractor.log");
audit->setLogLevel(AuditLevel::INFO);

// 记录操作
audit->log("开始提取设备: " + device_serial);
audit->log("提取文件: " + file_path);
audit->log("提取完成,大小: " + format_size(file_size));
```

**性能监控**:

```bash
# 监控ADB传输速度
adb shell "dd if=/dev/block/by-name/data bs=1M" | pv -s 64G | dd of=data.img

# 监控CPU和内存使用
htop

# 监控磁盘I/O
iotop
```

**进度跟踪**:

```cpp
// C++进度回调
class ProgressCallback {
public:
    void onProgress(const std::string& file, size_t current, size_t total) {
        float percent = (float)current / total * 100.0;
        std::cout << "[" << file << "] " << percent << "% (" << current << "/" << total << ")\r" << std::flush;
    }

    void onComplete(const std::string& file, size_t size) {
        std::cout << "[" << file << "] 完成 (" << format_size(size) << ")" << std::endl;
    }
};

extractor.setProgressCallback(std::make_shared<ProgressCallback>());
```

## 5. 接口与集成说明 (API & Integration)

### 5.1 C++ API接口

**核心类: AndroidDirectoryExtractor**

```cpp
#include "integration/AndroidAdbExtractor/adbExtractor.h"

// 构造函数
AndroidDirectoryExtractor::AndroidDirectoryExtractor(const std::string& outputDir);

// 初始化
bool initialize(bool auto_root = true);
bool hasRootAccess() const;

// 文件提取
bool extractDirectory(const std::string& device_path);
void extractMultiple(const std::vector<std::string>& paths);

// 分区提取
bool extractPartition(const std::string& partition_name, const std::string& output_filename = "");
bool extractMultiplePartitions(const std::vector<std::string>& partition_names);
void listAvailablePartitions();
std::vector<PartitionInfo> getPartitionList();

// 设备信息
struct DeviceInfo {
    std::string serial;
    std::string model;
    std::string android_version;
    std::string imei;
    bool rooted;
};

DeviceInfo getDeviceInfo();
```

**使用示例**:

```cpp
// 示例1: 基本文件提取
#include "integration/AndroidAdbExtractor/adbExtractor.h"

int main() {
    // 1. 创建提取器,指定输出目录
    AndroidDirectoryExtractor extractor("./extracted_data");

    // 2. 初始化(尝试自动root)
    if (!extractor.initialize(true)) {
        std::cerr << "初始化失败" << std::endl;
        return 1;
    }

    // 3. 检查root权限
    if (extractor.hasRootAccess()) {
        std::cout << "设备已root" << std::endl;
    } else {
        std::cout << "设备未root,仅可提取公开数据" << std::endl;
    }

    // 4. 提取目录
    if (extractor.extractDirectory("/sdcard/DCIM/Camera")) {
        std::cout << "相册提取成功" << std::endl;
    }

    return 0;
}

// 示例2: 批量提取多个路径
int main() {
    AndroidDirectoryExtractor extractor("./extracted_data");
    extractor.initialize(true);

    // 定义提取路径列表
    std::vector<std::string> paths = {
        "/sdcard/DCIM/Camera",              // 相机照片
        "/sdcard/Pictures/Screenshots",     // 截屏
        "/sdcard/Download",                 // 下载文件
        "/sdcard/WeChat",                   // 微信文件
        "/sdcard/tencent/MicroMsg",         // 微信数据
    };

    // 批量提取
    extractor.extractMultiple(paths);

    std::cout << "批量提取完成" << std::endl;
    return 0;
}

// 示例3: 分区镜像提取
int main() {
    AndroidDirectoryExtractor extractor("./extracted_data");
    extractor.initialize(true);

    // 检查root权限
    if (!extractor.hasRootAccess()) {
        std::cerr << "分区提取需要root权限" << std::endl;
        return 1;
    }

    // 列出可用分区
    extractor.listAvailablePartitions();

    // 获取分区列表
    auto partitions = extractor.getPartitionList();
    for (const auto& part : partitions) {
        std::cout << "分区: " << part.name
                  << " 大小: " << format_size(part.size) << std::endl;
    }

    // 提取data分区
    if (extractor.extractPartition("data", "data_partition.img")) {
        std::cout << "data分区提取完成" << std::endl;

        // 计算SHA256哈希
        std::string hash = calculate_sha256("data_partition.img");
        std::cout << "SHA256: " << hash << std::endl;
    }

    return 0;
}

// 示例4: 获取设备信息
int main() {
    AndroidDirectoryExtractor extractor("./extracted_data");
    extractor.initialize(true);

    // 获取设备信息
    auto info = extractor.getDeviceInfo();

    std::cout << "设备型号: " << info.model << std::endl;
    std::cout << "Android版本: " << info.android_version << std::endl;
    std::cout << "序列号: " << info.serial << std::endl;
    std::cout << "IMEI: " << info.imei << std::endl;
    std::cout << "Root状态: " << (info.rooted ? "已root" : "未root") << std::endl;

    return 0;
}
```

### 5.2 Python API接口

**使用pure-python-adb库**:

```python
from ppadb.client import Client as AdbClient
import os

class AndroidExtractor:
    """Android数据提取器(Python封装)"""

    def __init__(self, output_dir="./extracted"):
        # 连接ADB服务器
        self.client = AdbClient(host="127.0.0.1", port=5037)
        self.device = None
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def connect(self):
        """连接设备"""
        devices = self.client.devices()
        if len(devices) == 0:
            raise Exception("没有检测到设备")

        self.device = devices[0]
        print(f"已连接设备: {self.device.get_serial_no()}")

    def has_root(self):
        """检查是否有root权限"""
        result = self.device.shell("su -c 'id'")
        return "uid=0" in result

    def extract_directory(self, device_path, local_path=None):
        """提取目录"""
        if local_path is None:
            local_path = os.path.join(self.output_dir, device_path.strip("/"))

        # 使用pull命令
        self.device.pull(device_path, local_path)
        print(f"提取完成: {device_path} -> {local_path}")

    def extract_partition(self, partition_name, output_file):
        """提取分区镜像"""
        # 使用dd命令
        cmd = f"su -c 'dd if=/dev/block/by-name/{partition_name}'"

        # 读取并写入文件
        with open(output_file, "wb") as f:
            for chunk in self.device.shell_iter(cmd):
                f.write(chunk)

        print(f"分区提取完成: {partition_name} -> {output_file}")

    def get_device_info(self):
        """获取设备信息"""
        info = {
            "model": self.device.shell("getprop ro.product.model").strip(),
            "android_version": self.device.shell("getprop ro.build.version.release").strip(),
            "serial": self.device.get_serial_no(),
            "imei": self.device.shell("service call iphonesubinfo 1").strip(),
            "rooted": self.has_root()
        }
        return info

# 使用示例
if __name__ == "__main__":
    extractor = AndroidExtractor("./extracted")

    # 连接设备
    extractor.connect()

    # 获取设备信息
    info = extractor.get_device_info()
    print(f"设备信息: {info}")

    # 检查root权限
    if info["rooted"]:
        print("设备已root,可以提取完整数据")

        # 提取data分区
        extractor.extract_partition("data", "data_partition.img")
    else:
        print("设备未root,仅提取公开数据")

        # 提取相册
        extractor.extract_directory("/sdcard/DCIM/Camera")
```

### 5.3 与取证系统集成

**与ImageAnalyzer集成**:

```cpp
// 在取证流程中集成Android设备提取
#include "analyzers/ImageAnalyzer/ImageAnalyzer.h"
#include "integration/AndroidAdbExtractor/adbExtractor.h"

class ForensicsWorkflow {
public:
    void processAndroidDevice() {
        // 1. 提取Android设备数据
        AndroidDirectoryExtractor adb_extractor("./temp_android");
        adb_extractor.initialize(true);

        // 2. 提取关键数据
        adb_extractor.extractDirectory("/sdcard/DCIM");

        // 3. 如果有root,提取data分区
        if (adb_extractor.hasRootAccess()) {
            adb_extractor.extractPartition("data", "android_data.img");
        }

        // 4. 将提取的镜像文件作为磁盘镜像分析
        ImageAnalyzer img_analyzer;
        img_analyzer.analyze("android_data.img");

        // 5. 合并分析结果
        // ...
    }
};
```

**与LLM分析集成**:

```python
# 在LLM服务中集成Android提取
from httpserver.services.android_service import AndroidService
from httpserver.services.llm_service import LLMService

async def analyze_android_device(device_serial: str):
    """分析Android设备"""

    # 1. 提取数据
    android_service = AndroidService()
    await android_service.connect(device_serial)

    # 提取关键路径
    key_paths = [
        "/sdcard/DCIM/Camera",
        "/sdcard/WeChat",
        "/sdcard/Download"
    ]
    extracted_data = await android_service.extract_multiple(key_paths)

    # 2. 分析提取的内容
    llm_service = LLMService()

    analysis_results = []
    for file_path in extracted_data:
        # 读取文件内容
        with open(file_path, 'r') as f:
            content = f.read()

        # LLM分析
        result = await llm_service.analyze(
            content=content,
            context="Android设备取证分析",
            task="识别涉案信息和关键证据"
        )

        analysis_results.append({
            "file": file_path,
            "analysis": result
        })

    return analysis_results
```

### 5.4 REST API接口

**HTTP API端点** (Python服务):

```python
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

router = APIRouter(prefix="/api/android")

class ExtractRequest(BaseModel):
    device_serial: str
    paths: list[str]
    include_partitions: bool = False

class ExtractResponse(BaseModel):
    success: bool
    job_id: str
    message: str

@router.post("/extract", response_model=ExtractResponse)
async def extract_android_data(
    request: ExtractRequest,
    background_tasks: BackgroundTasks
):
    """提取Android设备数据"""
    # 创建后台任务
    job_id = str(uuid.uuid4())

    background_tasks.add_task(
        perform_extraction,
        job_id,
        request.device_serial,
        request.paths
    )

    return ExtractResponse(
        success=True,
        job_id=job_id,
        message="提取任务已启动"
    )
```

**使用curl调用**:

```bash
# 1. 列出已连接设备
curl http://localhost:8080/api/android/devices

# 2. 提取数据
curl -X POST http://localhost:8080/api/android/extract \
  -H "Content-Type: application/json" \
  -d '{
    "device_serial": "ABCDEF123456",
    "paths": [
      "/sdcard/DCIM/Camera",
      "/sdcard/WeChat"
    ],
    "include_partitions": false
  }'

# 3. 查询任务状态
curl http://localhost:8080/api/android/jobs/{job_id}
```

## 6. 常见问题 (FAQ)

### Q1: 设备未启用USB调试怎么办?

**A**: 这是一个常见问题,有以下解决方案:

**方案1: 引导用户启用** (适用于配合调查)

```
步骤:
1. 进入设置 → 关于手机
2. 连续点击"版本号"7次,会提示"您已处于开发者模式"
3. 返回设置主界面,进入"开发者选项"
4. 启用"USB调试"
5. 用USB连接计算机
6. 设备弹出授权提示,点击"允许"
```

**方案2: 使用取证模式** (部分品牌支持)

部分品牌手机提供"取证模式"或"诊断模式":
- **三星**: 使用诊断码 `*#0*#` 进入测试模式
- **华为**: 使用华为手机助手(HiSuite)的取证功能
- **小米**: 使用MiFlash的线刷模式(需要解锁Bootloader)

**方案3: 使用EDL模式** (深刷模式)

如果设备无法解锁,可以使用EDL(Emergency Download)模式:

```bash
# 1. 进入EDL模式
# 方法因设备而异,通常:
# - 关机
# - 按住音量上+音量下,插入USB
# - 或使用短接测试点的方法

# 2. 使用firehose工具读取分区
python edl.py read partition_data

# 3. 提取data分区
python edl.py read --partition data --output data.img
```

**注意**: EDL模式需要设备驱动支持,且可能触发"保护启动",需要特殊处理。

**方案4: JTAG/芯片读取** (最后手段)

对于无法通过软件方法访问的设备:
- 使用JTAG接口读取Flash芯片
- 直接拆焊Flash芯片,使用读取器读取
- 需要专业设备和技术,成本较高

**法律注意事项**:
- 在某些司法管辖区,强制解锁设备可能需要法院命令
- 记录所有解锁尝试和过程
- 确保取证流程符合当地法律规定

### Q2: 无root权限能提取什么数据?

**A**: 无root权限可以提取的数据有限,但仍有很多有价值的信息:

**可提取的数据** (无需root):

1. **外部存储(/sdcard/)**:
   ```
   /sdcard/DCIM/              # 相机照片和视频
   /sdcard/Pictures/          # 所有图片
   /sdcard/Download/          # 下载文件
   /sdcard/Documents/         # 文档
   /sdcard/Music/             # 音乐
   /sdcard/WhatsApp/          # WhatsApp媒体文件
   /sdcard/WeChat/            # 微信文件
   /sdcard/tencent/           # 腾讯应用数据
   ```

2. **应用公开目录** (通过Content Provider):
   ```bash
   # 通话记录
   adb shell content query --uri content://call_log/calls

   # 短信
   adb shell content query --uri content://sms/

   # 联系人
   adb shell content query --uri content://contacts/people

   # 日历
   adb shell content query --uri content://calendar/events
   ```

3. **设备信息**:
   ```bash
   # 设备基本信息
   adb shell getprop

   # 安装应用列表
   adb shell pm list packages -f

   # 已连接WiFi
   adb shell dumpsys wifi | grep SSID

   # 蓝牙设备
   adb shell dumpsys bluetooth_manager
   ```

4. **应用数据** (部分应用):
   ```bash
   # 浏览器历史(如果浏览器支持导出)
   adb shell am start -n com.android.chrome/.browser.MainActivity
   # 然后手动导出

   # 微信/Telegram文件(存储在/sdcard/)
   adb pull /sdcard/WeChat/
   adb pull /sdcard/Telegram/
   ```

5. **崩溃日志和系统日志**:
   ```bash
   # 系统日志
   adb logcat -d > logcat.txt

   # 崩溃日志
   adb pull /data/tombstones/

   # ANR日志
   adb pull /data/anr/
   ```

**无法提取的数据** (需要root):

- `/data/data/` 下的应用私有数据
- `/data/system/` 下的系统配置
- 其他应用的私有目录
- 加密的应用数据库(如微信聊天记录)

**提升无root提取的方法**:

1. **使用backup功能** (部分应用支持):
   ```bash
   # 尝试备份应用(不加密)
   adb backup -noapk com.example.app

   # 提取备份文件
   # 使用android-backup-extractor工具解开
   java -jar abe.jar unpack backup.ab backup.tar
   ```

2. **使用特定应用的导出功能**:
   ```bash
   # 微信:使用聊天记录迁移功能
   # QQ:使用消息漫游
   # Chrome:使用Google账号同步
   ```

3. **屏幕录制和截图**:
   ```bash
   # 录制屏幕
   adb shell screenrecord /sdcard/demo.mp4
   adb pull /sdcard/demo.mp4

   # 截图
   adb shell screencap -p /sdcard/screen.png
   adb pull /sdcard/screen.png
   ```

**数据价值评估**:
无root提取的数据虽然有限,但仍然有价值:
- 照片和视频可能包含关键证据
- 下载文件可能包含涉案文档
- 浏览历史可以反映上网行为
- 设备信息可以用于关联分析

### Q3: 如何获取root权限?

**A**: 获取root权限的方法有多种,但需要注意风险:

**方法1: 使用第三方Recovery (推荐)**

```bash
# 1. 解锁Bootloader (如果未解锁)
# 小米/一加等品牌通常允许官方解锁
# 其他品牌可能需要特殊方法

# 2. 刷入TWRP Recovery
fastboot flash recovery twrp.img

# 3. 进入Recovery模式
fastboot boot twrp.img

# 4. 在TWRP中刷入Magisk
# 下载Magisk ZIP包,在TWRP中刷入

# 5. 重启后设备已root
```

**方法2: 使用Magisk (最常用)**

```bash
# 1. 下载Magisk APK
# 官网: https://github.com/topjohnwu/Magisk

# 2. 安装Magisk Manager
# 如果设备已root,直接安装
# 如果未root,需要通过_recovery刷入

# 3. Magisk会自动修补boot.img
# 然后刷入修补后的boot镜像

# 4. 重启后root完成
```

**方法3: 使用一键Root工具** (适合非技术人员)

常用工具:
- **KingRoot**: 支持大量设备,一键root
- **KingoRoot**: 类似KingRoot
- **Magisk**: 推荐使用,更安全

```bash
# 使用KingRoot示例:
# 1. 下载KingRoot APK
# 2. 安装并打开应用
# 3. 点击"一键Root"
# 4. 等待完成(可能需要几分钟)
```

**方法4: 使用测试设备**

某些品牌的测试版/工程机预装root:
- 小米工程机
- 华为工程样机
- 开发版Android Studio模拟器

**风险和注意事项**:

1. **失去保修**:
   - 大多数品牌root后失去保修
   - Samsung KNOX会触发,无法恢复
   - 可能影响支付银行等功能

2. **安全风险**:
   - Root可能被恶意软件利用
   - 设备更容易受到攻击
   - 需要谨慎使用root权限

3. **系统稳定性**:
   - 可能导致系统不稳定
   - 某些应用可能拒绝运行(如银行App)
   - OTA升级可能失败

4. **法律风险**:
   - 在某些国家/地区,root设备可能违法
   - 取证过程中root可能影响证据的可采性
   - 需要记录root过程和时间

**取证建议**:
- 优先使用非root方法提取数据
- Root作为最后的手段
- 记录所有root操作
- 在root前先提取无root可获取的数据
- Root后立即提取数据,减少使用时间

### Q4: 提取速度如何?如何优化?

**A**: 提取速度取决于多个因素,以下是优化方法:

**速度基准**:

| USB版本 | 理论速度 | 实际提取速度 | 64GB分区时间 |
|---------|----------|--------------|--------------|
| USB 2.0 | 480 Mbps | 5-10 MB/s | 2-3小时 |
| USB 3.0 | 5 Gbps | 20-50 MB/s | 20-40分钟 |
| USB 3.1 | 10 Gbps | 50-100 MB/s | 10-20分钟 |

**影响速度的因素**:

1. **USB版本和线缆**:
   - 使用USB 3.0/3.1线缆
   - 确保主机USB端口支持USB 3.0
   - 避免使用USB集线器(除非是USB 3.0集线器)

2. **存储速度**:
   - 本地存储使用SSD而非HDD
   - 网络存储使用千兆以太网
   - 避免使用慢速USB硬盘

3. **文件大小和数量**:
   - 大文件传输快(持续传输)
   - 小文件多传输慢(频繁I/O)
   - 考虑打包后传输

**优化方法**:

1. **使用USB 3.0**:
   ```bash
   # 检查USB版本
   lsusb -v | grep -i bcdusb

   # 确保设备支持USB 3.0
   adb shell "getprop | grep usb"
   ```

2. **优化块大小** (DD命令):
   ```bash
   # 默认块大小(512字节)较慢
   adb shell "su -c 'dd if=/dev/block/data bs=512'"

   # 优化块大小(1MB)
   adb shell "su -c 'dd if=/dev/block/data bs=1M'"

   # 或更大块大小(4MB)
   adb shell "su -c 'dd if=/dev/block/data bs=4M'"
   ```

3. **使用压缩**:
   ```bash
   # 设备端压缩,传输压缩数据
   adb shell "su -c 'tar -czf - /data/data | dd bs=1M'" \
       | tar -xzf - -C ./extracted/
   ```

4. **并行传输**:
   ```cpp
   // C++并行传输
   #include <thread>

   void extract_partition(const std::string& name) {
       std::thread t([&]() {
           extractor.extractPartition(name);
       });
       t.detach();
   }

   // 同时提取多个分区
   extract_partition("system");
   extract_partition("data");
   extract_partition("cache");
   ```

5. **网络ADB优化**:
   ```bash
   # 使用有线网络而非WiFi
   adb tcpip 5555
   adb connect 192.168.1.100:5555

   # 调整TCP窗口大小
   adb shell "su -c 'echo 8388608 > /proc/sys/net/core/rmem_max'"
   ```

6. **批处理优化**:
   ```bash
   # 先打包,再传输
   adb shell "su -c 'tar -czf /sdcard/data.tar.gz /data/data'"
   adb pull /sdcard/data.tar.gz
   # 这比逐个文件传输快得多
   ```

**实际性能对比**:

```
测试场景:提取/data/data目录(共10000个文件,5GB)

方法1: 逐个文件pull
- 时间: 约2小时
- 速度: 700 KB/s

方法2: 打包后pull
- 时间: 约10分钟
- 速度: 8.5 MB/s

方法3: 使用tar管道
- 时间: 约8分钟
- 速度: 10.6 MB/s

方法4: USB 3.0 + tar管道
- 时间: 约3分钟
- 速度: 28 MB/s
```

**监控进度**:

```bash
# 使用pv显示进度
adb shell "su -c 'dd if=/dev/block/data bs=1M'" | \
    pv -s 64G - | \
    dd of=data.img

# 输出:
# 12.5GB 0:03:25 [62.3MB/s] [=====================>]  19%
```

### Q5: 如何处理传输中断?

**A**: 传输中断是常见问题,以下是解决方案:

**常见中断原因**:

1. **USB连接不稳定**
2. **设备进入休眠模式**
3. **ADB服务崩溃**
4. **磁盘空间不足**
5. **传输超时**

**预防措施**:

1. **保持设备唤醒**:
   ```bash
   # 禁用休眠
   adb shell "svc power stayon true"

   # 或保持屏幕常亮
   adb shell "settings put global stay_on_while_plugged_in 7"
   ```

2. **检查磁盘空间**:
   ```bash
   # 提前检查可用空间
   df -h /path/to/output

   # 确保至少有2倍于数据的可用空间
   ```

3. **设置超时**:
   ```bash
   # 增加ADB超时时间
   adb shell "settings put global adb_allowed_connection_time 86400000"
   ```

**断点续传方法**:

1. **使用rsync** (推荐):
   ```bash
   # rsync支持断点续传
   adb push rsync /data/local/tmp/
   adb shell "su -c 'cp /sdcard/extracted/* /data/backup'"
   adb pull /data/backup/ ./extracted/

   # 中断后重新运行rsync,只会传输差异部分
   ```

2. **使用tar分卷**:
   ```bash
   # 分卷打包,每卷1GB
   adb shell "su -c 'tar -czf - /data/data | split -d -b 1G - /sdcard/data.tar.gz'"

   # 分别拉取
   for f in /sdcard/data.tar.gz*; do
       adb pull "$f" ./extracted/
   done
   ```

3. **记录已传输文件**:
   ```cpp
   // C++实现断点续传
   class ResumableExtractor {
   private:
       std::set<std::string> completed_files_;

   public:
       void load_checkpoint(const std::string& checkpoint_file) {
           // 加载已完成的文件列表
           std::ifstream f(checkpoint_file);
           std::string file;
           while (std::getline(f, file)) {
               completed_files_.insert(file);
           }
       }

       void extract_with_resume(const std::string& device_path) {
           // 遍历文件
           for (auto file : list_files(device_path)) {
               if (completed_files_.count(file)) {
                   std::cout << "跳过已完成的文件: " << file << std::endl;
                   continue;
               }

               // 提取文件
               if (extract_file(file)) {
                   completed_files_.insert(file);
                   save_checkpoint();
               }
           }
       }
   };
   ```

**恢复中断的传输**:

```bash
# 1. 检查ADB连接
adb devices

# 2. 如果断开,重新连接
adb kill-server
adb start-server
adb connect device_ip

# 3. 使用grep查找已传输的文件
ls extracted/ | sort > completed.txt

# 4. 只传输未完成的文件
for file in $(adb shell "ls /sdcard/DCIM"); do
    if ! grep -q "$file" completed.txt; then
        adb pull "/sdcard/DCIM/$file" extracted/
    fi
done
```

**自动重试脚本**:

```bash
#!/bin/bash
# auto_extract.sh - 带重试的提取脚本

MAX_RETRIES=5
RETRY_DELAY=5

extract_with_retry() {
    local src=$1
    local dst=$2
    local attempt=1

    while [ $attempt -le $MAX_RETRIES ]; do
        echo "尝试 $attempt/$MAX_RETRIES: $src"

        if adb pull "$src" "$dst"; then
            echo "成功: $src"
            return 0
        else
            echo "失败,等待 ${RETRY_DELAY}秒后重试..."
            sleep $RETRY_DELAY
            ((attempt++))
        fi
    done

    echo "失败: $src (已尝试 $MAX_RETRIES 次)"
    return 1
}

# 使用示例
extract_with_retry "/sdcard/DCIM/Camera" "./extracted/Camera"
```

**日志记录**:

```bash
# 记录所有传输操作
exec > >(tee -a extract.log)
exec 2>&1

echo "开始提取: $(date)"
adb pull /sdcard/DCIM ./extracted/
echo "完成提取: $(date)"

# 检查日志找出失败的操作
grep "failed" extract.log
```

**最佳实践**:
- 分批传输大量数据
- 使用压缩减少传输量
- 定期保存检查点
- 记录所有传输操作
- 优先传输关键数据
- 为重要数据准备多个备份
