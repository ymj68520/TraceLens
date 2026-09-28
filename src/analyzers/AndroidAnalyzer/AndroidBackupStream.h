#pragma once

#include <archive.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include <openssl/evp.h>
#include <zlib.h>

// Streams a validated AOSP .ab payload into libarchive as TAR bytes. No
// archive members (or intermediate full TAR) are unpacked to disk.
class AndroidBackupStream {
public:
    static std::unique_ptr<AndroidBackupStream> open(
        const std::string& path, const std::string& password, std::string& errorCode);
    ~AndroidBackupStream();
    AndroidBackupStream(const AndroidBackupStream&) = delete;
    AndroidBackupStream& operator=(const AndroidBackupStream&) = delete;
    bool attach(struct archive* reader);
    bool finish();

private:
    AndroidBackupStream() = default;
    bool initialize(const std::string& path, const std::string& password,
                    std::string& errorCode);
    bool decryptHeader(const std::string& password, const std::vector<std::string>& fields,
                       std::string& errorCode);
    std::size_t nextPlainChunk();
    la_ssize_t read(const void** buffer);
    static int openCallback(struct archive*, void*);
    static la_ssize_t readCallback(struct archive*, void*, const void**);
    static int closeCallback(struct archive*, void*);

    std::ifstream source_;
    bool compressed_ = false;
    bool encrypted_ = false;
    bool sourceEof_ = false;
    bool plainEof_ = false;
    bool streamDone_ = false;
    bool failed_ = false;
    z_stream zstream_{};
    bool zstreamReady_ = false;
    EVP_CIPHER_CTX* cipher_ = nullptr;
    std::array<unsigned char, 65552> input_{};
    std::array<unsigned char, 65552> plain_{};
    std::array<unsigned char, 65552> output_{};
    std::vector<unsigned char> pending_;
};
