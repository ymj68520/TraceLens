// Volatility3Runner.h
// Subprocess wrapper around Volatility3. One run() call per plugin.
#pragma once
#include <string>

struct PluginResult {
    bool ok = false;
    std::string jsonText;    // raw stdout (JSON array)
    std::string stderrText;  // captured stderr
    int exitCode = -1;
};

class Volatility3Runner {
public:
    explicit Volatility3Runner(std::string memPath);

    // Override the vol binary path (otherwise resolved automatically).
    void setVolBinary(const std::string& path) { volBinary_ = path; }

    // Run one plugin. Returns captured stdout as JSON text on success.
    PluginResult run(const std::string& pluginName, int timeoutSeconds = 600);

    // Locate vol: probe python_service/.venv/bin/vol, then PATH. Empty if none.
    static std::string resolveVolBinary();

private:
    std::string memPath_;
    std::string volBinary_;
};
