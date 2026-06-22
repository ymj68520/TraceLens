// VolatilityPlugins.h
// Volatility3 linux.* plugin name constants used by MemoryAnalyzer.
#pragma once

namespace MemoryVolatility {
inline constexpr const char* PSLIST     = "linux.pslist";
inline constexpr const char* BASH       = "linux.bash";
inline constexpr const char* NETSTAT    = "linux.netstat";
inline constexpr const char* SOCKSTAT   = "linux.sockstat";
inline constexpr const char* BOOTTIME   = "linux.boottime";
inline constexpr const char* CMDLINE    = "linux.cmdline";
} // namespace MemoryVolatility
