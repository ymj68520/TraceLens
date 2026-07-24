#pragma once

// The local execution seam.
//
// Task 16 shipped ICommandExecutor + StubExecutor so the loop ran end-to-end.
// Task 17 adds AnalyzeDiskExecutor: the real bridge that runs the local
// `forensics_analyzer` binary on the raw image via an injected IProcessRunner,
// then collects the derived SQLite artifacts it produced. The service loop
// uploads those artifacts (ResultUploader) and reports terminal status.
//
// SECURITY INVARIANTS (enforced here, documented for the reviewer):
//  1. The raw disk image NEVER leaves the client. Execution is local; only
//     derived artifacts are collected and (by the loop) uploaded as METADATA.
//  2. The client NEVER runs the LLM. options.llm_text_extraction is IGNORED;
//     `--no-ai` is ALWAYS appended to the analyzer argv (no network/keys; LLM
//     is the server's job).

#include "models/command.h"
#include "process_runner.h"
#include "result_artifact.h"

#include <string>
#include <vector>

namespace tracelens {

struct ExecutionResult {
    bool success = true;
    std::string message;  // progress/error text (becomes the task message)
    std::string task_id;  // parsed task soft-link (empty if none) — drives upload
    std::vector<ResultArtifact> artifacts;  // derived artifacts produced locally
};

class ICommandExecutor {
public:
    virtual ~ICommandExecutor() = default;
    virtual ExecutionResult execute(const Command& cmd) = 0;
};

// No-op executor: acknowledges and succeeds. Kept for non-analyze command types
// and as a test stand-in (the real analyze_disk bridge is AnalyzeDiskExecutor).
class StubExecutor : public ICommandExecutor {
public:
    ExecutionResult execute(const Command& cmd) override;
};

// Builds the analyzer argv from a command's parameters (pure, testable).
// Returns a non-empty error string if the command is malformed (e.g. missing
// image_path); argv is empty in that case.
struct AnalyzerArgv {
    std::vector<std::string> argv;
    std::string image_path;  // the resolved positional image path
    std::string error;       // non-empty if malformed
    bool valid() const { return error.empty() && !argv.empty(); }
};
AnalyzerArgv build_analyzer_argv(const Command& cmd,
                                 const std::string& analyzer_path,
                                 const std::string& db_dir);

// The image's base name (filename without extension) used to glob output DBs.
std::string image_base_name(const std::string& image_path);

// Globs <db_dir>/<baseName>*.db into database artifacts with real file sizes.
// Pure over the filesystem state (tested by creating temp .db files). hostname
// labels the storage_location so the server knows which client holds the DB.
std::vector<ResultArtifact> collect_db_artifacts(const std::string& image_path,
                                                 const std::string& db_dir,
                                                 const std::string& hostname);

// Real analyze_disk bridge. Routes analyze_disk to the forensic binary via an
// injected runner; any other command_type is acknowledged + succeeds (so health
// checks and unknown commands do not abort the loop). Each command runs in a
// fresh per-command subdir of work_base_dir (named by command id) passed as
// --db-dir, so artifact collection is unambiguous.
class AnalyzeDiskExecutor : public ICommandExecutor {
public:
    AnalyzeDiskExecutor(IProcessRunner& runner,
                        const std::string& analyzer_path,
                        const std::string& work_base_dir,
                        const std::string& hostname = "");

    ExecutionResult execute(const Command& cmd) override;

private:
    IProcessRunner& runner_;
    std::string analyzer_path_;
    std::string work_base_dir_;
    std::string hostname_;
};

}  // namespace tracelens
