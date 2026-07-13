#include "DecryptionModule.h"

#ifdef _WIN32

EncryptionType DecryptionModule::detect(const std::string&, uint64_t) {
    return EncryptionType::NONE;
}

std::string DecryptionModule::encryptionTypeName(EncryptionType type) {
    switch (type) {
        case EncryptionType::BITLOCKER: return "BitLocker";
        case EncryptionType::LUKS: return "LUKS";
        case EncryptionType::VERACRYPT: return "VeraCrypt";
        case EncryptionType::UNKNOWN: return "Unknown-encrypted";
        default: return "None";
    }
}

bool DecryptionModule::isToolAvailable(const std::string&) {
    return false;
}

bool DecryptionModule::decrypt(const std::string&, uint64_t, const std::string&,
                               DecryptedPartition&, std::string& errMsg) {
    errMsg = "encrypted volume decryption is currently supported on Unix platforms only";
    return false;
}

bool DecryptionModule::decryptLuks(const std::string&, uint64_t, const std::string&,
                                   DecryptedPartition&, std::string& errMsg) {
    errMsg = "LUKS decryption is not available on Windows";
    return false;
}

bool DecryptionModule::decryptBitlocker(const std::string&, uint64_t, const std::string&,
                                        DecryptedPartition&, std::string& errMsg) {
    errMsg = "BitLocker image decryption is not available on Windows";
    return false;
}

bool DecryptionModule::decryptBitlockerWithFvek(const std::string&, uint64_t,
                                                const std::string&, DecryptedPartition&,
                                                std::string& errMsg) {
    errMsg = "BitLocker FVEK decryption is not available on Windows";
    return false;
}

bool DecryptionModule::decryptVeracrypt(const std::string&, uint64_t, const std::string&,
                                        DecryptedPartition&, std::string& errMsg) {
    errMsg = "VeraCrypt image decryption is not available on Windows";
    return false;
}

void DecryptionModule::cleanup(const DecryptedPartition&) {}

DecryptionModule::~DecryptionModule() = default;

#endif
