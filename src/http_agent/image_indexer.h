#pragma once

// Scans configured local directories for forensic disk images and gathers the
// METADATA the server's index-images endpoint needs (Task 19). This is the
// producer side of POST /api/clients/{client_id}/index-images — it lets the
// server learn which images exist locally so an analyze_disk command can later
// target a real image_path.
//
// SECURITY INVARIANT: only metadata (path/size/format) is gathered here. The
// image file is NEVER opened for reading — only stat()'d. md5 hashing is off in
// v1 (brief D2); enabling it later would read bytes, but only by explicit opt-in.

#include <cstdint>
#include <string>
#include <vector>

namespace tracelens {

enum class ImageFormat { Unknown, E01, DD, Directory };

struct DiskImageEntry {
    std::string path;          // absolute local path (reported to the server)
    std::uint64_t size_bytes;  // stat().st_size; schema requires > 0
    ImageFormat format;
};

// The wire string the server schema accepts: "E01" | "DD" | "Directory".
std::string format_string(ImageFormat f);

// Classifies a single filesystem entry by extension + entry type. `name` is the
// entry's filename; `is_dir` whether it is a directory. Returns Unknown for
// anything not recognized. Pure — no filesystem access. (Brief D4.)
//
//   directory                       -> Directory
//   *.dd / *.img / *.raw / *.000    -> DD      (case-insensitive)
//   *.E00 .. *.E99                  -> E01     (EWF segment; case-insensitive)
ImageFormat detect_format(const std::string& name, bool is_dir);

// For an E01 segment filename ("img.E02") returns the base name with the 4-char
// segment suffix stripped ("img"), used to dedup a segment set to its first
// member. Returns "" if `name` is not an E01-segment name. (Brief D4.)
std::string e01_base(const std::string& name);

// Scans the DIRECT children of each configured directory (single level — brief
// D3) and returns one DiskImageEntry per recognized image. E01 segments are
// deduped to the lexicographically-smallest member per base name (so a user can
// never target a non-first segment and run a broken partial analysis). Entries
// whose size is <= 0 are skipped (the schema requires size_bytes > 0). A scan
// problem on one directory sets `err` (first problem wins) but does NOT abort
// the remaining directories — the partial result is still returned.
class DiskImageIndexer {
public:
    explicit DiskImageIndexer(std::vector<std::string> dirs);

    std::vector<DiskImageEntry> scan(std::string& err) const;

    const std::vector<std::string>& dirs() const { return dirs_; }

private:
    std::vector<std::string> dirs_;
};

}  // namespace tracelens
