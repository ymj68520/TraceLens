#pragma once
#ifndef KEY_FILE_LOADER_H
#define KEY_FILE_LOADER_H

#include <string>
#include <optional>

/**
 * @brief Loads decryption passwords from sibling ".key" files placed next to
 *        disk images.
 *
 * Convention (per partition):
 *   <imageBase>.part<P>.key      — password for partition <P> (e.g. wmh-pc.part2.key)
 *   <imageBase>.key              — whole-image password (no partition table)
 * Fallbacks:
 *   <imageBase>.part<P>.txt
 *   <imageBase>.password
 *
 * The file contains the password as plain text (trailing newline is trimmed).
 *
 * For whole-image (non-partitioned) LUKS/VeraCrypt containers, partitionNum
 * is ignored and <imageBase>.key is used directly.
 */
class KeyFileLoader {
public:
    /**
     * @brief Look up the password for a specific partition of an image.
     * @param imagePath    Path to the disk image.
     * @param partitionNum Partition number (as reported by the partition walker).
     * @param keyFileDir   Optional override directory to look in instead of the
     *                     image's own directory.
     * @return The password if a sibling key file was found, or std::nullopt.
     */
    static std::optional<std::string> loadForPartition(
        const std::string& imagePath,
        int partitionNum,
        const std::string& keyFileDir = "");

    /**
     * @brief Look up a whole-image password (no partition number).
     */
    static std::optional<std::string> loadForImage(
        const std::string& imagePath,
        const std::string& keyFileDir = "");

    /**
     * @brief Look up a raw FVEK key file for a partition (BitLocker direct decrypt).
     *
     * Convention: "<imageBase>.part<P>.fvek" (raw 32-byte FVEK+tweak), falling back
     * to "<imageBase>.fvek". Returns the PATH to the file (not its contents), since
     * the FVEK is binary.
     * @return The FVEK file path if found, or std::nullopt.
     */
    static std::optional<std::string> loadFvekForPartition(
        const std::string& imagePath,
        int partitionNum,
        const std::string& keyFileDir = "");

private:
    /// Read a file, trim trailing CR/LF/whitespace, return its contents.
    static std::optional<std::string> readTrimmed(const std::string& path);

    /// Build the sibling directory: keyFileDir if non-empty, else the image's dir.
    static std::string resolveDir(const std::string& imagePath, const std::string& keyFileDir);

    /// Image base name without extension (e.g. "wmh-pc" from "wmh-pc.E01").
    static std::string baseNameNoExt(const std::string& imagePath);
};

#endif // KEY_FILE_LOADER_H
