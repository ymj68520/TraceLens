#include "AndroidContainerNormalization.h"
#include "PathManager/PathManager.h"

#include <array>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <string>
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

namespace fs = std::filesystem;

AndroidContainerNormalizationResult normalizeAndroidContainer(
    const std::string& source, const std::string& taskDirectory,
    const std::string& expectedSourceHash, const std::string& expectedPlanHash,
    int selectedSlot, const std::function<void()>& heartbeat,
    const std::function<bool()>& cancelled) {
    AndroidContainerNormalizationResult result;
    result.code = "NORMALIZATION_FAILED";
#ifndef _WIN32
    if (selectedSlot < 0 || selectedSlot > 31 || expectedSourceHash.size() != 64 ||
        expectedPlanHash.size() != 64 || cancelled()) return result;
    std::error_code ec;
    const fs::path taskRoot = fs::canonical(taskDirectory, ec);
    if (ec || !fs::is_directory(taskRoot)) return result;
    const fs::path tasksRoot = fs::canonical(
        forensics::PathManager::instance().getDataDir() / "tasks", ec);
    if (ec || taskRoot.parent_path() != tasksRoot) {
        result.code = "TASK_WORKDIR_CONFINEMENT_FAILED"; return result;
    }
    const fs::path work = taskRoot / "work" / "android_normalization";
    if (!fs::create_directories(work, ec) && !fs::is_directory(work, ec)) return result;
    if (ec || fs::is_symlink(fs::symlink_status(work, ec)) ||
        fs::weakly_canonical(work).lexically_relative(taskRoot).string().rfind("..", 0) == 0)
        return result;
    fs::permissions(work, fs::perms::owner_all, fs::perm_options::replace, ec);
    if (ec) return result;

    const char* fieldValue = std::getenv("TRACELENS_FIELD_AUTH");
    const char* releaseRequired = std::getenv("TRACELENS_REQUIRE_RELEASE_LAYOUT");
    const bool fieldRelease = fieldValue && std::string(fieldValue) == "enabled" &&
        releaseRequired && std::string(releaseRequired) == "1";
    const char* configuredRoot = std::getenv("TRACELENS_RELEASE_ROOT");
    const char* configuredPython = std::getenv("TRACELENS_PYTHON_BIN");
    std::string project;
    std::string python;
    if (fieldRelease) {
        if (!configuredRoot || !configuredPython ||
            !fs::path(configuredRoot).is_absolute() ||
            !fs::path(configuredPython).is_absolute()) {
            result.code = "NORMALIZATION_BRIDGE_NOT_CONFIGURED"; return result;
        }
        project = fs::canonical(configuredRoot, ec).string();
        python = configuredPython;
        if (ec || !fs::is_regular_file(python) ||
            !fs::is_regular_file(fs::path(project) / "scripts/android_container_pipeline_cli.py")) {
            result.code = "NORMALIZATION_BRIDGE_NOT_CONFIGURED"; return result;
        }
    } else {
#ifdef TRACELENS_SOURCE_ROOT
        project = TRACELENS_SOURCE_ROOT;
        python = project + "/python_service/.venv/bin/python";
#else
        result.code = "NORMALIZATION_BRIDGE_NOT_CONFIGURED"; return result;
#endif
    }
    std::vector<std::string> command{
        python,
        project + "/scripts/android_container_pipeline_cli.py",
        source, work.string(), expectedSourceHash, expectedPlanHash,
        std::to_string(selectedSlot)};
    std::vector<char*> argv;
    for (auto& item : command) argv.push_back(item.data());
    argv.push_back(nullptr);
    int outPipe[2], errPipe[2];
    if (pipe(outPipe) || pipe(errPipe)) { result.code = "NORMALIZATION_PIPE_FAILED"; return result; }
    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_adddup2(&actions, outPipe[1], STDOUT_FILENO);
    posix_spawn_file_actions_adddup2(&actions, errPipe[1], STDERR_FILENO);
    posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
    for (int fd : {outPipe[0], outPipe[1], errPipe[0], errPipe[1]})
        posix_spawn_file_actions_addclose(&actions, fd);
    pid_t pid = -1;
    const int spawned = posix_spawn(&pid, command[0].c_str(), &actions,
                                    nullptr, argv.data(), environ);
    posix_spawn_file_actions_destroy(&actions);
    close(outPipe[1]); close(errPipe[1]);
    if (spawned != 0) {
        close(outPipe[0]); close(errPipe[0]);
        result.code = "NORMALIZATION_SPAWN_FAILED"; return result;
    }
    fcntl(outPipe[0], F_SETFL, O_NONBLOCK);
    fcntl(errPipe[0], F_SETFL, O_NONBLOCK);
    bool outOpen = true, errOpen = true, stopped = false;
    std::string output, error;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::hours(2);
    auto lastHeartbeat = std::chrono::steady_clock::now();
    while (outOpen || errOpen) {
        if (cancelled() || std::chrono::steady_clock::now() >= deadline) {
            stopped = true; break;
        }
        if (std::chrono::steady_clock::now() - lastHeartbeat >= std::chrono::seconds(5)) {
            heartbeat(); lastHeartbeat = std::chrono::steady_clock::now();
        }
        pollfd fds[2]{{outPipe[0], static_cast<short>(outOpen ? POLLIN : 0), 0},
                      {errPipe[0], static_cast<short>(errOpen ? POLLIN : 0), 0}};
        if (poll(fds, 2, 250) < 0) { stopped = true; break; }
        auto drain = [&](int fd, bool& openFlag, std::string& target, std::size_t max) {
            if (!openFlag) return;
            std::array<char, 8192> bytes{};
            const auto readCount = read(fd, bytes.data(), bytes.size());
            if (readCount == 0) { openFlag = false; close(fd); }
            else if (readCount > 0) {
                if (target.size() + static_cast<std::size_t>(readCount) > max) stopped = true;
                else target.append(bytes.data(), static_cast<std::size_t>(readCount));
            }
        };
        if (fds[0].revents) drain(outPipe[0], outOpen, output, 8 * 1024 * 1024);
        if (fds[1].revents) drain(errPipe[0], errOpen, error, 8192);
        if (stopped) break;
    }
    if (outOpen) close(outPipe[0]);
    if (errOpen) close(errPipe[0]);
    if (stopped) kill(pid, SIGKILL);
    int exitStatus = 0;
    waitpid(pid, &exitStatus, 0);
    if (stopped) { result.code = cancelled() ? "NORMALIZATION_CANCELLED" : "NORMALIZATION_TIMEOUT_OR_LIMIT"; return result; }
    if (!WIFEXITED(exitStatus) || WEXITSTATUS(exitStatus) != 0) {
        try {
            const auto reported = nlohmann::json::parse(error.substr(error.rfind('\n') + 1));
            result.code = reported.value("code", std::string("NORMALIZATION_FAILED"));
        } catch (...) {
            // Error output may have AOSP diagnostics before/after the JSON.
            const auto first = error.find("{\"status\":\"ERROR\"");
            if (first != std::string::npos) {
                try { result.code = nlohmann::json::parse(error.substr(first)).value("code", result.code); }
                catch (...) {}
            }
        }
        return result;
    }
    try {
        result.manifest = nlohmann::json::parse(output);
        if (result.manifest.at("status") != "COMPLETE" ||
            result.manifest.at("source_sha256") != expectedSourceHash ||
            result.manifest.at("plan_sha256") != expectedPlanHash ||
            result.manifest.at("selected_slot").get<int>() != selectedSlot ||
            fs::canonical(result.manifest.at("manifest_path").get<std::string>()).parent_path() != taskRoot) {
            result.code = "NORMALIZATION_OUTPUT_MISMATCH"; return result;
        }
        const std::string kind = result.manifest.at("normalized_kind").get<std::string>();
        if (kind == "userdata") {
            if (fs::canonical(result.manifest.at("derived_image").get<std::string>()).parent_path() !=
                fs::canonical(work)) {
                result.code = "DERIVED_IMAGE_ESCAPES_TASK_WORKDIR"; return result;
            }
        } else if (kind == "super") {
            const fs::path expected = fs::canonical(work / "super");
            for (const auto& partition : result.manifest.at("partition_provenance")) {
                if (fs::canonical(partition.at("derived_partition_path").get<std::string>()).parent_path() !=
                    expected) {
                    result.code = "DERIVED_PARTITION_ESCAPES_TASK_WORKDIR"; return result;
                }
            }
        } else {
            result.code = "NORMALIZATION_KIND_UNSUPPORTED"; return result;
        }
        result.okay = true; result.code.clear();
    } catch (const std::exception&) { result.code = "NORMALIZATION_IPC_INVALID"; }
#else
    (void)source; (void)taskDirectory; (void)expectedSourceHash; (void)expectedPlanHash;
    (void)selectedSlot; (void)heartbeat; (void)cancelled;
    result.code = "NORMALIZATION_UNAVAILABLE_ON_THIS_PLATFORM";
#endif
    return result;
}
