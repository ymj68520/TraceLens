#include "ThreadPool.h"

namespace forensics {

ThreadPool::ThreadPool(size_t threads) {
    if (threads == 0) {
        threads = 1;  // At least one thread
    }
    
    workers_.reserve(threads);
    for (size_t i = 0; i < threads; ++i) {
        workers_.emplace_back([this] {
            while (true) {
                std::function<void()> task;
                
                {
                    std::unique_lock<std::mutex> lock(queueMutex_);
                    condition_.wait(lock, [this] {
                        return stop_ || !tasks_.empty();
                    });
                    
                    if (stop_ && tasks_.empty()) {
                        return;
                    }
                    
                    task = std::move(tasks_.front());
                    tasks_.pop();
                }
                
                task();
            }
        });
    }
}

ThreadPool::~ThreadPool() {
    {
        std::unique_lock<std::mutex> lock(queueMutex_);
        stop_ = true;
    }
    condition_.notify_all();
    
    for (std::thread& worker : workers_) {
        if (worker.joinable()) {
            worker.join();
        }
    }
}

size_t ThreadPool::pendingTasks() const {
    std::unique_lock<std::mutex> lock(queueMutex_);
    return tasks_.size();
}

} // namespace forensics
