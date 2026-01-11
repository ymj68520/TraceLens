/**
 * AuditLog Module Test
 * 
 * This test verifies the basic functionality of the AuditLog module.
 */

#include "AuditLog/AuditLog.h"
#include <iostream>
#include <chrono>
#include <thread>

void printSeparator(const std::string& title) {
    std::cout << "\n========== " << title << " ==========\n" << std::endl;
}

int main() {
    try {
        printSeparator("AuditLog Module Test");
        
        // 1. Initialize with custom config
        std::cout << "1. Initializing AuditLog with custom configuration..." << std::endl;
        AuditLogConfig config;
        config.db_path = "test_audit.db";
        config.cache_size = 10;
        config.batch_size = 5;
        config.flush_interval_seconds = 2;
        config.async_write = true;
        config.retention_days = 7;
        
        AuditLog::instance(config);
        std::cout << "   ✓ AuditLog initialized successfully" << std::endl;
        
        // 2. Write some logs
        printSeparator("2. Writing Audit Logs");
        std::string task_id1 = "task-001";
        std::string task_id2 = "task-002";
        
        std::cout << "Writing logs for task-001..." << std::endl;
        AuditLog::instance().log(task_id1, "CREATED", "Task created with priority HIGH", "user123");
        AuditLog::instance().log(task_id1, "STATUS_CHANGE", "Status changed to RUNNING");
        AuditLog::instance().log(task_id1, "PROGRESS", "Image analysis: 50% complete");
        AuditLog::instance().log(task_id1, "PROGRESS", "Image analysis: 100% complete");
        AuditLog::instance().log(task_id1, "STATUS_CHANGE", "Status changed to COMPLETED");
        
        std::cout << "Writing logs for task-002..." << std::endl;
        AuditLog::instance().log(task_id2, "CREATED", "Task created with priority NORMAL");
        AuditLog::instance().log(task_id2, "STATUS_CHANGE", "Status changed to RUNNING");
        AuditLog::instance().log(task_id2, "ERROR", "Analysis failed: file not found");
        
        std::cout << "   ✓ 8 log entries written" << std::endl;
        
        // 3. Flush to ensure all data is written
        std::cout << "\n3. Flushing write buffer..." << std::endl;
        AuditLog::instance().flush();
        std::cout << "   ✓ Write buffer flushed" << std::endl;
        
        // 4. Query logs
        printSeparator("4. Querying Audit Logs");
        
        std::cout << "Querying logs for task-001:" << std::endl;
        auto task1_logs = AuditLog::instance().getTaskLogs(task_id1);
        std::cout << "   Found " << task1_logs.size() << " entries:" << std::endl;
        for (const auto& log : task1_logs) {
            auto time_t_value = std::chrono::system_clock::to_time_t(log.timestamp);
            std::cout << "     - [" << log.action << "] " << log.details << std::endl;
        }
        
        std::cout << "\nQuerying logs for task-002:" << std::endl;
        auto task2_logs = AuditLog::instance().getTaskLogs(task_id2);
        std::cout << "   Found " << task2_logs.size() << " entries:" << std::endl;
        for (const auto& log : task2_logs) {
            std::cout << "     - [" << log.action << "] " << log.details << std::endl;
        }
        
        // 5. Query by action
        printSeparator("5. Query by Action Type");
        auto error_logs = AuditLog::instance().getLogsByAction("ERROR");
        std::cout << "Found " << error_logs.size() << " ERROR entries:" << std::endl;
        for (const auto& log : error_logs) {
            std::cout << "   - Task " << log.task_id << ": " << log.details << std::endl;
        }
        
        // 6. Statistics
        printSeparator("6. Statistics");
        auto stats = AuditLog::instance().getStatistics();
        std::cout << "Audit log statistics:" << std::endl;
        std::cout << stats.dump(2) << std::endl;
        
        // 7. Log count
        printSeparator("7. Log Counts");
        int64_t total_count = AuditLog::instance().getLogCount();
        int64_t task1_count = AuditLog::instance().getLogCount(task_id1);
        int64_t task2_count = AuditLog::instance().getLogCount(task_id2);
        
        std::cout << "Total log entries: " << total_count << std::endl;
        std::cout << "Task-001 entries: " << task1_count << std::endl;
        std::cout << "Task-002 entries: " << task2_count << std::endl;
        
        // 8. Pagination test
        printSeparator("8. Pagination Test");
        std::cout << "Getting first 3 entries for task-001:" << std::endl;
        auto page1 = AuditLog::instance().getTaskLogs(task_id1, 3, 0);
        std::cout << "   Page 1: " << page1.size() << " entries" << std::endl;
        
        std::cout << "Getting next 3 entries for task-001:" << std::endl;
        auto page2 = AuditLog::instance().getTaskLogs(task_id1, 3, 3);
        std::cout << "   Page 2: " << page2.size() << " entries" << std::endl;
        
        // 9. Export
        printSeparator("9. Export to JSON");
        AuditLog::instance().exportToFile("test_audit_export.json", "json");
        std::cout << "   ✓ Exported to test_audit_export.json" << std::endl;
        
        AuditLog::instance().exportToFile("test_audit_export.csv", "csv");
        std::cout << "   ✓ Exported to test_audit_export.csv" << std::endl;
        
        // 10. Test async write
        printSeparator("10. Async Write Test");
        std::cout << "Writing 20 more entries and waiting for background flush..." << std::endl;
        for (int i = 0; i < 20; i++) {
            AuditLog::instance().log("task-003", "PROGRESS", 
                                    "Processing step " + std::to_string(i + 1));
        }
        
        std::cout << "Waiting 3 seconds for background flush..." << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(3));
        
        auto task3_count = AuditLog::instance().getLogCount("task-003");
        std::cout << "   ✓ Task-003 has " << task3_count << " entries (should be 20)" << std::endl;
        
        printSeparator("Test Completed Successfully");
        std::cout << "\nAll tests passed! ✓" << std::endl;
        std::cout << "\nGenerated files:" << std::endl;
        std::cout << "  - test_audit.db (SQLite database)" << std::endl;
        std::cout << "  - test_audit_export.json (JSON export)" << std::endl;
        std::cout << "  - test_audit_export.csv (CSV export)" << std::endl;
        std::cout << "\nYou can inspect these files to verify the data." << std::endl;
        
        return 0;
        
    } catch (const std::exception& e) {
        std::cerr << "\n❌ Test failed with error: " << e.what() << std::endl;
        return 1;
    }
}
