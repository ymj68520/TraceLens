# 阿里云 Linux 系统盘导出包

在原任务创建、文件索引、Linux 解析、时间线、智能分析、图谱和报告流程中，增加 `aliyun-image` 来源选项。没有独立的云镜像分析任务或报告管线。

该入口使用 Linux/WSL 后端；Windows 原生构建会明确提示需要 Linux 运行环境。

## 前端操作

1. 在服务端配置证据目录，例如 `TRACELENS_EVIDENCE_INBOX=/mnt/e/取证/testimgs/阿里云服务器镜像`。
2. 在“分析任务 → 检材预检”选择 `.raw.tar.gz`，执行“后台计算完整 SHA-256”。
3. 点击“按此来源新建阿里云分析任务”，填写案情并提交。创建弹窗也提供“阿里云服务器镜像”选项，并提示先完成预检。
4. 原任务后台校验、解包到任务自己的工作目录，然后进入普通磁盘与 Linux 分析；后续仍使用文件、时间线、调查和报告入口。

预检只进行有界包头识别和原包哈希，不会提前展开 40 GiB 镜像，也不宣称完成 gzip CRC 或文件系统验证。完整容器校验在任务准备阶段执行。已解出的 RAW 继续选择普通“磁盘镜像”。

## 原任务 API

先调用原有预检接口：`GET /api/evidence-intake/candidates` 获取候选编号，以 `candidate_id` 和 `full_hash: true` 调用 `POST /api/evidence-intake/jobs`，再通过 `GET /api/evidence-intake/jobs/{id}` 查询进度。仅在 `status=completed` 且 `integrity_status=verified` 后，用该结果创建任务。

仍使用 `POST /api/tasks`。历史字段 `android_source` 在此处作为来源选择器沿用：

```json
{
  "image_path": "/evidence/file_m-xxx_system.raw.tar.gz",
  "android_source": "aliyun-image",
  "preflight_job_id": "预检返回的任务编号",
  "preflight_source_sha256": "预检返回的完整SHA-256",
  "preflight_detected_kind": "aliyun_raw_export",
  "scenarios": ["linux"],
  "platform_analyze": true,
  "llm_analyze": true,
  "filter_profile": "general_forensics",
  "case_description": "本次待核问题"
}
```

服务端校验预检记录与来源路径、大小，并固定 Linux 场景。创建请求不做多 GB 的同步重哈希；工作线程在解包时重新计算完整原包 SHA-256，在校验通过前不开始文件系统分析。缺预检或不支持的来源返回 400，路径/大小已变化返回 409；同大小内容变化会在后台哈希核对时使任务失败。

## 来源与读取链

- 支持 gzip TAR 中一个普通 `.raw` 数据成员，可含空目录及有界 PAX/GNU 长名元数据；支持实际样本的 gzip FEXTRA 和 TAR 大文件大小字段。
- 拒绝越界/绝对成员路径、链接/特殊文件、多个数据成员、稀疏 TAR 变体、损坏/截断压缩流、非零尾随内容、超限元数据和超过 2 TiB 的声明 RAW。
- 使用固定输出文件名，不按包内路径写文件。只读源文件，不启动检材系统。
- 输出前保守检查展开大小加 512 MiB 的空间，实际分析还需额外空间。RAW 的全零块以稀疏文件方式写入。
- 原包哈希、解出 RAW 哈希、包内成员名、大小和校验结果保存在 `work/aliyun_image/source_manifest.json`。任务元数据另保存该清单哈希。
- 校验成功后 `task.image_path` 指向任务内已验证 RAW，保证原有文件提取/预览/模型读取均使用此副本；原包路径保存在 `metadata.aliyun_original_source`，任务列表仍显示原文件名。
- `metadata.aliyun_prepared=true` 仅表示 RAW 准备完成，不代表整个分析或报告完成。
- 取消与失败不会发布未验证 RAW。正常取消清理临时文件；已经验证的产物可能保留供核对。
- 识别依据是导出包/磁盘结构，不是对阿里云账号、厂商签名或导出过程的真实性认证。

## Linux 与宝塔

原 Linux 模块新增 `/www/wwwlogs/`、宝塔虚拟主机配置及 Nginx 配置路径。修复了原 Nginx 调用将文件路径误当正文的问题。现存的普通访问日志按行解析、分批写库，保留来源文件、分区、inode、行号、字节偏移与原文；重叠候选路径不重复解析同一个 inode。

宝塔面板自身的 JSON 请求日志单独保存到 `linux_panel_requests`，来源/同内容副本映射保存到 `linux_panel_request_sources`，不会冒充网站访问日志。字段布局依据样本内 `class/public.py` 的 `write_request_log`，仅解析 JSON，不执行其中的参数文本。同内容文件只解析一次，重复来源保留映射；同一文件内的重复请求行仍保留。

面板时间保留 `timestamp_raw`，不擅自给无时区的本地时间赋予 UTC 偏移，因此不会将其强行插入绝对时间线。标准 Nginx 有效时间事件进入原时间线，`source_id=nginx:<记录编号>`。压缩、已删除日志及无法识别/过长的行不等于已恢复：原文件仍在索引中，面板来源表记录拒绝行数。普通访问日志行上限 16 KiB，面板 JSON 行上限 1 MiB、嵌套层级上限 32。

本选项不新增 Windows 云盘、qcow2/VHD、加密备份、挂载启动、MySQL 业务表恢复能力。原有图谱和报告完成门控保持生效；模型/服务失败不能通过解包成功掩盖。

## 回归

- `python_service/tests/unit/test_aliyun_image.py`：扩展 gzip 头、完整哈希/CRC、异常成员、空间、取消、内容变化和上限。
- `tests/integration/test_aliyun_image_http.py`：真实 C++ Task/预检/解包/Linux/时间线/文件提取；模型与图谱为本地桩，验证原报告等待门控。可用 `--source` 和独立 `--work` 测试真实导出包；真实材料模式关闭模型分析。
- `CreateTaskModal.aliyun.test.jsx` 与预检组件测试：来源绑定、路径改变后失效、Linux 参数及原筛选流程。
