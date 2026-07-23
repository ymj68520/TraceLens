#pragma once

// HTTP transport abstraction. The real implementation (HttpLibClient) wraps
// cpp-httplib with TLS + Bearer auth; the IHttpClient interface lets Poller /
// StatusReporter / HttpAgentService be unit-tested with a fake that returns
// canned JSON — no live server, no network. That is what makes this C++ task
// testable in a build-only environment.

#include <memory>
#include <string>

namespace tracelens {

// status == 0 means a transport-level failure (DNS / connect / TLS); error
// holds the description. status != 0 is the HTTP status code; body is the raw
// response (JSON text on the success path).
struct HttpResponse {
    int status = 0;
    std::string body;
    std::string error;

    bool ok() const { return status >= 200 && status < 300; }
};

class IHttpClient {
public:
    virtual ~IHttpClient() = default;
    virtual HttpResponse get(const std::string& path) = 0;
    virtual HttpResponse post(const std::string& path,
                              const std::string& json_body) = 0;
};

// Production transport over cpp-httplib. The base URL is fixed at construction
// (e.g. "https://server.example.com"); cpp-httplib's Client auto-selects SSL
// for https:// URLs (0.19.0, requires CPPHTTPLIB_OPENSSL_SUPPORT). The Bearer
// token is injected as a default header on every request. Thread-safe: calls
// are serialized with a mutex (cpp-httplib's Client is not safe across
// concurrent calls on the same instance).
class HttpLibClient : public IHttpClient {
public:
    HttpLibClient(const std::string& base_url, const std::string& bearer_token);
    ~HttpLibClient();
    HttpResponse get(const std::string& path) override;
    HttpResponse post(const std::string& path,
                      const std::string& json_body) override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace tracelens
