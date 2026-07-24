#pragma once

// Subprocess abstraction for the analyze_disk bridge (Task 17). The executor
// spawns the local `forensics_analyzer` binary to run analysis on the raw image
// — never linking the heavy forensic deps into this standalone build (see the
// task-17 brief, design decision D1). IProcessRunner decouples the executor
// from fork/exec so the argv-building + exit-handling logic is unit-tested with
// a FakeProcessRunner (no real process, no forensic binary required).
//
// SECURITY: argv is passed to execvp directly — NO shell — so a path containing
// spaces, quotes, '$()', etc. cannot inject commands. The image path is an
// untrusted local string (it came from the server command); shell-free exec is
// the injection defense.

#include <string>
#include <vector>

namespace tracelens {

struct ProcessResult {
    int exit_code = -1;       // child exit status; -1 means it never ran
    std::string stdout_text;  // captured child stdout (may be large; truncated)
    std::string stderr_text;  // captured child stderr
    std::string error;        // non-empty if spawn/wait failed (binary missing, etc.)

    bool ok() const { return error.empty() && exit_code == 0; }
};

class IProcessRunner {
public:
    virtual ~IProcessRunner() = default;
    // argv[0] is the program path; work_dir is the child cwd ("" = inherit).
    virtual ProcessResult run(const std::vector<std::string>& argv,
                              const std::string& work_dir) = 0;
};

// Production runner: fork/execvp/waitpid with pipes for stdout+stderr. Captures
// both streams fully (bounded — truncated at a few MiB to avoid unbounded RAM
// on a chatty child). Thread-safe: each call is self-contained (no shared state).
class PosixProcessRunner : public IProcessRunner {
public:
    ProcessResult run(const std::vector<std::string>& argv,
                      const std::string& work_dir) override;
};

}  // namespace tracelens
