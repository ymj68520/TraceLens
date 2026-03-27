#pragma once

#include <string>

namespace forensics {

enum class FileCategory {
    IMAGES,
    VIDEOS,
    AUDIO,
    DOCUMENTS,
    ARCHIVES,
    EXECUTABLES,
    DATABASES,
    SOURCE_CODE,
    WEB_FILES,
    EMAIL,
    SYSTEM_FILES,
    ENCRYPTED,
    UNKNOWN
};

} // namespace forensics
