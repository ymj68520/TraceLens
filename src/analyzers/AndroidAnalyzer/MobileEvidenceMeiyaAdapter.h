// MobileEvidenceMeiyaAdapter.h
// 美亚（MobileMaster FL-901）案件 → 统一取数包。
//
// 该适配器读已解密的 .dmf（设备规范化库），把 TBL_PR_* 表翻译成统一记录。
// 之所以只打 TBL_PR_*：它是美亚自己的跨设备统一 schema，三台设备列名一致，
// 一次映射即可覆盖全部检材；各应用的 AppsAmf/*.amf 私有表结构各异，作为
// 后续按应用扩展的输入保留在文件清单里。

#pragma once
#ifndef MOBILE_EVIDENCE_MEIYA_ADAPTER_H
#define MOBILE_EVIDENCE_MEIYA_ADAPTER_H

#include <string>

#include "MeiyaBackupExtractor.h"
#include "MobileEvidencePackage.h"

namespace mobile_evidence {

struct MeiyaAdapterOptions {
    std::string adapterVersion = "1.0";
    // 是否把 AppsAmf/*.amf 等未逐行解析的库登记进文件清单。
    bool inventoryApplicationDatabases = true;
    // 每个容器最多导出的行数（防止单表失控）。0 表示不限制。
    std::uint64_t maximumRowsPerTable = 500000;
};

// 从已初始化的美亚提取器构建统一包。
bool buildPackageFromMeiya(const meiya::MeiyaBackupExtractor& source,
                           const MeiyaAdapterOptions& options,
                           Package& out);

}  // namespace mobile_evidence

#endif  // MOBILE_EVIDENCE_MEIYA_ADAPTER_H
