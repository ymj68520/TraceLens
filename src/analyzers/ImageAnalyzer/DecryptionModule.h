#pragma once
#ifndef DECRYPTION_MODULE_H
#define DECRYPTION_MODULE_H

#include <string>
#include <cstdint>
#include <vector>

/**
 * @brief Encryption type detected on a partition/volume.
 *
 * Used by ImageAnalyzer to decide which external decryption tool to invoke
 * when a partition is reported as "encrypted" by The Sleuth Kit.
 */
enum class EncryptionType {
    NONE,        ///< Not encrypted (or signature unrecognised)
    BITLOCKER,   ///< Microsoft BitLocker ("-FVE-FS-" signature)
    LUKS,        ///< Linux Unified Key Setup ("LUKS\xba\xbe" signature)
    VERACRYPT,   ///< VeraCrypt container ("TRUE" / "VERA" signature)
    UNKNOWN      ///< Looks encrypted but type cannot be determined
};

/**
 * @brief Handle to a successfully decrypted partition/volume.
 *
 * `accessiblePath` is what downstream extractors should read instead of the
 * original encrypted partition. It is either:
 *   - a device-mapper node ("/dev/mapper/<name>") for LUKS, or
 *   - a regular file containing the decrypted (NTFS/ext4/...) filesystem,
 *     produced by dislocker/bdemount for BitLocker, or
 *   - a mounted VeraCrypt volume path.
 */
struct DecryptedPartition {
    EncryptionType encType = EncryptionType::NONE;
    std::string accessiblePath;     ///< Path to read the decrypted data from
    std::string mapperName;         ///< cryptsetup/dm name (for cleanup)
    std::string loopDevice;         ///< associated loop device (for cleanup)
    std::string tempFile;           ///< temp file created (for cleanup), if any
    std::string mountPoint;         ///< mount point created (for cleanup), if any
    bool mounted = false;           ///< whether a mount() was performed
};

/**
 * @brief Decrypts encrypted disk partitions using system crypto tools.
 *
 * ImageAnalyzer itself (via The Sleuth Kit) cannot read BitLocker/LUKS/
 * VeraCrypt volumes. This module bridges that gap by:
 *   1. Detecting the encryption type from the partition's first sector.
 *   2. Invoking the appropriate external tool (cryptsetup / dislocker /
 *      bdemount / veracrypt) with a password obtained from a sibling .key file.
 *   3. Producing an accessible (decrypted) path that TSK/loop-mount can read.
 *
 * All external tools are located at runtime (PATH lookup); absence of a tool
 * is reported as a clear error rather than a hard dependency.
 */
class DecryptionModule {
public:
    DecryptionModule() = default;
    ~DecryptionModule();

    /**
     * @brief Detect encryption type of a partition inside an image.
     * @param imagePath      Path to the (possibly EWF) disk image.
     * @param partitionOffset Byte offset of the partition within the image.
     * @return Detected encryption type (NONE/UNKNOWN if not encrypted).
     *
     * Uses ewfinfo/blkcat-free raw read via a helper; reads the first 512 bytes
     * of the partition and matches known magic signatures.
     */
    static EncryptionType detect(const std::string& imagePath, uint64_t partitionOffset);

    /**
     * @brief Human-readable name for an encryption type.
     */
    static std::string encryptionTypeName(EncryptionType t);

    /**
     * @brief Check whether a given external decryption tool is available on PATH.
     * @param tool Binary name (e.g. "cryptsetup", "dislocker", "bdemount").
     */
    static bool isToolAvailable(const std::string& tool);

    /**
     * @brief Decrypt a partition.
     *
     * Dispatches to decryptLuks / decryptBitlocker / decryptVeracrypt based on
     * the detected (or previously known) encryption type. On success, fills
     * `out` with an accessible path; on failure returns false and sets errMsg.
     *
     * @param imagePath       Disk image path.
     * @param partitionOffset Byte offset of the encrypted partition.
     * @param password        Password / passphrase / recovery key.
     * @param out             [out] Handle to the decrypted volume on success.
     * @param errMsg          [out] Error description on failure.
     * @return true on success.
     */
    bool decrypt(const std::string& imagePath, uint64_t partitionOffset,
                 const std::string& password, DecryptedPartition& out,
                 std::string& errMsg);

    /**
     * @brief Release all resources held by a decrypted partition.
     *
     * Unmounts (if mounted), removes device-mapper nodes, detaches loop
     * devices, and deletes temp files. Safe to call on a partially-set-up
     * DecryptedPartition.
     */
    void cleanup(const DecryptedPartition& part);

    /**
     * @brief Decrypt using LUKS (cryptsetup).
     *
     * Sets up a loop device at the partition offset, then `cryptsetup open`
     * to create /dev/mapper/<name>. accessiblePath = the mapper node.
     */
    bool decryptLuks(const std::string& imagePath, uint64_t partitionOffset,
                     const std::string& password, DecryptedPartition& out,
                     std::string& errMsg);

    /**
     * @brief Decrypt using BitLocker (dislocker / bdemount).
     *
     * Uses bdemount when available (preferred for AES-XTS), falling back to
     * dislocker. Produces a decrypted view.
     */
    bool decryptBitlocker(const std::string& imagePath, uint64_t partitionOffset,
                          const std::string& password, DecryptedPartition& out,
                          std::string& errMsg);

    /**
     * @brief Decrypt a BitLocker volume directly from a recovered FVEK.
     *
     * When dislocker/libbde cannot handle AES-XTS-128 (common with older
     * versions), a Full Volume Encryption Key recovered from a memory dump
     * can decrypt the data area directly via AES-XTS-128.
     *
     * The FVEK is read from a sibling file "<image>.part<N>.fvek" (32 bytes:
     * 16-byte key || 16-byte tweak), as emitted by the volatility3
     * bitlocker_fvek_scan plugin. Decryption is performed by the bundled
     * scripts/bitlocker_fvek_decrypt.py helper.
     *
     * @param fvekPath  Path to the 32-byte FVEK file.
     * @return true on success; out.accessiblePath = decrypted raw image.
     */
    bool decryptBitlockerWithFvek(const std::string& imagePath, uint64_t partitionOffset,
                                  const std::string& fvekPath, DecryptedPartition& out,
                                  std::string& errMsg);

    /**
     * @brief Decrypt a VeraCrypt container file.
     */
    bool decryptVeracrypt(const std::string& imagePath, uint64_t partitionOffset,
                          const std::string& password, DecryptedPartition& out,
                          std::string& errMsg);

private:
    /**
     * @brief Execute argv directly, optionally feed stdin, and capture stdout+stderr.
     *
     * No shell is involved, so paths and other arguments are not subject to shell
     * parsing. Returns the child's exit status, or -1 when setup/wait fails.
     */
    static int runProcess(const std::vector<std::string>& argv,
                          const std::string& stdinData, std::string& output);

    /**
     * @brief Attach a loop device to a partition inside an image.
     * @return The loop device path (e.g. "/dev/loop3"), or empty on failure.
     *
     * For EWF images the partition is first extracted to a temp raw file
     * (cryptsetup/losetup cannot read EWF directly); loopDevice is set on
     * that temp file and `tempFile` is filled for cleanup.
     */
    bool setupLoopForPartition(const std::string& imagePath, uint64_t partitionOffset,
                               std::string& loopDevice, std::string& tempFile,
                               std::string& errMsg);

    /**
     * @brief Extract a raw partition image to a temp file (for EWF sources).
     *
     * Returns false if the image is raw (DD) — in that case a loop device with
     * offset should be used directly instead of extracting.
     * @return true if extraction performed, false if not needed (raw image).
     */
    bool extractPartitionToTemp(const std::string& imagePath, uint64_t partitionOffset,
                                uint64_t partitionSize, std::string& tempFile,
                                std::string& errMsg);

    /// Detach a loop device set up by setupLoopForPartition.
    void detachLoop(const std::string& loopDevice);

    /// Is the given image an EWF (E01) container?
    static bool isEwfImage(const std::string& imagePath);

    /// Keep track of all decrypted handles so the destructor can clean up.
    std::vector<DecryptedPartition> owned_;
};

#endif // DECRYPTION_MODULE_H
