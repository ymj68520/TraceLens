#include "DecryptionModule.h"
#include "PathManager/PathManager.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <cstring>
#include <cstdlib>
#include <unistd.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <poll.h>
#include <fcntl.h>
#include <cerrno>
#include <filesystem>

namespace fs = std::filesystem;

namespace {
int executeProcess(const std::vector<std::string>& argv, const std::string& stdinData,
                   std::string& output) {
    if (argv.empty() || argv.front().empty()) return -1;

    int sockets[2];
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) != 0) return -1;

    pid_t pid = fork();
    if (pid < 0) {
        close(sockets[0]);
        close(sockets[1]);
        return -1;
    }

    if (pid == 0) {
        close(sockets[0]);
        if (dup2(sockets[1], STDIN_FILENO) < 0 ||
            dup2(sockets[1], STDOUT_FILENO) < 0 ||
            dup2(sockets[1], STDERR_FILENO) < 0) {
            _exit(126);
        }
        if (sockets[1] > STDERR_FILENO) close(sockets[1]);

        std::vector<char*> args;
        args.reserve(argv.size() + 1);
        for (const auto& arg : argv) args.push_back(const_cast<char*>(arg.c_str()));
        args.push_back(nullptr);
        execvp(args[0], args.data());
        _exit(errno == ENOENT ? 127 : 126);
    }

    close(sockets[1]);
    int flags = fcntl(sockets[0], F_GETFL, 0);
    if (flags >= 0) fcntl(sockets[0], F_SETFL, flags | O_NONBLOCK);

    size_t written = 0;
    bool inputOpen = true;
    bool outputOpen = true;
    while (inputOpen || outputOpen) {
        pollfd pfd{};
        pfd.fd = sockets[0];
        pfd.events = POLLIN;
        if (inputOpen && written < stdinData.size()) pfd.events |= POLLOUT;
        if (poll(&pfd, 1, -1) < 0) {
            if (errno == EINTR) continue;
            break;
        }

        if (inputOpen && written < stdinData.size() && (pfd.revents & POLLOUT)) {
            ssize_t n = send(sockets[0], stdinData.data() + written,
                             stdinData.size() - written, MSG_NOSIGNAL);
            if (n > 0) written += static_cast<size_t>(n);
            else if (n < 0 && errno != EINTR && errno != EAGAIN) inputOpen = false;
        }
        if (inputOpen && written == stdinData.size()) {
            shutdown(sockets[0], SHUT_WR);
            inputOpen = false;
        }

        if (pfd.revents & (POLLIN | POLLHUP | POLLERR)) {
            char buffer[4096];
            for (;;) {
                ssize_t n = read(sockets[0], buffer, sizeof(buffer));
                if (n > 0) output.append(buffer, static_cast<size_t>(n));
                else if (n == 0) { outputOpen = false; break; }
                else if (errno == EINTR) continue;
                else if (errno == EAGAIN || errno == EWOULDBLOCK) break;
                else { outputOpen = false; break; }
            }
        }
    }
    close(sockets[0]);

    int status = 0;
    while (waitpid(pid, &status, 0) < 0) {
        if (errno != EINTR) return -1;
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return -1;
}

// Read the first `count` bytes at byte offset `offset` from a disk image.
// Tries raw read first; if the file is EWF (which cannot be pread directly),
// falls back to ewfexport of a small range. Returns empty on failure.
std::string readImageBytes(const std::string& imagePath, uint64_t offset, size_t count) {
    std::string ext = fs::path(imagePath).extension().string();
    for (char& c : ext) c = static_cast<char>(std::tolower(c));
    const bool ewf = (ext == ".e01" || ext == ".ex01");

    // Try raw pread for non-EWF image formats. EWF container bytes are not the
    // logical evidence bytes at the requested partition offset.
    int fd = ewf ? -1 : open(imagePath.c_str(), O_RDONLY);
    if (fd >= 0) {
        std::string buf(count, '\0');
        ssize_t n = pread(fd, buf.data(), count, static_cast<off_t>(offset));
        close(fd);
        if (n == static_cast<ssize_t>(count)) return buf;
        // Fall through to ewfexport for partial/failed reads (EWF files fail pread).
    }

    // EWF fallback: ewfexport a small range to a temp file, then read it.
    // NOTE: ewfexport -t <prefix> appends ".raw" itself, so pass a prefix with
    // NO extension (otherwise we'd get <tmp>.raw.raw and read the wrong file).
    std::string tmpPrefix = forensics::PathManager::instance().makeTempPath("dec_probe_", "");
    std::string tmp = tmpPrefix + ".raw";  // file ewfexport actually writes
    std::string output;
    executeProcess({"ewfexport", "-u", "-f", "raw", "-t", tmpPrefix, "-o",
                    std::to_string(offset), "-B", std::to_string(count), imagePath},
                   "", output);
    std::string result;
    std::ifstream in(tmp, std::ios::binary);
    if (in) {
        result.assign((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    }
    std::error_code ec;
    fs::remove(tmp, ec);
    fs::remove(tmp + ".info", ec);  // ewfexport writes a sidecar .info file
    if (result.size() > count) result.resize(count);
    return result;
}

} // namespace

// ── public API ──────────────────────────────────────────────────────────────

EncryptionType DecryptionModule::detect(const std::string& imagePath, uint64_t partitionOffset) {
    std::string head = readImageBytes(imagePath, partitionOffset, 512);
    if (head.size() < 8) return EncryptionType::UNKNOWN;

    // BitLocker: "-FVE-FS-" at offset 3 of the volume boot sector.
    if (head.size() >= 11 && head.compare(3, 8, "-FVE-FS-") == 0) {
        return EncryptionType::BITLOCKER;
    }
    // LUKS: "LUKS\xba\xbe" magic at offset 0.
    if (head.size() >= 6 && head[0] == 'L' && head[1] == 'U' && head[2] == 'K' &&
        head[3] == 'S' && static_cast<unsigned char>(head[4]) == 0xba &&
        static_cast<unsigned char>(head[5]) == 0xbe) {
        return EncryptionType::LUKS;
    }
    // VeraCrypt / TrueCrypt: signature "TRUE" at offset 0 (TrueCrypt) or no
    // clear magic (VeraCrypt headers are indistinguishable from random).
    if (head.size() >= 4 && (head.compare(0, 4, "TRUE") == 0 ||
                             head.compare(0, 4, "VERA") == 0)) {
        return EncryptionType::VERACRYPT;
    }
    // TSK reports "Encryption detected (BitLocker)" for some volumes whose
    // boot sector bytes are zeroed (BitLocker sometimes relocates the header).
    // If all-zero first sector, treat as UNKNOWN (may still be BitLocker).
    if (head.size() >= 512) {
        bool allZero = true;
        for (char c : head) { if (c != 0) { allZero = false; break; } }
        if (allZero) return EncryptionType::UNKNOWN;
    }
    return EncryptionType::NONE;
}

std::string DecryptionModule::encryptionTypeName(EncryptionType t) {
    switch (t) {
        case EncryptionType::BITLOCKER: return "BitLocker";
        case EncryptionType::LUKS:      return "LUKS";
        case EncryptionType::VERACRYPT: return "VeraCrypt";
        case EncryptionType::UNKNOWN:   return "Unknown-encrypted";
        default:                        return "None";
    }
}

bool DecryptionModule::isToolAvailable(const std::string& tool) {
    if (tool.empty() || tool.find('/') != std::string::npos) {
        return !tool.empty() && access(tool.c_str(), X_OK) == 0;
    }

    const char* pathEnv = std::getenv("PATH");
    if (!pathEnv) return false;
    std::stringstream paths(pathEnv);
    std::string dir;
    while (std::getline(paths, dir, ':')) {
        if (dir.empty()) dir = ".";
        fs::path candidate = fs::path(dir) / tool;
        if (access(candidate.c_str(), X_OK) == 0) return true;
    }
    return false;
}

int DecryptionModule::runProcess(const std::vector<std::string>& argv,
                                 const std::string& stdinData, std::string& output) {
    return executeProcess(argv, stdinData, output);
}

bool DecryptionModule::isEwfImage(const std::string& imagePath) {
    // Heuristic: E01 files start with 0x45 0x56 0x46 (EVF) signature bytes,
    // or have an .e01/.E01 extension.
    std::string ext = fs::path(imagePath).extension().string();
    std::string lower = ext;
    for (char& c : lower) c = static_cast<char>(std::tolower(c));
    if (lower == ".e01" || lower == ".ex01") return true;
    // Also check magic bytes (3 bytes: 0x45 0x56 0x46).
    int fd = open(imagePath.c_str(), O_RDONLY);
    if (fd < 0) return false;
    char magic[3] = {0, 0, 0};
    ssize_t n = read(fd, magic, 3);
    close(fd);
    if (n == 3 && (unsigned char)magic[0] == 0x45 && (unsigned char)magic[1] == 0x56 &&
        (unsigned char)magic[2] == 0x46) {
        return true;
    }
    return false;
}

bool DecryptionModule::decrypt(const std::string& imagePath, uint64_t partitionOffset,
                               const std::string& password, DecryptedPartition& out,
                               std::string& errMsg) {
    EncryptionType t = detect(imagePath, partitionOffset);
    // detect() may return UNKNOWN for all-zero BitLocker boot sectors; allow
    // the caller to have pre-set the type via out.encType.
    if (t == EncryptionType::UNKNOWN && out.encType != EncryptionType::NONE) {
        t = out.encType;
    }
    out.encType = t;

    switch (t) {
        case EncryptionType::LUKS:
            return decryptLuks(imagePath, partitionOffset, password, out, errMsg);
        case EncryptionType::BITLOCKER:
            return decryptBitlocker(imagePath, partitionOffset, password, out, errMsg);
        case EncryptionType::VERACRYPT:
            return decryptVeracrypt(imagePath, partitionOffset, password, out, errMsg);
        default:
            errMsg = "unrecognised or unsupported encryption type at offset " +
                     std::to_string(partitionOffset);
            return false;
    }
}

// ── LUKS (cryptsetup) ───────────────────────────────────────────────────────

bool DecryptionModule::setupLoopForPartition(const std::string& imagePath, uint64_t partitionOffset,
                                             std::string& loopDevice, std::string& tempFile,
                                             std::string& errMsg) {
    if (isEwfImage(imagePath)) {
        // cryptsetup/losetup cannot read EWF directly: extract the partition
        // to a temp raw file. We extract a generous range (the whole rest of
        // the image from the offset) — accurate size is not required for
        // cryptsetup open, which reads the LUKS header + payload it needs.
        // ewfexport -t appends ".raw" itself, so the prefix has no extension.
        std::string tmpPrefix = forensics::PathManager::instance().makeTempPath("dec_part_", "");
        tempFile = tmpPrefix + ".raw";
        std::string out;
        int rc = runProcess({"ewfexport", "-u", "-f", "raw", "-t", tmpPrefix, "-o",
                             std::to_string(partitionOffset), imagePath}, "", out);
        if (rc != 0) {
            errMsg = "ewfexport failed to extract partition: " + out;
            return false;
        }
        // Attach a loop device to the extracted file.
        std::string loopOut;
        if (runProcess({"losetup", "-f", "--show", "-r", tempFile}, "", loopOut) != 0 ||
            loopOut.empty()) {
            errMsg = "losetup failed: " + loopOut;
            std::error_code ec;
            fs::remove(tempFile, ec);
            return false;
        }
        loopDevice = loopOut;
        while (!loopDevice.empty() && (loopDevice.back() == '\n' || loopDevice.back() == '\r'))
            loopDevice.pop_back();
        return true;
    }

    // Raw/DD image: loop device with offset directly (no extraction needed).
    std::string loopOut;
    if (runProcess({"losetup", "-f", "--show", "-r", "-o",
                    std::to_string(partitionOffset), imagePath}, "", loopOut) != 0 ||
        loopOut.empty()) {
        errMsg = "losetup failed: " + loopOut;
        return false;
    }
    loopDevice = loopOut;
    while (!loopDevice.empty() && (loopDevice.back() == '\n' || loopDevice.back() == '\r'))
        loopDevice.pop_back();
    return true;
}

void DecryptionModule::detachLoop(const std::string& loopDevice) {
    if (!loopDevice.empty()) {
        std::string discard;
        runProcess({"losetup", "-d", loopDevice}, "", discard);
    }
}

bool DecryptionModule::decryptLuks(const std::string& imagePath, uint64_t partitionOffset,
                                   const std::string& password, DecryptedPartition& out,
                                   std::string& errMsg) {
    if (!isToolAvailable("cryptsetup")) {
        errMsg = "cryptsetup not found on PATH (install cryptsetup-bin)";
        return false;
    }

    std::string loopDevice, tempFile;
    if (!setupLoopForPartition(imagePath, partitionOffset, loopDevice, tempFile, errMsg)) {
        return false;
    }
    out.loopDevice = loopDevice;
    out.tempFile = tempFile;

    // Unique mapper name (cryptsetup creates /dev/mapper/<name>). Feed the
    // passphrase through stdin so it never appears in argv or a temp file.
    out.mapperName = "forensic_luks_" + std::to_string(getpid()) + "_" +
                     std::to_string(reinterpret_cast<uintptr_t>(&out));
    std::string csout;
    int rc = runProcess({"cryptsetup", "open", "--readonly", "--type", "luks",
                         "--key-file", "-", loopDevice, out.mapperName}, password, csout);
    std::error_code ec;

    if (rc != 0) {
        errMsg = "cryptsetup open failed: " + csout;
        detachLoop(loopDevice);
        if (!tempFile.empty()) fs::remove(tempFile, ec);
        return false;
    }

    out.accessiblePath = "/dev/mapper/" + out.mapperName;
    out.encType = EncryptionType::LUKS;
    std::cout << "  [decrypt] LUKS volume opened at " << out.accessiblePath << std::endl;
    AuditLog::instance().log("SYSTEM", "DECRYPT_LUKS",
                             "Opened LUKS partition (offset " + std::to_string(partitionOffset) +
                             ") -> " + out.accessiblePath);
    return true;
}

// ── BitLocker (bdemount / dislocker) ────────────────────────────────────────

bool DecryptionModule::decryptBitlocker(const std::string& imagePath, uint64_t partitionOffset,
                                        const std::string& password, DecryptedPartition& out,
                                        std::string& errMsg) {
    // Prefer dislocker's standard FUSE mount. Keep bdemount as a fallback for
    // volumes unsupported by the installed dislocker version.
    if (!isToolAvailable("bdemount") && !isToolAvailable("dislocker")) {
        errMsg = "neither bdemount nor dislocker found on PATH";
        return false;
    }

    // Both tools work on a raw partition file. Extract the partition for EWF,
    // or set up a loop device for raw images.
    std::string partSource;
    std::string loopDevice, tempFile;
    if (isEwfImage(imagePath)) {
        std::string tmpPrefix = forensics::PathManager::instance().makeTempPath("dec_part_", "");
        tempFile = tmpPrefix + ".raw";
        std::string o;
        if (runProcess({"ewfexport", "-u", "-f", "raw", "-t", tmpPrefix, "-o",
                        std::to_string(partitionOffset), imagePath}, "", o) != 0) {
            errMsg = "ewfexport failed: " + o;
            return false;
        }
        partSource = tempFile;
    } else {
        // Loop device with offset for raw images.
        std::string lo;
        if (runProcess({"losetup", "-f", "--show", "-r", "-o",
                        std::to_string(partitionOffset), imagePath}, "", lo) != 0 || lo.empty()) {
            errMsg = "losetup failed: " + lo;
            return false;
        }
        while (!lo.empty() && (lo.back() == '\n' || lo.back() == '\r')) lo.pop_back();
        loopDevice = lo;
        partSource = loopDevice;
    }
    out.loopDevice = loopDevice;
    out.tempFile = tempFile;

    bool ok = false;
    std::error_code ec;
    std::string mountDir = forensics::PathManager::instance().makeTempPath("bde_mount_", "");
    fs::create_directories(mountDir, ec);

    if (isToolAvailable("dislocker")) {
        // Standard dislocker FUSE mode creates <mountpoint>/dislocker-file.
        // A bare -u prompts on stdin instead of embedding the password in argv.
        std::string o;
        int rc = runProcess({"dislocker", "-r", "-u", "-V", partSource, "--", mountDir},
                            password + "\n", o);
        fs::path dislockerFile = fs::path(mountDir) / "dislocker-file";
        if (rc == 0 && fs::exists(dislockerFile, ec)) {
            out.accessiblePath = dislockerFile.string();
            out.mapperName = "dislocker";
            out.mountPoint = mountDir;
            out.mounted = true;
            ok = true;
        } else {
            errMsg = "dislocker failed (note: dislocker 0.7.x has limited AES-XTS support): " + o;
        }
    }

    if (!ok && isToolAvailable("bdemount")) {
        // libbde has no supported password-on-stdin option. Keep this direct-exec
        // fallback, but warn because its -p argument is visible to local process
        // inspection while bdemount starts.
        std::cerr << "  [decrypt] WARNING: bdemount fallback exposes the BitLocker password "
                     "in process arguments" << std::endl;
        std::string o;
        int rc = runProcess({"bdemount", "-p", password, partSource, mountDir}, "", o);
        if (rc == 0 && fs::exists(fs::path(mountDir) / "bde1", ec)) {
            out.accessiblePath = mountDir + "/bde1";
            out.mapperName = "bdemount";
            out.mountPoint = mountDir;
            out.mounted = true;
            ok = true;
        } else {
            errMsg = "bdemount fallback failed: " + o;
        }
    }

    if (!ok) {
        detachLoop(loopDevice);
        if (!tempFile.empty()) fs::remove(tempFile, ec);
        if (!mountDir.empty()) fs::remove_all(mountDir, ec);
        return false;
    }

    out.encType = EncryptionType::BITLOCKER;
    std::cout << "  [decrypt] BitLocker volume opened at " << out.accessiblePath << std::endl;
    AuditLog::instance().log("SYSTEM", "DECRYPT_BITLOCKER",
                             "Opened BitLocker partition (offset " + std::to_string(partitionOffset) +
                             ") -> " + out.accessiblePath);
    return true;
}

// ── BitLocker via recovered FVEK (AES-XTS-128 direct decrypt) ────────────────

bool DecryptionModule::decryptBitlockerWithFvek(const std::string& imagePath, uint64_t partitionOffset,
                                                const std::string& fvekPath, DecryptedPartition& out,
                                                std::string& errMsg) {
    // This path bypasses dislocker/libbde (which lack AES-XTS-128 support) by
    // decrypting the data area directly with a FVEK recovered from memory.
    // The bundled Python helper scripts/bitlocker_fvek_decrypt.py does the work.

    // Locate the project root to find the helper script. Prefer the env var, else
    // derive from the executable dir (PathManager) as <root>/scripts/.
    namespace phfs = std::filesystem;
    std::string scriptPath;
    const char* envRoot = std::getenv("FORENSICS_PROJECT_ROOT");
    if (envRoot && phfs::exists(phfs::path(envRoot) / "scripts" / "bitlocker_fvek_decrypt.py")) {
        scriptPath = (phfs::path(envRoot) / "scripts" / "bitlocker_fvek_decrypt.py").string();
    } else {
        auto root = forensics::PathManager::instance().getProjectRoot();
        std::string cand = (root / "scripts" / "bitlocker_fvek_decrypt.py").string();
        if (phfs::exists(cand)) {
            scriptPath = cand;
        } else {
            auto exeDir = forensics::PathManager::instance().getExeDir();
            cand = (exeDir / "scripts" / "bitlocker_fvek_decrypt.py").string();
            if (phfs::exists(cand)) scriptPath = cand;
        }
    }
    if (scriptPath.empty()) {
        errMsg = "bitlocker_fvek_decrypt.py helper not found (set FORENSICS_PROJECT_ROOT)";
        return false;
    }

    // Resolve the Python interpreter (project venv preferred).
    std::string pyBin = "python3";
    {
        auto root = forensics::PathManager::instance().getProjectRoot();
        std::string venvPy = (root / "python_service" / ".venv" / "bin" / "python").string();
        if (phfs::exists(venvPy)) pyBin = venvPy;
    }

    // We need the encrypted partition as a raw file. For EWF images, extract the
    // partition to a temp raw file (the Python helper cannot read EWF directly).
    std::string partSource, loopDevice, tempPart;
    if (isEwfImage(imagePath)) {
        std::string tmpPrefix = forensics::PathManager::instance().makeTempPath("dec_part_", "");
        tempPart = tmpPrefix + ".raw";
        std::string o;
        if (runProcess({"ewfexport", "-u", "-f", "raw", "-t", tmpPrefix, "-o",
                        std::to_string(partitionOffset), imagePath}, "", o) != 0) {
            errMsg = "ewfexport failed to extract partition for FVEK decrypt: " + o;
            return false;
        }
        partSource = tempPart;
    } else {
        // Raw image: decrypt from the partition offset.
        partSource = imagePath;
        // Pass the offset to the script via the data-start-sector mechanism? The
        // script operates on a file; for raw images we point it at the whole image
        // and let auto-detection find the NTFS boot sector. This is only correct
        // when partitionOffset == 0. For offset raw images, extract is safer.
        if (partitionOffset != 0) {
            std::string tmpPrefix = forensics::PathManager::instance().makeTempPath("dec_part_", "");
            tempPart = tmpPrefix + ".raw";
            std::vector<std::string> ddArgs = {"dd", "if=" + imagePath, "of=" + tempPart,
                                               "bs=1M", "skip=" + std::to_string(
                                                   partitionOffset / (1024 * 1024)),
                                               "status=none"};
            // Fall back to sector-sized skipping if the offset is not MiB-aligned.
            if (partitionOffset % (1024 * 1024) != 0) {
                ddArgs = {"dd", "if=" + imagePath, "of=" + tempPart, "bs=512",
                          "skip=" + std::to_string(partitionOffset / 512), "status=none"};
            }
            std::string ddOut;
            int ddRc = runProcess(ddArgs, "", ddOut);
            if (ddRc != 0) {
                errMsg = "dd failed to extract partition for FVEK decrypt: " + ddOut;
                std::error_code removeEc;
                fs::remove(tempPart, removeEc);
                return false;
            }
            partSource = tempPart;
        }
    }

    // Output decrypted image (temp file). Use --max-sectors to bound time for very
    // large volumes during automated runs (caller may extend). Default: full volume.
    std::string decFile = forensics::PathManager::instance().makeTempPath("fvek_dec_", ".raw");
    std::string pyOut;
    int rc = runProcess({pyBin, scriptPath, partSource, fvekPath, decFile}, "", pyOut);

    std::error_code ec;
    if (rc != 0 || !phfs::exists(decFile, ec)) {
        errMsg = "FVEK decrypt failed: " + pyOut;
        if (!tempPart.empty()) phfs::remove(tempPart, ec);
        phfs::remove(decFile, ec);
        return false;
    }

    out.encType = EncryptionType::BITLOCKER;
    out.accessiblePath = decFile;
    out.mapperName = "fvek";
    out.tempFile = decFile;            // cleanup target
    out.loopDevice = loopDevice;
    if (!tempPart.empty()) {
        // remember to clean the extracted partition too
        // (stored in tempFile would overwrite decFile; append as a second temp)
    }
    std::cout << "  [decrypt] BitLocker FVEK decrypt -> " << decFile << std::endl;
    AuditLog::instance().log("SYSTEM", "DECRYPT_BITLOCKER_FVEK",
                             "Opened BitLocker via FVEK (offset " + std::to_string(partitionOffset) +
                             ") -> " + decFile);

    // Best-effort cleanup of the extracted partition (separate from decFile).
    if (!tempPart.empty() && tempPart != decFile) phfs::remove(tempPart, ec);
    return true;
}

// ── VeraCrypt ───────────────────────────────────────────────────────────────

bool DecryptionModule::decryptVeracrypt(const std::string& imagePath, uint64_t partitionOffset,
                                        const std::string& password, DecryptedPartition& out,
                                        std::string& errMsg) {
    if (!isToolAvailable("veracrypt")) {
        errMsg = "veracrypt not found on PATH";
        return false;
    }

    std::string partSource, loopDevice, tempFile;
    if (isEwfImage(imagePath)) {
        std::string tmpPrefix = forensics::PathManager::instance().makeTempPath("dec_part_", "");
        tempFile = tmpPrefix + ".raw";
        std::string o;
        if (runProcess({"ewfexport", "-u", "-f", "raw", "-t", tmpPrefix, "-o",
                        std::to_string(partitionOffset), imagePath}, "", o) != 0) {
            errMsg = "ewfexport failed: " + o;
            return false;
        }
        partSource = tempFile;
    } else {
        std::string lo;
        if (runProcess({"losetup", "-f", "--show", "-r", "-o",
                        std::to_string(partitionOffset), imagePath}, "", lo) != 0 || lo.empty()) {
            errMsg = "losetup failed: " + lo;
            return false;
        }
        while (!lo.empty() && (lo.back() == '\n' || lo.back() == '\r')) lo.pop_back();
        loopDevice = lo;
        partSource = loopDevice;
    }
    out.loopDevice = loopDevice;
    out.tempFile = tempFile;

    std::error_code ec;
    std::string mountDir = forensics::PathManager::instance().makeTempPath("vc_mount_", "");
    fs::create_directories(mountDir, ec);

    // VeraCrypt supports reading the password from stdin, keeping it out of argv.
    std::string o;
    int rc = runProcess({"veracrypt", "-t", "--stdin", "--non-interactive",
                         "--mount-options=ro", partSource, mountDir}, password + "\n", o);
    if (rc != 0) {
        errMsg = "veracrypt failed: " + o;
        detachLoop(loopDevice);
        if (!tempFile.empty()) fs::remove(tempFile, ec);
        fs::remove_all(mountDir, ec);
        return false;
    }

    out.accessiblePath = mountDir;
    out.mountPoint = mountDir;
    out.mounted = true;
    out.encType = EncryptionType::VERACRYPT;
    std::cout << "  [decrypt] VeraCrypt volume mounted at " << out.accessiblePath << std::endl;
    AuditLog::instance().log("SYSTEM", "DECRYPT_VERACRYPT",
                             "Opened VeraCrypt partition (offset " + std::to_string(partitionOffset) +
                             ") -> " + out.accessiblePath);
    return true;
}

// ── cleanup ─────────────────────────────────────────────────────────────────

void DecryptionModule::cleanup(const DecryptedPartition& part) {
    std::error_code ec;
    // VeraCrypt / bdemount / dislocker: unmount the FUSE or filesystem mount.
    if (part.mounted && !part.mountPoint.empty()) {
        std::string discard;
        if (part.encType == EncryptionType::VERACRYPT && isToolAvailable("veracrypt")) {
            runProcess({"veracrypt", "-t", "-d", part.mountPoint}, "", discard);
        } else if (isToolAvailable("fusermount")) {
            runProcess({"fusermount", "-u", part.mountPoint}, "", discard);
        } else {
            runProcess({"umount", part.mountPoint}, "", discard);
        }
    }
    if (!part.mountPoint.empty()) fs::remove_all(part.mountPoint, ec);

    // LUKS: remove the device-mapper node.
    if (!part.mapperName.empty() &&
        part.mapperName != "bdemount" && part.mapperName != "dislocker" &&
        part.mapperName != "fvek") {
        std::string discard;
        runProcess({"cryptsetup", "close", part.mapperName}, "", discard);
    }

    // Detach loop device.
    if (!part.loopDevice.empty()) detachLoop(part.loopDevice);

    // Remove temp files.
    if (!part.tempFile.empty()) fs::remove(part.tempFile, ec);

    // For dislocker path, accessiblePath itself is the temp decrypted image.
    if (part.mapperName == "dislocker" && !part.accessiblePath.empty() &&
        part.accessiblePath != part.tempFile) {
        fs::remove(part.accessiblePath, ec);
    }
}

DecryptionModule::~DecryptionModule() {
    for (const auto& p : owned_) cleanup(p);
}
