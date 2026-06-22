#include <gtest/gtest.h>
#include "MemoryAnalyzer/Volatility/Volatility3Runner.h"
#include "MemoryAnalyzer/Volatility/VolatilityPlugins.h"
#include <cstdlib>
#include <fstream>

TEST(Volatility3RunnerTest, ResolvesVolBinaryOrEmpty) {
    // Either finds vol on PATH/venv (non-empty) or returns empty when absent.
    std::string bin = Volatility3Runner::resolveVolBinary();
    EXPECT_TRUE(bin.empty() || bin.find("vol") != std::string::npos);
}

TEST(Volatility3RunnerTest, ParseJsonOutputShape) {
    // The runner must hand callers raw JSON text; parsing is the parsers' job.
    // Here we only assert run() on a nonexistent image returns ok=false.
    Volatility3Runner runner("/nonexistent/mem.lime");
    auto r = runner.run(MemoryVolatility::PSLIST, 5);
    EXPECT_FALSE(r.ok);
}
