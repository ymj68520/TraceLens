#include "EncryptionUtils.h"
#include <fstream>
#include <cmath>
#include <map>
#include <vector>
#include <array>
#include <iostream>

bool EncryptionUtils::isEncrypted(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file.is_open()) return false;

    // Read first block (4KB) for header check
    std::vector<uint8_t> header(4096);
    file.read(reinterpret_cast<char*>(header.data()), header.size());
    size_t bytesRead = file.gcount();
    header.resize(bytesRead);

    if (bytesRead < 8) return false; // Too small to be useful

    // 1. Magic Header Check (Fast and Accurate)
    if (hasEncryptedHeader(header)) {
        return true;
    }

    // 2. Entropy Check (For headerless/unknown encrypted files)
    // Only verify if we have enough data to be statistically significant
    if (bytesRead >= 256) {
        double entropy = calculateEntropy(header);
        // High entropy threshold: 7.95 (Encryption is typically very close to 8.0)
        // Normal compressed files (zip, jpg) are usually around 7.5 - 7.9
        if (entropy > 7.95) {
            return true;
        }
    }

    return false;
}

double EncryptionUtils::calculateEntropy(const std::vector<uint8_t>& data) {
    if (data.empty()) return 0.0;

    std::map<uint8_t, size_t> frequencies;
    for (uint8_t byte : data) {
        frequencies[byte]++;
    }

    double entropy = 0.0;
    double totalLen = static_cast<double>(data.size());

    for (const auto& pair : frequencies) {
        double p = static_cast<double>(pair.second) / totalLen;
        entropy -= p * std::log2(p);
    }

    return entropy;
}

bool EncryptionUtils::hasEncryptedHeader(const std::vector<uint8_t>& header) {
    if (header.size() < 16) return false;

    // LUKS: 'L', 'U', 'K', 'S', 0xBA, 0xBE
    const std::array<uint8_t, 6> luksSig = {0x4C, 0x55, 0x4B, 0x53, 0xBA, 0xBE};
    if (std::equal(luksSig.begin(), luksSig.end(), header.begin())) return true;

    // BitLocker: '-FVE-FS-' (offset 3, usually matches jmp instruction first)
    // Checking specifically for the signature string
    const std::string bitlockerSig = "-FVE-FS-";
    // Search in first 128 bytes
    std::string headerStr(header.begin(), header.begin() + std::min(header.size(), size_t(128)));
    if (headerStr.find(bitlockerSig) != std::string::npos) return true;

    // OpenSSL Salted: 'Salted__'
    const std::string openSSL = "Salted__";
    if (headerStr.find(openSSL) == 0) return true;
    
    // VeraCrypt / TrueCrypt (No fixed header, relying on Entropy + size modulo 64 check potentially)
    // But pure magic check fails for them. We rely on Entropy for these.

    return false;
}
