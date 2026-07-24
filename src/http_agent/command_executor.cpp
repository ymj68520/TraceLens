#include "command_executor.h"

#include <algorithm>
#include <filesystem>
#include <system_error>

namespace fs = std::filesystem;

namespace tracelens {

ExecutionResult StubExecutor::execute(const Command& cmd) {
    ExecutionResult r;
    r.success = true;
    r.message = "stub execution of " + cmd.command_type;
    return r;
}

namespace {

// Reads a string field from the command parameters object, or "" if absent.
std::string param_string(const nlohmann::json& parameters, const char* key) {
    if (parameters.is_object() && parameters.contains(key) &&
        parameters[key].is_string()) {
        return parameters[key].get<std::string>();
    }
    return "";
}

bool param_bool(const nlohmann::json& parameters, const char* parent,
                const char* key) {
    if (!parameters.is_object() || !parameters.contains(parent)) return false;
    const auto& opts = parameters[parent];
    if (opts.is_object() && opts.contains(key) && opts[key].is_boolean()) {
        return opts[key].get<bool>();
    }
    return false;
}

std::string to_lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    return s;
}

std::string tail(const std::string& s, size_t n) {
    return s.size() <= n ? s : s.substr(s.size() - n);
}

}  // namespace

std::string image_base_name(const std::string& image_path) {
    // fs::path::stem() drops the last extension (case.E01 -> case).
    return fs::path(image_path).stem().string();
}

AnalyzerArgv build_analyzer_argv(const Command& cmd,
                                 const std::string& analyzer_path,
                                 const std::string& db_dir) {
    AnalyzerArgv out;
    if (analyzer_path.empty()) {
        out.error = "analyzer binary path is not configured";
        return out;
    }
    out.image_path = param_string(cmd.parameters, "image_path");
    if (out.image_path.empty()) {
        out.error = "analyze_disk command is missing 'image_path'";
        return out;
    }

    std::vector<std::string>& a = out.argv;
    a.push_back(analyzer_path);
    a.push_back(out.image_path);          // positional image path
    a.push_back("--db-dir");
    a.push_back(db_dir);
    a.push_back("--no-ai");               // INVARIANT: client never runs the LLM.
    a.push_back("--overwrite");           // fresh dir, but always regenerate cleanly.

    const std::string atype = to_lower(param_string(cmd.parameters, "analysis_type"));
    if (atype == "windows")      a.push_back("--windows-analyze");
    else if (atype == "linux")   a.push_back("--linux-analyze");
    else if (atype == "android") a.push_back("--android-analyze");
    // "full"/"quick"/unknown: defer to the analyzer default (no platform flag).

    // options.file_carving -> --carve. options.llm_text_extraction is
    // INTENTIONALLY ignored (the client never runs the LLM; --no-ai above).
    if (param_bool(cmd.parameters, "options", "file_carving")) {
        a.push_back("--carve");
    }
    return out;
}

std::vector<ResultArtifact> collect_db_artifacts(const std::string& image_path,
                                                 const std::string& db_dir,
                                                 const std::string& hostname) {
    std::vector<ResultArtifact> out;
    std::error_code ec;
    if (db_dir.empty()) return out;
    const std::string base = image_base_name(image_path);
    if (base.empty()) return out;

    for (const auto& entry : fs::directory_iterator(db_dir, ec)) {
        if (ec) break;
        if (!entry.is_regular_file()) continue;
        const std::string name = entry.path().filename().string();
        // <baseName>*.db (case-insensitive suffix), excluding temp journals.
        if (name.rfind(base, 0) != 0) continue;
        const std::string lower = to_lower(name);
        // The ".db" suffix requirement already excludes SQLite sidecars
        // (case.db-wal / -shm / -journal), since those end in -wal/-shm/-journal,
        // not .db. No separate sidecar filter is needed.
        if (lower.size() < 3 || lower.compare(lower.size() - 3, 3, ".db") != 0) {
            continue;
        }
        ResultArtifact art;
        art.result_type = "database";
        art.file_path = fs::absolute(entry.path(), ec).string();
        std::error_code sec;
        const auto sz = fs::file_size(entry.path(), sec);
        if (!sec) art.file_size = static_cast<uint64_t>(sz);
        art.storage_location = hostname.empty() ? "client-local" : hostname;
        art.result_metadata = {{"base_name", base}};
        out.push_back(std::move(art));
    }
    // Stable order for deterministic test assertions.
    std::sort(out.begin(), out.end(),
              [](const ResultArtifact& x, const ResultArtifact& y) {
                  return x.file_path < y.file_path;
              });
    return out;
}

AnalyzeDiskExecutor::AnalyzeDiskExecutor(IProcessRunner& runner,
                                         const std::string& analyzer_path,
                                         const std::string& work_base_dir,
                                         const std::string& hostname)
    : runner_(runner),
      analyzer_path_(analyzer_path),
      work_base_dir_(work_base_dir),
      hostname_(hostname) {}

ExecutionResult AnalyzeDiskExecutor::execute(const Command& cmd) {
    ExecutionResult r;
    cmd.has_task_id(r.task_id);  // empty if no soft link

    // Non-analyze commands: acknowledge + succeed (health_check, etc.).
    if (cmd.command_type != "analyze_disk") {
        r.success = true;
        r.message = "ignored non-analyze command: " + cmd.command_type;
        return r;
    }

    const std::string image_path = param_string(cmd.parameters, "image_path");
    if (image_path.empty()) {
        r.success = false;
        r.message = "analyze_disk command is missing 'image_path' (no analysis run)";
        return r;
    }
    // Pre-check the image exists locally so we fail fast with a clear message
    // rather than spawning the analyzer to discover the same thing. Identify the
    // case by its stem only — the full raw-image path must never appear in any
    // uploaded status body.
    std::error_code ec;
    if (!fs::exists(image_path, ec)) {
        r.success = false;
        r.message = "image not found locally: " + image_base_name(image_path);
        return r;
    }

    // Fresh per-command work dir = the analyzer --db-dir. Everything <base>*.db
    // in it after the run belongs to this command (no stale contamination).
    const fs::path work_dir = fs::path(work_base_dir_) / cmd.id;
    fs::create_directories(work_dir, ec);
    if (ec) {
        r.success = false;
        r.message = "cannot create work dir " + work_dir.string() + ": " + ec.message();
        return r;
    }

    const auto built = build_analyzer_argv(cmd, analyzer_path_, work_dir.string());
    if (!built.valid()) {
        r.success = false;
        r.message = built.error;
        return r;
    }

    const auto pr = runner_.run(built.argv, work_dir.string());
    if (!pr.error.empty()) {
        r.success = false;
        r.message = "failed to run analyzer: " + pr.error;
        return r;
    }
    if (pr.exit_code != 0) {
        r.success = false;
        r.message = "analyzer exited " + std::to_string(pr.exit_code);
        if (!pr.stderr_text.empty()) {
            r.message += ": " + tail(pr.stderr_text, 500);
        }
        return r;
    }

    r.artifacts = collect_db_artifacts(image_path, work_dir.string(), hostname_);
    r.success = true;
    // No image_path in the message: this string is POSTed to the server in the
    // status body, and the raw-image path must never leave the client.
    r.message = "analyzed; " + std::to_string(r.artifacts.size()) + " artifact(s)";
    if (r.artifacts.empty()) {
        // Analyzer reported success but produced no DBs — surface as a warning
        // in the message; the task is still marked completed (analyzer success).
        r.message += " (warning: no output databases found)";
    }
    return r;
}

}  // namespace tracelens
