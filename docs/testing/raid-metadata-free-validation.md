# 无元数据RAID0/5：本轮开发和实际样本验收

## 结果级别

无元数据RAW适配、有界自动布局搜索、CLI分类/查询/报告和记录级来源回读已实现。
**不是全部取证验收COMPLETE**：4组奇偶校验不一致、缺少独立已重组参考镜像，
文件内容抽查有数量上限；网页Task/Investigation/c001来源集成仍未上线。

## 实际输入与预期

用户明确获准目录 `D:\取证\RAID`（WSL `/mnt/d/取证/RAID`）。共22组目录分组、
98个RAW成员候选，最大13成员；含说明等材料的102个文件共4594600934字节。
没有将这些原始镜像、文件正文或私有结果提交Git。

要求：不手工预排盘序，不把目录名/编号作为参数，重组后读取文件、查询分析、
返回原始成员及对应内容。缺少独立参考镜像时，不能给出完整原文内容一致性结论。

## 最终布局与重组验证

所有组随机打乱输入顺序；只使用镜像内容搜索。每组均找到搜索范围内的唯一
结构候选。完成22/22组诊断逻辑镜像导出：

| 项目 | 实际结果 | 不能据此宣称 |
| --- | --- | --- |
| 自动布局 | 22个唯一结构候选；初轮7/10/13成员触及上限，加入MFT镜像及NTFS 3.1版本限定的记录编号约束后复测通过 | 通用任意RAID/任意偏移都能恢复 |
| 导出完整状态 | 18包COMPLETE，全量逻辑读取和源哈希复核完成 | 独立内容参考比对通过 |
| 部分状态 | 4包PARTIAL，观察到奇偶不一致，原样重组、不重建/填零/修复 | 奇偶不一致的原因已确认 |
| 源输入 | 所有导出均与准入清单原文件SHA-256一致，导出后再次检查 | 可以自动写回原盘 |

最终逐组私有记录：
`/root/tracelens-raid-validation/batch-a39d6c707f6d47e99fdfdabbc0102b6c/batch-summary.json`。
每组保留推断JSON、实际计划、候选ID、原始SHA-256、布局/派生镜像哈希、manifest。
22组推断合计93.93秒；包括重组、哈希、分析的总流程不是这个时间。

4个部分组的匿名sample_id：
`d3162971f536a8a1634e47e9`、`488b26b4c071f3aa7d416e60`、
`ecb19bb3941e0859562f54ce`、`04c82adb6fdf19730923b9d9`。
默认严格模式仍拒绝奇偶不一致，仅显式诊断允许部分包，不抹除警告。

## 逐组文件、分析与来源回读

22组均完成 `PASS_BOUNDED_ANALYSIS_AND_SOURCE`。每组：

1. SDK结果层抽查最多128个文件，生成私有 `results.db`、JSONL与绑定manifest；
2. 原始成员重新读取一个选定非空文件，内容哈希MATCH；
3. 现有C++ CLI生成文件库、分类、TXT查询统计、Markdown报告；
4. 不调用AI，不创建生产Task，不更改调查库或原始文件。

共2816个抽查记录，22次原始来源回读匹配。13个 `/$Secure` 对象没有按默认
数据流读取成功；它们是NTFS含命名流的系统对象，不能据此说文件已损坏。
当前结果层默认流覆盖有限，数量上限也明确保留为PARTIAL。

Native文件库记录数量分布：13组20393条、1组4335条、8组21618条。
这是文件库/分类结果数，不是“有罪证据数”或取证完整率。Native与SDK结果层
口径不同，不能拿这些计数做内容真值对照或相互抵消覆盖缺口。

逐组实际检查、数据库/报告哈希与回读材料：同一私有batch目录下的
`analysis-summary.json`、`*-analysis-check.json`、各包 `source-readback-samples.json`、
`native-analysis/analysis_manifest.json`。来源为MFT段/FAT目录项与真实成员
读轨迹；轨迹包含元数据，不虚构精确extent、磁盘偏移或WAL frame。

两组先行端到端示例：

- RAID0 NTFS：重组SHA-256
  `dcfcb98bdcad7229dafcd2b9b0acf649655c88485de82a6654d972be2f41b6dd`；
- RAID5 NTFS部分包：重组SHA-256
  `65cd64d64fc64ac5c7a2eca36248367fcdbd1ffaa8233123e12c6da369a96e7a`。

先行示例私有路径：
`/root/tracelens-raid-validation/batch-ad1abc1592f9447aab9865c6ae195539/`。
二者现有C++查询/报告和选定文件来源回读均成功；该事实不会把第二包升为COMPLETE。

## 安全、依赖与回归

- 64项合成/独立工具回归通过，0失败、0跳过；报告
  `build/raid-validation/nometa-tests.xml`，pytest60.65秒，wall69.50秒，最大RSS89940KiB。
  后续来源根边界和结果DB篡改断言也通过；不把合成测试当成教学/现场样本真值。
- 已知NTFS合成逻辑镜像作为独立字节oracle，不用同一parser生成expected；
  检查打乱输入、跨条带、成员映射、严格/部分校验、数据库篡改和来源根约束。
- 所有原文件仅O_RDONLY；拒绝绝对/越界/symlink、重复成员、未知布局和不支持
  范围；没有挂载、mdadm装配、修复、上传或未知程序执行。
- 102文件全量SHA-256在本轮前后保持一致；最后一次私有复核清单
  `/root/tracelens-raid-validation/fd6d67d66e6c4db884ed95a2feb18215/sample_manifest.json`。
- 分支/基线不变：`feature/android-forensics-report-structure`，
  `c7f1fc3c0281527fb635773515521ed23960aecc`；保留既有dirty状态，未部署或重启服务。
- C++、Python、nginx仍是本轮原PID `1715913`、`1943646`、`1943681`；未接触历史Task。
- 新增完整 `dissect.ntfs`/`dissect.fat`源码，固定提交、保留AGPL原许可。
  v2源码包包含10仓库/11快照/2880文件，哈希和使用范围见主说明。

## 仍需独立完成

- `CONTENT_REFERENCE_VALIDATION_REQUIRED`：未提供独立已重组参考镜像；
- `RAID5_PARITY_MISMATCH_CONTENT_UNCONFIRMED`：4组部分校验不一致；
- `FILE_ENUMERATION_LIMIT_REACHED`、命名流默认未导出：不是全文件内容验证；
- 前一CLI阶段保留 `WEB_TASK_AND_INVESTIGATION_INTEGRATION_PENDING`；后续已接入
  现有Task表单并进行合成任务、文件、调查快照/报告证据选择验证，见
  [系统镜像接入](../raid-system-image-integration.md)。这里22组样本的网页逐组
  验收与成员级精确回跳仍未完成，生产冻结服务也不因工作区修改自动上线；
- 项目方真实现场样本和TB规模仍未验证；教学模型通过不能替代它们。

再现整个批次须显式传入私有清单和批准的源码/分析器路径，见
`scripts/raid_validate_samples.py`、`scripts/raid_analyze_batch.py`；重试使用新私有
批次目录，不覆盖已验证包。详见 `docs/raid-metadata-free-input.md`。
