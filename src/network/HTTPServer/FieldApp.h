#pragma once

#include <crow.h>
#include <string>

namespace forensics {

// Global, fail-closed field middleware. The Python field identity service
// validates signed user JWTs; C++ never trusts X-User or a nonempty Bearer.
struct FieldAuthMiddleware {
    struct context {
        std::string principal;
        std::string role;
    };

    void before_handle(crow::request& req, crow::response& res, context& ctx);
    void after_handle(crow::request&, crow::response&, context&) {}
};

using HttpApp = crow::App<FieldAuthMiddleware>;

bool field_runtime_ready();

} // namespace forensics
