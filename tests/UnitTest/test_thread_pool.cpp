#include <gtest/gtest.h>
#include <gmock/gmock.h>

#include "../../src/core/ThreadPool/ThreadPool.h"

#include <atomic>
#include <chrono>
#include <thread>
#include <vector>

using namespace forensics;

// ============================================================================
// ThreadPool Basic Tests
// ============================================================================

TEST(ThreadPoolTest, ConstructorCreatesWorkerThreads) {
    ThreadPool pool(4);
    EXPECT_EQ(pool.size(), 4);
    EXPECT_FALSE(pool.isStopped());
}

TEST(ThreadPoolTest, DefaultConstructorUsesHardwareConcurrency) {
    ThreadPool pool;
    EXPECT_GE(pool.size(), 1);  // At least 1 thread
}

TEST(ThreadPoolTest, EnqueueAndExecuteSingleTask) {
    ThreadPool pool(2);
    
    auto future = pool.enqueue([]() { return 42; });
    
    EXPECT_EQ(future.get(), 42);
}

TEST(ThreadPoolTest, EnqueueAndExecuteMultipleTasks) {
    ThreadPool pool(4);
    std::atomic<int> counter{0};
    
    std::vector<std::future<void>> futures;
    for (int i = 0; i < 100; ++i) {
        futures.push_back(pool.enqueue([&counter]() {
            counter++;
        }));
    }
    
    // Wait for all tasks to complete
    for (auto& f : futures) {
        f.get();
    }
    
    EXPECT_EQ(counter.load(), 100);
}

TEST(ThreadPoolTest, TasksReturnValues) {
    ThreadPool pool(4);
    
    std::vector<std::future<int>> futures;
    for (int i = 0; i < 10; ++i) {
        futures.push_back(pool.enqueue([i]() { return i * 2; }));
    }
    
    int sum = 0;
    for (auto& f : futures) {
        sum += f.get();
    }
    
    // Sum of 0*2 + 1*2 + ... + 9*2 = 2 * (0+1+...+9) = 2 * 45 = 90
    EXPECT_EQ(sum, 90);
}

TEST(ThreadPoolTest, TasksExecuteConcurrently) {
    ThreadPool pool(4);
    std::atomic<int> maxConcurrent{0};
    std::atomic<int> currentCount{0};
    
    std::vector<std::future<void>> futures;
    for (int i = 0; i < 8; ++i) {
        futures.push_back(pool.enqueue([&]() {
            int current = ++currentCount;
            
            // Update max if needed
            int oldMax = maxConcurrent.load();
            while (current > oldMax && !maxConcurrent.compare_exchange_weak(oldMax, current)) {}
            
            // Simulate some work
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
            
            currentCount--;
        }));
    }
    
    for (auto& f : futures) {
        f.get();
    }
    
    // With 4 threads and 8 tasks, we should see at least 2 concurrent executions
    // (likely 4, but at least 2 is a safe assertion)
    EXPECT_GE(maxConcurrent.load(), 2);
}

TEST(ThreadPoolTest, DestructorWaitsForTasks) {
    std::atomic<bool> completed{false};
    
    {
        ThreadPool pool(1);
        pool.enqueue([&completed]() {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            completed = true;
        });
        // Destructor should wait for the task to complete
    }
    
    EXPECT_TRUE(completed.load());
}

TEST(ThreadPoolTest, TaskWithException) {
    ThreadPool pool(1);
    
    auto future = pool.enqueue([]() -> int {
        throw std::runtime_error("Test exception");
        return 0;
    });
    
    EXPECT_THROW(future.get(), std::runtime_error);
}

// ============================================================================
// Main
// ============================================================================

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
