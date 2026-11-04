#include "VivoDeobfuscator.h"

#include <array>
#include <fstream>
#include <iterator>

namespace vivo {
namespace {

bool startsWith(const std::vector<std::uint8_t>& bytes,
                std::initializer_list<std::uint8_t> prefix) {
    if (bytes.size() < prefix.size()) return false;
    std::size_t index = 0;
    for (std::uint8_t value : prefix) {
        if (bytes[index++] != value) return false;
    }
    return true;
}

}  // namespace

void deobfuscateInPlace(std::vector<std::uint8_t>& bytes, std::size_t offset) {
    for (std::size_t index = 0; index < bytes.size(); ++index) {
        bytes[index] ^= kObfuscationKey[(offset + index) % 8];
    }
}

std::vector<std::uint8_t> deobfuscate(const std::vector<std::uint8_t>& bytes,
                                      std::size_t offset) {
    std::vector<std::uint8_t> copy = bytes;
    deobfuscateInPlace(copy, offset);
    return copy;
}

bool hasKnownMagic(const std::vector<std::uint8_t>& bytes) {
    if (startsWith(bytes, {0xFF, 0xD8, 0xFF})) return true;                 // JPEG
    if (startsWith(bytes, {0x89, 0x50, 0x4E, 0x47})) return true;           // PNG
    if (startsWith(bytes, {'P', 'K', 0x03, 0x04})) return true;             // ZIP
    if (startsWith(bytes, {'R', 'a', 'r', '!'})) return true;               // RAR
    if (startsWith(bytes, {0x37, 0x7A, 0xBC, 0xAF})) return true;           // 7z
    if (startsWith(bytes, {'G', 'I', 'F', '8'})) return true;               // GIF
    if (startsWith(bytes, {'%', 'P', 'D', 'F'})) return true;               // PDF
    if (startsWith(bytes, {0xD0, 0xCF, 0x11, 0xE0})) return true;           // OLE
    if (startsWith(bytes, {'f', 'L', 'a', 'C'})) return true;               // FLAC
    if (startsWith(bytes, {'R', 'I', 'F', 'F'})) return true;               // RIFF
    if (startsWith(bytes, {'I', 'D', '3'})) return true;                    // MP3
    if (startsWith(bytes, {'O', 'g', 'g', 'S'})) return true;               // Ogg
    if (startsWith(bytes, {'M', 'Z'})) return true;                         // PE
    if (startsWith(bytes, {0x49, 0x54, 0x53, 0x46})) return true;           // CHM
    if (bytes.size() >= 8 && bytes[4] == 'f' && bytes[5] == 't' &&
        bytes[6] == 'y' && bytes[7] == 'p') return true;                    // MP4/M4A
    if (startsWith(bytes, {'{', '"'}) || startsWith(bytes, {'<', '?', 'x'})) return true;
    return false;
}

std::string describeDecodedType(const std::string& path, std::string* detected) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        if (detected) *detected = "unreadable";
        return {};
    }
    std::vector<std::uint8_t> head(32);
    input.read(reinterpret_cast<char*>(head.data()), static_cast<std::streamsize>(head.size()));
    head.resize(static_cast<std::size_t>(input.gcount()));
    deobfuscateInPlace(head);

    std::string kind = "unknown";
    if (startsWith(head, {0xFF, 0xD8, 0xFF})) kind = "jpeg";
    else if (startsWith(head, {0x89, 0x50, 0x4E, 0x47})) kind = "png";
    else if (startsWith(head, {'P', 'K', 0x03, 0x04})) kind = "zip";
    else if (startsWith(head, {'R', 'a', 'r', '!'})) kind = "rar";
    else if (startsWith(head, {0x37, 0x7A, 0xBC, 0xAF})) kind = "7z";
    else if (startsWith(head, {'G', 'I', 'F', '8'})) kind = "gif";
    else if (startsWith(head, {'%', 'P', 'D', 'F'})) kind = "pdf";
    else if (startsWith(head, {0xD0, 0xCF, 0x11, 0xE0})) kind = "ole";
    else if (startsWith(head, {'f', 'L', 'a', 'C'})) kind = "flac";
    else if (startsWith(head, {'R', 'I', 'F', 'F'})) kind = "riff";
    else if (startsWith(head, {'I', 'D', '3'})) kind = "mp3";
    else if (startsWith(head, {'O', 'g', 'g', 'S'})) kind = "ogg";
    else if (startsWith(head, {'M', 'Z'})) kind = "pe";
    else if (startsWith(head, {'I', 'T', 'S', 'F'})) kind = "chm";
    else if (head.size() >= 8 && head[4] == 'f' && head[5] == 't' &&
             head[6] == 'y' && head[7] == 'p') kind = "mp4";
    if (detected) *detected = kind;
    return kind;
}

}  // namespace vivo
