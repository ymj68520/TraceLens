// MeiyaBackupExtractor.h
// 美亚柏科（MobileMaster FL-901）案件的取数后端。
//
// 一个案件目录的形状：
//   <案件>/
//     <案件>.mf                      案件库（案件/设备/策略）
//     MFCExcerpt.db, MFCMark.db      笔录/标记库
//     SummaryMarkInfo.bm             标记摘要
//     <设备>/
//       <设备>.dmf                   规范化业务库（TBL_PR_*）
//       config.db                    设备配置库
//       <设备>_RECORD_MFC.DB         操作审计流水
//       AppsAmf/*.amf                每应用解析库
//
// 容器都以 1024 字节周期 XOR 混淆，掩码按文件族在运行时推导
// （见 MeiyaContainerCrypto）。本类把解出的 SQLite 暴露给统一取数适配器。

#pragma once
#ifndef MEIYA_BACKUP_EXTRACTOR_H
#define MEIYA_BACKUP_EXTRACTOR_H

#include <cstdint>
#include <filesystem>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "MeiyaContainerCrypto.h"

namespace meiya {

// 一个已解密的容器及其元数据。
struct DecryptedContainer {
    std::filesystem::path sourcePath;
    std::filesystem::path decryptedPath;  // 位于私有临时目录
    std::string family;                   // case / device / appdb / record / mark
    std::string deviceSerial;             // 从设备目录名推断，案件级容器为空
    std::string encryptionLabel;          // 实际采用的推导策略
    std::size_t schemaEntries = 0;
    std::uint64_t containerSize = 0;
    std::string status;                   // decrypted / failed / skipped
    std::string detail;
};

// 设备级元数据（来自 .dmf 的 TBL_PR_DEVICE_INFO）。
struct DeviceSummary {
    std::string serial;       // 设备目录名，例如 V1824BA
    std::string manufacturer;
    std::string model;
    std::string imei;
    std::string mac;
    std::string bluetoothMac;
    std::string characteristic;
    std::string sourceContainer;
};

class MeiyaBackupExtractor {
public:
    explicit MeiyaBackupExtractor(std::string root);
    ~MeiyaBackupExtractor();

    MeiyaBackupExtractor(const MeiyaBackupExtractor&) = delete;
    MeiyaBackupExtractor& operator=(const MeiyaBackupExtractor&) = delete;

    // 识别：目录含 <name>.mf 或 <device>/<device>.dmf 即为美亚案件。
    static bool recognizes(const std::string& path);

    bool initialize();

    const std::vector<DecryptedContainer>& containers() const { return containers_; }
    const std::vector<DeviceSummary>& devices() const { return devices_; }
    const std::string& error() const { return error_; }
    const std::string& caseRoot() const { return caseRoot_; }

    // 按 family 取第一个解出的容器（供适配器读取）。
    const DecryptedContainer* findContainer(const std::string& family) const;
    std::vector<const DecryptedContainer*> findContainers(const std::string& family) const;

private:
    bool decryptFamily(const std::string& family,
                       const std::vector<ContainerCandidate>& candidates);
    // 判断一个已推导的掩码是否适用于该族的容器（同案件内掩码共享）。
    bool canDecryptFamily(const std::vector<ContainerCandidate>& members,
                          const DerivedKey& key) const;
    void readDeviceSummary(const DecryptedContainer& container);

    std::string root_;
    std::string caseRoot_;
    std::string error_;
    std::filesystem::path temporaryRoot_;
    std::vector<DecryptedContainer> containers_;
    std::vector<DeviceSummary> devices_;
    // family → 推导出的掩码（同族共用）
    std::map<std::string, DerivedKey> masks_;
};

}  // namespace meiya

#endif  // MEIYA_BACKUP_EXTRACTOR_H
