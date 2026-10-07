# 无元数据RAID0/5：适配、候选与来源回读

## 真实调用链

```text
已授权成员选择（输入随机排序，文件名不是算法输入）
  -> boot/MBR锚点 + MFT/MFT镜像或FAT副本约束
  -> 确认NTFS 3.1后才使用XP记录编号；不对NTFS 3.0套用该字段
  -> 有界all-different盘序搜索
  -> Dissect条带映射 + NTFS/FAT交叉引用检查
  -> 唯一结构候选 / 歧义 / 搜索超限
  -> 操作人员确认候选（不需要手工排列成员）
  -> 原成员SHA-256 + 只读逻辑读取 + 源重哈希
  -> logical.img + raid_manifest.json
  -> 独立results.db / JSONL / 现有C++分类、查询、Markdown报告
  -> record_id -> MFT段/FAT目录项 -> 原始成员重新读取 -> 文件哈希MATCH
```

本轮只自动搜索等大小、offset-zero RAW成员，级别0/5、RAID5四种循环布局、
4KiB至1MiB的2幂条带，文件系统为NTFS/FAT32的直接卷或MBR主分区。
不伪造MD超级块、阵列/设备UUID，不更改Android解析、证据键或v7/v8协议。

复用固定的 `dissect.volume`、`dissect.ntfs`、`dissect.fat`；新增的是候选
编排、约束和校验，不从零另写条带或文件系统解析器。

## 状态不是“取证完整率”

| 状态 | 含义 |
| --- | --- |
| `UNIQUE_STRUCTURAL_CANDIDATE` | 指定搜索范围只有一个通过结构检查的候选；不是独立内容对照通过 |
| `AMBIGUOUS` | 多个候选，不自动选择第一个 |
| `SEARCH_LIMIT_REACHED` | 时间/排列/候选上限，不能声称唯一，即使当前只找到一个 |
| `NO_SUPPORTED_CANDIDATE` | 当前搜索范围未找到，不等于损坏或加密 |
| 导出 `COMPLETE` | 全逻辑读取和源哈希复核完成；仍有内容参考对照缺口 |
| 导出 `PARTIAL` | 显式诊断读遇到奇偶不一致，不恢复、填零或替换字节 |

默认严格拒绝RAID5奇偶不一致。仅显式 `--allow-partial` 允许保留诊断重组，
manifest记录不一致请求/位置、`recovered_bytes=false`、PARTIAL及内容未确认。
原因保持未知，不推断为未初始化、损坏或加密。默认包验证拒绝PARTIAL；明确
允许部分包时仅验证交付包哈希，不提升业务状态。结构验证的引用数量有限，
`truncated`保留；文件结果的数量、大小和深度上限也要明确计为PARTIAL。

## 查询、分析和来源

- `raid/raw.py`提供只读逻辑视图、布局清单和成员读取映射。
- `raid/infer.py`使用内容约束搜索；目录标签和文件编号不能作为参数。
- `raid/results.py`生成独立 `file-results/results.db` 和JSONL；结果标为
  `raid_reassembled_file` / `MACHINE_EXTRACTED_UNVERIFIED`，不写 `android.db`
  或HTML派生的 `records.db`。
- `raid/pipeline.py`调用现有C++ CLI，生成文件库、分类、查询统计和Markdown
  报告；使用私有运行目录与配置，不创建生产Task、不修改旧调查库、不调用AI。

来源记录包含结果ID、文件系统路径、size、SHA-256、volume_offset、NTFS MFT
segment或FAT cluster/path。这些是实际SDK定位，不冒充原始数据库行号。
回读必须显式传入批准的inbox，与manifest根匹配，核对原成员哈希、结果DB
哈希和来源manifest绑定后，再读原始成员并比较文件哈希。

`member_reads`是 `READ_TRACE_INCLUDES_METADATA_NOT_EXACT_FILE_EXTENTS`，
包含解析所需元数据，不是所有文件内容的精确extent证明。驻留NTFS内容保留
MFT段定位，不编造磁盘扇区、WAL frame或字节偏移。网页已增加现有新建Task
弹窗内的RAID来源选项，准备逻辑镜像后复用TSK流水线（见
[系统接入](raid-system-image-integration.md)）。独立CLI的SDK回读不能冒充
网页精确成员extent回跳；本轮接入也不等于生产冻结服务已加载。

成员路径沿用目录fd边界校验，拒绝绝对路径、`..`、symlink、特殊设备和重复
成员；输出与检材目录互不包含。候选记录source_revision，拒绝推断后变化的
输入。受限批次前后和全量源重哈希检查身份，避免每个小读重复Windows/WSL
元数据RPC；变化时不发布完成结果清单。原检材永不打开写入。

## CLI

```sh
python3 scripts/raid_cli.py infer --inbox /approved/members --selection /private/selection.json --timeout 120
# 将选中的候选保存为私有JSON，保留source_revision：
python3 scripts/raid_cli.py raw-export --inbox /approved/members --selection /private/selection.json --plan /private/chosen.json --output-root /private/output
python3 scripts/raid_cli.py files --inbox /approved/members --package /private/output/RUN_ID --volume-offset 32256
python3 scripts/raid_cli.py source --inbox /approved/members --package /private/output/RUN_ID --record-id RECORD_ID
python3 scripts/raid_cli.py analyze --package /private/output/RUN_ID --analyzer /approved/isolated/forensic_analyzer
```

无元数据E01、非零数据偏移、GPT/扩展分区、RAID6/10、缺盘重建、其他条带/
布局及未知文件系统不在本轮自动识别承诺内。没有独立参考镜像时保留内容
对照缺口。不启用备用公网模型或启动时下载。

## 完整开源源码

旧 `sources.bundle.tar.gz` 不覆盖。新增 `sources.bundle-v2.tar.gz` 包含10个
上游仓库、11份源码快照、2880个上游文件；SHA-256为
`eb375c72329839833a7782a588a3b5ee1fae9f8074b42e4cf2e34e9ac9d46891`。
新适配和测试采用AGPL-3.0-or-later，保留每个上游原许可。
`raid_recovery`的ASCII启发式仍未启用：它不是这些小条带NTFS/FAT模型的通用
识别器。本轮主要复用Dissect读取器与文件系统解析器。
