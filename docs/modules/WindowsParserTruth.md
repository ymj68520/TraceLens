# Windows 解析真实性

Prefetch 使用 libscca，EVTX 使用既有 libevtx / python-evtx。缺失解析能力或解析失败时不猜测执行次数、时间、程序路径、SID，也不把错误信息送入模型或报告正文。任务创建、分析和报告入口不变。

## 原生依赖

在 Linux / WSL 的既有构建环境中运行：

```bash
bash scripts/build_libscca.sh "$HOME/.cache/tracelens/libscca/20260527"
export PKG_CONFIG_PATH="$HOME/.cache/tracelens/libscca/20260527/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
cmake -S . -B build
cmake --build build --target forensic_analyzer test_windows_parser_truth_gtest -j2
ctest --test-dir build -R WindowsParserTruthTests --output-on-failure
```

脚本下载固定版本及 SHA256 校验的源包，使用包内 libbfio，并隐藏内部依赖符号。不得直接部署导出了 libbfio、libfdatetime 等私有符号的 libscca：这些符号可能干扰程序原有的 libevtx。单独解析通过不足以证明整程序兼容，原生测试会同时加载两种解析库。

CMake 未找到 libscca 时仍可构建，Prefetch 返回 unsupported，次数和时间保持未知。正式启用 Prefetch 解析必须安装经过有效样本和完整流程验证的库。Python 仍使用 requirements.txt 中的 libscca-python；本轮验证版本为 20260527。EVTX 的 Python 补充解码路径动态读取既有 libevtx，只接受标准记录索引与记录 ID 同时匹配的 XML。

## 状态与来源

- Prefetch 的 parse_status、parse_error、parser_version 与原始 FILETIME 单独保存；执行次数 0 与未知 NULL 不同。
- Prefetch 创建时间来自原文件元数据，不由执行时间推断；完整程序路径不能从文件名猜测。
- EVTX 按 Provider 和 EventID 解释事件；级别 0 至 5 分别为始终记录、严重、错误、警告、信息、详细。
- 标准记录与恢复记录分别标记；缺失 SID、事件时间或事件 ID 保持未知，不填默认事实。
- parser_outcomes 保存空日志、错误、仅元数据和部分解析结果。诊断字段不属于证据正文。
- Python ExtractionResult 分离状态、内容、记录、诊断和覆盖；无可读内容时抛出 DocumentContentUnavailableError，调用者不得继续把二进制、元数据占位符或工具错误当成正文。
- 报告冻结保留部分解析限制和不可读原因；既有冻结报告、输入哈希和历史快照不回写。

## 历史数据与续跑

数据库增加新列时，历史行标记 legacy_unverified，保留原值供历史追溯，不自动认证旧值。新分析候选排除失败及未复核的 Prefetch / EVTX 记录。Windows 平台阶段指纹含规则版本及解析库版本，CLI 首次运行与续跑均执行正确的平台解析分支。

对已有任务执行重新分析会产生新的派生结果；历史报告保持原冻结内容。本变更不自动重写既有报告，也不修复尚未纳入本阶段的候选排序、来源身份及 Windows 时间线桥接问题。

## 验证

测试使用仓库中的自制有效 SCCA / MAM 样本和损坏样本。真实 PC 样本仅在本地验收目录读取，未加入仓库。测试覆盖 UTC 转换、未知与零值、EVTX 3.2、提供程序冲突、最近事件抽样、原生 XML 补充解码的身份检查、数据库升级和错误文本阻断。
