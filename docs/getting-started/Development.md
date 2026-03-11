# 开发环境配置

本文档说明如何配置 ForensicsProject 的开发环境，包括 IDE 设置、调试工具、代码风格和测试框架。

---

## 1. 开发工具安装

### 1.1 必备工具

| 工具 | 用途 | 安装命令 |
|------|------|---------|
| **Git** | 版本控制 | `sudo apt-get install git` |
| **CMake** | 构建系统 | `sudo apt-get install cmake` |
| **GCC/Clang** | C++ 编译器 | `sudo apt-get install build-essential clang` |
| **GDB** | 调试器 | `sudo apt-get install gdb` |
| **Valgrind** | 内存检测 | `sudo apt-get install valgrind` |
| **clang-format** | 代码格式化 | `sudo apt-get install clang-format` |
| **clang-tidy** | 静态分析 | `sudo apt-get install clang-tidy` |

### 1.2 推荐工具

```bash
# 性能分析
sudo apt-get install perf flamegraph

# 代码覆盖率
sudo apt-get install lcov gcovr

# 依赖分析
sudo apt-get install graphviz

# 文档生成
pip install mkdocs mkdocs-material
```

### 1.3 Python 开发工具

```bash
# 创建开发虚拟环境
python3 -m venv .venv-dev
source .venv-dev/bin/activate

# 安装开发依赖
pip install -r requirements-dev.txt
```

`requirements-dev.txt`：

```txt
# 测试框架
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
pytest-mock>=3.12.0

# 代码质量
black>=23.11.0
isort>=5.12.0
flake8>=6.1.0
mypy>=1.7.0
pylint>=3.0.0

# 类型检查
types-requests>=2.31.0

# 调试工具
ipython>=8.18.0
ipdb>=0.13.0
```

---

## 2. IDE 配置

### 2.1 Visual Studio Code

#### 安装扩展

```bash
# 推荐扩展列表
code --install-extension ms-vscode.cpptools
code --install-extension ms-vscode.cmake-tools
code --install-extension twxs.cmake
code --install-extension ms-python.python
code --install-extension ms-python.debugpy
code --install-extension ms-python.vscode-pylance
code --install-extension usernamehw.errorlens
code --install-extension eamodio.gitlens
code --install-extension zxh404.vscode-proto3
```

#### 工作区配置

创建 `.vscode/settings.json`：

```json
{
    // C++ 配置
    "C_Cpp.default.configurationProvider": "ms-vscode.cmake-tools",
    "C_Cpp.default.cppStandard": "c++20",
    "C_Cpp.default.compilerPath": "/usr/bin/gcc",
    "C_Cpp.default.includePath": [
        "${workspaceFolder}/src",
        "${workspaceFolder}/libs/**",
        "/usr/local/include"
    ],

    // CMake 配置
    "cmake.configureOnOpen": true,
    "cmake.buildDirectory": "${workspaceFolder}/build",
    "cmake.defaultVariants": {
        "debug": {
            "buildType": "Debug",
            "settings": {
                "BUILD_TESTS": "ON"
            }
        },
        "release": {
            "buildType": "Release"
        }
    },

    // 格式化
    "C_Cpp.clang_format_style": "file",
    "editor.formatOnSave": true,
    "editor.formatOnPaste": true,
    "editor.codeActionsOnSave": {
        "source.fixAll": true,
        "source.organizeImports": true
    },

    // Python 配置
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv-dev/bin/python",
    "python.formatting.provider": "black",
    "python.linting.enabled": true,
    "python.linting.flake8Enabled": true,
    "python.linting.mypyEnabled": true,
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": [
        "python_service"
    ],

    // 文件排除
    "files.exclude": {
        "**/.git": true,
        "**/build": true,
        "**/.venv*": true,
        "**/__pycache__": true,
        "**/*.pyc": true
    },

    // 代码分析
    "C_Cpp.errorSquiggles": "enabled",
    "C_Cpp.autocomplete": "default"
}
```

#### 调试配置

创建 `.vscode/launch.json`：

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "C++: 调试 forensic_analyzer",
            "type": "cppdbg",
            "request": "launch",
            "program": "${workspaceFolder}/build/forensic_analyzer",
            "args": ["--http-server", "8080"],
            "stopAtEntry": false,
            "cwd": "${workspaceFolder}",
            "environment": [],
            "externalConsole": false,
            "MIMode": "gdb",
            "setupCommands": [
                {
                    "description": "启用 pretty-printing",
                    "text": "-enable-pretty-printing",
                    "ignoreFailures": true
                }
            ],
            "preLaunchTask": "CMake: Build debug"
        },
        {
            "name": "Python: 调试 FastAPI 服务",
            "type": "debugpy",
            "request": "launch",
            "module": "python_service.httpserver.main",
            "console": "integratedTerminal",
            "env": {
                "PYTHONPATH": "${workspaceFolder}",
                "NEO4J_URI": "bolt://localhost:7687"
            }
        },
        {
            "name": "Python: 附加到进程",
            "type": "debugpy",
            "request": "attach",
            "connect": {
                "host": "localhost",
                "port": 5678
            }
        }
    ]
}
```

#### 任务配置

创建 `.vscode/tasks.json`：

```json
{
    "version": "2.0.0",
    "tasks": [
        {
            "label": "CMake: Configure",
            "type": "shell",
            "command": "cmake",
            "args": ["-B", "build", "-DCMAKE_BUILD_TYPE=Debug"],
            "options": {
                "cwd": "${workspaceFolder}"
            },
            "group": "build"
        },
        {
            "label": "CMake: Build",
            "type": "shell",
            "command": "cmake",
            "args": ["--build", "build", "-j", "$(nproc)"],
            "options": {
                "cwd": "${workspaceFolder}"
            },
            "group": {
                "kind": "build",
                "isDefault": true
            },
            "dependsOn": ["CMake: Configure"]
        },
        {
            "label": "C++: 运行测试",
            "type": "shell",
            "command": "cd build && ctest --output-on-failure",
            "options": {
                "cwd": "${workspaceFolder}"
            },
            "group": "test",
            "dependsOn": ["CMake: Build"]
        },
        {
            "label": "Python: 运行测试",
            "type": "shell",
            "command": "pytest",
            "args": ["python_service/", "-v", "--cov=python_service"],
            "options": {
                "cwd": "${workspaceFolder}",
                "env": {
                    "PYTHONPATH": "${workspaceFolder}"
                }
            },
            "group": "test"
        },
        {
            "label": "格式化 C++ 代码",
            "type": "shell",
            "command": "find src -name '*.cpp' -o -name '*.h' | xargs clang-format -i",
            "options": {
                "cwd": "${workspaceFolder}"
            }
        },
        {
            "label": "格式化 Python 代码",
            "type": "shell",
            "command": "black python_service/ && isort python_service/",
            "options": {
                "cwd": "${workspaceFolder}"
            }
        }
    ]
}
```

### 2.2 CLion

#### 配置 CMake

```cmake
# CMakeLists.txt 添加开发选项
option(BUILD_TESTS "Build tests" ON)
option(ENABLE_COVERAGE "Enable code coverage" OFF)
option(ENABLE_CLANG_TIDY "Enable clang-tidy" OFF)

if(ENABLE_CLANG_TIDY)
    find_program(CLANG_TIDY clang-tidy)
    if(CLANG_TIDY)
        set_target_properties(forensic_analyzer PROPERTIES
            CXX_CLANG_TIDY "${CLANG_TIDY};-checks=*")
    endif()
endif()
```

#### 配置代码风格

Settings → Editor → Code Style → C/C++：
- 选择 "Project" 方案
- 导入 `.clang-format` 配置

#### 运行配置

创建 Run Configuration：
- **C++ Executable**: `forensic_analyzer`
- **Program arguments**: `--http-server 8080`
- **Working directory**: `$ProjectFileDir$`

### 2.3 Vim/Neovim

#### 安装插件（使用 vim-plug）

```vim
" ~/.vimrc 或 ~/.config/nvim/init.vim

call plug#begin('~/.vim/plugged')

" C++ 支持
Plug 'rhysd/vim-clang-format'
Plug 'ycm-core/YouCompleteMe'

" CMake 支持
Plug 'itchyny/vim-cmake'

" Python 支持
Plug 'dense-analysis/ale'
Plug 'psf/black', { 'branch': 'main' }

" Git 集成
Plug 'tpope/vim-fugitive'

" 文件浏览
Plug 'preservim/nerdtree'

call plug#end()

" 配置
let g:clang_format#auto_format = 1
let g:ale_linters = {
    \ 'cpp': ['clang-tidy', 'clang-check'],
    \ 'python': ['flake8', 'mypy']
    \}
```

---

## 3. 代码风格

### 3.1 C++ 代码风格

项目使用 `.clang-format` 配置：

```yaml
# .clang-format
BasedOnStyle: Google
IndentWidth: 4
ColumnLimit: 100
PointerAlignment: Left
SortIncludes: true
IncludeBlocks: Regroup
```

**命名约定**：

| 类型 | 约定 | 示例 |
|------|------|------|
| 类名 | PascalCase | `class ImageAnalyzer` |
| 函数名 | PascalCase | `void AnalyzeImage()` |
| 成员变量 | camelCase + 下划线后缀 | `std::string filePath_` |
| 局部变量 | camelCase | `std::string filePath` |
| 常量 | UPPER_SNAKE_CASE | `const int MAX_FILES` |
| 宏 | UPPER_SNAKE_CASE | `#define LOG_DEBUG(msg)` |

**注释风格**：

```cpp
/**
 * @brief 分析磁盘镜像并提取文件元数据
 *
 * @param imagePath 镜像文件路径
 * @param outputPath 输出数据库路径
 * @return true 分析成功
 * @return false 分析失败
 *
 * @throws std::runtime_error 如果镜像格式不支持
 *
 * 示例：
 * @code
 * ImageAnalyzer analyzer("image.dd");
 * analyzer.analyze("output.db");
 * @endcode
 */
bool analyze(const std::string& imagePath, const std::string& outputPath);
```

### 3.2 Python 代码风格

项目使用 Black + isort：

```bash
# 格式化代码
black python_service/
isort python_service/

# 检查代码
flake8 python_service/
mypy python_service/
pylint python_service/
```

**命名约定**（PEP 8）：

| 类型 | 约定 | 示例 |
|------|------|------|
| 类名 | PascalCase | `class GraphitiIngestor` |
| 函数名 | snake_case | `def ingest_data():` |
| 变量名 | snake_case | `file_path = "..."` |
| 常量 | UPPER_SNAKE_CASE | `MAX_RETRIES = 3` |
| 私有成员 | 前缀下划线 | `def _internal_method():` |

**类型注解**：

```python
from typing import List, Dict, Optional
from pydantic import BaseModel

class FileRecord(BaseModel):
    """文件记录模型"""
    inode: int
    name: str
    path: str
    size: Optional[int] = None
    category: str = "unknown"

def analyze_files(
    files: List[FileRecord],
    options: Dict[str, bool]
) -> Dict[str, int]:
    """
    分析文件列表并返回统计信息

    Args:
        files: 文件记录列表
        options: 分析选项字典

    Returns:
        包含统计信息的字典
    """
    ...
```

### 3.3 Git 提交信息

使用 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**类型**：
- `feat`: 新功能
- `fix`: 修复 Bug
- `docs`: 文档更新
- `style`: 代码格式（不影响功能）
- `refactor`: 重构
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建/工具链更新

**示例**：

```
feat(analyzer): 添加 XFS 文件系统原生解析支持

- 添加 XFSHelper 类用于挂载回环设备
- 实现 NativeXFSParser 使用内核驱动
- 添加 --xfs-mode 参数支持 auto/native/pure 模式

Closes #123
```

---

## 4. 调试配置

### 4.1 GDB 调试

#### 基本 GDB 命令

```bash
# 启动调试
gdb --args ./build/forensic_analyzer --http-server 8080

# 常用命令
(gdb) break main                    # 设置断点
(gdb) run                           # 运行程序
(gdb) next                          # 单步执行（不进入函数）
(gdb) step                          # 单步执行（进入函数）
(gdb) print variable_name           # 打印变量
(gdb) backtrace                     # 查看调用栈
(gdb) continue                      # 继续执行
(gdb) quit                          # 退出 GDB
```

#### GDB 初始化文件

创建 `.gdbinit`：

```
# ~/.gdbinit 或项目目录下

# 显示友好提示
set startup-with-shell off

# 优化输出
set print pretty on
set print union on
set print array on
set print elements 0

# 自动显示源代码
set listsize 20

# 代码片段
define hook-stop
    echo ===========================================\n
    echo Source file: $file\n
    echo Line: $line\n
    disassemble 1
    echo ===========================================\n
end
```

### 4.2 Valgrind 内存检测

```bash
# 检测内存泄漏
valgrind --leak-check=full \
         --show-leak-kinds=all \
         --track-origins=yes \
         --verbose \
         --log-file=valgrind-out.txt \
         ./build/forensic_analyzer test_image.dd

# 性能分析
valgrind --tool=callgrind \
         ./build/forensic_analyzer test_image.dd

# 查看结果
kcachegrind callgrind.out.<pid>
```

### 4.3 Python 调试

#### 使用 pdb

```python
# 在代码中插入断点
import pdb; pdb.set_trace()

# 或使用 ipdb（需要安装）
import ipdb; ipdb.set_trace()
```

#### VSCode 调试配置

已在 [2.1 节](#21-visual-studio-code) 提供。

---

## 5. 测试框架

### 5.1 C++ 单元测试（Google Test）

#### 创建测试

```cpp
// tests/UnitTest/test_image_analyzer.cpp

#include <gtest/gtest.h>
#include "analyzers/ImageAnalyzer/ImageAnalyzer.h"

class ImageAnalyzerTest : public ::testing::Test {
protected:
    void SetUp() override {
        // 每个测试前执行
        analyzer_ = std::make_unique<ImageAnalyzer>();
    }

    void TearDown() override {
        // 每个测试后执行
        analyzer_.reset();
    }

    std::unique_ptr<ImageAnalyzer> analyzer_;
};

TEST_F(ImageAnalyzerTest, AnalyzeValidImage) {
    // Arrange
    std::string imagePath = "tests/fixtures/test.dd";

    // Act
    auto result = analyzer_->analyze(imagePath);

    // Assert
    EXPECT_TRUE(result.isSuccess());
    EXPECT_GT(result.getFileCount(), 0);
}

TEST_F(ImageAnalyzerTest, AnalyzeInvalidImage) {
    EXPECT_THROW(analyzer_->analyze("nonexistent.dd"), std::runtime_error);
}
```

#### 运行测试

```bash
# 编译测试
cd build
cmake .. -DBUILD_TESTS=ON
cmake --build . -j$(nproc)

# 运行所有测试
ctest --output-on-failure

# 运行特定测试
./tests/UnitTest/test_image_analyzer

# 运行特定测试用例
./tests/UnitTest/test_image_analyzer --gtest_filter=ImageAnalyzerTest.AnalyzeValidImage

# 重复运行（查找间歇性错误）
./tests/UnitTest/test_image_analyzer --gtest_repeat=1000
```

### 5.2 Python 单元测试（pytest）

#### 创建测试

```python
# python_service/tests/test_graphiti_service.py

import pytest
from unittest.mock import Mock, patch
from httpserver.services.graphiti_service import GraphitiService

@pytest.fixture
def mock_neo4j_driver():
    """模拟 Neo4j 驱动"""
    with patch('neo4j.GraphDatabase.driver') as mock:
        driver = Mock()
        mock.return_value = driver
        yield driver

@pytest.fixture
def graphiti_service(mock_neo4j_driver):
    """创建 GraphitiService 实例"""
    return GraphitiService(uri="bolt://localhost:7687", user="neo4j", password="test")

class TestGraphitiService:
    """GraphitiService 测试类"""

    @pytest.mark.asyncio
    async def test_ingest_data(self, graphiti_service, mock_neo4j_driver):
        # Arrange
        task_id = "test_task_123"

        # Act
        result = await graphiti_service.ingest_data(task_id)

        # Assert
        assert result["status"] == "success"
        mock_neo4j_driver.execute_query.assert_called()

    def test_invalid_connection(self):
        with pytest.raises(ConnectionError):
            GraphitiService(uri="bolt://invalid:7687", user="neo4j", password="test")
```

#### 运行测试

```bash
# 运行所有测试
pytest python_service/ -v

# 运行特定文件
pytest python_service/tests/test_graphiti_service.py

# 运行特定测试
pytest python_service/tests/test_graphiti_service.py::TestGraphitiService::test_ingest_data

# 生成覆盖率报告
pytest python_service/ --cov=python_service --cov-report=html

# 并行运行
pytest python_service/ -n auto
```

### 5.3 集成测试

```bash
# 创建测试镜像
bash tests/create_android_image.sh

# 运行集成测试
bash tests/test_e01_http.sh

# Python 集成测试
pytest python_service/tests/integration/
```

---

## 6. 性能分析

### 6.1 使用 perf

```bash
# 记录性能数据
perf record -g ./build/forensic_analyzer large_image.dd

# 分析报告
perf report

# 火焰图
perf script | ./FlameGraph/stackcollapse-perf.pl | ./FlameGraph/flamegraph.pl > flamegraph.svg
```

### 6.2 使用 FlameGraph

```bash
# 安装 FlameGraph
git clone https://github.com/brendangregg/FlameGraph.git

# 生成火焰图
perf script | FlameGraph/stackcollapse-perf.pl | FlameGraph/flamegraph.pl > output.svg
```

### 6.3 内存分析

```bash
# 使用 massif（Valgrind 工具）
valgrind --tool=massif \
         --massif-out-file=massif.out \
         ./build/forensic_analyzer image.dd

# 分析结果
ms_print massif.out
```

---

## 7. CI/CD 配置

### 7.1 GitHub Actions

创建 `.github/workflows/ci.yml`：

```yaml
name: CI

on:
  push:
    branches: [ main, dev ]
  pull_request:
    branches: [ main ]

jobs:
  cpp-tests:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v3

      - name: 安装依赖
        run: |
          sudo apt-get update
          sudo apt-get install -y build-essential cmake \
            libsqlite3-dev libewf-dev libhivex-dev \
            libboost-system-dev nlohmann-json3-dev

      - name: 编译
        run: |
          mkdir build && cd build
          cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=ON
          make -j$(nproc)

      - name: 运行测试
        run: |
          cd build
          ctest --output-on-failure

  python-tests:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v3

      - name: 设置 Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: 安装依赖
        run: |
          python -m pip install --upgrade pip
          pip install -r python_service/httpserver/requirements.txt
          pip install pytest pytest-cov

      - name: 运行测试
        run: |
          pytest python_service/ --cov=python_service --cov-report=xml

      - name: 上传覆盖率
        uses: codecov/codecov-action@v3
```

---

## 8. 开发工作流

### 8.1 功能开发流程

```bash
# 1. 更新主分支
git checkout main
git pull origin main

# 2. 创建功能分支
git checkout -b feature/new-analyzer

# 3. 开发和测试
# ... 编写代码 ...
./scripts/format_code.sh
cd build && ctest

# 4. 提交更改
git add .
git commit -m "feat(analyzer): 添加新的分析器"

# 5. 推送到远程
git push origin feature/new-analyzer

# 6. 创建 Pull Request
# 在 GitHub 上创建 PR
```

### 8.2 代码审查清单

- [ ] 代码符合项目风格指南
- [ ] 添加了单元测试
- [ ] 所有测试通过
- [ ] 更新了相关文档
- [ ] 没有内存泄漏（Valgrind 检查）
- [ ] 没有编译警告
- [ ] 提交信息符合 Conventional Commits
- [ ] 更新了 CHANGELOG（如需要）

---

## 9. 常用命令

### 9.1 编译相关

```bash
# Debug 构建
cmake -B build-debug -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTS=ON
cmake --build build-debug -j$(nproc)

# Release 构建
cmake -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release -j$(nproc)

# 清理重建
rm -rf build && mkdir build && cd build && cmake .. && make -j$(nproc)
```

### 9.2 测试相关

```bash
# C++ 测试
cd build && ctest -V

# Python 测试
pytest python_service/ -v --tb=short

# 集成测试
./tests/run_all_integration_tests.sh
```

### 9.3 代码质量

```bash
# 格式化代码
./scripts/format_code.sh

# 静态分析
clang-tidy src/**/*.cpp -- -Isrc/
cppcheck src/ --enable=all --inconclusive

# Python 代码检查
flake8 python_service/
mypy python_service/
pylint python_service/
```

---

## 10. 故障排查

### 10.1 编译错误

**问题**: undefined reference to `TSK functions`

**解决**:
```bash
# 确保 TSK 已安装
ldconfig -p | grep libtsk

# 重新编译 TSK
cd sleuthkit-4.14.0
make clean && ./configure && make && sudo make install
sudo ldconfig
```

### 10.2 测试失败

**问题**: 测试超时或挂起

**解决**:
```bash
# 使用 GDB 附加到测试进程
gdb -p <test_pid>

# 或使用 pytest 的 --timeout 选项
pytest python_service/ --timeout=10
```

---

## 相关文档

- **[安装指南](Installation.md)** - 依赖和编译步骤
- **[常见任务](CommonTasks.md)** - 添加分析器、路由等
- **[架构总览](../architecture/Overview.md)** - 系统架构

---

**最后更新**: 2026-03-11
**维护者**: ymj68520
