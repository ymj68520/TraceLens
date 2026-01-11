#pragma once

#include <string>
#include <vector>
#include <cstdint>

/**
 * @brief Utilities for detecting encrypted files
 */
class EncryptionUtils {
public:
    /**
     * @brief Check if a file is likely encrypted
     * 
     * Uses a combination of Magic Bytes (header signature) and Shannon Entropy analysis.
     * 
     * @param path File path
     * @return true if file is detected as encrypted
     */
    static bool isEncrypted(const std::string& path);

    /**
     * @brief Calculate Shannon Entropy of a data buffer
     * 
     * @param data Data buffer
     * @return Entropy value (0.0 - 8.0)
     */
    static double calculateEntropy(const std::vector<uint8_t>& data);

private:
    /**
     * @brief Check if header matches known encrypted file signatures
     */
    static bool hasEncryptedHeader(const std::vector<uint8_t>& header);
};
