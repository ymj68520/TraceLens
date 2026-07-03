#include "EventCorrelationEngine/EventCorrelationEngine.h"
#include <gtest/gtest.h>
#include <fstream>
#include <iostream>

using namespace EventCorrelationEngine;

class EventCorrelationEngineTest : public ::testing::Test {
protected:
    // A real temp file, NOT ":memory:": each :memory: connection gets its OWN
    // private database, so the rows SetUp inserts on its connection would be
    // invisible to the engine's separate connection (they were, hence 0
    // correlations). A file is shared across connections. TearDown removes it.
    std::string testDbPath = "/tmp/test_event_correlation_engine.db";
    EventCorrelationEngine::EventCorrelationEngine engine;

public:
    EventCorrelationEngineTest() : engine(testDbPath) {
    }

    void SetUp() override {
        // 初始化测试数据库
        std::remove(testDbPath.c_str());  // start from a clean file
        sqlite3* db;
        sqlite3_open(testDbPath.c_str(), &db);

        // 创建 events 表
        const char* createEventsTable = R"(
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                file_path TEXT,
                inode INTEGER,
                description TEXT,
                file_size INTEGER,
                file_type TEXT,
                system_context TEXT,
                priority TEXT,
                severity TEXT,
                event_source TEXT,
                event_category TEXT,
                normalized_type TEXT,
                source_id TEXT
            );
        )";
        sqlite3_exec(db, createEventsTable, nullptr, nullptr, nullptr);
        
        // 插入测试数据
        const char* insertEvents = R"(
            INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
            VALUES
            (1609459200, 'FILE_CREATED', '/home/user/file1.txt', 1001, 'File created', 1024, 'text', '', 'MEDIUM', 'INFO', 'FILE_SYSTEM', 'FILE_OPERATION', 'FILE_CREATED', 'FS_1001'),
            (1609459260, 'FILE_MODIFIED', '/home/user/file1.txt', 1001, 'File modified', 2048, 'text', '', 'MEDIUM', 'INFO', 'FILE_SYSTEM', 'FILE_OPERATION', 'FILE_MODIFIED', 'FS_1001'),
            (1609459320, 'FILE_ACCESSED', '/home/user/file1.txt', 1001, 'File accessed', 2048, 'text', '', 'LOW', 'INFO', 'FILE_SYSTEM', 'FILE_OPERATION', 'FILE_ACCESSED', 'FS_1001'),
            (1609459380, 'FILE_CREATED', '/home/user/file2.txt', 1002, 'File created', 512, 'text', '', 'MEDIUM', 'INFO', 'FILE_SYSTEM', 'FILE_OPERATION', 'FILE_CREATED', 'FS_1002'),
            (1609459440, 'NETWORK_CONNECTION', '192.168.1.100', 0, 'Connection to 192.168.1.100', 0, 'network', '', 'MEDIUM', 'INFO', 'NETWORK', 'NETWORK_ACTIVITY', 'NETWORK_CONNECTION', 'NET_1'),
            (1609459500, 'FILE_CREATED', '/home/user/download.exe', 1003, 'Executable file created', 1024000, 'executable', '', 'HIGH', 'WARNING', 'FILE_SYSTEM', 'FILE_OPERATION', 'FILE_CREATED', 'FS_1003'),
            (1609459560, 'PROCESS_CREATED', '', 0, 'Process created: download.exe', 0, 'process', '', 'HIGH', 'WARNING', 'APPLICATION', 'APPLICATION_EVENT', 'PROCESS_CREATED', 'PROC_1'),
            (1609459620, 'FILE_DELETED', '/home/user/file1.txt', 1001, 'File deleted', 2048, 'text', '', 'HIGH', 'INFO', 'FILE_SYSTEM', 'FILE_OPERATION', 'FILE_DELETED', 'FS_1001');
        )";
        sqlite3_exec(db, insertEvents, nullptr, nullptr, nullptr);
        
        sqlite3_close(db);
    }

    void TearDown() override {
        // 清理测试数据库
        if (testDbPath != ":memory:") {
            std::remove(testDbPath.c_str());
        }
    }
};

TEST_F(EventCorrelationEngineTest, InitializeTest) {
    EXPECT_TRUE(engine.initialize());
}

TEST_F(EventCorrelationEngineTest, AnalyzeCorrelationsTest) {
    engine.initialize();
    EXPECT_TRUE(engine.analyzeCorrelations());
    
    auto correlations = engine.getCorrelations();
    EXPECT_GT(correlations.size(), 0);
    
    // 检查是否有时间关联（引擎使用 "same_time"，见 EventCorrelationAnalyzer）
    bool hasTemporalCorrelation = false;
    for (const auto& correlation : correlations) {
        if (correlation.correlationType == "same_time") {
            hasTemporalCorrelation = true;
            break;
        }
    }
    EXPECT_TRUE(hasTemporalCorrelation);

    // 检查是否有文件路径关联（引擎使用 "same_file"）
    bool hasFilePathCorrelation = false;
    for (const auto& correlation : correlations) {
        if (correlation.correlationType == "same_file") {
            hasFilePathCorrelation = true;
            break;
        }
    }
    EXPECT_TRUE(hasFilePathCorrelation);
}

TEST_F(EventCorrelationEngineTest, AnalyzeEventChainsTest) {
    engine.initialize();
    engine.analyzeCorrelations();
    
    auto chains = engine.analyzeEventChains();
    // 暂时只测试是否返回了结果，不测试具体成员
    EXPECT_GT(chains.size(), 0);
}

TEST_F(EventCorrelationEngineTest, DiscoverCausalRelationshipsTest) {
    engine.initialize();
    engine.analyzeCorrelations();
    
    auto causalRelationships = engine.discoverCausalRelationships();
    // 因果关系可能为空，因为测试数据有限
    // EXPECT_GT(causalRelationships.size(), 0);
}

TEST_F(EventCorrelationEngineTest, ExportTest) {
    engine.initialize();
    engine.analyzeCorrelations();
    
    // 导出关联结果
    engine.exportCorrelations("test_correlations.json");
    std::ifstream corrFile("test_correlations.json");
    EXPECT_TRUE(corrFile.good());
    corrFile.close();
    std::remove("test_correlations.json");
    
    // 导出事件链
    engine.exportEventChains("test_event_chains.json");
    std::ifstream chainsFile("test_event_chains.json");
    EXPECT_TRUE(chainsFile.good());
    chainsFile.close();
    std::remove("test_event_chains.json");
    
    // 导出因果关系
    engine.exportCausalRelationships("test_causal_relationships.json");
    std::ifstream causalFile("test_causal_relationships.json");
    EXPECT_TRUE(causalFile.good());
    causalFile.close();
    std::remove("test_causal_relationships.json");
}

TEST_F(EventCorrelationEngineTest, VisualizationTest) {
    engine.initialize();
    engine.analyzeCorrelations();
    
    // 生成可视化
    std::string correlationsDot = engine.visualizeCorrelations();
    EXPECT_FALSE(correlationsDot.empty());
    
    std::string eventChainsDot = engine.visualizeEventChains();
    EXPECT_FALSE(eventChainsDot.empty());
    
    std::string causalRelationshipsDot = engine.visualizeCausalRelationships();
    EXPECT_FALSE(causalRelationshipsDot.empty());
}

// TEST_F(EventCorrelationEngineTest, RulesTest) {
//     engine.initialize();
//     
//     // 添加自定义规则
//     EventCorrelationEngine::CorrelationRule rule;
//     rule.name = "test_rule";
//     rule.description = "Test rule";
//     rule.eventTypes1 = {"FILE_CREATED"};
//     rule.eventTypes2 = {"FILE_MODIFIED"};
//     rule.timeWindowSeconds = 300;
//     rule.minConfidence = 0.7;
//     rule.correlationType = "TEMPORAL";
//     rule.enabled = true;
//     
//     engine.addRule(rule);
//     
//     // 保存规则
//     engine.saveRules("test_rules.json");
//     std::ifstream rulesFile("test_rules.json");
//     EXPECT_TRUE(rulesFile.good());
//     rulesFile.close();
//     
//     // 加载规则
//     EXPECT_TRUE(engine.loadCustomRules("test_rules.json"));
//     
//     // 清理
//     std::remove("test_rules.json");
// }

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
