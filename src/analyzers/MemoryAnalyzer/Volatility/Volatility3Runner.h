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

    // Extra symbol directory passed to vol3 via `-s`. vol3 needs an ISF
    // symbol file matching the dump's kernel; without it every plugin fails
    // with "No Linux banners found". Empty = rely on vol3's default search.
    void setSymbolDir(const std::string& dir) { symbolDir_ = dir; }

    // Run one plugin. Returns captured stdout as JSON text on success.
    PluginResult run(const std::string& pluginName, int timeoutSeconds = 600);

    // Locate vol: probe python_service/.venv/bin/vol, then PATH. Empty if none.
    static std::string resolveVolBinary();

private:
    std::string memPath_;
    std::string volBinary_;
    std::string symbolDir_;
};
