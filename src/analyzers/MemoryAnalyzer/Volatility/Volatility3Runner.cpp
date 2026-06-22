// Volatility3Runner.cpp
#include "Volatility3Runner.h"
#include "VolatilityPlugins.h"
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <unistd.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <signal.h>
#include <iostream>
#include <filesystem>
#include <array>
#include <chrono>

Volatility3Runner::Volatility3Runner(std::string memPath) : memPath_(std::move(memPath)) {
    volBinary_ = resolveVolBinary();
}

std::string Volatility3Runner::resolveVolBinary() {
    namespace fs = std::filesystem;
    // 1) project-local venv
    fs::path cwd = fs::current_path();
    fs::path venvVol = cwd / "python_service" / ".venv" / "bin" / "vol";
    if (fs::exists(venvVol)) return venvVol.string();
    // 2) walk up a few dirs (in case CWD differs from project root)
    fs::path p = cwd;
    for (int i = 0; i < 6 && p.has_parent_path(); ++i) {
        fs::path candidate = p / "python_service" / ".venv" / "bin" / "vol";
        if (fs::exists(candidate)) return candidate.string();
        p = p.parent_path();
    }
    // 3) PATH
    std::array<char, 4096> buf{};
    FILE* fp = popen("command -v vol", "r");
    if (fp) {
        if (fgets(buf.data(), buf.size(), fp)) {
            std::string s(buf.data());
            while (!s.empty() && (s.back() == '\n' || s.back() == '\r')) s.pop_back();
            if (!s.empty()) { pclose(fp); return s; }
        }
        pclose(fp);
    }
    return "";
}

PluginResult Volatility3Runner::run(const std::string& pluginName, int timeoutSeconds) {
    PluginResult result;
    if (volBinary_.empty()) {
        result.stderrText = "volatility3 'vol' binary not found (install into python_service/.venv)";
        return result;
    }
    if (access(memPath_.c_str(), R_OK) != 0) {
        result.stderrText = "cannot read memory image: " + memPath_;
        return result;
    }

    // Pipes: child stdout -> parent, child stderr -> parent
    int outPipe[2], errPipe[2];
    if (pipe(outPipe) != 0 || pipe(errPipe) != 0) {
        result.stderrText = "pipe() failed";
        return result;
    }

    pid_t pid = fork();
    if (pid < 0) {
        result.stderrText = "fork() failed";
        close(outPipe[0]); close(outPipe[1]); close(errPipe[0]); close(errPipe[1]);
        return result;
    }
    if (pid == 0) {
        // child
        dup2(outPipe[1], STDOUT_FILENO);
        dup2(errPipe[1], STDERR_FILENO);
        close(outPipe[0]); close(outPipe[1]);
        close(errPipe[0]); close(errPipe[1]);
        // NOTE: in vol3 2.x the plugin is a POSITIONAL arg placed LAST.
        // `-p` is --plugin-dirs, NOT the plugin name. Correct order: flags first, plugin last.
        execl(volBinary_.c_str(), "vol", "-r", "json",
              "-f", memPath_.c_str(), pluginName.c_str(), (char*)nullptr);
        _exit(127);  // exec failed
    }
    // parent
    close(outPipe[1]); close(errPipe[1]);

    auto readAll = [](int fd) {
        std::string s; std::array<char, 4096> b;
        ssize_t n;
        while ((n = read(fd, b.data(), b.size())) > 0) s.append(b.data(), n);
        return s;
    };

    // Wait with timeout
    bool timedOut = false;
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(timeoutSeconds);
    int status = 0;
    while (true) {
        pid_t r = waitpid(pid, &status, WNOHANG);
        if (r == pid) break;
        if (r == -1) { result.stderrText = "waitpid failed"; close(outPipe[0]); close(errPipe[0]); return result; }
        if (std::chrono::steady_clock::now() > deadline) {
            kill(pid, SIGTERM);
            timedOut = true;
            waitpid(pid, &status, 0);
            break;
        }
        usleep(100000);
    }
    result.jsonText = readAll(outPipe[0]);
    result.stderrText = readAll(errPipe[0]);
    close(outPipe[0]); close(errPipe[0]);

    if (timedOut) {
        result.stderrText += "\n[timeout after " + std::to_string(timeoutSeconds) + "s]";
        return result;
    }
    result.exitCode = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    result.ok = (result.exitCode == 0 && !result.jsonText.empty());
    return result;
}
