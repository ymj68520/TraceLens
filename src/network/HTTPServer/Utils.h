#pragma once

#include <coroutine>
#include <future>
#include <iostream>

#include "HTTPServerDataTypes.h"

// 线程包装池
template <typename Func>
auto run_async(Func&& func) {
    return std::async(std::launch::async, std::forward<Func>(func));
}