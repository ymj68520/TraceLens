// D4b: task-scoped LLM extraction scratch tests.
//
// Proves per-task scratch independence and that cleanup removes exactly one
// task's subtree (the RAII cleanup in LLMAnalysisService's destructor and the
// TaskManager deletion paths both call these helpers).

#include <gtest/gtest.h>

#include <filesystem>
#include <fstream>
#include <string>

#include "network/HTTPServer/LLMScratch.h"

namespace fs = std::filesystem;
using forensics::llm_scratch::cleanupTask;
using forensics::llm_scratch::dirForTask;

static fs::path makeScratchFile(const std::string& taskId, const std::string& name) {
    fs::path dir(dirForTask(taskId));
    fs::create_directories(dir);
    fs::path file = dir / name;
    std::ofstream out(file);
    out << "x";
    out.close();
    return file;
}

TEST(LLMScratchTest, DirectoriesAreTaskScopedAndIndependent) {
    const std::string a = dirForTask("task-a");
    const std::string b = dirForTask("task-b");
    EXPECT_NE(a, b);
    EXPECT_NE(a, dirForTask("notask-legacy-empty"));
    const fs::path root = fs::temp_directory_path() / "forensics_llm_extract";
    EXPECT_TRUE(fs::path(a).parent_path() == root);
    EXPECT_TRUE(fs::path(b).parent_path() == root);
}

TEST(LLMScratchTest, CleanupRemovesOnlyThatTask) {
    auto fileA = makeScratchFile("task-a", "grub_grub.cfg");
    auto fileB = makeScratchFile("task-b", "grub_grub.cfg");

    ASSERT_TRUE(fs::exists(fileA));
    ASSERT_TRUE(fs::exists(fileB));

    cleanupTask("task-a");

    EXPECT_FALSE(fs::exists(fileA));
    EXPECT_FALSE(fs::exists(fs::path(dirForTask("task-a"))));
    // Task B's scratch is untouched.
    EXPECT_TRUE(fs::exists(fileB));

    cleanupTask("task-b");
    EXPECT_FALSE(fs::exists(fileB));
}

TEST(LLMScratchTest, CleanupIsIdempotentAndSafe) {
    cleanupTask("task-never-existed");
    cleanupTask("task-never-existed");
    SUCCEED();
}
