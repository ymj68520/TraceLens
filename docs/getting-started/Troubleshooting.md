# 故障排查指南

本文档提供 ForensicsProject 的常见问题诊断和解决方案。

---

## 1. 编译问题

### 1.1 CMake 配置失败

#### 问题：找不到 SQLite3

```
CMake Error: Could not find SQLite3
```

**原因**：SQLite3 开发库未安装

**解决方案**：

```bash
# Ubuntu/Debian
sudo apt-get install -y libsqlite3-dev

# CentOS/RHEL
sudo yum install -y sqlite-devel

# macOS
brew install sqlite3

# 验证安装
pkg-config --modversion sqlite3
```

#### 问题：找不到 The Sleuth Kit

```
CMake Error: Could not find TSK library
```

**原因**：TSK 未安装或不在库路径中

**解决方案**：

```bash
# 检查 TSK 是否安装
ldconfig -p | grep libtsk

# 如果没有输出，重新安装 TSK
cd sleuthkit-4.14.0
sudo make install
sudo ldconfig

# 或手动指定 TSK 路径
cmake .. -DTSK_ROOT=/usr/local
```

#### 问题：Boost 库找不到

```
error: boost/system/error_code.hpp: No such file or directory
```

**解决方案**：

```bash
# Ubuntu/Debian
sudo apt-get install -y libboost-all-dev

# 或安装特定组件
sudo apt-get install -y \
    libboost-system-dev \
    libboost-thread-dev \
    libboost-filesystem-dev \
    libboost-program-options-dev
```

### 1.2 编译错误

#### 问题：C++20 特性不支持

```
error: 'ranges' is not a member of 'std'
```

**原因**：编译器版本过低或未启用 C++20

**解决方案**：

```bash
# 检查 GCC 版本（需要 10+）
gcc --version

# 如果版本过低，升级 GCC
sudo apt-get install gcc-12 g++-12

# 设置为默认编译器
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 100
sudo update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-12 100

# 或在 CMake 中指定
cmake .. -DCMAKE_CXX_STANDARD=20
```

#### 问题：链接错误

```
undefined reference to `TSK functions'
```

**解决方案**：

```bash
# 确保链接了正确的库
# 检查 CMakeLists.txt 中的 target_link_libraries

# 手动指定库路径
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# 重新编译
cd build
make clean
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

---

## 2. 运行时问题

### 2.1 动态链接库错误

#### 问题：找不到共享库

```
error while loading shared libraries: libtsk.so.13: cannot open shared object file
```

**解决方案**：

```bash
# 方案 1：更新动态链接库缓存
sudo ldconfig

# 方案 2：添加库路径到 ld.so.conf
echo "/usr/local/lib" | sudo tee /etc/ld.so.conf.d/custom.conf
sudo ldconfig

# 方案 3：设置环境变量（临时）
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# 方案 4：添加到 ~/.bashrc（永久）
echo 'export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc
```

### 2.2 权限问题

#### 问题：无法挂载回环设备

```
Error: Failed to mount XFS filesystem: Operation not permitted
```

**原因**：挂载文件系统需要 root 权限

**解决方案**：

```bash
# 使用 sudo 运行
sudo ./build/forensic_analyzer image.dd --xfs-mode native

# 或使用 pure 模式（不需要 root）
./build/forensic_analyzer image.dd --xfs-mode pure
```

#### 问题：无法读取某些文件

```
Error: Permission denied when reading /path/to/file
```

**解决方案**：

```bash
# 检查文件权限
ls -la /path/to/file

# 如果是当前用户拥有的文件
chmod 600 /path/to/file

# 如果需要 root 访问
sudo ./build/forensic_analyzer image.dd
```

### 2.3 内存不足

#### 问题：分析大镜像时崩溃

```
Segmentation fault (core dumped)
```

**原因**：内存不足导致程序崩溃

**解决方案**：

```bash
# 增加交换空间
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# 永久生效
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 或限制内存使用
ulimit -v 8388608  # 限制为 8GB
./build/forensic_analyzer large_image.dd
```

---

## 3. 数据库问题

### 3.1 数据库锁定

#### 问题：数据库文件被锁定

```
Error: database is locked
```

**原因**：另一个进程正在访问数据库

**解决方案**：

```bash
# 查找占用进程
lsof | grep ".db"

# 或使用 fuser
fuser output/*.db

# 终止进程
kill <PID>

# 如果是 SQLite 内部锁定，删除锁文件
rm output/*.db-shm output/*.db-wal
```

### 3.2 数据库损坏

#### 问题：数据库无法打开

```
Error: database disk image is malformed
```

**解决方案**：

```bash
# 使用 SQLite 的恢复模式
sqlite3 corrupted.db "PRAGMA integrity_check;"

# 导出数据
sqlite3 corrupted.db ".dump" > dump.sql

# 创建新数据库并导入
sqlite3 recovered.db < dump.sql

# 或使用专门的修复工具
python3 << EOF
import sqlite3
conn = sqlite3.connect("corrupted.db")
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("VACUUM")
conn.close()
EOF
```

### 3.3 查询性能问题

#### 问题：查询非常慢

**解决方案**：

```sql
-- 检查索引
.schema files

-- 创建缺失的索引
CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
CREATE INDEX IF NOT EXISTS idx_files_extension ON files(extension);
CREATE INDEX IF NOT EXISTS idx_files_size ON files(size);

-- 分析查询计划
EXPLAIN QUERY PLAN SELECT * FROM files WHERE path LIKE '%.txt';

-- 运行 VACUUM 优化数据库
VACUUM;

-- 更新统计信息
ANALYZE;
```

---

## 4. HTTP 服务问题

### 4.1 服务无法启动

#### 问题：端口已被占用

```
Error: Failed to bind to port 8080: Address already in use
```

**解决方案**：

```bash
# 查找占用端口的进程
sudo netstat -tulpn | grep 8080
# 或
sudo lsof -i :8080

# 终止占用进程
sudo kill <PID>

# 或更换端口
./forensic_analyzer --http-server 8081
```

#### 问题：C++ 服务启动失败

```
Error: HTTP server failed to start
```

**诊断步骤**：

```bash
# 1. 检查日志
tail -f /var/log/forensics/debug.log

# 2. 启用详细日志
export LOG_LEVEL=DEBUG
./forensic_analyzer --http-server 8080

# 3. 检查防火墙
sudo ufw status
sudo ufw allow 8080/tcp

# 4. 验证配置
./forensic_analyzer --help
```

### 4.2 Python 服务问题

#### 问题：FastAPI 服务无法连接 Neo4j

```
Failed to connect to Neo4j: Connection refused
```

**解决方案**：

```bash
# 1. 检查 Neo4j 是否运行
sudo systemctl status neo4j
# 或
docker ps | grep neo4j

# 2. 启动 Neo4j
sudo systemctl start neo4j
# 或
docker start neo4j

# 3. 验证连接
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="your_password"

python3 << EOF
from neo4j import GraphDatabase
driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "your_password"))
driver.verify_connectivity()
print("Connection successful!")
driver.close()
EOF
```

#### 问题：Python 依赖冲突

```
ModuleNotFoundError: No module named 'fastapi'
```

**解决方案**：

```bash
# 重新安装依赖
pip install --force-reinstall -r python_service/httpserver/requirements.txt

# 或使用虚拟环境
python3 -m venv .venv-clean
source .venv-clean/bin/activate
pip install -r python_service/httpserver/requirements.txt

# 检查依赖冲突
pip check
pip install pipdeptree
pipdeptree
```

---

## 5. LLM 集成问题

### 5.1 LLM API 连接失败

#### 问题：无法连接到 LLM 服务

```
Error: Failed to connect to LLM API at http://localhost:1234
```

**诊断步骤**：

```bash
# 1. 检查 LLM 服务是否运行
curl http://localhost:1234/v1/models

# 2. 启动 LM Studio 或其他 LLM 服务
# LM Studio: Start Server from the application

# 3. 验证配置
cat .env | grep LLM

# 4. 测试连接
curl -X POST http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama-3.2-3b",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

#### 问题：LLM 响应超时

**解决方案**：

```cpp
// 增加超时时间
config_.timeout = 120;  // 秒

// 或减少请求大小
std::string truncatedContent = content.substr(0, 10000);
```

### 5.2 模型兼容性问题

#### 问题：模型响应格式错误

```
Error: Failed to parse LLM response: Invalid JSON
```

**解决方案**：

```python
# 测试模型响应格式
import requests

response = requests.post(
    "http://localhost:1234/v1/chat/completions",
    json={
        "model": "llama-3.2-3b",
        "messages": [{"role": "user", "content": "Test"}],
        "temperature": 0.7,
        "max_tokens": 100
    }
)

print(response.json())
```

---

## 6. 文件分析问题

### 6.1 镜像格式不支持

#### 问题：无法识别镜像格式

```
Error: Unsupported image format
```

**解决方案**：

```bash
# 检查文件类型
file evidence.dd

# 检查文件头
xxd evidence.dd | head -n 5

# 如果是 E01 格式，确保安装了 libewf
sudo apt-get install -y libewf-dev

# 重新编译
cd build
cmake .. -DENABLE_EWF=ON
make -j$(nproc)
```

### 6.2 文件系统解析错误

#### 问题：无法解析 NTFS 文件系统

```
Error: Failed to parse NTFS filesystem
```

**诊断步骤**：

```bash
# 使用 TSK 工具验证
fls -f ntfs evidence.dd

# 检查镜像完整性
tsk_loaddb evidence.dd test.db

# 查看详细错误
./forensic_analyzer evidence.dd --verbose
```

### 6.3 文件提取失败

#### 问题：提取文件时出错

```
Error: Failed to extract file: /path/to/file
```

**解决方案**：

```bash
# 检查文件是否被删除
./forensic_analyzer evidence.dd --list-deleted

# 使用 icat 恢复文件
icat -f ntfs evidence.dd <inode> > recovered_file

# 检查磁盘空间
df -h
```

---

## 7. 性能问题

### 7.1 分析速度慢

#### 问题：大镜像分析耗时过长

**优化方案**：

```bash
# 1. 使用多线程
./forensic_analyzer image.dd --threads 8

# 2. 禁用不需要的分析模块
./forensic_analyzer image.dd --skip-llm --skip-fulltext-search

# 3. 分段分析
./forensic_analyzer image.dd --partition 1

# 4. 使用缓存
./forensic_analyzer image.dd --cache-dir /tmp/forensics_cache
```

### 7.2 内存占用过高

#### 问题：分析时内存占用超过 16GB

**解决方案**：

```bash
# 1. 限制并发任务
export MAX_CONCURRENT_TASKS=2

# 2. 禁用 LLM 分析
./forensic_analyzer image.dd --skip-llm

# 3. 分批处理
./forensic_analyzer image.dd --batch-size 1000

# 4. 使用系统资源限制
ulimit -v 16777216  # 限制为 16GB
```

### 7.3 数据库写入慢

#### 问题：数据库写入成为瓶颈

**优化方案**：

```cpp
// 使用事务
db->beginTransaction();

// 批量插入
for (const auto& file : files) {
    db->insertFile(file);
}

db->commitTransaction();

// 或使用批量插入
db->insertFiles(files);  // 一次性插入
```

```sql
-- 优化数据库设置
PRAGMA synchronous = NORMAL;  -- 而不是 FULL
PRAGMA journal_mode = WAL;
PRAGMA cache_size = -64000;   -- 64MB 缓存
PRAGMA temp_store = MEMORY;
```

---

## 8. 调试技巧

### 8.1 启用详细日志

```bash
# C++ 服务
export LOG_LEVEL=DEBUG
export LOG_FILE=/tmp/forensics_debug.log
./forensic_analyzer image.dd

# Python 服务
export LOG_LEVEL=DEBUG
python -m python_service.httpserver.main
```

### 8.2 使用 GDB 调试

```bash
# 编译 Debug 版本
cd build
cmake .. -DCMAKE_BUILD_TYPE=Debug
make -j$(nproc)

# 使用 GDB 运行
gdb --args ./forensic_analyzer image.dd

# GDB 常用命令
(gdb) run
(gdb) backtrace  # 查看调用栈
(gdb) print variable_name
(gdb) info locals
```

### 8.3 内存泄漏检测

```bash
# 使用 Valgrind
valgrind --leak-check=full \
         --show-leak-kinds=all \
         --track-origins=yes \
         --log-file=valgrind-out.txt \
         ./forensic_analyzer image.dd

# 查看报告
cat valgrind-out.txt | grep "definitely lost"
```

### 8.4 性能分析

```bash
# 使用 perf
perf record -g ./forensic_analyzer image.dd
perf report

# 生成火焰图
perf script | FlameGraph/stackcollapse-perf.pl | FlameGraph/flamegraph.pl > flamegraph.svg
```

---

## 9. 常见错误代码

| 错误代码 | 说明 | 解决方案 |
|---------|------|---------|
| `E01` | 无法打开镜像文件 | 检查文件路径和权限 |
| `E02` | 无法识别镜像格式 | 确认文件格式，安装相应库 |
| `E03` | 数据库创建失败 | 检查磁盘空间和权限 |
| `E04` | 文件系统解析失败 | 使用 TSK 工具验证镜像 |
| `E05` | 内存不足 | 增加交换空间或减少并发 |
| `E06` | LLM API 调用失败 | 检查 LLM 服务状态 |
| `E07` | HTTP 服务启动失败 | 检查端口占用 |

---

## 10. 获取帮助

### 10.1 日志收集

提交 Bug 时，请提供：

```bash
# 系统信息
uname -a
gcc --version
cmake --version

# 应用日志
tar -czf logs.tar.gz /var/log/forensics/

# 配置文件
cat .env

# 复现步骤
echo "Steps to reproduce:"
echo "1. ./forensic_analyzer image.dd"
echo "2. ..."
```

### 10.2 社区支持

- **GitHub Issues**: https://github.com/ymj68520/ForensicsProject/issues
- **Discussions**: https://github.com/ymj68520/ForensicsProject/discussions
- **Wiki**: https://github.com/ymj68520/ForensicsProject/wiki

### 10.3 专业支持

如果需要商业支持，请联系：

- Email: support@forensicsproject.com
- Website: https://forensicsproject.com

---

## 11. 预防性维护

### 11.1 定期检查

```bash
#!/bin/bash
# 健康检查脚本

echo "=== ForensicsProject 健康检查 ==="

# 检查磁盘空间
echo "磁盘空间："
df -h

# 检查内存使用
echo "内存使用："
free -h

# 检查数据库完整性
echo "数据库完整性："
for db in output/*.db; do
    echo "检查 $db"
    sqlite3 "$db" "PRAGMA integrity_check;"
done

# 检查服务状态
echo "服务状态："
systemctl status forensics-cpp || echo "C++ 服务未运行"
systemctl status forensics-python || echo "Python 服务未运行"
```

### 11.2 备份策略

```bash
#!/bin/bash
# 备份脚本

BACKUP_DIR="/backup/forensics"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# 备份数据库
tar -czf "$BACKUP_DIR/db_$DATE.tar.gz" output/*.db

# 备份配置
cp .env "$BACKUP_DIR/env_$DATE"

# 清理旧备份（保留 30 天）
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete
```

---

## 相关文档

- **[安装指南](Installation.md)** - 依赖和编译
- **[开发环境配置](Development.md)** - 调试工具设置
- **[常见任务](CommonTasks.md)** - 开发指南
- **[架构总览](../architecture/Overview.md)** - 系统架构

---

**最后更新**: 2026-03-11
**维护者**: ymj68520
