# RAID只读重组：首批开发与验收边界

## 本轮范围

在 `feature/android-forensics-report-structure` 上增加独立、可离线运行的
RAID 核心、命令行入口、源码供应链清单及合成测试。不改变既有服务配置、
历史 Task、调查库、Android 解析规则或 AI 开关。

首批支持：完整、干净、元数据一致的 Linux MD **v1.2** RAID0/1/5 成员集。
成员选择顺序和文件名不决定盘序；盘序来自经校验的 metadata role。
只接受明确指定的普通文件，不扫描宿主机设备，不装配 `/dev/md*`。

## 真实调用链

```text
显式 selection.json（成员及每个成员的完整 EWF 分段集合）
  -> raid_cli.py inspect / export
  -> 目录 fd 逐级约束 + 只读 RAW / 固定 ewfprobe 解码
  -> MD v1 有界元数据与 checksum 检查
  -> dissect.volume MDPhysicalDisk / MDVirtualDisk
  -> 成员角色、阵列标识、版本事件、布局和状态一致性检查
  -> 上游条带映射 + 本地有界读取修正
  -> RAID5 校验 / RAID1 副本一致性核对
  -> 只读逻辑视图
  -> 显式限额导出 logical.img + raid_manifest.json
  -> 现有 TSK / TraceLens CLI（只处理派生逻辑镜像）
```

`inspect` 的 `READY_READONLY` 仅代表元数据准入通过，不代表全量内容已验证。
`export` 的 `COMPLETE` 表示全量逻辑读取及源哈希复核成功，不代表所有应用
或文件系统都已经被解析。包内独立保留 `REAL_SAMPLE_REQUIRED`。

## 使用步骤

显式指定获准检材目录。以下路径是占位符，不会自动探测真实检材：

```json
{
  "schema_version": 1,
  "members": [
    {"files": ["member-z.raw"]},
    {"files": ["member-a.raw"]},
    {"files": ["member-m.raw"]}
  ]
}
```

E01 成员写为 `{"files":["disk.E01","disk.E02"]}`。这里的顺序是该成员的
EWF 分段顺序，不是 RAID 成员盘序；不自动搜索未指定分段。

```sh
python3 scripts/raid_vendor_sources.py verify
python3 scripts/raid_cli.py inspect --inbox /approved/member-directory --selection /local/selection.json
python3 scripts/raid_cli.py export --inbox /approved/member-directory --selection /local/selection.json --output-root /local/separate-output --max-bytes 1073741824
python3 scripts/raid_cli.py verify --package /local/separate-output/RUN_ID
```

输出目录必须预先存在且与检材目录互不包含。默认导出上限 **1 GiB**，
可由操作人员显式调整；不默认复制 TB 级镜像。后续虚拟读取桥接未完成。

CLI 默认使用 512 MiB 进程地址空间限额和 CPU 时间限额，作用于独立 worker，
不改变 HTTP 服务或宿主机资源配置。缺少资源控制时拒绝启动，不无界降级。
库内调用不自行修改调用者 rlimit；未来 API 必须使用受限独立 worker，
不能在长期服务的主进程直接调用不可信 EWF 的索引器。元数据索引过大将
明确失败，不表示该 TB 级格式已通过性能验收。

## 来源与失败输出

每次导出创建独立 UUID 目录，包含：

- `logical.img`：重组派生镜像，不是某一成员原始文件；
- `raid_manifest.json`：版本、阵列 UUID、成员角色、RAW/EWF 来源、原始
  分段文件 SHA-256、成员数据偏移、逻辑大小、布局哈希、派生镜像哈希；
- 全量源哈希、读取/校验/导出、源重哈希分别计时；
- `manifest_sha256`：排除自身字段计算，避免自引用。

完整源码发布包为 `third_party/raid/sources.bundle.tar.gz`，覆盖 8 个上游仓库的
9 份固定提交快照，共 2806 个上游文件，包含许可证和被 `.gitignore` 忽略的
Windows 源码及 fuzz seeds。不是只有下载链接或预编译二进制。

检材文件始终以只读 fd 持有，拒绝绝对路径、`..`、目录/文件 symlink、
特殊设备和重复文件身份。读取及导出校验源身份和变化；导出前后全量哈希。
异常、取消、超时和磁盘不足不得发布有效完成清单。部分输出保持
`logical.img.partial` / `failure.json`；中断后的目录没有完成清单就不能交付。

EWF 的 `data_offset` 是**解码后成员逻辑字节偏移**，不能冒充压缩 E01
物理文件偏移。当前没有声明文件内容的逐 extent 成员映射、磁盘扇区或
WAL frame 定位，也不把派生镜像本身伪装成原始单盘。

## 上游复用与修正

完整源码见 `third_party/raid/`，有固定提交和逐文件哈希。新适配代码及测试
采用 AGPL-3.0-or-later，现有 MIT 主许可证不变，发行义务见该目录 README。

本地适配保留上游源码原样：

1. 修正 RAID5 `_read` 把剩余总长度当作当前条带读取长度的问题，仍复用
   上游 `_get_stripe_read_info`，不另写 RAID 布局算法。
2. 按 MD v1 component sectors 和有效成员数计算逻辑容量，避免 RAID5
   截短输出；所有读取限制在有效 component 范围内。
3. 不接受上游“缺盘数量允许”作为已有 parity reconstruction 的证明。
4. 固定兼容的 cstruct 4.7，不使用不满足 `<5` 要求的主分支。

## 尚未实现 / 尚未验证

- 前端多成员勾选、生产 Task 准入、nbdkit/libnbd/TSK external 虚拟桥；
- Investigation 的成员级来源回跳及版本化报告来源绑定；
- 更广范围的无元数据布局：当前RAW RAID0/5的有界内容搜索、诊断重组和来源回读
  见 `docs/raid-metadata-free-input.md`；`raid_recovery`的ASCII启发式仍未启用；
- DDF/IMSM、MD 0.90/1.0/1.1、RAID6/10、缺盘恢复、reshape、bitmap、journal、
  bad-block、其他非零 MD feature，以及成员容量不等的阵列；
- 整盘内自动发现 MD 分区：首批要求输入本身是 MD 成员的逻辑范围；
- 原始 RAW 分段、未知格式、加密解锁、厂商私有布局和 TB 性能。

MD v1 元数据识别不等于上述版本和布局均经真实样本验收。没有授权真实
RAID 样本，不自动扫描现有检材，不以 HTML 报告替代 RAID 镜像验收。

## 合成回归入口

```sh
PYTHONDONTWRITEBYTECODE=1 python_service/.venv/bin/python -m pytest tests/raid_validation -q --import-mode=importlib -p no:cacheprovider
bash scripts/build_raid_md_examine.sh
```

`mdadm` 在独立临时目录编译，不安装服务。只允许对明确选定合成文件执行
`--examine --config=/dev/null`，不执行 assemble/create/force/update。
验收用预先已知逻辑字节作为 oracle，不用生产 parser 的结果生成 expected。

真实 CLI 集成测试发现并修复既有路径别名断点：TSK 文件索引保存 `/data/...`，
Android 候选路径为 `data/...`；提取层使用参数化双路径匹配，仍拒绝多条匹配，
不修改保存路径、不新增伪造文件、不改变 Android 字段解析。修复采用临时
增量编译/链接验证，当前运行服务和原 `build/forensic_analyzer` 不被覆盖。

生产 HTTP Task 的 `android.db` 接入仍未宣称通过：本轮验证的是现有 C++ CLI
路径，Android 工件按该路径既有语义写入统一 `*_files.db`。不要将 CLI 验证
混同于 Task/Investigation/报告的全链验收。

## 获准实验样本登记

用户现已提供 `D:\取证\RAID` 作为后续验收输入。本轮完成22组、98个成员
候选的只读清单及全文件哈希检查，尚未完成这些模型的重组验收，不能将
上述合成MD验收扩展为实验模型兼容。实际样本未命中当前探测器检查的MD
超级块位置，下一阶段优先完成无MD元数据适配。详情见
`docs/testing/raid-authorized-sample-intake.md`；清单和样本均留在仓库外。
