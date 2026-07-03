// VolatilityPlugins.h
// Volatility3 linux.* plugin name constants used by MemoryAnalyzer.
//
// These MUST match real vol3 2.x plugin names. Note that vol3 has NO
// `linux.netstat` or `linux.cmdline` plugin: socket/connection data comes from
// `linux.sockstat`, and per-process command lines come from `linux.psaux`.
#pragma once

namespace MemoryVolatility {
inline constexpr const char* PSLIST     = "linux.pslist";
inline constexpr const char* BASH       = "linux.bash";
inline constexpr const char* SOCKSTAT   = "linux.sockstat";
inline constexpr const char* BOOTTIME   = "linux.boottime";
inline constexpr const char* PSAUX      = "linux.psaux";
} // namespace MemoryVolatility
