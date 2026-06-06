# 快速入门指南

## 概述

本指南将帮助您在 30 分钟内完成 ForensicsProject 的安装、配置和第一次取证分析。

**前置要求**：
- Ubuntu 20.04+ 或其他 Linux 发行版
- Python 3.10+
- 至少 8GB RAM
- 20GB 可用磁盘空间

---

## 目录

1. [安装依赖](#1-安装依赖)
2. [编译项目](#2-编译项目)
3. [运行第一次分析](#3-运行第一次分析)
4. [启动 HTTP 服务](#4-启动-http-服务)
5. [使用知识图谱](#5-使用知识图谱)
6. [常见问题](#6-常见问题)

---

## 1. 安装依赖

### 1.1 系统包

```bash
# 更新包列表
sudo apt-get update

# 安装编译依赖
sudo apt-get install -y \
    build-essential \
    cmake \
    git \
    libsqlite3-dev \
    libewf-dev \
    libhivex-dev \
    libevtx-dev \
    libasio-dev \
    nlohmann-json3-dev \
    libboost-system-dev \
    libboost-thread-dev \
    libesedb-dev \
    libolecf-dev \
    libxapian-dev \
    libpoppler-cpp-dev \
    libzip-dev \
    libpugixml-dev \
    libgtest-dev \
    libgmock-dev \
    pkg-config \
    libcurl4-openssl-dev
```

### 1.2 The Sleuth Kit (TSK) 4.14.0

```bash
# 下载
wget https://github.com/sleuthkit/sleuthkit/releases/download/sleuthkit-4.14.0.tar.gz
tar -xzf sleuthkit-4.14.0.tar.gz && cd sleuthkit-4.14.0

# 编译安装
./configure
make -j$(nproc)
sudo make install
sudo ldconfig

# 验证
tsk_loaddb -V  # 应显示 4.14.0
```

### 1.3 Crow 框架

```bash
# 克隆
git clone https://github.com/CrowCpp/Crow.git
cd Crow && mkdir build && cd build

# 配置安装
cmake .. \
    -DCROW_BUILD_EXAMPLES=OFF \
    -DCROW_BUILD_TESTS=OFF
sudo make install
```

### 1.4 Python 依赖

```bash
# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r python_service/httpserver/requirements.txt
```

---

## 2. 编译项目

### 2.1 创建构建目录

```bash
cd /path/to/ForensicsProject
mkdir build && cd build
```

### 2.2 配置和编译

```bash
# Release 构建
cmake .. -DCMAKE_BUILD_TYPE=Release

# 编译（使用所有 CPU 核心）
cmake --build . -j$(nproc)
```

### 2.3 验证安装

```bash
# 检查可执行文件
./forensic_analyzer --version

# 应显示版本信息
# ForensicProject Digital Forensics Image Analyzer v1.0.0
```

---

## 3. 运行第一次分析

### 3.1 准备磁盘镜像

```bash
# 假设您有一个 E01 镜像文件
ls -lh evidence.E01
# -rw-r--r-- 1 user user 2.0G Jan 15 10:00 evidence.E01
```

### 3.2 执行分析

```bash
# 完整分析（推荐）
./forensic_analyzer evidence.E01

# 这将生成三个数据库：
# - evidence_raw.db      (原始文件系统元数据)
# - evidence_events.db   (时间线事件)
# - evidence_files.db    (文件分类)
```

### 3.3 查看结果

```bash
# 查看生成的文件
ls -lh evidence_*.db

# 查看文件数量
sqlite3 evidence_files.db "SELECT COUNT(*) FROM files;"

# 查看分类统计
sqlite3 evidence_files.db "
    SELECT category, COUNT(*) as count
    FROM files
    GROUP BY category
    ORDER BY count DESC;
"
```

### 3.4 提取文件

```bash
# 提取所有文档
./forensic_analyzer --database evidence_files.db \
    --extract-ext ".doc,.docx,.pdf,.txt" \
    --output-dir extracted_docs

# 提取所有图片
./forensic_analyzer --database evidence_files.db \
    --extract-ext ".jpg,.png,.gif" \
    --output-dir extracted_images
```

---

## 4. 启动 HTTP 服务

### 4.1 启动 C++ 服务

```bash
# 终端 1：启动 C++ HTTP 服务器
./forensic_analyzer --http-server 8080

# 服务将在 http://localhost:8080 运行
```

### 4.2 启动 Python 服务

```bash
# 终端 2：启动 Python HTTP 服务器
source .venv/bin/activate
python -m python_service.httpserver.main

# 服务将在 http://localhost:8090 运行
```

### 4.3 验证服务

```bash
# 检查 C++ 服务
curl http://localhost:8080/api/health

# 检查 Python 服务
curl http://localhost:8090/health
```

**预期响应**：
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

---

## 5. 使用知识图谱

### 5.1 配置 Neo4j

```bash
# 安装 Neo4j（如果未安装）
wget -O - https://debian.neo4j.com/neotechnology/neoon-repo-pubkey.gpg.key | sudo apt-key add -
echo 'deb https://debian.neo4j.com/debian/ stable main' | sudo tee /etc/apt/sources.list.d/neo4j.list
sudo apt-get update
sudo apt-get install -y neo4j

# 启动 Neo4j
sudo systemctl start neo4j
sudo systemctl enable neo4j

# 验证
neo4j status
```

### 5.2 摄取数据到知识图谱

```bash
# 摄取证文件数据库到知识图谱
curl -X POST http://localhost:8090/api/graphiti/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "evidence",
    "include_llm_descriptions": true,
    "batch_size": 50
  }'
```

**响应**：
```json
{
  "success": true,
  "job_id": "job_xyz789",
  "status": "running",
  "message": "知识图谱摄取已启动"
}
```

### 5.3 搜索知识图谱

```bash
# 搜索关键词
curl -X POST http://localhost:8090/api/graphiti/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "malware documents",
    "task_id": "evidence",
    "limit": 20
  }'
```

**响应**：
```json
{
  "success": true,
  "results": [
    {
      "entity": {
        "name": "trojan.exe",
        "type": "FILE",
        "summary": "可疑可执行文件"
      },
      "score": 0.95
    }
  ]
}
```

---

## 6. 常见问题

### 6.1 编译错误

**问题**：`TSK not found`

**解决**：
```bash
# 检查 TSK 是否安装
pkg-config --modversion tsk

# 如果未安装，重新安装 TSK
```

**问题**：`Crow not found`

**解决**：
```bash
# 检查 Crow 是否安装
pkg-config --modversion --cflags --libs crow

# 如果未安装，重新安装 Crow
```

### 6.2 运行时错误

**问题**：`libtsk.so: cannot open shared object file`

**解决**：
```bash
# 添加库路径
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# 或更新 ldconfig
sudo ldconfig
```

**问题**：`database is locked`

**解决**：
```bash
# 检查是否有其他进程占用数据库
lsof evidence_*.db

# 关闭占用数据库的进程
```

### 6.3 HTTP 服务问题

**问题**：C++ 服务无法启动

**解决**：
```bash
# 检查端口占用
netstat -tulpn | grep 8080

# 终止占用端口的进程
sudo kill -9 <PID>
```

**问题**：Python 服务连接 C++ 失败

**解决**：
```bash
# 检查 C++ 服务是否运行
curl http://localhost:8080/api/health

# 检查配置
cat .env | grep CPP_BACKEND_URL
```

### 6.4 知识图谱问题

**问题**：Neo4j 连接失败

**解决**：
```bash
# 检查 Neo4j 状态
sudo systemctl status neo4j

# 重启 Neo4j
sudo systemctl restart neo4j

# 检查连接
neo4j-console
# 连接字符串：bolt://localhost:7687
# 用户名：neo4j
# 密码：（安装时设置的密码）
```

---

## 7. 下一步

现在您已完成基础设置，可以探索更多功能：

1. **读取完整文档**
   - [架构总览](../architecture/overview.md)
   - [C++ API 参考](../api_reference/CPP_REST_API.md)
   - [Python API 参考](../api_reference/Python_REST_API.md)

2. **高级功能**
   - [Android 取证分析](../modules/cpp/analyzers/AndroidAnalyzer.md)
   - [Windows 取证分析](../modules/cpp/analyzers/WindowsFilesAnalyzer.md)
   - [LLM 集成](../modules/cpp/integration/LLMIntegration.md)
   - [文件雕刻](../modules/cpp/analyzers/FileCarving.md)

3. **开发指南**
   - [添加新的分析器](../getting-started/development.md)
   - [添加新的路由](../modules/cpp/network/HTTPServer.md#二次开发)
   - [扩展 Python 服务](../modules/python/httpserver/Main.md#二次开发)

---

**需要帮助？**

- 查看 [故障排查](../getting-started/troubleshooting.md)
- 查看 [常见问题](../getting-started/faq.md)
- 提交 Issue：https://github.com/ymj68520/ForensicsProject/issues

---

**最后更新**: 2026-06-06
**维护者**: ymj68520
