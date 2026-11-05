# TraceLens 第三方测试验收演示数据集 (Demo Datasets)

本目录为面向第三方权威测试机构的现场验收演示专用数据集。数据集覆盖项目合同指标要求的全部来源，
包括 1 份 Windows、1 份 Linux、1 份阿里云 OSS、1 份 iOS、以及 3 份主流国产 Android 移动设备数据。

各数据集均已进行脱敏，且植入了统一的案情证据链（涉案嫌疑人：张伟-仓库主管、李娜-财务经理、王五-收款账户；涉案标的：￥386,000 设备采购与异常调拨款项）。

---

## 演示数据集清单与指标对应关系

| 序号 | 演示数据集目录 / 文件 | 数据源类型与品牌 | 包含核心工件与内容 | 对应验收指标 |
| :--- | :--- | :--- | :--- | :--- |
| **01** | `01_windows/windows_evidence.img` | **Windows 操作系统镜像** | Prefetch 执行痕迹(CMD/PowerShell)、EVTX 系统日志、LNK 快捷方式、注册表 Hive(SYSTEM/SOFTWARE)、财务审计报告文档 | 指标 1(1) 磁盘镜像与操作系统接入 |
| **02** | `02_linux/linux_evidence.img` | **Linux 操作系统镜像** (RAW/DD) | 涉案沟通记录、涉案合同、财务台账、syslog/auth.log、重复文件对、低价值混合系统文件 | 指标 1(1) 兼容RAW/DD<br>指标 1(2) 轻量化过滤(10MB/s, 剔除率≥70%, 压缩至12-15%)<br>指标 2(2) 重复证据去重 |
| **03** | `03_aliyun_oss/file_m-demo_aliyun_system.raw.tar.gz` | **阿里云 OSS / ECS 导出包** | Alibaba Cloud Linux、nginx 访问日志、OSS 接口转账调用日志、系统用户与服务日志 | 指标 1(1) 服务器日志与云数据源接入 |
| **04** | `04_ios/ios_backup_evidence/` | **苹果 iOS 移动设备逻辑备份** | iTunes/Finder 备份规范(Manifest.plist, Manifest.db)、涉案短信 iMessage (sms.db)、通讯录 (AddressBook)、涉案备忘录、日程 | 指标 1(1) IOS 移动设备接入 |
| **05** | `05_android_miui/miui_backup_evidence/` | **Android (小米 MIUI 备份)** | 小米备份清单 descript.xml、Contacts(com.android.contacts).bak 联系人库、Mms(com.android.mms).bak 短信库 | 指标 1(1) Android 移动设备 (类别 1: 小米) |
| **06** | `06_android_harmony/harmony_backup_evidence/` | **Android (华为鸿蒙 HarmonyOS 备份)** | 鸿蒙备份清单 .info.json、分卷归档 part.0.tarx、WAL 日志、日历与通讯工件库 | 指标 1(1) Android 移动设备 (类别 2: 华为鸿蒙) |
| **07** | `07_android_vivo/vivo_backup_evidence/` | **Android (vivo / OPPO 雷电快取备份)** | .backup 头、LevelDB 索引规范 index.json、涉案转账截图相册、涉案合同文档、微信应用包 | 指标 1(1) Android 移动设备 (类别 3: vivo/OPPO) |

---

## 演示与验收测试方法

### 方法一：全自动化第三方验收测试套件（自动化验证指标）
在 TraceLens 根目录下运行（无需任何人工交互）：
```bash
# 1. 一键生成测试夹具与演示数据集
python3 tests/acceptance_metrics/prepare_fixtures.py

# 2. 运行第三方指标验收测试（非 LLM 部分，耗时约 1 分钟）
python_service/.venv/bin/python -m pytest tests/acceptance_metrics -v -m "not llm"

# 3. 运行含大模型案情推演与多模态聚合的完整验收测试
python_service/.venv/bin/python -m pytest tests/acceptance_metrics -v
```

### 方法二：图形化 Web 前端界面演示（人工交互验收）
1. 打开浏览器访问前端（默认 `http://localhost:5173` 或部署地址）；
2. 点击 **“新建任务”**；
3. 选择对应演示数据路径：
   - 导入 Windows 演示数据：选择 `01_windows/windows_evidence.img`，场景勾选 **Windows**；
   - 导入 Linux 演示数据：选择 `02_linux/linux_evidence.img`，场景勾选 **Linux**；
   - 导入 阿里云 OSS 数据：选择 `03_aliyun_oss/file_m-demo_aliyun_system.raw.tar.gz`，来源类型选择 **aliyun-image**；
   - 导入 iOS 移动备份：选择 `04_ios/ios_backup_evidence`，来源类型选择 **ios-backup**；
   - 导入 小米 备份：选择 `05_android_miui/miui_backup_evidence`，来源类型选择 **miui-backup**；
   - 导入 华为鸿蒙 备份：选择 `06_android_harmony/harmony_backup_evidence`，来源类型选择 **harmony-backup**；
   - 导入 vivo 备份：选择 `07_android_vivo/vivo_backup_evidence`，来源类型选择 **vivo-backup**；
4. 任务分析完成后，可在 **工件卡片**、**重复证据列表**、**动态时间线** 以及 **案情推演报告** 中查看完整的结构化研判成果。
