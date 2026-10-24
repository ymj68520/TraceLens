#include "AliyunImagePreparation.h"
#include <array>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <thread>
#include <vector>
#ifndef _WIN32
#include <fcntl.h>
#include <poll.h>
#include <spawn.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>
extern char** environ;
#endif

AliyunImageResult prepareAliyunImage(const std::string& source, const std::string& work,
    const std::string& sha256, const std::function<void(uint64_t, uint64_t)>& progress,
    const std::function<bool()>& cancelled) {
    AliyunImageResult result;
#ifdef _WIN32
    result.code = "ALIYUN_REQUIRES_LINUX_RUNTIME";
#else
    namespace fs = std::filesystem;
    try {
        const char* configured = std::getenv("TRACELENS_RELEASE_ROOT");
        std::string root;
        if (configured && *configured) root = configured;
#ifdef TRACELENS_SOURCE_ROOT
        else root = TRACELENS_SOURCE_ROOT;
#endif
        const auto script = fs::path(root) / "python_service/httpserver/services/aliyun_image.py";
        const char* python = std::getenv("TRACELENS_PYTHON_BIN");
        std::vector<std::string> args{python && *python ? python : "/usr/bin/python3",
            script.string(), source, work, sha256};
        if (!fs::path(root).is_absolute() || !fs::is_regular_file(script) ||
            !fs::path(args[0]).is_absolute() || !fs::is_regular_file(args[0])) {
            result.code = "ALIYUN_RUNTIME_NOT_CONFIGURED"; return result;
        }
        std::vector<char*> argv;
        for (auto& value : args) argv.push_back(value.data());
        argv.push_back(nullptr);
        int pipes[2];
        if (pipe(pipes)) { result.code = "ALIYUN_PIPE_FAILED"; return result; }
        posix_spawn_file_actions_t actions;
        posix_spawn_file_actions_init(&actions);
        posix_spawn_file_actions_adddup2(&actions, pipes[1], STDOUT_FILENO);
        posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
        posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
        posix_spawn_file_actions_addclose(&actions, pipes[0]);
        posix_spawn_file_actions_addclose(&actions, pipes[1]);
        pid_t pid = -1;
        const int spawned = posix_spawn(&pid, argv[0], &actions, nullptr, argv.data(), environ);
        posix_spawn_file_actions_destroy(&actions);
        close(pipes[1]);
        if (spawned) { close(pipes[0]); result.code = "ALIYUN_SPAWN_FAILED"; return result; }
        fcntl(pipes[0], F_SETFL, O_NONBLOCK);
        std::string pending;
        uint64_t done = 0, total = 0;
        bool stopped = false;
        auto heartbeat = std::chrono::steady_clock::now();
        const auto deadline = heartbeat + std::chrono::hours(2);
        while (true) {
            if (cancelled() || std::chrono::steady_clock::now() > deadline) {
                result.code = cancelled() ? "ALIYUN_CANCELLED" : "ALIYUN_TIMEOUT";
                stopped = true; break;
            }
            if (std::chrono::steady_clock::now()-heartbeat > std::chrono::seconds(2)) {
                progress(done, total); heartbeat = std::chrono::steady_clock::now();
            }
            pollfd descriptor{pipes[0], POLLIN, 0};
            if (poll(&descriptor, 1, 250) < 0) { stopped = true; break; }
            if (!descriptor.revents) continue;
            std::array<char, 8192> buffer{};
            const auto count = read(pipes[0], buffer.data(), buffer.size());
            if (count == 0) break;
            if (count < 0) continue;
            pending.append(buffer.data(), count);
            if (pending.size() > 512 * 1024) { stopped = true; break; }
            size_t newline;
            while ((newline = pending.find('\n')) != std::string::npos) {
                const auto line = pending.substr(0, newline);
                pending.erase(0, newline+1);
                try {
                    const auto event = nlohmann::json::parse(line);
                    const auto type = event.value("type", "");
                    if (type == "progress") {
                        done = event.at("done").get<uint64_t>();
                        total = event.at("total").get<uint64_t>();
                    } else if (type == "complete") result.manifest = event.at("manifest");
                    else if (type == "error") result.code = event.at("code").get<std::string>();
                } catch (...) { stopped = true; }
            }
            if (stopped) break;
        }
        close(pipes[0]);
        int status = 0;
        if (stopped) {
            kill(pid, SIGTERM);
            bool reaped = false;
            for (int i=0; i<50; ++i) {
                if (waitpid(pid, &status, WNOHANG) == pid) { reaped = true; break; }
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
            }
            if (!reaped) { kill(pid, SIGKILL); waitpid(pid, &status, 0); }
            // A forced stop may bypass the Python finally block. Only remove
            // incomplete files at our fixed task-owned paths, never a published RAW.
            std::error_code cleanupError;
            fs::remove(fs::path(work) / "system.raw.partial", cleanupError);
            fs::remove(fs::path(work) / "source_manifest.json.partial", cleanupError);
            return result;
        }
        waitpid(pid, &status, 0);
        if (!WIFEXITED(status) || WEXITSTATUS(status) != 0 || cancelled()) return result;
        const auto& m = result.manifest;
        const auto expected = fs::path(work) / "system.raw";
        if (m.at("status") != "verified" || m.at("source_sha256") != sha256 ||
            !m.at("gzip_crc_verified").get<bool>() || !m.at("single_raw_verified").get<bool>() ||
            fs::canonical(m.at("source_path").get<std::string>()) != fs::canonical(source) ||
            fs::canonical(m.at("derived_path").get<std::string>()) != fs::canonical(expected) ||
            fs::is_symlink(expected) || !fs::is_regular_file(expected) ||
            fs::file_size(expected) != m.at("raw_size").get<uint64_t>()) return result;
        result.okay = true;
        result.code = "VERIFIED";
    } catch (...) {}
#endif
    return result;
}
