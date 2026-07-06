# 现场测试发现报告 — 多分区镜像数据丢失问题

> 测试日期：2026-07-06
> 测试数据：盘古石杯决赛真实镜像（../TestImgs/）
> 测试环境：AI/LLM 不可用（模拟甲方现场）
> 严重程度：🔴 **致命**——影响几乎所有真实取证镜像

## 一、问题摘要

**系统在处理多分区磁盘镜像时，只解析第一个能打开的分区，静默丢弃其余所有分区的数据。** 用户看到"任务完成"，但实际只获得了镜像 5-10% 的数据，Windows/Linux 平台专项分析因此几乎得不到任何 artifact。

这不是偶发——**所有含分区表的真实镜像都受影响**。只有"整个镜像就是一个文件系统"（无分区表，如已挂载的单分区 dd）才能正常工作。

## 二、测试证据

用三个真实镜像测试，全部复现：

| 镜像 | 大小 | 实际分区数 | 解析的分区 | 抽取文件数 | 预期文件数 | 平台专项 |
|---|---|---|---|---|---|---|
| `Server.dd` | 20G | 4（含 LVM） | 1（NTFS boot 区） | 30 | 几十万 | ❌ 无 linux.db |
| `window.e01` | 52G | 10 | 1（小 NTFS boot 区） | 162 | 几十万 | ❌ windows.db 全空 |
| `darkwing_companion.img` | 2.6G | 4（FAT32+Ext4） | 1（FAT32 boot 区） | 415 | 几千 | ❌ linux.db 全空 |

### 关键观察

1. **抽到的都是 boot/系统保留分区的文件**，不是用户数据分区
   - window.e01 抽到的 162 个文件全是 `$Extend/$RmMetadata/...` 等 NTFS 系统文件
   - drone 抽到的 415 个是 FAT32 boot 区文件
2. **平台专项 DB 存在但全空**
   - windows.db 有 33 个表，但每张表 0 行
   - linux.db 同样全空
   - 原因：专项分析器依赖文件抽取，而抽取没走到含 artifact 的分区
3. **任务状态显示 completed**，前端无任何告警——**用户无法察觉数据丢失**

## 三、根因定位

**文件**：`src/analyzers/ImageAnalyzer/ImageAnalyzer.cpp`
**函数**：`ImageAnalyzer::openFileSystem()`（L97-199）

### 缺陷代码（L109-138）

```cpp
// Try each allocated partition until we find one that works
for (TSK_PNUM_T i = 0; i < vsInfo->part_count && !fsOpened; i++) {
//                                        ^^^^^^^^^^
//                找到第一个能打开的就停，不遍历后续分区
    const TSK_VS_PART_INFO* part = tsk_vs_part_get(vsInfo, i);
    if (part && (part->flags & TSK_VS_PART_FLAG_ALLOC)) {
        offset = part->start * vsInfo->block_size;
        // ...
        fsInfo_ = tsk_fs_open_img(imgInfo_, offset, TSK_FS_TYPE_DETECT);
        if (fsInfo_) {
            // ...
            fsOpened = true;
            break;  // ← 找到第一个就 break，后续分区全跳过
        }
    }
}
```

### 问题本质

代码把"打开文件系统"设计成**单选**（找一个能用的就停），但真实取证镜像的多个分区**都需要解析**。正确的做法应该是**遍历所有分区，每个可识别的文件系统都走一遍，结果合并入库**。

### 次要问题：LVM/加密卷无提示跳过

`Server.dd` 的主数据在 LVM 分区（0x8e），TSK 不支持 LVM。代码尝试后静默跳过（`Warning: Failed to initialize Linux analyzer` 仅在日志，不反馈前端）。同理 LUKS、BitLocker 等加密卷也会被静默跳过。

## 四、影响范围

- **Windows 取证**：注册表、事件日志、Prefetch、Amcache、浏览器历史等几乎全部丢失
- **Linux 取证**：系统日志、auth、bash 历史、cron 等几乎全部丢失
- **文件分类/时间线/搜索**：只覆盖 boot 分区，用户数据分区完全缺失
- **AI 分析**：即使 LLM 可用，也没有足够数据可分析

## 五、现场应对建议（短期）

### 去现场前

1. **降低客户预期**：明确告知当前版本对多分区/LVM 镜像支持有限，可能需要预处理
2. **准备预处理工具**：带上能手动提取分区的工具（ewfmount + losetup -P），现场把目标分区单独导出成单分区 dd，再喂给系统
3. **验证脚本已加入分区检查**：见下方"脚本增强"

### 现场操作

**遇到"任务完成但文件特别少"时**（典型症状：< 1000 文件 for > 10G 镜像）：

```bash
# 1. 确认镜像分区情况
mmls -i ewf image.E01        # E01
mmls image.dd                 # raw

# 2. 如果有多个数据分区，手动导出目标分区
ewfmount image.E01 /mnt/ewf
losetup -P -f --show /mnt/ewf/ewf1   # 得到 /dev/loopXpY
dd if=/dev/loopXpY of=partition_NN.dd bs=4M   # 导出单分区

# 3. 用单分区 dd 重新跑分析
bash scripts/onsite_smoke_test.sh partition_NN.dd
```

## 六、修复方向（中长期，代码层面）

### 修复 1：遍历所有分区（核心）

`ImageAnalyzer` 需要重构为**多文件系统遍历**模式：
- 遍历所有 alloc 分区，每个能打开的文件系统都 walk 一遍
- 文件路径加分区前缀（如 `/part2/Users/...`、`/part3/var/log/...`）避免冲突
- inode 去重（不同分区的 inode 会重复）

### 修复 2：分区失败要反馈

- LVM/加密卷检测到时，在任务结果里明确标注"分区 X 因 Y 未解析"
- 任务状态可考虑加 `partial`（部分完成）而非纯 `completed`
- 前端展示分区解析报告

### 修复 3：分区解析后置选择

- 对于"只想看 Windows 数据"的场景，识别出最大的 NTFS 分区优先解析
- 或让用户选择要解析哪些分区

## 七、已验证正常的部分

为避免过度悲观，明确哪些是**好的**：

- ✅ **AI 降级行为**完美：LLM/Neo4j 不可用时服务不崩、health 正常、案件分析优雅失败
- ✅ **单文件系统镜像**（如 test_image.img）分析完全正常：抽取/分类/时间线/统计/导出全通
- ✅ **HTTP 任务管理/数据库写入/产物生成**管线正常
- ✅ **E01 (libewf) 和 TSK 文件系统解析**本身工作正常（能正确识别 NTFS/FAT32/Ext4）
- ✅ **重构 bug 已修**：案件智能分析端点不再 500

**结论：系统的"管道"是通的，问题出在"只接了一根管子（一个分区）就关了阀门"。**
