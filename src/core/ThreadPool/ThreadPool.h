#pragma once

#include <vector>
#include <queue>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <future>
#include <functional>
#include <stdexcept>

namespace forensics {

/**
 * @brief Simple thread pool for parallel task execution
 * 
 * Usage:
 *   ThreadPool pool(4);
 *   auto future = pool.enqueue([](int x) { return x * 2; }, 21);
 *   int result = future.get(); // 42
 */
class ThreadPool {
public:
    /**
     * @brief Construct thread pool with specified number of worker threads
     * @param threads Number of worker threads (default: hardware concurrency)
     */
    explicit ThreadPool(size_t threads = std::thread::hardware_concurrency());
    
    /**
     * @brief Destructor - waits for all tasks to complete
     */
    ~ThreadPool();
    
    // Non-copyable, non-movable
    ThreadPool(const ThreadPool&) = delete;
    ThreadPool& operator=(const ThreadPool&) = delete;
    ThreadPool(ThreadPool&&) = delete;
    ThreadPool& operator=(ThreadPool&&) = delete;
    
    /**
     * @brief Enqueue a task for execution
     * @param f Function to execute
     * @param args Arguments to pass to the function
     * @return Future containing the result
     */
    template<class F, class... Args>
    auto enqueue(F&& f, Args&&... args) 
        -> std::future<typename std::invoke_result<F, Args...>::type>;
    
    /**
     * @brief Get the number of worker threads
     */
    size_t size() const { return workers_.size(); }
    
    /**
     * @brief Get the number of pending tasks
     */
    size_t pendingTasks() const;
    
    /**
     * @brief Check if the pool is stopped
     */
    bool isStopped() const { return stop_; }

private:
    std::vector<std::thread> workers_;
    std::queue<std::function<void()>> tasks_;
    
    mutable std::mutex queueMutex_;
    std::condition_variable condition_;
    bool stop_ = false;
};

// ============================================================================
// Template Implementation
// ============================================================================

template<class F, class... Args>
auto ThreadPool::enqueue(F&& f, Args&&... args) 
    -> std::future<typename std::invoke_result<F, Args...>::type>
{
    using return_type = typename std::invoke_result<F, Args...>::type;
    
    auto task = std::make_shared<std::packaged_task<return_type()>>(
        std::bind(std::forward<F>(f), std::forward<Args>(args)...)
    );
    
    std::future<return_type> res = task->get_future();
    {
        std::unique_lock<std::mutex> lock(queueMutex_);
        
        if (stop_) {
            throw std::runtime_error("enqueue on stopped ThreadPool");
        }
        
        tasks_.emplace([task]() { (*task)(); });
    }
    condition_.notify_one();
    return res;
}

} // namespace forensics
