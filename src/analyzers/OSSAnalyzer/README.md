# OSS分析器模块 (OSSAnalyzer)

## 概述

阿里云OSS（对象存储服务）分析模块，用于取证分析OSS存储的数据。支持多种分析方式：

- **API直连分析**：实时连接OSS获取对象元数据
- **本地目录分析**：分析已下载的OSS导出目录（离线模式）
- **Inventory清单分析**：解析OSS Inventory定期生成的CSV清单
- **访问日志分析**：解析OSS访问日志还原操作历史

## 功能特性

- 多种认证方式支持（AK/SK、STS临时凭证、ECS RAM角色）
- 完整的对象元数据提取
- 访问日志时间线分析
- 按存储类型、扩展名统计
- 数据库持久化存储

## 使用示例

### API分析

```cpp
#include "OSSAnalyzer/OSSAnalyzer.h"

using namespace ForensicAnalyzer::OSS;

OSSConnectionConfig config;
config.endpoint = "oss-cn-hangzhou.aliyuncs.com";
config.accessKeyId = "your-access-key-id";
config.accessKeySecret = "your-access-key-secret";
config.bucket = "my-bucket";

OSSAnalyzer analyzer(config, dbManager);
analyzer.setOutputDbPath("task_oss.db");

if (analyzer.initialize()) {
    analyzer.analyzeFromAPI();
    
    auto summary = analyzer.getAnalysisSummary();
    std::cout << "Total objects: " << summary.totalObjects << std::endl;
}
```

### 本地目录分析

```cpp
OSSAnalyzer analyzer;
analyzer.setOutputDbPath("local_oss.db");
analyzer.initialize();
analyzer.analyzeFromLocalDirectory("/path/to/oss/export", "my-bucket");
```

### Inventory分析

```cpp
analyzer.analyzeFromInventory("/path/to/inventory.csv");
```

### 访问日志分析

```cpp
analyzer.analyzeAccessLogs("/path/to/logs/");
```

## 数据库模式

生成 `_oss.db` 数据库包含：

- **oss_objects**：对象元数据（键、大小、ETag、修改时间、存储类型等）
- **oss_access_logs**：访问日志（操作、IP、时间、状态码等）
- **oss_buckets**：Bucket配置信息

## 依赖

- 阿里云OSS C++ SDK (`libs/aliyun-oss-cpp-sdk`)
- SQLite3
- libcurl
- OpenSSL

## 环境变量配置

```env
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
OSS_ACCESS_KEY_ID=your-key-id
OSS_ACCESS_KEY_SECRET=your-key-secret
OSS_BUCKET=default-bucket
```
