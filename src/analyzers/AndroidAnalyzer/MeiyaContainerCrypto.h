// MeiyaContainerCrypto.h
// 美亚柏科（Meiya Pico / MobileMaster FL-901）取证中间结果的容器解码。
//
// 背景
// ----
// 该软件的 .mf / .dmf / .amf / config.db 等容器不是真正的加密：内容是标准
// SQLite，只是按 1024 字节周期与一段固定掩码逐字节 XOR。同一案件内多个容器
// 共用同一套掩码（软件版本常量派生），因此掩码既与案件无关，也与设备无关。
//
// 设计原则
// --------
// 本模块**不硬编码任何厂商掩码**。掩码在运行时从检材自身推导：
//   1. 按 1024 字节切页；
//   2. 用两种统计假设各自生成候选掩码
//        - zero_page: 最高频页被当作"全零页"（SQLite 空闲页即为全零）
//        - mode:      逐字节取众数（多数页的多数偏移为 0）
//   3. 用 SQLite 页 0 的已知头部修正前 16 字节（`SQLite format 3\0`）；
//   4. 用 SQLite 自身执行 `PRAGMA integrity_check` 验证，通过者才算解出。
//
// 第 4 步是关键：统计假设可能在小文件上失效，而 SQLite 的完整性校验是
// 客观判据。任何候选只要不被 SQLite 接受就丢弃，因此不存在"静默解错"。
//
// 同一案件内掩码共享，所以求解时会把同族文件合并取页：小文件（如 4 KB 的
// 记录库）单独没有足够页做统计，合并后即可恢复。

#pragma once
#ifndef MEIYA_CONTAINER_CRYPTO_H
#define MEIYA_CONTAINER_CRYPTO_H

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace meiya {

inline constexpr std::size_t kMaskPeriod = 1024;

// 一次成功求解的结果。mask 长度恒为 kMaskPeriod。
struct DerivedKey {
    std::string label;        // 来源标签，写入溯源；例如 "zero_page"
    std::vector<unsigned char> mask;
    std::size_t pagesUsed = 0;  // 参与统计的页数
    std::size_t validationEntries = 0;  // integrity_check 通过时的 sqlite_master 行数
};

// 一个候选容器的识别结果。
struct ContainerCandidate {
    std::filesystem::path path;
    std::string family;        // case / device / appdb / record / mark / unknown
    std::uint64_t size = 0;
};

// 判断文件是否是美亚加密容器：长度是 1024 的整数倍、首 16 字节与 SQLite 头部
// 的 XOR 结果在多个文件间一致（即共享掩码），且首字节不是明文 SQLite 头。
bool looksLikeEncryptedContainer(const std::string& path);

// 从一组同族容器中推导掩码。pages 取自这些文件。
// 返回 false 表示所有候选都未通过 SQLite 校验；error 说明原因。
bool deriveMask(const std::vector<std::filesystem::path>& familyFiles,
                DerivedKey& out, std::string& error);

// 用给定掩码把源文件解码写出到 destination。按 1024 字节周期 XOR。
bool decryptFile(const std::string& source, const std::string& destination,
                 const std::vector<unsigned char>& mask);

// 内存内解码（测试与小型容器用）。
std::vector<unsigned char> decryptBytes(const std::vector<unsigned char>& data,
                                        const std::vector<unsigned char>& mask);

// 校验一段（已解密的）SQLite 镜像是否通过 integrity_check。
// 实现为写入临时文件后用 SQLite 打开；通过返回 true 并给出 sqlite_master 行数。
bool validateSqlite(const std::vector<unsigned char>& image,
                    std::size_t& schemaEntries, std::string& error);

// 从文件系统枚举一个美亚案件目录下的候选容器（按 family 分组）。
// root 可以是案件根目录、设备目录或 .mf 文件路径。
bool enumerateContainers(const std::string& root,
                         std::vector<ContainerCandidate>& out);

}  // namespace meiya

#endif  // MEIYA_CONTAINER_CRYPTO_H
