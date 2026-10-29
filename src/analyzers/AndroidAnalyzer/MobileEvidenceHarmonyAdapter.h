// MobileEvidenceHarmonyAdapter.h
// 鸿蒙已解密备份 → 统一取数包（mobile_evidence::Package）。
//
// 该适配器持有鸿蒙的解析规则；HarmonyArtifactParsers 只把包落进 android.db。

#pragma once
#ifndef MOBILE_EVIDENCE_HARMONY_ADAPTER_H
#define MOBILE_EVIDENCE_HARMONY_ADAPTER_H

#include <filesystem>
#include <string>

#include "MobileEvidencePackage.h"

class HarmonyBackupExtractor;

namespace mobile_evidence {

struct HarmonyAdapterOptions {
    std::string adapterVersion = "harmony-decrypted-v1";
};

// 从已初始化的 HarmonyBackupExtractor 构建统一包。
// temporaryRoot 用于暂存待解析的数据库；调用方负责其生命周期与证据隔离。
// 证据在索引后被改动时抛出 std::runtime_error（EVIDENCE_CHANGED_AFTER_INDEX）。
bool buildPackageFromHarmony(HarmonyBackupExtractor& source,
                             const std::filesystem::path& temporaryRoot,
                             const HarmonyAdapterOptions& options,
                             Package& out);

}  // namespace mobile_evidence

#endif  // MOBILE_EVIDENCE_HARMONY_ADAPTER_H
