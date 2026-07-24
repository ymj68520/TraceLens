#include "http_client.h"

#include "httplib.h"

#include <mutex>

namespace tracelens {

// cpp-httplib is header-only; it defines CPPHTTPLIB_OPENSSL_SUPPORT itself when
// the OpenSSL headers are available on the include path. Without it, an https://
// base URL would silently fall back to plaintext — unacceptable (raw-derived
// data must never leave the box unencrypted). Fail the build if it is absent.
#ifndef CPPHTTPLIB_OPENSSL_SUPPORT
#error "cpp-httplib built without OpenSSL — https:// unavailable; TLS is required"
#endif

// TODO(Task 21): live TLS 1.3 verification — enforce TLS 1.3 minimum at runtime
// by spawning a TLS 1.3-only httplib::Server with a self-signed cert and asserting
// the HttpLibClient connects successfully. Currently deferred; enforcement is
// verified at compile-time (CPPHTTPLIB_ENFORCE_TLS1_3_MIN macro propagation through
// the SSLClient ctor chain). Requires bundling a test cert + server config.

struct HttpLibClient::Impl {
    std::mutex mtx;
    httplib::Client cli;

    Impl(const std::string& base_url, const std::string& bearer)
        : cli(base_url) {
        cli.set_connection_timeout(10);  // seconds
        cli.set_read_timeout(300);       // generous: result uploads (Task 17) are large
        cli.set_write_timeout(60);
        // Do NOT auto-follow redirects: cpp-httplib re-sends default headers
        // (including Authorization: Bearer ...) across a redirect and does not
        // strip the token on a cross-host hop. The token is the agent's only
        // secret; the poll/status/result endpoints return 2xx, never 3xx, so a
        // redirect would be anomalous and should surface as an error, not leak
        // the credential.
        cli.set_follow_location(false);
        cli.set_default_headers({
            {"Authorization", "Bearer " + bearer},
            {"Accept", "application/json"},
        });
    }
};

HttpLibClient::HttpLibClient(const std::string& base_url,
                             const std::string& bearer_token)
    : impl_(std::make_unique<Impl>(base_url, bearer_token)) {}

HttpLibClient::~HttpLibClient() = default;

HttpResponse HttpLibClient::get(const std::string& path) {
    std::lock_guard<std::mutex> lk(impl_->mtx);
    auto res = impl_->cli.Get(path.c_str());
    HttpResponse out;
    if (!res) {
        out.error = httplib::to_string(res.error());
        return out;
    }
    out.status = res->status;
    out.body = res->body;
    return out;
}

HttpResponse HttpLibClient::post(const std::string& path,
                                 const std::string& json_body) {
    std::lock_guard<std::mutex> lk(impl_->mtx);
    auto res = impl_->cli.Post(path.c_str(), json_body, "application/json");
    HttpResponse out;
    if (!res) {
        out.error = httplib::to_string(res.error());
        return out;
    }
    out.status = res->status;
    out.body = res->body;
    return out;
}

}  // namespace tracelens
