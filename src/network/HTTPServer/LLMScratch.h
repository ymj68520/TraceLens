#pragma once

#include <string>

namespace forensics {

/**
 * @brief Task-scoped scratch directory for LLM image-file extraction (D4b)
 *
 * Layout: ``<tempdir>/forensics_llm_extract/<task_id>/`` — one subtree per
 * task so concurrent tasks never collide on flattened file names, and one
 * task's cleanup never touches another's scratch.
 */
namespace llm_scratch {

/// Scratch directory for one task ("notask" segment when no task is set).
std::string dirForTask(const std::string& taskId);

/// Remove one task's scratch subtree. Idempotent; never throws.
void cleanupTask(const std::string& taskId);

} // namespace llm_scratch
} // namespace forensics
