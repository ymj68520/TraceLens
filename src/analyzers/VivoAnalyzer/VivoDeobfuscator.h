/**
 * @file VivoDeobfuscator.h
 * @brief Reverses the payload obfuscation used by vivo PC-assistant backups.
 *
 * A vivo backup whose ``.backup`` header declares ``xor_obfuscated`` (and whose
 * LevelDB index repeats ``xor_obfuscated: true``) stores every payload file
 * XORed with a fixed eight-byte repeating key. The transform is position-based,
 * not per-file: the same key applies at ``offset % 8`` regardless of which file
 * is being read.
 *
 * The key was recovered by known-plaintext analysis: a standalone JPEG begins
 * ``FF D8 FF E1`` (JPEG SOI + APP1), and dozens of camera images share that
 * prefix, which fixes key bytes 0..3. APP1 length and the ``Exif\0\0`` marker
 * then fix the remaining bytes. The recovery is verified across the whole
 * index by checking that decoded headers land on known magic numbers.
 *
 * AES is deliberately not assumed: this is obfuscation, not encryption. There is
 * no per-file nonce, no KDF and no integrity tag.
 */

#pragma once
#ifndef VIVO_DEOBFUSCATOR_H
#define VIVO_DEOBFUSCATOR_H

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace vivo {

/** The eight-byte repeating XOR key. */
inline constexpr std::uint8_t kObfuscationKey[8] = {
    0x7f, 0xa3, 0xc8, 0xe1, 0x5b, 0x9d, 0x2e, 0xf4,
};

/**
 * @brief XOR `bytes` in place. The offset matters: callers decoding a slice
 *        must pass the absolute file offset so the key aligns.
 */
void deobfuscateInPlace(std::vector<std::uint8_t>& bytes, std::size_t offset = 0);

/** Convenience wrapper returning a decoded copy. */
std::vector<std::uint8_t> deobfuscate(const std::vector<std::uint8_t>& bytes,
                                      std::size_t offset = 0);

/** True when the buffer starts with a recognised container magic. */
bool hasKnownMagic(const std::vector<std::uint8_t>& bytes);

/**
 * @brief Read a file, deobfuscate, and report the detected type.
 * @param detected Optional out-parameter naming the magic family.
 */
std::string describeDecodedType(const std::string& path, std::string* detected = nullptr);

}  // namespace vivo

#endif  // VIVO_DEOBFUSCATOR_H
