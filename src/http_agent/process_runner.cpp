#include "process_runner.h"

#include <algorithm>
#include <cerrno>
#include <csignal>
#include <cstring>
#include <fcntl.h>
#include <poll.h>
#include <sys/wait.h>
#include <unistd.h>

#include <string>
#include <vector>

namespace tracelens {

namespace {

// Cap captured stream size so a pathological child cannot exhaust RAM. A few
// MiB is ample for a forensic analyzer's progress/error tail.
constexpr size_t kStreamCap = 8 * 1024 * 1024;  // 8 MiB per stream

// Sets fd close-on-exec so a later execvp in another thread can't leak it.
bool set_cloexec(int fd) {
    int flags = fcntl(fd, F_GETFD);
    if (flags == -1) return false;
    return fcntl(fd, F_SETFD, flags | FD_CLOEXEC) != -1;
}

void set_nonblock(int fd) {
    int flags = fcntl(fd, F_GETFL);
    if (flags != -1) fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

// Drains fd into dest until EOF or would-block. Returns true on EOF. Past the
// cap, bytes are read-and-DISCARDED so the pipe keeps draining: if we stopped
// reading at the cap, a chatty child would block on write(), the poll loop
// would spin on POLLIN forever, waitpid() would never return, and the whole
// agent would wedge (the signal handler can't break a stuck run()). A forensic
// analyzer on a large case easily exceeds 8 MiB on either stream.
bool drain(int fd, std::string& dest) {
    if (fd < 0) return true;
    char buf[4096];
    while (true) {
        ssize_t n = read(fd, buf, sizeof(buf));
        if (n > 0) {
            if (dest.size() < kStreamCap) {
                size_t room = kStreamCap - dest.size();
                size_t take = std::min(static_cast<size_t>(n), room);
                dest.append(buf, take);
            }
            // else: cap reached — discard to keep the pipe draining.
        } else if (n == 0) {
            return true;  // EOF
        } else {
            if (errno == EINTR) continue;
            return false;  // EAGAIN (non-blocking, nothing right now) or error
        }
    }
}

}  // namespace

ProcessResult PosixProcessRunner::run(const std::vector<std::string>& argv,
                                      const std::string& work_dir) {
    ProcessResult r;
    if (argv.empty()) {
        r.error = "empty argv";
        return r;
    }

    int outp[2] = {-1, -1};
    int errp[2] = {-1, -1};
    if (pipe(outp) != 0 || pipe(errp) != 0) {
        r.error = std::string("pipe failed: ") + std::strerror(errno);
        if (outp[0] != -1) { close(outp[0]); close(outp[1]); }
        if (errp[0] != -1) { close(errp[0]); close(errp[1]); }
        return r;
    }

    pid_t pid = fork();
    if (pid == -1) {
        r.error = std::string("fork failed: ") + std::strerror(errno);
        close(outp[0]); close(outp[1]); close(errp[0]); close(errp[1]);
        return r;
    }

    if (pid == 0) {
        // ---- child ----
        // Redirect stdio FIRST, so any later failure diagnostic (chdir, exec)
        // is written to the captured pipe and reaches the parent — not lost to
        // the agent's inherited console.
        if (dup2(outp[1], STDOUT_FILENO) == -1 || dup2(errp[1], STDERR_FILENO) == -1) {
            _exit(127);
        }
        // Close all pipe descriptors in the child after dup2.
        close(outp[0]); close(outp[1]); close(errp[0]); close(errp[1]);

        if (!work_dir.empty() && chdir(work_dir.c_str()) != 0) {
            const std::string m = "chdir failed: " + std::string(std::strerror(errno)) + "\n";
            ssize_t w = write(STDERR_FILENO, m.data(), m.size());
            (void)w;
            _exit(127);
        }

        // Build a mutable char* argv (execvp requires char* const[], not const).
        std::vector<std::vector<char>> buffers;
        std::vector<char*> cargs;
        for (const auto& a : argv) {
            std::vector<char> b(a.begin(), a.end());
            b.push_back('\0');
            cargs.push_back(b.data());
            buffers.push_back(std::move(b));
        }
        cargs.push_back(nullptr);

        execvp(cargs[0], cargs.data());  // NO shell: argv is passed verbatim.
        // execvp only returns on failure.
        const std::string m = "exec failed: " + std::string(std::strerror(errno)) + "\n";
        ssize_t w = write(STDERR_FILENO, m.data(), m.size());
        (void)w;
        _exit(127);  // 127 = "command not found / not runnable" by convention.
    }

    // ---- parent ----
    close(outp[1]); close(errp[1]);  // close write ends so reads see EOF
    set_nonblock(outp[0]); set_nonblock(errp[0]);
    (void)set_cloexec(outp[0]); (void)set_cloexec(errp[0]);

    // Poll both pipes until EOF on both, draining each as it becomes ready.
    // Relying on drain()'s EOF return (not a dest.size() heuristic) means
    // discarding past the cap — which keeps size flat — still closes the stream
    // correctly at EOF.
    pollfd fds[2];
    fds[0].fd = outp[0];
    fds[1].fd = errp[0];
    bool out_open = true, err_open = true;
    while (out_open || err_open) {
        fds[0].events = out_open ? POLLIN : static_cast<short>(0);
        fds[1].events = err_open ? POLLIN : static_cast<short>(0);
        fds[0].revents = 0;
        fds[1].revents = 0;
        int pr = poll(fds, 2, -1);
        if (pr < 0) {
            if (errno == EINTR) continue;
            break;  // unrecoverable poll error; stop reading
        }
        if (out_open && (fds[0].revents & (POLLIN | POLLHUP | POLLERR))) {
            if (drain(outp[0], r.stdout_text)) out_open = false;  // EOF
        }
        if (err_open && (fds[1].revents & (POLLIN | POLLHUP | POLLERR))) {
            if (drain(errp[0], r.stderr_text)) err_open = false;  // EOF
        }
    }
    close(outp[0]); close(errp[0]);

    int status = 0;
    while (waitpid(pid, &status, 0) == -1) {
        if (errno == EINTR) continue;
        r.error = std::string("waitpid failed: ") + std::strerror(errno);
        return r;
    }
    if (WIFEXITED(status)) {
        r.exit_code = WEXITSTATUS(status);
    } else if (WIFSIGNALED(status)) {
        r.exit_code = 128 + WTERMSIG(status);  // shell-style 128+sig
    } else {
        r.exit_code = -1;
    }
    return r;
}

}  // namespace tracelens
