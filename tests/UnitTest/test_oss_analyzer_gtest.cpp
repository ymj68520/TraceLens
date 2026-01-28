/**
 * @file test_oss_analyzer_gtest.cpp
 * @brief OSSAnalyzer模块单元测试
 */

#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>

#include "OSSAnalyzer/Common/OSSDataTypes.h"
#include "OSSAnalyzer/Common/OSSExportTypes.h"
#include "OSSAnalyzer/Database/OSSAnalysisDatabase.h"

namespace fs = std::filesystem;
using namespace ForensicAnalyzer::OSS;

class OSSAnalyzerTest : public ::testing::Test {
protected:
    void SetUp() override {
        // 创建临时测试目录
        test_dir_ = fs::temp_directory_path() / "oss_test";
        fs::create_directories(test_dir_);
        
        db_path_ = (test_dir_ / "test_oss.db").string();
    }
    
    void TearDown() override {
        fs::remove_all(test_dir_);
    }
    
    fs::path test_dir_;
    std::string db_path_;
};

// ========== 数据类型测试 ==========

TEST_F(OSSAnalyzerTest, OSSExportTypeEnumValues) {
    EXPECT_EQ(static_cast<int>(OSSExportType::DIRECT_API), 0);
    EXPECT_EQ(static_cast<int>(OSSExportType::LOCAL_DIRECTORY), 1);
    EXPECT_EQ(static_cast<int>(OSSExportType::INVENTORY_CSV), 2);
    EXPECT_EQ(static_cast<int>(OSSExportType::ACCESS_LOG), 3);
}

TEST_F(OSSAnalyzerTest, OSSAuthTypeEnumValues) {
    EXPECT_EQ(static_cast<int>(OSSAuthType::ACCESS_KEY), 0);
    EXPECT_EQ(static_cast<int>(OSSAuthType::STS_TOKEN), 1);
    EXPECT_EQ(static_cast<int>(OSSAuthType::ECS_RAM_ROLE), 2);
    EXPECT_EQ(static_cast<int>(OSSAuthType::ANONYMOUS), 3);
}

TEST_F(OSSAnalyzerTest, OSSObjectInfoDefaultValues) {
    OSSObjectInfo obj;
    EXPECT_TRUE(obj.bucket.empty());
    EXPECT_TRUE(obj.key.empty());
    EXPECT_EQ(obj.size, 0);
    EXPECT_FALSE(obj.isDeleted);
}

TEST_F(OSSAnalyzerTest, OSSConnectionConfigDefaultValues) {
    OSSConnectionConfig config;
    EXPECT_EQ(config.connectTimeoutMs, 10000);
    EXPECT_EQ(config.requestTimeoutMs, 30000);
    EXPECT_EQ(config.maxConnections, 16);  // SDK default
    EXPECT_TRUE(config.enableCrc);
}

// ========== 数据库测试 ==========

TEST_F(OSSAnalyzerTest, DatabaseInitialization) {
    OSSAnalysisDatabase db(db_path_);
    EXPECT_TRUE(db.initialize());
    EXPECT_TRUE(fs::exists(db_path_));
}

TEST_F(OSSAnalyzerTest, InsertAndQueryObject) {
    OSSAnalysisDatabase db(db_path_);
    ASSERT_TRUE(db.initialize());
    
    OSSObjectInfo obj;
    obj.bucket = "test-bucket";
    obj.key = "folder/test-file.txt";
    obj.size = 12345;
    obj.etag = "abc123";
    obj.lastModified = 1700000000;
    obj.storageClass = "Standard";
    obj.contentType = "text/plain";
    obj.analyzedAt = 1700000100;
    
    EXPECT_TRUE(db.insertObject(obj));
    
    auto objects = db.getAllObjects();
    EXPECT_EQ(objects.size(), 1);
    EXPECT_EQ(objects[0].bucket, "test-bucket");
    EXPECT_EQ(objects[0].key, "folder/test-file.txt");
    EXPECT_EQ(objects[0].size, 12345);
}

TEST_F(OSSAnalyzerTest, QueryObjectsByBucket) {
    OSSAnalysisDatabase db(db_path_);
    ASSERT_TRUE(db.initialize());
    
    // 插入多个对象
    for (int i = 0; i < 5; i++) {
        OSSObjectInfo obj;
        obj.bucket = (i < 3) ? "bucket-a" : "bucket-b";
        obj.key = "file" + std::to_string(i) + ".txt";
        obj.size = 100 + i;
        obj.analyzedAt = 1700000000 + i;
        db.insertObject(obj);
    }
    
    auto objectsA = db.getObjectsByBucket("bucket-a");
    auto objectsB = db.getObjectsByBucket("bucket-b");
    
    EXPECT_EQ(objectsA.size(), 3);
    EXPECT_EQ(objectsB.size(), 2);
}

TEST_F(OSSAnalyzerTest, InsertAndQueryAccessLog) {
    OSSAnalysisDatabase db(db_path_);
    ASSERT_TRUE(db.initialize());
    
    OSSAccessLogEntry entry;
    entry.requestId = "req-12345";
    entry.timestamp = 1700000000;
    entry.operation = "GetObject";
    entry.bucket = "test-bucket";
    entry.objectKey = "test.txt";
    entry.remoteIP = "192.168.1.1";
    entry.httpStatus = 200;
    entry.bytesSent = 1024;
    
    EXPECT_TRUE(db.insertAccessLog(entry));
    
    auto logs = db.getAccessLogsByTimeRange(1699999999, 1700000001);
    EXPECT_EQ(logs.size(), 1);
    EXPECT_EQ(logs[0].operation, "GetObject");
}

TEST_F(OSSAnalyzerTest, InsertAndQueryBucket) {
    OSSAnalysisDatabase db(db_path_);
    ASSERT_TRUE(db.initialize());
    
    OSSBucketInfo bucket;
    bucket.name = "my-bucket";
    bucket.region = "cn-hangzhou";
    bucket.acl = "private";
    bucket.storageClass = "Standard";
    bucket.objectCount = 100;
    bucket.totalSize = 1024000;
    bucket.versioningEnabled = true;
    bucket.analyzedAt = 1700000000;
    
    EXPECT_TRUE(db.insertBucket(bucket));
    
    auto buckets = db.getAllBuckets();
    EXPECT_EQ(buckets.size(), 1);
    EXPECT_EQ(buckets[0].name, "my-bucket");
    EXPECT_TRUE(buckets[0].versioningEnabled);
}

TEST_F(OSSAnalyzerTest, AnalysisSummary) {
    OSSAnalysisDatabase db(db_path_);
    ASSERT_TRUE(db.initialize());
    
    // 插入测试数据
    for (int i = 0; i < 10; i++) {
        OSSObjectInfo obj;
        obj.bucket = "bucket";
        obj.key = "file" + std::to_string(i) + ".txt";
        obj.size = 1000;
        obj.storageClass = (i < 7) ? "Standard" : "IA";
        obj.isDeleted = (i == 9);
        obj.analyzedAt = 1700000000;
        db.insertObject(obj);
    }
    
    auto summary = db.getAnalysisSummary();
    EXPECT_EQ(summary.totalObjects, 10);
    EXPECT_EQ(summary.totalSize, 10000);
    EXPECT_EQ(summary.deletedObjects, 1);
}

// ========== 事务测试 ==========

TEST_F(OSSAnalyzerTest, BatchInsertWithTransaction) {
    OSSAnalysisDatabase db(db_path_);
    ASSERT_TRUE(db.initialize());
    
    std::vector<OSSObjectInfo> objects;
    for (int i = 0; i < 100; i++) {
        OSSObjectInfo obj;
        obj.bucket = "bucket";
        obj.key = "file" + std::to_string(i) + ".txt";
        obj.size = i * 100;
        obj.analyzedAt = 1700000000;
        objects.push_back(obj);
    }
    
    int inserted = db.insertObjects(objects);
    EXPECT_EQ(inserted, 100);
    
    auto allObjects = db.getAllObjects();
    EXPECT_EQ(allObjects.size(), 100);
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
