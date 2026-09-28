#include "AndroidBackupStream.h"

#include <openssl/crypto.h>
#include <openssl/evp.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cstring>
#include <limits>

namespace {
bool line(std::ifstream& source, std::string& value) {
    value.clear();
    char ch;
    while (source.get(ch)) {
        if (ch == '\n') return true;
        if (value.size() >= 2048 || ch == '\r' || ch == '\0') return false;
        value.push_back(ch);
    }
    return false;
}

bool decimal(const std::string& text, int& value) {
    if (text.empty() || text.size() > 8) return false;
    const auto [end, ec] = std::from_chars(text.data(), text.data() + text.size(), value);
    return ec == std::errc{} && end == text.data() + text.size();
}

bool hexBytes(const std::string& text, std::vector<unsigned char>& bytes) {
    if (text.empty() || text.size() > 2048 || text.size() % 2) return false;
    bytes.clear();
    bytes.reserve(text.size() / 2);
    auto digit = [](char ch) -> int {
        if (ch >= '0' && ch <= '9') return ch - '0';
        if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
        if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
        return -1;
    };
    for (std::size_t i = 0; i < text.size(); i += 2) {
        const int a = digit(text[i]), b = digit(text[i + 1]);
        if (a < 0 || b < 0) return false;
        bytes.push_back(static_cast<unsigned char>((a << 4) | b));
    }
    return true;
}

// AOSP PasswordUtils.makeKeyChecksum casts each signed key byte to a Java
// char, then PBEKeySpec converts those chars to UTF-8 before PBKDF2. A negative
// byte therefore becomes U+FF80..U+FFFF rather than an 8-bit password byte.
std::vector<unsigned char> javaChecksumPassword(const unsigned char* key,
                                                std::size_t length) {
    std::vector<unsigned char> utf8;
    utf8.reserve(length * 3);
    for (std::size_t i = 0; i < length; ++i) {
        const unsigned int code = key[i] < 128 ? key[i] : 0xff00U + key[i];
        if (code < 0x80) utf8.push_back(static_cast<unsigned char>(code));
        else {
            utf8.push_back(static_cast<unsigned char>(0xe0 | (code >> 12)));
            utf8.push_back(static_cast<unsigned char>(0x80 | ((code >> 6) & 0x3f)));
            utf8.push_back(static_cast<unsigned char>(0x80 | (code & 0x3f)));
        }
    }
    return utf8;
}
} // namespace

std::unique_ptr<AndroidBackupStream> AndroidBackupStream::open(
    const std::string& path, const std::string& password, std::string& errorCode) {
    auto stream = std::unique_ptr<AndroidBackupStream>(new AndroidBackupStream());
    if (!stream->initialize(path, password, errorCode)) return {};
    return stream;
}

AndroidBackupStream::~AndroidBackupStream() {
    if (zstreamReady_) inflateEnd(&zstream_);
    if (cipher_) EVP_CIPHER_CTX_free(cipher_);
    OPENSSL_cleanse(input_.data(), input_.size());
    OPENSSL_cleanse(plain_.data(), plain_.size());
    OPENSSL_cleanse(output_.data(), output_.size());
}

bool AndroidBackupStream::initialize(const std::string& path, const std::string& password,
                                     std::string& errorCode) {
    source_.open(path, std::ios::binary);
    if (!source_) { errorCode = "SOURCE_UNREADABLE"; return false; }
    std::string magic, versionText, compressionText, encryptionText;
    if (!line(source_, magic) || magic != "ANDROID BACKUP" ||
        !line(source_, versionText) || !line(source_, compressionText) ||
        !line(source_, encryptionText)) {
        errorCode = "MALFORMED_BACKUP"; return false;
    }
    int version = 0;
    if (!decimal(versionText, version) || version < 1 || version > 5) {
        errorCode = "UNSUPPORTED_BACKUP_VARIANT"; return false;
    }
    if (compressionText != "0" && compressionText != "1") {
        errorCode = "UNSUPPORTED_BACKUP_VARIANT"; return false;
    }
    compressed_ = compressionText == "1";
    if (encryptionText == "AES-256") {
        if (version == 1) {
            errorCode = "UNSUPPORTED_BACKUP_VARIANT"; return false;
        }
        encrypted_ = true;
        if (password.empty()) { errorCode = "LOCKED_BACKUP"; return false; }
        std::vector<std::string> fields(5);
        for (auto& field : fields) {
            if (!line(source_, field)) { errorCode = "MALFORMED_BACKUP"; return false; }
        }
        if (!decryptHeader(password, fields, errorCode)) return false;
    } else if (encryptionText != "none") {
        errorCode = "UNSUPPORTED_BACKUP_VARIANT"; return false;
    }
    if (compressed_) {
        if (inflateInit(&zstream_) != Z_OK) {
            errorCode = "UNSUPPORTED_BACKUP_VARIANT"; return false;
        }
        zstreamReady_ = true;
    }
    return true;
}

bool AndroidBackupStream::decryptHeader(const std::string& password,
                                        const std::vector<std::string>& fields,
                                        std::string& errorCode) {
    std::vector<unsigned char> userSalt, checkSalt, userIv, encryptedBlob;
    int rounds = 0;
    if (!hexBytes(fields[0], userSalt) || !hexBytes(fields[1], checkSalt) ||
        !decimal(fields[2], rounds) || rounds < 1 || rounds > 1000000 ||
        !hexBytes(fields[3], userIv) || userIv.size() != 16 ||
        !hexBytes(fields[4], encryptedBlob) || encryptedBlob.size() < 32 ||
        encryptedBlob.size() % 16) {
        errorCode = "MALFORMED_BACKUP"; return false;
    }
    std::array<unsigned char, 32> userKey{}, masterKey{}, check{};
    const bool derived = PKCS5_PBKDF2_HMAC(
        password.data(), static_cast<int>(password.size()), userSalt.data(),
        static_cast<int>(userSalt.size()), rounds, EVP_sha1(),
        static_cast<int>(userKey.size()), userKey.data()) == 1;
    if (!derived) { errorCode = "UNSUPPORTED_BACKUP_VARIANT"; return false; }
    EVP_CIPHER_CTX* blobCtx = EVP_CIPHER_CTX_new();
    if (!blobCtx) { errorCode = "UNSUPPORTED_BACKUP_VARIANT"; return false; }
    std::vector<unsigned char> blob(encryptedBlob.size() + 16);
    int length = 0, finalLength = 0;
    bool okay = EVP_DecryptInit_ex(blobCtx, EVP_aes_256_cbc(), nullptr,
                                   userKey.data(), userIv.data()) == 1 &&
                EVP_DecryptUpdate(blobCtx, blob.data(), &length,
                                  encryptedBlob.data(), static_cast<int>(encryptedBlob.size())) == 1 &&
                EVP_DecryptFinal_ex(blobCtx, blob.data() + length, &finalLength) == 1;
    EVP_CIPHER_CTX_free(blobCtx);
    OPENSSL_cleanse(userKey.data(), userKey.size());
    if (!okay) { errorCode = "LOCKED_BACKUP"; return false; }
    blob.resize(static_cast<std::size_t>(length + finalLength));
    std::size_t offset = 0;
    auto segment = [&](std::vector<unsigned char>& output) -> bool {
        if (offset >= blob.size()) return false;
        const std::size_t size = blob[offset++];
        if (size == 0 || offset + size > blob.size()) return false;
        output.assign(blob.begin() + offset, blob.begin() + offset + size);
        offset += size;
        return true;
    };
    std::vector<unsigned char> dataIv, dataKey, storedCheck;
    okay = segment(dataIv) && segment(dataKey) && segment(storedCheck) &&
           offset == blob.size() && dataIv.size() == 16 && dataKey.size() == 32 &&
           storedCheck.size() == 32;
    if (okay) {
        std::copy(dataKey.begin(), dataKey.end(), masterKey.begin());
        auto checksumPassword = javaChecksumPassword(masterKey.data(), masterKey.size());
        okay = PKCS5_PBKDF2_HMAC(
            reinterpret_cast<const char*>(checksumPassword.data()),
            static_cast<int>(checksumPassword.size()), checkSalt.data(),
            static_cast<int>(checkSalt.size()), rounds, EVP_sha1(),
            static_cast<int>(check.size()), check.data()) == 1 &&
            CRYPTO_memcmp(check.data(), storedCheck.data(), check.size()) == 0;
        OPENSSL_cleanse(checksumPassword.data(), checksumPassword.size());
    }
    if (okay) {
        cipher_ = EVP_CIPHER_CTX_new();
        okay = cipher_ && EVP_DecryptInit_ex(cipher_, EVP_aes_256_cbc(), nullptr,
                                             masterKey.data(), dataIv.data()) == 1;
    }
    OPENSSL_cleanse(masterKey.data(), masterKey.size());
    OPENSSL_cleanse(check.data(), check.size());
    OPENSSL_cleanse(blob.data(), blob.size());
    if (!dataKey.empty()) OPENSSL_cleanse(dataKey.data(), dataKey.size());
    if (!okay) { errorCode = "LOCKED_BACKUP"; return false; }
    return true;
}

std::size_t AndroidBackupStream::nextPlainChunk() {
    if (plainEof_ || failed_) return 0;
    if (!encrypted_) {
        source_.read(reinterpret_cast<char*>(plain_.data()), 65536);
        const auto size = source_.gcount();
        if (size <= 0) plainEof_ = true;
        return static_cast<std::size_t>(std::max<std::streamsize>(size, 0));
    }
    for (;;) {
        source_.read(reinterpret_cast<char*>(input_.data()), 65536);
        const int size = static_cast<int>(source_.gcount());
        int produced = 0;
        if (size > 0) {
            if (EVP_DecryptUpdate(cipher_, plain_.data(), &produced, input_.data(), size) != 1) {
                failed_ = true; return 0;
            }
            if (produced > 0) return static_cast<std::size_t>(produced);
        } else {
            if (EVP_DecryptFinal_ex(cipher_, plain_.data(), &produced) != 1) {
                failed_ = true; return 0;
            }
            plainEof_ = true;
            return static_cast<std::size_t>(produced);
        }
    }
}

la_ssize_t AndroidBackupStream::read(const void** buffer) {
    if (failed_) return -1;
    if (streamDone_) return 0;
    if (!compressed_) {
        const std::size_t size = nextPlainChunk();
        if (failed_) return -1;
        *buffer = plain_.data();
        if (size == 0) streamDone_ = true;
        return static_cast<la_ssize_t>(size);
    }
    for (;;) {
        if (zstream_.avail_in == 0 && !plainEof_) {
            const std::size_t size = nextPlainChunk();
            if (failed_) return -1;
            zstream_.next_in = plain_.data();
            zstream_.avail_in = static_cast<uInt>(size);
        }
        zstream_.next_out = output_.data();
        zstream_.avail_out = static_cast<uInt>(output_.size());
        const int rc = inflate(&zstream_, Z_NO_FLUSH);
        const auto produced = output_.size() - zstream_.avail_out;
        if (rc == Z_STREAM_END) streamDone_ = true;
        else if (rc != Z_OK && rc != Z_BUF_ERROR) { failed_ = true; return -1; }
        *buffer = output_.data();
        if (produced > 0) return static_cast<la_ssize_t>(produced);
        if (streamDone_) return 0;
        if (plainEof_ && zstream_.avail_in == 0) { failed_ = true; return -1; }
    }
}

int AndroidBackupStream::openCallback(struct archive*, void*) { return ARCHIVE_OK; }
la_ssize_t AndroidBackupStream::readCallback(struct archive*, void* data,
                                            const void** buffer) {
    return static_cast<AndroidBackupStream*>(data)->read(buffer);
}
int AndroidBackupStream::closeCallback(struct archive*, void*) { return ARCHIVE_OK; }

bool AndroidBackupStream::attach(struct archive* reader) {
    return archive_read_open(reader, this, openCallback, readCallback,
                             closeCallback) == ARCHIVE_OK;
}

bool AndroidBackupStream::finish() {
    const void* output = nullptr;
    while (!streamDone_ && !failed_) {
        if (read(&output) < 0) break;
    }
    // A zlib stream can end before the AES-CBC padding block is consumed.
    // Verify EVP_DecryptFinal_ex rather than accepting a valid TAR prefix.
    if (encrypted_ && !failed_) {
        while (!plainEof_ && !failed_) nextPlainChunk();
    }
    return streamDone_ && !failed_;
}
