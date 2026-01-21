#pragma once

#include <coroutine>
#include <future>
#include <iostream>

#include "HTTPServerDataTypes.h"

/**
 * @brief Execute function asynchronously
 * Wraps std::async to launch function in a new thread.
 * @tparam Func Function type
 * @param func Function to execute
 * @return std::future<Result> Future holding the execution result
 */
template <typename Func>
auto run_async(Func&& func) {
    return std::async(std::launch::async, std::forward<Func>(func));
}