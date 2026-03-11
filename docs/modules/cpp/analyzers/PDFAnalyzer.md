# PDFAnalyzer 模块文档

## 1. 模块背景

### 业务背景

PDF（Portable Document Format）是取证分析中最常见的文档格式之一。调查人员需要从 PDF 文件中提取：
- 文本内容用于关键词搜索
- 元数据（作者、创建时间、标题）用于时间线分析
- 页数统计用于文件分类

### 技术背景

**Poppler 库**：
- 开源的 PDF 渲染库
- 支持 PDF 1.0 到 2.0
- 跨平台兼容（Windows/Linux/macOS）

## 2. 模块功能

### 核心功能

#### 文本提取
```cpp
std::string text = PDFAnalyzer::extractText("document.pdf");
```
- 逐页提取文本
- UTF-8 编码支持
- 多语言支持

#### 元数据提取
```cpp
PDFMetadata meta = PDFAnalyzer::extractMetadata("document.pdf");
```

提取的元数据：
- 标题 (Title)
- 作者 (Author)
- 主题 (Subject)
- 关键词 (Keywords)
- 创建应用 (Creator)
- 生成器 (Producer)
- 页数 (Page Count)
- 加密状态 (Encrypted)

#### LLM 报告生成
```cpp
bool success = PDFAnalyzer::createLLMReport("document.pdf", "report.md");
```

生成 Markdown 格式报告，包含：
- 文件信息（路径、大小、时间戳）
- 元数据表格
- 分页内容

## 3. 模块使用的库

| 库名称 | 版本 | 用途 |
|--------|------|------|
| **Poppler-C++** | latest | PDF 解析核心 |

## 4. 模块实现方式

### 核心类

```cpp
class PDFAnalyzer {
public:
    // 文本提取
    static std::string extractText(const std::string& pdfPath);

    // 元数据提取
    static PDFMetadata extractMetadata(const std::string& pdfPath);

    // LLM 报告生成
    static bool createLLMReport(const std::string& pdfPath,
                                 const std::string& outputPath);

private:
    static std::string cleanText(const std::string& text);
};
```

### PDFMetadata 结构

```cpp
struct PDFMetadata {
    std::string title;
    std::string author;
    std::string subject;
    std::string keywords;
    std::string creator;
    std::string producer;
    int pageCount = 0;
    std::vector<std::string> permissions;
    int64_t creationTime = 0;
    int64_t modificationTime = 0;
    bool isEncrypted = false;
};
```

## 5. API 调用

### C++ API

```cpp
#include "analyzers/PDFAnalyzer/PDFAnalyzer.h"

// 文本提取
std::string text = PDFAnalyzer::extractText("/path/to/document.pdf");
std::cout << text << std::endl;

// 元数据提取
PDFMetadata meta = PDFAnalyzer::extractMetadata("/path/to/document.pdf");
std::cout << "标题: " << meta.title << std::endl;
std::cout << "作者: " << meta.author << std::endl;
std::cout << "页数: " << meta.pageCount << std::endl;

// LLM 报告
std::string reportPath = "/tmp/report.md";
bool success = PDFAnalyzer::createLLMReport("/path/to/document.pdf", reportPath);
```

### 集成到 LLM 分析

```cpp
// FileAnalyzer.cpp 自动检测 PDF 文件
if (extension == ".pdf") {
    LOG_DEBUG("使用 PDFAnalyzer");
    content = PDFAnalyzer::extractText(filePath);
}
```

## 6. 二次开发

### 添加图像提取功能

```cpp
class PDFAnalyzer {
public:
    // 新增：图像提取
    static std::vector<std::pair<int, std::string>> extractImages(
        const std::string& pdfPath,
        const std::string& outputDir);
};
```

## 7. 其他

### 限制

- ❌ 不支持扫描 PDF（需要 OCR）
- ❌ 不支持加密 PDF（需要密码）
- ❌ 不提取图像（元数据仅）

### 测试

```bash
cd build
./test_pdf_analyzer
```

### 相关模块

- **[FileAnalyzer](../../integration/LLMIntegration/FileAnalyzer.md)** - LLM 文件分析集成

---

**最后更新**: 2026-03-11
**维护者**: ymj68520
