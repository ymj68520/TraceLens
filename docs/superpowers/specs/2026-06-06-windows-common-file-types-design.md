# Windows 常见文件类型 Extractor 扩展设计

**日期**: 2026-06-06
**状态**: 已批准
**目标**: 覆盖日常 Windows 使用中常见但尚未支持的文件类型

## 背景

当前 extractor 系统已覆盖 200+ 扩展名，但在日常 Windows 使用场景中仍有以下常见类型缺失：
- 数据交换格式（CSV, JSON, XML）
- Microsoft 补充格式（OneNote, XPS, Publisher, Visio, Project）
- Adobe 设计格式（PSD, AI, INDD）
- 电子书/字幕/3D/科学数据格式（EPUB, MOBI, SRT, OBJ, HDF5, DICOM）

## 架构方案

采用**方案 A：按功能分文件**，创建 4 个新 extractor 文件，每类一个。与现有项目 extractor 文件组织结构一致。

## 新增文件

### 1. `data_exchange.py` — 结构化数据格式

| Extractor 类 | 格式 | 依赖 |
|-------------|------|------|
| CsvExtractor | .csv, .tsv | csv（内置） |
| JsonDataExtractor | .json, .jsonl, .ndjson | json（内置） |
| XmlDataExtractor | .xml, .xsl, .xslt, .svg (冲突, 不映射svg), .xaml, .config (冲突) | defusedxml |

**设计细节**：

**CsvExtractor**:
- 使用 Python `csv` 模块，自动检测分隔符（逗号/制表符/分号）
- 输出：文件名、大小、行列数、列名列表、数据类型推断
- 大文件采样：超过 1000 行只预览前 100 行，以 markdown 表格呈现
- 数值列提供基本统计（min/max/mean，如果适用）

**JsonDataExtractor**:
- 使用 `json` 模块，支持标准 JSON 和 JSON Lines (.jsonl/.ndjson)
- 输出：顶层结构类型（object/array）、键列表、嵌套深度、数组长度
- 大文件采样：超过 500 键只展示结构摘要
- JSONL 格式逐行解析，统计行数和字段分布

**XmlDataExtractor**:
- 使用 `defusedxml`（XXE 防护）
- 输出：根元素名、命名空间、子元素树、属性列表、元素计数
- 文本内容提取（截断到合理长度）
- 注意：`.svg` 已有 SvgExtractor，不重复映射

### 2. `microsoft_extended.py` — 微软补充格式

| Extractor 类 | 格式 | 依赖 |
|-------------|------|------|
| OneNoteExtractor | .one, .onetoc2 | olefile |
| XpsExtractor | .xps, .oxps | zipfile + defusedxml |
| PublisherExtractor | （不映射 .pub，见冲突说明） | olefile |
| VisioExtractor | .vsdx, .vsdm | zipfile + defusedxml |
| ProjectExtractor | .mpp, .mpt | olefile (fallback) |
| EtlExtractor | .etl | 手动二进制解析 |
| MscExtractor | .msc | defusedxml |
| UrlExtractor | .url | configparser（内置） |

**设计细节**：

**OneNoteExtractor**:
- OneNote 文件基于 OLE2 格式，使用 `olefile` 读取流结构
- 提取：笔记本 GUID、创建/修改时间、节（section）列表、页面标题（如果可解析）
- Fallback：如果 `olefile` 无法解析，输出 OLE 流列表作为元数据

**XpsExtractor**:
- XPS 本质是 ZIP 包，内含 FixedDocument 和 FixedPage XML
- 解压后解析 `FixedDocumentSequence`、`FixedDocument`、`FixedPage`
- 提取：文档属性、页面数、每页文本内容

**PublisherExtractor**:
- Publisher (.pub) 是 OLE2 格式
- 使用 `olefile` 提取文档属性（标题、作者、页数）和 OLE 流结构
- 由于 .pub 格式文档有限，以流列表和属性为主

**VisioExtractor**:
- VSDX/VSDM 是 ZIP 包，内含 Visio XML 格式
- 解压后解析 `visio/document.xml`（属性）和 `visio/pages/*.xml`（页面和形状）
- 提取：文档属性、页面列表、形状列表（名称、类型）、连接关系

**ProjectExtractor**:
- MPP 格式是 OLE2 容器，Python 库支持有限
- 使用 `olefile` 提取流结构和可用的项目属性
- Fallback：输出 OLE 流列表

**EtlExtractor**:
- ETL 是 Windows 事件跟踪二进制格式
- 尝试使用 `python-etw` 库解析（如果可用）
- Fallback：解析 ETL 文件头，提取基本信息（版本、创建时间、缓冲区大小）
- 输出：事件统计、事件类型分布、时间范围

**MscExtractor**:
- MSC 是 MMC 控制台文件，本质是 XML
- 使用 `defusedxml` 解析
- 提取：控制台名称、snap-in 列表、视图配置

**UrlExtractor**:
- `.url` 文件是纯文本 INI 格式（Windows Internet Shortcut）
- 使用 `configparser` 解析 `[InternetShortcut]` section
- 提取：URL、标题（Title）、图标文件（IconFile）、最后访问时间（Visited）

### 3. `adobe_formats.py` — Adobe 设计格式

| Extractor 类 | 格式 | 依赖 |
|-------------|------|------|
| PsdExtractor | .psd | psd-tools（可选）或手动解析 |
| AiExtractor | .ai | 手动解析（PDF/EPS） |
| InddExtractor | .indd | olefile |

**设计细节**：

**PsdExtractor**:
- PSD 有规范的二进制结构：File Header → Color Mode → Image Resources → Layer/Mask → Image Data
- 优先使用 `psd-tools` 库（如果安装），可提取完整图层信息
- Fallback：手动解析 File Header（魔数 `8BPS`、版本、通道数、尺寸、颜色模式）和 Image Resources（缩略图、分辨率、ICC 配置）
- 输出：图像尺寸、颜色模式、位深度、分辨率、图层列表（名称、可见性、混合模式）

**AiExtractor**:
- AI 文件通常是 PDF 或 EPS 格式
- 检测文件头：`%PDF` → 按 PDF 提取元数据；`%!PS` → 按 EPS 提取
- PDF 元数据：使用 `pypdf` 或手动解析 PDF 对象
- EPS 元数据：解析 PostScript DSC 注释
- 输出：格式类型、元数据（标题、作者、创建日期）、页面尺寸

**InddExtractor**:
- INDD 是 OLE2 容器格式
- 使用 `olefile` 提取流结构和文档属性
- 输出：OLE 流列表、可识别的文档属性

### 4. `ebook_science.py` — 电子书 / 字幕 / 3D / 科学数据

| Extractor 类 | 格式 | 依赖 |
|-------------|------|------|
| EpubExtractor | .epub | zipfile + defusedxml |
| MobiExtractor | .mobi, .azw, .azw3 | 手动二进制解析 |
| SrtExtractor | .srt | re（内置） |
| AssVttExtractor | .ass, .ssa, .vtt | re（内置） |
| ObjExtractor | .obj | 手动文本解析 |
| StlExtractor | .stl | 手动解析（文本+二进制） |
| Hdf5Extractor | .hdf5, .h5, .hdf | h5py |
| DicomExtractor | .dcm, .dicom | pydicom |

**设计细节**：

**EpubExtractor**:
- EPUB 是 ZIP 包，内含 `META-INF/container.xml` → `content.opf` → 章节 XHTML
- 解析 OPF 元数据：书名、作者、出版商、ISBN、语言、描述、日期
- 解析 `toc.ncx` 或 `nav.xhtml` 获取目录结构
- 输出：书名、作者、出版信息、章节数和列表、描述

**MobiExtractor**:
- MOBI 格式有固定的二进制 header 结构
- 解析 PalmDOC header → MOBI header → EXTH header
- EXTH 记录包含：书名(100)、作者(101)、出版商(102)、描述(103)、ISBN(104) 等
- 输出：书名、作者、出版商、描述、MOBI 版本、记录数

**SrtExtractor**:
- SRT 是纯文本格式：序号 → 时间码 → 文本 → 空行
- 正则解析：`(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n([\s\S]*?)(?=\n\n|\Z)`
- 输出：字幕条数、时间范围（首条-末条）、总时长、前 20 条预览

**AssVttExtractor**:
- ASS/SSA：解析 `[Script Info]`、`[V4+ Styles]`、`[Events]` section
- VTT：解析 `WEBVTT` header 和 cue blocks
- 输出：格式、样式列表、事件数、前 20 条预览

**ObjExtractor**:
- OBJ 是纯文本 3D 格式，逐行解析
- 指令：`v`（顶点）、`vt`（纹理坐标）、`vn`（法线）、`f`（面）、`mtllib`（材质库）、`o`/`g`（对象/组）
- 输出：顶点数、面数、法线数、材质列表、对象列表、包围盒

**StlExtractor**:
- 检测格式：ASCII STL 以 `solid` 开头；二进制 STL 前 80 字节 header + 4 字节三角形数
- ASCII：逐行解析 `facet normal`、`vertex`、`endfacet`
- 二进制：struct 解析 header 和三角形数据
- 输出：三角形数、格式（ASCII/二进制）、表面积估算、包围盒

**Hdf5Extractor**:
- 使用 `h5py` 库读取 HDF5 文件结构
- 遍历组（group）和数据集（dataset），记录树形结构
- 输出：根组属性、数据集列表（名称、形状、dtype）、组层次结构、文件属性

**DicomExtractor**:
- 使用 `pydicom` 库解析 DICOM 医学影像
- 提取：患者信息（ID、姓名，可选脱敏）、检查信息（日期、类型、描述）、设备信息（制造商、型号）、图像参数（尺寸、像素间距、位深度）
- 输出：标准化的 DICOM 标签信息

## 路由配置更新

`extractor_mapping.json` 新增映射：

```json
{
  "csv": "CsvExtractor",
  "tsv": "CsvExtractor",
  "tab": "CsvExtractor",
  "json": "JsonDataExtractor",
  "jsonl": "JsonDataExtractor",
  "ndjson": "JsonDataExtractor",
  "xml": "XmlDataExtractor",
  "xsl": "XmlDataExtractor",
  "xslt": "XmlDataExtractor",
  "xaml": "XmlDataExtractor",
  "one": "OneNoteExtractor",
  "onetoc2": "OneNoteExtractor",
  "xps": "XpsExtractor",
  "oxps": "XpsExtractor",
  "vsdx": "VisioExtractor",
  "vsdm": "VisioExtractor",
  "mpp": "ProjectExtractor",
  "mpt": "ProjectExtractor",
  "etl": "EtlExtractor",
  "msc": "MscExtractor",
  "url": "UrlExtractor",
  "psd": "PsdExtractor",
  "ai": "AiExtractor",
  "indd": "InddExtractor",
  "epub": "EpubExtractor",
  "mobi": "MobiExtractor",
  "azw": "MobiExtractor",
  "azw3": "MobiExtractor",
  "srt": "SrtExtractor",
  "ass": "AssVttExtractor",
  "ssa": "AssVttExtractor",
  "vtt": "AssVttExtractor",
  "obj": "ObjExtractor",
  "stl": "StlExtractor",
  "hdf5": "Hdf5Extractor",
  "h5": "Hdf5Extractor",
  "hdf": "Hdf5Extractor",
  "dcm": "DicomExtractor",
  "dicom": "DicomExtractor"
}
```

### 冲突处理

- **`.pub` 冲突**：`.pub` 当前映射到 TextExtractor（SSH/GPG 公钥文件）。Publisher 文件是 OLE2 二进制格式，公钥文件是纯文本。解决方案：不映射 `.pub` 到 PublisherExtractor，保持 TextExtractor。PublisherExtractor 仅作为类存在，不自动路由。
- `.svg` → 保持现有 SvgExtractor，不映射到 XmlDataExtractor
- `.config` → 保持现有 IniExtractor，不映射到 XmlDataExtractor

### TextExtractor 重映射

以下扩展名当前映射到 TextExtractor（纯文本提取），需要移除并映射到新的专用 extractor（结构化解析）：

| 扩展名 | TextExtractor → 新 Extractor |
|--------|------------------------------|
| .json, .jsonl, .ndjson | JsonDataExtractor |
| .xml | XmlDataExtractor |
| .csv, .tsv, .tab | CsvExtractor |
| .srt | SrtExtractor |
| .ass, .ssa, .vtt | AssVttExtractor |

需要从 TextExtractor 的扩展名数组中移除这些扩展名。

## 依赖更新

`requirements.txt` 新增：
```
h5py>=3.10.0
pydicom>=2.4.0
```

已有依赖（无需新增）：olefile, defusedxml, psd-tools（可选）

## Markdown 输出风格

遵循现有 extractor 风格：
- `# Title` 标题包含文件名
- `**Key:** Value` 元数据行
- `## Section` 分节
- `| Col | Col |` 表格
- 大文件采样策略：限制行数/条目数，添加 `*(Showing first N of M ...)*` 说明
- 错误处理：`Error: ...` 格式

## 测试策略

- 每个 extractor 的 `test_<name>_nonexistent_file` 测试（不存在文件返回错误消息）
- 每个 extractor 的基本功能测试（使用真实或构造的测试文件）
- 测试 import 和 registry 注册
