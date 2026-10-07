# RAID 作为系统镜像接入既有任务

## 页面与调用链

没有新增 `/raid` 网页、菜单、路由或独立的分析数据库范式。
入口仍是“任务列表 → Create Task”，数据源增加“RAID 系统镜像”。
在同一弹窗选择成员、识别、确认候选、准备镜像，完成后提交普通任务。
已重组的单份逻辑镜像仍可直接使用原有“磁盘镜像”选项。

```text
现有任务弹窗（成员复选，不要求手动盘序）
  → /python/api/evidence-intake/raid/candidates、jobs、prepare
  → 私有有界 worker：既有 raid.core / raid.infer / raid.raw / raid.export
  → DATA_DIR/raid_intake/JOB/packages/RUN/logical.img + raid_manifest.json
  → 原 POST /api/tasks，image_source=raid、android_source=tsk
  → C++ RaidTaskAdmission：作业身份、归属、镜像/清单/每个原成员 SHA-256
  → 原 TaskManager TSK 流水线 → raw.db / files.db / events.db
  → 原文件列表/提取、时间线及现有调查/报告读取器
```

不会把 RAID 当作 Android 逻辑目录，不强制 Android 场景，也不更换证据键、
调查状态机或 v7/v8 协议。UI 场景过滤、案情描述与平台分析选项沿用原表单。
本轮没有更改既有模型开关、端点或安全部署策略；隔离测试禁用 AI。

## 来源绑定

任务创建和分析启动各核对一次准备产物及成员哈希。受管理的准备镜像不能
省略 RAID 作业身份冒充普通原始镜像，客户端 metadata 中的 RAID 字段不可信。
`requested_by` 来自认证上下文，不接受客户端伪造审核人。

Task metadata 新增 `source_kind=raid`、`source_label`、`raid_job_id`、
`raid_manifest_sha256`、`raid_manifest_file_sha256`、`raid_manifest_path`、
`raid_image_sha256`、`raid_integrity_status`、`raid_requested_by`、
`raid_allow_partial`；无需新增或迁移业务表。
任务目录保存 `raid_source_manifest.json` 的原字节快照。
逻辑镜像哈希、清单原字节哈希和清单规范化摘要分别保存，不互相替代。

现有任务表/全局任务选择器使用来源名称。文件页内可展开“RAID 镜像来源”，
查看重组状态、成员相对路径及哈希、镜像哈希和清单摘要。
来源接口先通过 C++ Task store 解析归属，再核对准备作业与任务绑定。
不接受任意本机路径，不用 `file://`，不新增独立来源页面。

这里展示的是生成时的来源绑定，不是每次浏览都重新哈希整个检材。
文件提取仍按已有 Task/文件路径边界从逻辑镜像进行。
网页尚未提供每个文件的成员级精确 extent 证明；原成员重新读取/SDK定位
仍是既有 CLI 诊断能力，不能称为网页已实现精确扇区回跳。

## 配置与安全边界

- Python 和 C++ 必须共用同一绝对 `DATA_DIR`，加载本轮代码；前端走已有
  `/python` 受控入口，不新增服务端口。
- 服务端 `TRACELENS_RAID_INBOX` 指向已授权成员目录；未设置时使用项目根
  同级 `RAID`。浏览器只提交不透明成员 ID，不提交服务器目录路径。
- 当前网页成员选择仅列出 RAW 类扩展（img/raw/dd/bin/hdd）；不按扩展名
  推断布局。既有 CLI 的显式 EWF 分段选择尚未接入此复选界面。
- 新作业需要用户写权限；准备/取消/状态归属检查，允许 PARTIAL 诊断需要
  管理员。C++ RAID 准入需要既有现场认证启用，不增加匿名例外。
- 原成员只读；拒绝符号链接、越界、重复成员和准备后变化的来源。
- 2–32 成员，目录深度8、文件1000、并发2；推断180秒、最多4096盘序，
  准备最多1GiB、1800秒、worker内存768MiB。资源上限是当前工程边界，
  超限不会发布成功镜像。TB级重组尚未通过本接入链验收。

布局支持保持原边界：完整干净 MD v1.2 的 RAID0/1/5；无元数据模式只自动
搜索等大小、offset-zero RAW 的 RAID0/5、限定条带与循环布局、NTFS/FAT32
直接卷或 MBR 主分区。不是任意 RAID、缺盘恢复或未知偏移的通用自动重组。

多个候选需要操作者显式选择，不自动确认第一个；搜索超限/无候选不能提交。
默认拒绝奇偶异常，仅明确管理员诊断允许 PARTIAL，保留机器重组/内容未人工
核验标识。`COMPLETE` 指重组读取与哈希核对完成，不是案件事实或独立参考
内容对照已经成立。此标识不因 Task completed 自动提升。

## 验证与发布区分

`tests/raid_validation/test_task_integration.py` 验证真实 RAID worker 与路由；
其简化 principal 注入仅为测试，不是生产认证方案。
`tests/raid_validation/http_task_e2e.py` 使用真实应用登录/服务间认证、实际
C++任务创建和两份独立定义正文的 EXT4 合成文件，检查逻辑镜像哈希、文件
提取内容、时间线、来源清单以及错误身份/清单/镜像变化拒绝。
`scripts/raid_task_browser.mjs` 使用实际前后端在原任务弹窗准备镜像，并
进入原文件页面，不 mock Task 或 RAID API。

全部服务端到端测试在新的仅 loopback 网络命名空间、独立数据目录和随机
端口运行；不会访问 8666/8090/8091 或真实历史 Task。
编译使用明确的 field-auth 兼容基线加新对象构建临时回归二进制，不覆盖
原 `build/forensic_analyzer`，也不等同新的冻结生产候选。

已存在的授权22组样本验证记录继续保留在仓库外，其内容约束/SDK回读结果
不是本轮网页全组验收或独立参考逻辑镜像对照。本轮是否通过原生调查证据
选择、最终 c001 引用及真实模型分析，必须分别记录，不用文件落库替代。
生产冻结包不会自动加载工作区修改；部署需另行受控构建、核验作业及切换。

## 本轮实测记录（2026-09-29）

| 检查 | 结果 |
| --- | --- |
| 现有 Task 表单/选择器/任务表回归 | 12项通过；无新增 RAID 页面 |
| RAID intake 路由/归属/角色/容量及实际 worker | 3项通过 |
| 无元数据网页 worker | RAID0/RAID5 两项通过；打乱输入、实际推断/准备、整个逻辑镜像与独立合成字节 oracle 相同 |
| 既有 RAID 解析回归 | 首轮64通过、2项需显式二进制；随后带指定分析器/mdadm的 integration 子集8项全通过 |
| 实际 HTTP Task 流水线 | 3个 MD RAID5 合成成员 → EXT4逻辑镜像 → 普通Task completed → 文件库2条已知文件 |
| 文件内容 | `case-note.txt`、`accounts.txt` 提取正文逐字节一致，成员哈希前后不变 |
| 既有调查链 | `file:/case-note.txt` 快照200、选择 main 报告证据200；新库v8；伪造 added_by 未生效，实际为 alice |
| 来源及拒绝路径 | 来源接口200；错误归属/清单摘要、无绑定普通/批量创建400；派生镜像变化409 |
| 无头浏览器 | 实际登录、`/tasks` 原弹窗选择/准备、`/files` 文件及来源展开通过；0运行时异常、0意外 API 失败 |
| 生产服务 | PID/监听未切换；DEPLOYMENT_PENDING |

两份正文SHA-256分别为
`677c96a4f49d6f9e61330f363f9f35c623c99ea301bab16e3df6bfe72172fd4c`、
`6692a93301d58bfc7a4374e582f7a8fd488eb9d6f3c4936cad8d60b802804b80`。
完整隔离结果保存在仓库外 `/tmp/tracelens-raid-task-http-e2e-final.json`，
实际合成数据/服务日志在该结果的 `root` 中，未将日志或任何真实检材提交Git。
本轮没有运行真实模型，没有生成新的最终 c001 叙事报告；已验证的是快照及
原有报告证据选择。AI disabled 下原LLM/Graphiti端点503被单独记录为预期
策略结果，不隐藏为成功，不修改生产的AI配置。
