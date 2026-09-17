// SqliteRocksMirrorStub.cpp
// No-op build of the mirror for machines without the rocksdb development
// library (mvp-phase1-acceptance SPEC §8). run() reports failure so callers
// degrade gracefully; the SQLite pipeline is unaffected.

#include "SqliteRocksMirror.h"

#include <stdexcept>

namespace forensics::kv {

std::vector<MirrorResult> SqliteRocksMirror::run(const std::string&,
                                                 const std::string&,
                                                 const std::vector<std::string>&) {
    throw std::runtime_error(
        "RocksDB support is not built into this binary (rocksdb library missing); "
        "set ROCKSDB_MIRROR_RAW=0 to silence this warning");
}

}  // namespace forensics::kv
