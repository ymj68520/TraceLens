// MobileEvidenceMiuiAdapter.h
// MIUI 离线备份 → 统一取数包（mobile_evidence::Package）。
//
// 该适配器是"取数阶段"的唯一入口：它只关心 MIUI 的容器布局与记录编码，
// 产出的包不含任何分析结论。分析阶段由 MobileEvidenceAnalysis 消费。

#pragma once
#ifndef MOBILE_EVIDENCE_MIUI_ADAPTER_H
#define MOBILE_EVIDENCE_MIUI_ADAPTER_H

#include <string>

#include "MobileEvidencePackage.h"

class MiuiBackupExtractor;

namespace mobile_evidence {

struct MiuiAdapterOptions {
    std::string backupPassword;   // 加密 .bak 的密码（暂未启用，保留）
    bool includeExternalStorage = true;
    std::string adapterVersion = "1.0";
};

// 从已初始化的 MiuiBackupExtractor 构建统一包。
// 返回 false 仅在无法读取备份清单时；单个成员读取失败会记入 coverage 而不中断。
bool buildPackageFromMiui(MiuiBackupExtractor& source,
                          const MiuiAdapterOptions& options,
                          Package& out);

}  // namespace mobile_evidence

#endif  // MOBILE_EVIDENCE_MIUI_ADAPTER_H
