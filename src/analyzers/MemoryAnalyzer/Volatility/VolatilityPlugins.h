// VolatilityPlugins.h
// Volatility3 plugin-name constants used by MemoryAnalyzer.
//
// These MUST match real vol3 2.x plugin names. Note that vol3 has NO
// `linux.netstat` or `linux.cmdline` plugin: socket/connection data comes from
// `linux.sockstat`, and per-process command lines come from `linux.psaux`.
#pragma once

namespace MemoryVolatility {
// ---- Linux plugins ----
inline constexpr const char* LINUX_PSLIST     = "linux.pslist";
inline constexpr const char* LINUX_BASH       = "linux.bash";
inline constexpr const char* LINUX_SOCKSTAT   = "linux.sockstat";
inline constexpr const char* LINUX_BOOTTIME   = "linux.boottime";
inline constexpr const char* LINUX_PSAUX      = "linux.psaux";

// ---- Windows plugins ----
inline constexpr const char* WIN_PSLIST       = "windows.pslist";
inline constexpr const char* WIN_CMDLINE      = "windows.cmdline";
inline constexpr const char* WIN_NETSTAT      = "windows.netstat";
inline constexpr const char* WIN_HIVELIST     = "windows.registry.hivelist";
inline constexpr const char* WIN_FILESCAN     = "windows.filescan";
} // namespace MemoryVolatility
