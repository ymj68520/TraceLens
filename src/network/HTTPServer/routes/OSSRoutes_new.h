#pragma once

#include <crow.h>

namespace forensics {

/**
 * @brief OSS routes coordinator
 */
class OSSRoutes {
public:
    explicit OSSRoutes(crow::App<>& app);
};

} // namespace forensics
