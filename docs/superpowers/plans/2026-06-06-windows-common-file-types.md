# Windows 常见文件类型 Extractor 扩展实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 覆盖日常 Windows 使用中常见但尚未支持的文件类型（CSV, JSON, XML, OneNote, XPS, Visio, Project, PSD, AI, EPUB, MOBI, SRT, OBJ, STL, HDF5, DICOM 等）

**Architecture:** 创建 4 个新 extractor 文件（data_exchange.py, microsoft_extended.py, adobe_formats.py, ebook_science.py），共 15 个 extractor 类。更新 extractor_mapping.json 路由配置，从 MarkitdownExtractor 移除已覆盖的扩展名。

**Tech Stack:** Python 内置 csv/json/configparser/re/struct/zipfile, defusedxml, olefile, h5py, pydicom, psd-tools（可选）

---

## 文件结构

### 新建文件
- `python_service/httpserver/services/extractors/data_exchange.py` — CsvExtractor, JsonDataExtractor, XmlDataExtractor
- `python_service/httpserver/services/extractors/microsoft_extended.py` — OneNoteExtractor, XpsExtractor, PublisherExtractor, VisioExtractor, ProjectExtractor, EtlExtractor, MscExtractor, UrlExtractor
- `python_service/httpserver/services/extractors/adobe_formats.py` — PsdExtractor, AiExtractor, InddExtractor
- `python_service/httpserver/services/extractors/ebook_science.py` — EpubExtractor, MobiExtractor, SrtExtractor, AssVttExtractor, ObjExtractor, StlExtractor, Hdf5Extractor, DicomExtractor

### 修改文件
- `python_service/config/extractor_mapping.json` — 添加新路由，从 MarkitdownExtractor 移除已覆盖扩展名
- `python_service/httpserver/requirements.txt` — 添加 h5py, pydicom

---

### Task 1: data_exchange.py — CsvExtractor

**Files:**
- Create: `python_service/httpserver/services/extractors/data_exchange.py`
- Test: `python_service/tests/unit/test_forensic_extractors.py` (追加)

- [ ] **Step 1: 创建 data_exchange.py 骨架和 CsvExtractor**

```python
"""Data exchange format extractors: CSV, JSON, XML."""
import csv
import io
import json
import logging
import os
from collections import Counter, defaultdict

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    else: return f"{size_bytes/1024/1024:.2f} MB"


def _infer_type(value: str) -> str:
    """Infer the data type of a string value."""
    if not value or value.strip() == '':
        return 'empty'
    v = value.strip()
    try:
        int(v)
        return 'integer'
    except ValueError:
        pass
    try:
        float(v)
        return 'float'
    except ValueError:
        pass
    if v.lower() in ('true', 'false', 'yes', 'no'):
        return 'boolean'
    if len(v) == 10 and v[4] == '-' and v[7] == '-':
        return 'date'
    if len(v) >= 19 and v[4] == '-' and v[7] == '-' and 'T' in v:
        return 'datetime'
    return 'string'


@register_extractor
class CsvExtractor(BaseExtractor):
    """Structured parser for CSV/TSV data files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            file_size = os.path.getsize(file_path)
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                sample = f.read(8192)

            # Detect delimiter
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=',\t;|')
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = ','

            del_name = {',': 'comma', '\t': 'tab', ';': 'semicolon', '|': 'pipe'}.get(delimiter, repr(delimiter))

            # Read all rows
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                reader = csv.reader(f, delimiter=delimiter)
                rows = list(reader)

            if not rows:
                return f"# CSV Data: `{os.path.basename(file_path)}`\n\n**Error:** Empty file."

            headers = rows[0] if rows else []
            data_rows = rows[1:] if len(rows) > 1 else []
            num_cols = len(headers)

            result = [f"# CSV Data: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(file_size)}")
            result.append(f"**Delimiter:** {del_name} (`{delimiter}`)")
            result.append(f"**Columns:** {num_cols}")
            result.append(f"**Data Rows:** {len(data_rows)}")
            result.append("")

            # Column info with type inference
            result.append("## Columns")
            result.append("| # | Name | Inferred Type |")
            result.append("| --- | --- | --- |")
            col_types = []
            for i, h in enumerate(headers):
                types = Counter()
                sample_count = min(len(data_rows), 100)
                for row in data_rows[:sample_count]:
                    if i < len(row):
                        types[_infer_type(row[i])] += 1
                main_type = types.most_common(1)[0][0] if types else 'unknown'
                col_types.append(main_type)
                result.append(f"| {i+1} | {h[:50]} | {main_type} |")
            result.append("")

            # Numeric stats
            numeric_cols = [(i, h) for i, (h, t) in enumerate(zip(headers, col_types)) if t in ('integer', 'float')]
            if numeric_cols:
                result.append("## Numeric Statistics")
                result.append("| Column | Min | Max | Mean |")
                result.append("| --- | --- | --- | --- |")
                for ci, name in numeric_cols[:10]:
                    values = []
                    for row in data_rows:
                        if ci < len(row):
                            try:
                                values.append(float(row[ci]))
                            except ValueError:
                                pass
                    if values:
                        result.append(f"| {name[:30]} | {min(values):.2f} | {max(values):.2f} | {sum(values)/len(values):.2f} |")
                result.append("")

            # Data preview
            preview_count = min(len(data_rows), 100)
            result.append(f"## Data Preview")
            if len(data_rows) > preview_count:
                result.append(f"*(Showing first {preview_count} of {len(data_rows)} rows)*")
            result.append("")

            # Table header
            h_line = "| " + " | ".join(h[:30] for h in headers[:15]) + " |"
            sep_line = "| " + " | ".join("---" for _ in headers[:15]) + " |"
            result.append(h_line)
            result.append(sep_line)
            for row in data_rows[:preview_count]:
                cells = [row[i][:30] if i < len(row) else '' for i in range(min(num_cols, 15))]
                result.append("| " + " | ".join(cells) + " |")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse CSV file: {e}"
```

- [ ] **Step 2: 运行 import 测试**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
python3 -c "from python_service.httpserver.services.extractors.data_exchange import CsvExtractor; print('CsvExtractor imported OK')"
```

- [ ] **Step 3: 提交**

```bash
git add python_service/httpserver/services/extractors/data_exchange.py
git commit -m "feat(extractors): add CsvExtractor in data_exchange.py"
```

---

### Task 2: data_exchange.py — JsonDataExtractor

**Files:**
- Modify: `python_service/httpserver/services/extractors/data_exchange.py`

- [ ] **Step 1: 添加 JsonDataExtractor**

在 `data_exchange.py` 末尾追加：

```python
@register_extractor
class JsonDataExtractor(BaseExtractor):
    """Structured parser for JSON and JSON Lines files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            file_size = os.path.getsize(file_path)
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                first_chars = f.read(100).strip()

            # Detect JSON Lines format
            is_jsonl = False
            if first_chars and not first_chars[0] in ('{', '['):
                is_jsonl = True
            else:
                # Check if file extension suggests JSONL
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ('.jsonl', '.ndjson'):
                    is_jsonl = True

            if is_jsonl:
                return await self._parse_jsonl(file_path, file_size)
            else:
                return await self._parse_json(file_path, file_size)
        except Exception as e:
            return f"Error: Failed to parse JSON file: {e}"

    async def _parse_json(self, file_path: str, file_size: int) -> str:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            data = json.load(f)

        result = [f"# JSON Data: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(file_size)}")

        if isinstance(data, dict):
            result.append(f"**Type:** Object")
            result.append(f"**Top-level Keys:** {len(data)}")
            result.append("")
            result.append("## Structure")
            result.append("| Key | Type | Value Preview |")
            result.append("| --- | --- | --- |")
            for i, (k, v) in enumerate(list(data.items())[:50]):
                vtype = type(v).__name__
                if isinstance(v, (dict, list)):
                    preview = f"({len(v)} items)" if isinstance(v, list) else f"({len(v)} keys)"
                else:
                    preview = str(v)[:80]
                result.append(f"| {k[:50]} | {vtype} | {preview} |")
            if len(data) > 50:
                result.append(f"\n*(Showing first 50 of {len(data)} keys)*")
        elif isinstance(data, list):
            result.append(f"**Type:** Array")
            result.append(f"**Items:** {len(data)}")
            result.append("")
            if data and isinstance(data[0], dict):
                result.append("## Item Structure")
                keys = list(data[0].keys())[:20]
                result.append("| Key | Type | Sample Value |")
                result.append("| --- | --- | --- |")
                for k in keys:
                    v = data[0][k]
                    vtype = type(v).__name__
                    preview = str(v)[:80] if not isinstance(v, (dict, list)) else f"({type(v).__name__})"
                    result.append(f"| {k[:50]} | {vtype} | {preview} |")
                result.append("")
                result.append(f"## First Items (up to 10)")
                for i, item in enumerate(data[:10]):
                    result.append(f"\n### Item {i}")
                    for k, v in list(item.items())[:10]:
                        result.append(f"- **{k}:** {str(v)[:100]}")
            else:
                result.append("## Values")
                for i, v in enumerate(data[:20]):
                    result.append(f"- `{str(v)[:100]}`")
        else:
            result.append(f"**Type:** {type(data).__name__}")
            result.append(f"**Value:** `{str(data)[:500]}`")

        return "\n".join(result)

    async def _parse_jsonl(self, file_path: str, file_size: int) -> str:
        lines = []
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        result = [f"# JSON Lines Data: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(file_size)}")
        result.append(f"**Records:** {len(lines)}")
        result.append("")

        if not lines:
            return "\n".join(result)

        # Field distribution
        field_counts = Counter()
        field_types = defaultdict(lambda: Counter())
        for obj in lines:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    field_counts[k] += 1
                    field_types[k][type(v).__name__] += 1

        if field_counts:
            result.append("## Field Distribution")
            result.append("| Field | Occurrences | Primary Type |")
            result.append("| --- | --- | --- |")
            for field, count in field_counts.most_common(30):
                ptype = field_types[field].most_common(1)[0][0]
                result.append(f"| {field[:50]} | {count}/{len(lines)} | {ptype} |")
            result.append("")

        # Sample records
        result.append("## Sample Records")
        for i, obj in enumerate(lines[:5]):
            result.append(f"\n### Record {i+1}")
            if isinstance(obj, dict):
                for k, v in list(obj.items())[:10]:
                    result.append(f"- **{k}:** {str(v)[:100]}")
            else:
                result.append(f"- `{str(obj)[:200]}`")

        return "\n".join(result)
```

- [ ] **Step 2: 测试 import**

```bash
python3 -c "from python_service.httpserver.services.extractors.data_exchange import JsonDataExtractor; print('JsonDataExtractor imported OK')"
```

- [ ] **Step 3: 提交**

```bash
git add python_service/httpserver/services/extractors/data_exchange.py
git commit -m "feat(extractors): add JsonDataExtractor in data_exchange.py"
```

---

### Task 3: data_exchange.py — XmlDataExtractor

**Files:**
- Modify: `python_service/httpserver/services/extractors/data_exchange.py`

- [ ] **Step 1: 添加 XmlDataExtractor**

在 `data_exchange.py` 末尾追加：

```python
@register_extractor
class XmlDataExtractor(BaseExtractor):
    """Structured parser for XML data files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from defusedxml import ElementTree as ET
        except ImportError:
            return "Error: defusedxml library is not installed."

        try:
            file_size = os.path.getsize(file_path)
            tree = ET.parse(file_path)
            root = tree.getroot()

            result = [f"# XML Data: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(file_size)}")

            # Namespace handling
            ns = ''
            if '}' in root.tag:
                ns = root.tag.split('}')[0] + '}'
                result.append(f"**Namespace:** {ns.strip('{}')}")

            result.append(f"**Root Element:** {root.tag.replace(ns, '')}")
            result.append(f"**Root Attributes:** {len(root.attrib)}")
            result.append("")

            # Root attributes
            if root.attrib:
                result.append("## Root Attributes")
                result.append("| Name | Value |")
                result.append("| --- | --- |")
                for k, v in root.attrib.items():
                    result.append(f"| {k} | {v[:100]} |")
                result.append("")

            # Element tree structure
            result.append("## Element Structure")
            self._render_element(root, result, ns, depth=0, max_depth=3)

            # Text content summary
            texts = []
            for elem in root.iter():
                if elem.text and elem.text.strip():
                    texts.append(elem.text.strip()[:200])
            if texts:
                result.append("")
                result.append("## Text Content Summary")
                result.append(f"**Elements with text:** {len(texts)}")
                result.append("")
                result.append("```")
                for t in texts[:20]:
                    result.append(t)
                if len(texts) > 20:
                    result.append(f"... ({len(texts) - 20} more)")
                result.append("```")

            return "\n".join(result)
        except ET.ParseError as e:
            return f"Error: XML parse error: {e}"
        except Exception as e:
            return f"Error: Failed to parse XML file: {e}"

    def _render_element(self, elem, result, ns, depth, max_depth):
        if depth > max_depth:
            return
        indent = "  " * depth
        tag = elem.tag.replace(ns, '')
        child_count = len(elem)
        attr_count = len(elem.attrib)

        info_parts = []
        if child_count:
            info_parts.append(f"{child_count} children")
        if attr_count:
            info_parts.append(f"{attr_count} attrs")
        if elem.text and elem.text.strip():
            text_preview = elem.text.strip()[:50]
            info_parts.append(f"text: `{text_preview}`")

        info = f" ({', '.join(info_parts)})" if info_parts else ""
        result.append(f"{indent}- **{tag}**{info}")

        for child in elem:
            self._render_element(child, result, ns, depth + 1, max_depth)
```

- [ ] **Step 2: 测试 import**

```bash
python3 -c "from python_service.httpserver.services.extractors.data_exchange import XmlDataExtractor; print('XmlDataExtractor imported OK')"
```

- [ ] **Step 3: 提交**

```bash
git add python_service/httpserver/services/extractors/data_exchange.py
git commit -m "feat(extractors): add XmlDataExtractor in data_exchange.py"
```

---

### Task 4: microsoft_extended.py — UrlExtractor, MscExtractor, XpsExtractor

**Files:**
- Create: `python_service/httpserver/services/extractors/microsoft_extended.py`

- [ ] **Step 1: 创建 microsoft_extended.py 骨架和简单 extractors**

```python
"""Microsoft supplementary format extractors: OneNote, XPS, Publisher, Visio, Project, ETL, MSC, URL."""
import configparser
import logging
import os
import re
import struct
import zipfile
from collections import defaultdict

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    else: return f"{size_bytes/1024/1024:.2f} MB"


@register_extractor
class UrlExtractor(BaseExtractor):
    """Parser for Windows Internet Shortcut (.url) files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            config = configparser.ConfigParser()
            config.read(file_path, encoding='utf-8')

            result = [f"# Internet Shortcut: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            if config.has_section('InternetShortcut'):
                url = config.get('InternetShortcut', 'URL', fallback='N/A')
                result.append(f"**URL:** {url}")

                if config.has_option('InternetShortcut', 'IconFile'):
                    result.append(f"**Icon File:** {config.get('InternetShortcut', 'IconFile')}")
                if config.has_option('InternetShortcut', 'IconIndex'):
                    result.append(f"**Icon Index:** {config.get('InternetShortcut', 'IconIndex')}")
                if config.has_option('InternetShortcut', 'Visited'):
                    result.append(f"**Last Visited:** {config.get('InternetShortcut', 'Visited')}")
                if config.has_option('InternetShortcut', 'HotKey'):
                    result.append(f"**Hotkey:** {config.get('InternetShortcut', 'HotKey')}")
            elif config.has_section('InternetShortcut.A]:
                # Some .url files use different section names
                url = config.get('InternetShortcut.A', 'URL', fallback='N/A')
                result.append(f"**URL:** {url}")
            else:
                # Fallback: read as plain text
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                result.append("## Content")
                result.append(f"```\n{content[:2000]}\n```")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse URL shortcut: {e}"


@register_extractor
class MscExtractor(BaseExtractor):
    """Parser for Microsoft Management Console (.msc) files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from defusedxml import ElementTree as ET
        except ImportError:
            return "Error: defusedxml library is not installed."

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            result = [f"# MMC Console: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            # MMC version
            ver = root.attrib.get('Version', 'N/A')
            result.append(f"**MMC Version:** {ver}")
            result.append("")

            # VisualAttributes
            va = root.find('.//VisualAttributes')
            if va is not None:
                result.append("## Visual Attributes")
                for child in va:
                    tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    result.append(f"- **{tag}:** {child.text or child.attrib}")

            # Snap-Ins
            snapins = root.findall('.//SnapIn')
            if snapins:
                result.append("")
                result.append(f"## Snap-Ins ({len(snapins)})")
                result.append("| Name | CLSID |")
                result.append("| --- | --- |")
                for si in snapins:
                    name = si.attrib.get('Name', 'N/A')
                    clsid = si.attrib.get('CLSID', 'N/A')
                    result.append(f"| {name[:50]} | {clsid} |")

            # Favorites
            favorites = root.findall('.//Favorite')
            if favorites:
                result.append("")
                result.append(f"## Favorites ({len(favorites)})")
                for fav in favorites[:20]:
                    name = fav.attrib.get('Name', 'N/A')
                    result.append(f"- {name}")

            return "\n".join(result)
        except ET.ParseError as e:
            return f"Error: XML parse error: {e}"
        except Exception as e:
            return f"Error: Failed to parse MSC file: {e}"


@register_extractor
class XpsExtractor(BaseExtractor):
    """Parser for XPS/OXPS documents (ZIP-based XML format)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from defusedxml import ElementTree as ET
        except ImportError:
            return "Error: defusedxml library is not installed."

        try:
            if not zipfile.is_zipfile(file_path):
                return "Error: Not a valid XPS/OXPS file (not a ZIP archive)."

            result = [f"# XPS Document: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

            with zipfile.ZipFile(file_path, 'r') as zf:
                names = zf.namelist()
                result.append(f"**Entries:** {len(names)}")
                result.append("")

                # Find FixedDocumentSequence
                fds_files = [n for n in names if 'FixedDocumentSequence' in n]
                fd_files = [n for n in names if n.endswith('.fpage') or 'FixedPage' in n or n.endswith('.xml')]

                # Document properties
                props = [n for n in names if 'Properties' in n or 'CoreProperties' in n or n.endswith('.rels')]
                if props:
                    result.append("## Document Properties")
                    for p in props[:5]:
                        try:
                            with zf.open(p) as pf:
                                content = pf.read(4096).decode('utf-8', errors='replace')
                            result.append(f"### {p}")
                            result.append(f"```\n{content[:1000]}\n```")
                        except Exception:
                            pass
                    result.append("")

                # Pages
                page_files = sorted([n for n in names if n.endswith('.fpage')])
                if not page_files:
                    page_files = sorted([n for n in names if 'Page' in n and n.endswith('.xml')])

                result.append(f"## Pages ({len(page_files)})")
                result.append("")

                for pf in page_files[:20]:
                    try:
                        with zf.open(pf) as f:
                            content = f.read()
                        page_tree = ET.fromstring(content)
                        # Extract text from Glyphs elements
                        texts = []
                        for glyph in page_tree.iter():
                            tag = glyph.tag.split('}')[-1] if '}' in glyph.tag else glyph.tag
                            if tag == 'Glyphs' and glyph.attrib.get('UnicodeString'):
                                texts.append(glyph.attrib['UnicodeString'])
                        page_name = os.path.basename(pf)
                        result.append(f"### {page_name}")
                        if texts:
                            text_content = ' '.join(texts[:50])
                            result.append(f"> {text_content[:500]}")
                        else:
                            result.append("*(No text content extracted)*")
                        result.append("")
                    except Exception:
                        result.append(f"### {os.path.basename(pf)}")
                        result.append("*(Parse error)*")
                        result.append("")

            return "\n".join(result)
        except zipfile.BadZipFile:
            return "Error: Not a valid XPS/OXPS file (corrupt ZIP)."
        except Exception as e:
            return f"Error: Failed to parse XPS file: {e}"
```

- [ ] **Step 2: 测试 import**

```bash
python3 -c "from python_service.httpserver.services.extractors.microsoft_extended import UrlExtractor, MscExtractor, XpsExtractor; print('OK')"
```

- [ ] **Step 3: 提交**

```bash
git add python_service/httpserver/services/extractors/microsoft_extended.py
git commit -m "feat(extractors): add UrlExtractor, MscExtractor, XpsExtractor in microsoft_extended.py"
```

---

### Task 5: microsoft_extended.py — OneNoteExtractor, PublisherExtractor, VisioExtractor, ProjectExtractor

**Files:**
- Modify: `python_service/httpserver/services/extractors/microsoft_extended.py`

- [ ] **Step 1: 添加 OLE2 和 ZIP-based extractors**

在 `microsoft_extended.py` 末尾追加：

```python
@register_extractor
class OneNoteExtractor(BaseExtractor):
    """Parser for OneNote notebooks (.one, .onetoc2) using OLE2 structure."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import olefile
        except ImportError:
            return "Error: olefile library is not installed."

        try:
            if not olefile.isOleFile(file_path):
                # Try as a raw binary and extract what we can
                return self._parse_raw(file_path)

            ole = olefile.OleFileIO(file_path)
            result = [f"# OneNote Notebook: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            # List streams
            streams = ole.listdir()
            result.append(f"## OLE Streams ({len(streams)})")
            result.append("| Stream Path | Size |")
            result.append("| --- | --- |")
            for s in streams[:50]:
                path = '/'.join(s)
                try:
                    size = ole.get_size(path)
                    result.append(f"| {path[:80]} | {_format_size(size)} |")
                except Exception:
                    result.append(f"| {path[:80]} | N/A |")
            if len(streams) > 50:
                result.append(f"\n*(Showing first 50 of {len(streams)} streams)*")

            ole.close()
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse OneNote file: {e}"

    def _parse_raw(self, file_path: str) -> str:
        """Fallback: read raw binary and extract readable strings."""
        result = [f"# OneNote File (raw): `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append("")
        result.append("*(OLE2 parsing failed, showing raw metadata)*")
        return "\n".join(result)


@register_extractor
class PublisherExtractor(BaseExtractor):
    """Parser for Microsoft Publisher (.pub) using OLE2 structure."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import olefile
        except ImportError:
            return "Error: olefile library is not installed."

        try:
            if not olefile.isOleFile(file_path):
                return "Error: Not a valid Publisher file (not OLE2 format)."

            ole = olefile.OleFileIO(file_path)
            result = [f"# Publisher Document: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            # Metadata
            meta = ole.get_metadata()
            if meta.title:
                result.append(f"**Title:** {meta.title}")
            if meta.author:
                result.append(f"**Author:** {meta.author}")
            if meta.num_pages:
                result.append(f"**Pages:** {meta.num_pages}")
            if meta.create_time:
                result.append(f"**Created:** {meta.create_time}")
            if meta.last_saved_time:
                result.append(f"**Modified:** {meta.last_saved_time}")
            result.append("")

            # Streams
            streams = ole.listdir()
            result.append(f"## OLE Streams ({len(streams)})")
            result.append("| Stream Path | Size |")
            result.append("| --- | --- |")
            for s in streams[:50]:
                path = '/'.join(s)
                try:
                    size = ole.get_size(path)
                    result.append(f"| {path[:80]} | {_format_size(size)} |")
                except Exception:
                    result.append(f"| {path[:80]} | N/A |")

            ole.close()
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Publisher file: {e}"


@register_extractor
class VisioExtractor(BaseExtractor):
    """Parser for Visio drawings (.vsdx, .vsdm) using ZIP-based XML format."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from defusedxml import ElementTree as ET
        except ImportError:
            return "Error: defusedxml library is not installed."

        try:
            if not zipfile.is_zipfile(file_path):
                return "Error: Not a valid Visio file (not a ZIP archive)."

            result = [f"# Visio Drawing: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

            with zipfile.ZipFile(file_path, 'r') as zf:
                names = zf.namelist()
                result.append(f"**Entries:** {len(names)}")
                result.append("")

                # Document properties from docProps
                for prop_file in ['docProps/core.xml', 'docProps/app.xml']:
                    if prop_file in names:
                        try:
                            with zf.open(prop_file) as f:
                                tree = ET.parse(f)
                            root = tree.getroot()
                            ns = {'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
                                  'dc': 'http://purl.org/dc/elements/1.1/',
                                  'dcterms': 'http://purl.org/dc/terms/'}
                            for elem in root.iter():
                                tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                                if elem.text and elem.text.strip() and tag in ('title', 'creator', 'created', 'modified', 'Pages', 'Slides'):
                                    result.append(f"**{tag.title()}:** {elem.text.strip()[:100]}")
                        except Exception:
                            pass
                    result.append("")

                # Pages
                page_files = sorted([n for n in names if 'pages/page' in n.lower() or 'pages/page' in n])
                if page_files:
                    result.append(f"## Pages ({len(page_files)})")
                    for pf in page_files[:10]:
                        try:
                            with zf.open(pf) as f:
                                page_tree = ET.parse(f)
                            page_root = page_tree.getroot()
                            # Find Shape elements
                            shapes = []
                            for elem in page_root.iter():
                                tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                                if tag == 'Shape':
                                    name = elem.attrib.get('Name', '')
                                    id_val = elem.attrib.get('ID', '')
                                    shapes.append(f"{name} (ID:{id_val})")
                            result.append(f"\n### {os.path.basename(pf)}")
                            if shapes:
                                result.append(f"**Shapes:** {len(shapes)}")
                                for s in shapes[:20]:
                                    result.append(f"- {s}")
                            else:
                                result.append("*(No shapes found)*")
                        except Exception:
                            result.append(f"\n### {os.path.basename(pf)}")
                            result.append("*(Parse error)*")
                else:
                    result.append("## Pages")
                    result.append("*(No page files found in archive)*")

            return "\n".join(result)
        except zipfile.BadZipFile:
            return "Error: Not a valid Visio file (corrupt ZIP)."
        except Exception as e:
            return f"Error: Failed to parse Visio file: {e}"


@register_extractor
class ProjectExtractor(BaseExtractor):
    """Parser for Microsoft Project (.mpp, .mpt) using OLE2 structure."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import olefile
        except ImportError:
            return "Error: olefile library is not installed."

        try:
            if not olefile.isOleFile(file_path):
                return "Error: Not a valid Project file (not OLE2 format)."

            ole = olefile.OleFileIO(file_path)
            result = [f"# Project File: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            # Metadata
            meta = ole.get_metadata()
            if meta.title:
                result.append(f"**Title:** {meta.title}")
            if meta.author:
                result.append(f"**Author:** {meta.author}")
            if meta.num_pages:
                result.append(f"**Pages:** {meta.num_pages}")
            if meta.create_time:
                result.append(f"**Created:** {meta.create_time}")
            if meta.last_saved_time:
                result.append(f"**Modified:** {meta.last_saved_time}")
            result.append("")

            # Streams
            streams = ole.listdir()
            result.append(f"## OLE Streams ({len(streams)})")
            result.append("| Stream Path | Size |")
            result.append("| --- | --- |")
            for s in streams[:50]:
                path = '/'.join(s)
                try:
                    size = ole.get_size(path)
                    result.append(f"| {path[:80]} | {_format_size(size)} |")
                except Exception:
                    result.append(f"| {path[:80]} | N/A |")

            ole.close()
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Project file: {e}"
```

- [ ] **Step 2: 测试 import**

```bash
python3 -c "from python_service.httpserver.services.extractors.microsoft_extended import OneNoteExtractor, PublisherExtractor, VisioExtractor, ProjectExtractor; print('OK')"
```

- [ ] **Step 3: 提交**

```bash
git add python_service/httpserver/services/extractors/microsoft_extended.py
git commit -m "feat(extractors): add OneNote, Publisher, Visio, Project extractors"
```

---

### Task 6: microsoft_extended.py — EtlExtractor

**Files:**
- Modify: `python_service/httpserver/services/extractors/microsoft_extended.py`

- [ ] **Step 1: 添加 EtlExtractor**

在 `microsoft_extended.py` 末尾追加：

```python
@register_extractor
class EtlExtractor(BaseExtractor):
    """Parser for Windows Event Trace Log (.etl) binary files."""

    ETL_MAGIC = b'\x00\x00\x00\x00'  # ETL files start with 4 zero bytes + signature

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            file_size = os.path.getsize(file_path)
            with open(file_path, 'rb') as f:
                header = f.read(512)

            result = [f"# Event Trace Log: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(file_size)}")
            result.append("")

            # Try python-etw first
            try:
                import python_etw
                return await self._parse_with_etw(file_path, file_size)
            except ImportError:
                pass

            # Fallback: parse ETL header manually
            # ETL header structure (simplified):
            # Offset 0: LoggerName (varies)
            # The header is complex; we extract what we can
            result.append("## Header Analysis")
            result.append(f"**First 32 bytes (hex):** `{header[:32].hex()}`")

            # Look for WMI/ETW markers
            if b'WindowsEventTrace' in header or b'ETW' in header:
                result.append("**Format:** Windows Event Trace (ETW)")

            # Count events by scanning for event markers
            # ETL events have a signature pattern
            event_count = 0
            with open(file_path, 'rb') as f:
                chunk_size = 65536
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    # Count potential event records (simplified heuristic)
                    # Real ETL parsing requires the full ETW parser
                    event_count += chunk.count(b'\x00\x00') // 100  # Very rough estimate

            result.append(f"**Estimated Events:** ~{event_count} (approximate)")
            result.append("")
            result.append("> **Note:** Full ETL parsing requires `python-etw` library. "
                         "Install with `pip install python-etw` for detailed event extraction.")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse ETL file: {e}"

    async def _parse_with_etw(self, file_path: str, file_size: int) -> str:
        """Parse using python-etw library if available."""
        result = [f"# Event Trace Log: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(file_size)}")
        result.append("")
        result.append("*(Full ETW parsing not yet implemented)*")
        return "\n".join(result)
```

- [ ] **Step 2: 测试 import**

```bash
python3 -c "from python_service.httpserver.services.extractors.microsoft_extended import EtlExtractor; print('OK')"
```

- [ ] **Step 3: 提交**

```bash
git add python_service/httpserver/services/extractors/microsoft_extended.py
git commit -m "feat(extractors): add EtlExtractor in microsoft_extended.py"
```

---

### Task 7: adobe_formats.py — PsdExtractor, AiExtractor, InddExtractor

**Files:**
- Create: `python_service/httpserver/services/extractors/adobe_formats.py`

- [ ] **Step 1: 创建 adobe_formats.py**

```python
"""Adobe design format extractors: PSD, AI, INDD."""
import logging
import os
import struct

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    else: return f"{size_bytes/1024/1024:.2f} MB"


# PSD color mode names
PSD_COLOR_MODES = {0: 'Bitmap', 1: 'Grayscale', 2: 'Indexed', 3: 'RGB', 4: 'CMYK', 7: 'Multichannel', 8: 'Duotone', 9: 'Lab'}


@register_extractor
class PsdExtractor(BaseExtractor):
    """Parser for Adobe Photoshop (.psd) files with manual binary parsing."""

    async def extract_to_markdown(self, file_path: str) -> str:
        # Try psd-tools first
        try:
            return await self._parse_with_psd_tools(file_path)
        except ImportError:
            pass
        except Exception:
            pass

        # Fallback: manual binary parsing
        return self._parse_manual(file_path)

    async def _parse_with_psd_tools(self, file_path: str) -> str:
        """Parse using psd-tools library."""
        from psd_tools import PSDImage

        psd = PSDImage.open(file_path)
        result = [f"# Photoshop Document: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Width:** {psd.width} px")
        result.append(f"**Height:** {psd.height} px")
        result.append(f"**Channels:** {psd.channels}")
        result.append(f"**Color Mode:** {PSD_COLOR_MODES.get(psd.color_mode, str(psd.color_mode))}")
        result.append(f"**Bit Depth:** {psd.depth} bits")
        result.append(f"**Layers:** {len(psd)}")
        result.append("")

        # Layer info
        if psd:
            result.append("## Layers")
            result.append("| Name | Visible | Opacity | Blend Mode |")
            result.append("| --- | --- | --- | --- |")
            for layer in psd[:50]:
                name = layer.name or '(unnamed)'
                visible = '✓' if layer.visible else '✗'
                opacity = f"{layer.opacity}%" if layer.opacity is not None else 'N/A'
                blend = layer.blend_mode.name if layer.blend_mode else 'Normal'
                result.append(f"| {name[:40]} | {visible} | {opacity} | {blend} |")
            if len(psd) > 50:
                result.append(f"\n*(Showing first 50 of {len(psd)} layers)*")

        return "\n".join(result)

    def _parse_manual(self, file_path: str) -> str:
        """Manual binary parsing of PSD header and image resources."""
        try:
            with open(file_path, 'rb') as f:
                # File Header (26 bytes)
                magic = f.read(4)
                if magic != b'8BPS':
                    return f"Error: Not a valid PSD file (magic: {magic})"

                version = struct.unpack('>H', f.read(2))[0]
                reserved = f.read(6)  # 6 bytes reserved
                channels = struct.unpack('>H', f.read(2))[0]
                height = struct.unpack('>I', f.read(4))[0]
                width = struct.unpack('>I', f.read(4))[0]
                depth = struct.unpack('>H', f.read(2))[0]
                color_mode = struct.unpack('>H', f.read(2))[0]

            result = [f"# Photoshop Document: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Version:** {version}")
            result.append(f"**Width:** {width} px")
            result.append(f"**Height:** {height} px")
            result.append(f"**Channels:** {channels}")
            result.append(f"**Color Mode:** {PSD_COLOR_MODES.get(color_mode, str(color_mode))}")
            result.append(f"**Bit Depth:** {depth} bits")
            result.append("")
            result.append("> **Note:** Install `psd-tools` for full layer extraction: `pip install psd-tools`")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse PSD file: {e}"


@register_extractor
class AiExtractor(BaseExtractor):
    """Parser for Adobe Illustrator (.ai) files (PDF or EPS format)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(20)

            if header.startswith(b'%PDF'):
                return self._parse_as_pdf(file_path)
            elif header.startswith(b'%!PS') or header.startswith(b'\xc5\xd0\xd3\xc6'):
                return self._parse_as_eps(file_path)
            else:
                return self._parse_generic(file_path, header)
        except Exception as e:
            return f"Error: Failed to parse AI file: {e}"

    def _parse_as_pdf(self, file_path: str) -> str:
        """Parse AI file as PDF to extract metadata."""
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            meta = reader.metadata

            result = [f"# Adobe Illustrator (PDF): `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Pages:** {len(reader.pages)}")
            result.append("")

            if meta:
                result.append("## Metadata")
                result.append(f"**Title:** {meta.title or 'N/A'}")
                result.append(f"**Author:** {meta.author or 'N/A'}")
                result.append(f"**Creator:** {meta.creator or 'N/A'}")
                result.append(f"**Producer:** {meta.producer or 'N/A'}")
                result.append(f"**Creation Date:** {meta.creation_date or 'N/A'}")

            return "\n".join(result)
        except ImportError:
            return self._parse_generic(file_path, b'%PDF')
        except Exception as e:
            return f"Error: Failed to parse AI/PDF file: {e}"

    def _parse_as_eps(self, file_path: str) -> str:
        """Parse AI file as EPS to extract DSC comments."""
        try:
            result = [f"# Adobe Illustrator (EPS): `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()[:50]

            result.append("")
            result.append("## DSC Comments")
            for line in lines:
                line = line.strip()
                if line.startswith('%%'):
                    result.append(f"- {line[:100]}")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse AI/EPS file: {e}"

    def _parse_generic(self, file_path: str, header: bytes) -> str:
        result = [f"# Adobe Illustrator: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Header (hex):** `{header[:16].hex()}`")
        result.append("")
        result.append("*(Could not determine format — install pypdf for PDF mode)*")
        return "\n".join(result)


@register_extractor
class InddExtractor(BaseExtractor):
    """Parser for Adobe InDesign (.indd) using OLE2 structure."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import olefile
        except ImportError:
            return "Error: olefile library is not installed."

        try:
            if not olefile.isOleFile(file_path):
                return self._parse_raw(file_path)

            ole = olefile.OleFileIO(file_path)
            result = [f"# InDesign Document: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            # Metadata
            meta = ole.get_metadata()
            if meta.title:
                result.append(f"**Title:** {meta.title}")
            if meta.author:
                result.append(f"**Author:** {meta.author}")
            if meta.num_pages:
                result.append(f"**Pages:** {meta.num_pages}")
            if meta.create_time:
                result.append(f"**Created:** {meta.create_time}")
            if meta.last_saved_time:
                result.append(f"**Modified:** {meta.last_saved_time}")
            result.append("")

            # Streams
            streams = ole.listdir()
            result.append(f"## OLE Streams ({len(streams)})")
            result.append("| Stream Path | Size |")
            result.append("| --- | --- |")
            for s in streams[:50]:
                path = '/'.join(s)
                try:
                    size = ole.get_size(path)
                    result.append(f"| {path[:80]} | {_format_size(size)} |")
                except Exception:
                    result.append(f"| {path[:80]} | N/A |")

            ole.close()
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse InDesign file: {e}"

    def _parse_raw(self, file_path: str) -> str:
        result = [f"# InDesign Document: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append("")
        result.append("*(Not a valid OLE2 file)*")
        return "\n".join(result)
```

- [ ] **Step 2: 测试 import**

```bash
python3 -c "from python_service.httpserver.services.extractors.adobe_formats import PsdExtractor, AiExtractor, InddExtractor; print('OK')"
```

- [ ] **Step 3: 提交**

```bash
git add python_service/httpserver/services/extractors/adobe_formats.py
git commit -m "feat(extractors): add PsdExtractor, AiExtractor, InddExtractor in adobe_formats.py"
```

---

### Task 8: ebook_science.py — SrtExtractor, AssVttExtractor, ObjExtractor, StlExtractor

**Files:**
- Create: `python_service/httpserver/services/extractors/ebook_science.py`

- [ ] **Step 1: 创建 ebook_science.py 骨架和纯文本格式 extractors**

```python
"""eBook, subtitle, 3D, and scientific data extractors."""
import logging
import os
import re
import struct

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    else: return f"{size_bytes/1024/1024:.2f} MB"


@register_extractor
class SrtExtractor(BaseExtractor):
    """Parser for SubRip subtitle files (.srt)."""

    SRT_PATTERN = re.compile(
        r'(\d+)\s*\n'
        r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n'
        r'([\s\S]*?)(?=\n\n|\n\d+\n|\Z)',
        re.MULTILINE
    )

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

            matches = self.SRT_PATTERN.findall(content)

            result = [f"# SubRip Subtitles: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Subtitle Entries:** {len(matches)}")

            if matches:
                first_time = matches[0][1]
                last_time = matches[-1][2]
                result.append(f"**Time Range:** {first_time} → {last_time}")
            result.append("")

            # Preview
            result.append("## Subtitle Preview")
            for i, (num, start, end, text) in enumerate(matches[:20]):
                text_clean = text.strip().replace('\n', ' ')
                result.append(f"**[{num}]** `{start}` → `{end}`")
                result.append(f"> {text_clean[:200]}")
                result.append("")
            if len(matches) > 20:
                result.append(f"*(Showing first 20 of {len(matches)} entries)*")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse SRT file: {e}"


@register_extractor
class AssVttExtractor(BaseExtractor):
    """Parser for ASS/SSA and WebVTT subtitle files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

            ext = os.path.splitext(file_path)[1].lower()
            if ext in ('.ass', '.ssa'):
                return self._parse_ass(content, file_path)
            else:
                return self._parse_vtt(content, file_path)
        except Exception as e:
            return f"Error: Failed to parse subtitle file: {e}"

    def _parse_ass(self, content: str, file_path: str) -> str:
        """Parse ASS/SSA format."""
        result = [f"# ASS/SSA Subtitles: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append("")

        # Script Info
        info_match = re.search(r'\[Script Info\]\s*\n([\s\S]*?)(?=\n\[|\Z)', content)
        if info_match:
            result.append("## Script Info")
            for line in info_match.group(1).strip().split('\n'):
                line = line.strip()
                if line and not line.startswith(';') and ':' in line:
                    key, _, val = line.partition(':')
                    result.append(f"**{key.strip()}:** {val.strip()}")
            result.append("")

        # Styles
        style_match = re.search(r'\[V4\+? Styles\]\s*\n([\s\S]*?)(?=\n\[|\Z)', content)
        if style_match:
            lines = style_match.group(1).strip().split('\n')
            format_line = [l for l in lines if l.startswith('Format:')]
            style_lines = [l for l in lines if l.startswith('Style:')]
            if style_lines:
                result.append(f"## Styles ({len(style_lines)})")
                for s in style_lines[:10]:
                    parts = s.split(',')
                    name = parts[0].replace('Style:', '').strip() if parts else 'N/A'
                    result.append(f"- {name}")
                result.append("")

        # Events
        event_match = re.search(r'\[Events\]\s*\n([\s\S]*?)(?=\n\[|\Z)', content)
        if event_match:
            lines = event_match.group(1).strip().split('\n')
            event_lines = [l for l in lines if l.startswith('Dialogue:')]
            result.append(f"## Events ({len(event_lines)})")
            result.append("")
            for ev in event_lines[:20]:
                parts = ev.split(',', 9)
                if len(parts) >= 10:
                    start = parts[1].strip()
                    end = parts[2].strip()
                    text = parts[9].strip().replace('\\N', ' ').replace('{', '').replace('}', '')
                    result.append(f"`{start}` → `{end}`: {text[:150]}")
            if len(event_lines) > 20:
                result.append(f"\n*(Showing first 20 of {len(event_lines)} events)*")

        return "\n".join(result)

    def _parse_vtt(self, content: str, file_path: str) -> str:
        """Parse WebVTT format."""
        result = [f"# WebVTT Subtitles: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append("")

        # Parse cues
        cue_pattern = re.compile(
            r'(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})\s*\n([\s\S]*?)(?=\n\n|\Z)',
            re.MULTILINE
        )
        cues = cue_pattern.findall(content)

        result.append(f"**Cues:** {len(cues)}")
        if cues:
            result.append(f"**Time Range:** {cues[0][0]} → {cues[-1][1]}")
        result.append("")

        result.append("## Cue Preview")
        for i, (start, end, text) in enumerate(cues[:20]):
            text_clean = text.strip().replace('\n', ' ')
            result.append(f"`{start}` → `{end}`: {text_clean[:200]}")
        if len(cues) > 20:
            result.append(f"\n*(Showing first 20 of {len(cues)} cues)*")

        return "\n".join(result)


@register_extractor
class ObjExtractor(BaseExtractor):
    """Parser for Wavefront OBJ 3D model files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            vertices = []
            normals = []
            texcoords = []
            faces = []
            objects = []
            materials = set()
            current_object = None

            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if not parts:
                    continue

                cmd = parts[0]
                if cmd == 'v' and len(parts) >= 4:
                    try:
                        vertices.append(tuple(float(x) for x in parts[1:4]))
                    except ValueError:
                        pass
                elif cmd == 'vn' and len(parts) >= 4:
                    try:
                        normals.append(tuple(float(x) for x in parts[1:4]))
                    except ValueError:
                        pass
                elif cmd == 'vt' and len(parts) >= 3:
                    texcoords.append(parts[1:3])
                elif cmd == 'f':
                    faces.append(parts[1:])
                elif cmd == 'o':
                    current_object = parts[1] if len(parts) > 1 else 'unnamed'
                    objects.append(current_object)
                elif cmd == 'g' and len(parts) > 1:
                    objects.append(parts[1])
                elif cmd == 'mtllib':
                    materials.add(parts[1] if len(parts) > 1 else '')
                elif cmd == 'usemtl':
                    materials.add(parts[1] if len(parts) > 1 else '')

            result = [f"# 3D Model (OBJ): `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Vertices:** {len(vertices)}")
            result.append(f"**Faces:** {len(faces)}")
            result.append(f"**Normals:** {len(normals)}")
            result.append(f"**Texture Coords:** {len(texcoords)}")
            result.append(f"**Objects/Groups:** {len(objects)}")
            result.append(f"**Materials:** {len(materials)}")
            result.append("")

            # Bounding box
            if vertices:
                xs = [v[0] for v in vertices]
                ys = [v[1] for v in vertices]
                zs = [v[2] for v in vertices]
                result.append("## Bounding Box")
                result.append(f"**X:** {min(xs):.4f} → {max(xs):.4f} (range: {max(xs)-min(xs):.4f})")
                result.append(f"**Y:** {min(ys):.4f} → {max(ys):.4f} (range: {max(ys)-min(ys):.4f})")
                result.append(f"**Z:** {min(zs):.4f} → {max(zs):.4f} (range: {max(zs)-min(zs):.4f})")
                result.append("")

            # Objects list
            if objects:
                result.append("## Objects")
                for obj in objects[:30]:
                    result.append(f"- {obj}")

            # Material list
            if materials:
                result.append("")
                result.append("## Materials")
                for mat in sorted(materials):
                    if mat:
                        result.append(f"- {mat}")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse OBJ file: {e}"


@register_extractor
class StlExtractor(BaseExtractor):
    """Parser for STL 3D model files (ASCII and binary)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            file_size = os.path.getsize(file_path)
            with open(file_path, 'rb') as f:
                header = f.read(80)

            # Detect format: ASCII starts with "solid"
            is_ascii = header.startswith(b'solid') and b'facet' in header

            if is_ascii:
                return self._parse_ascii(file_path, file_size)
            else:
                return self._parse_binary(file_path, file_size, header)
        except Exception as e:
            return f"Error: Failed to parse STL file: {e}"

    def _parse_ascii(self, file_path: str, file_size: int) -> str:
        """Parse ASCII STL."""
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        facets = re.findall(r'facet normal\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)', content)
        vertices = re.findall(r'vertex\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)', content)

        result = [f"# 3D Model (STL ASCII): `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(file_size)}")
        result.append(f"**Triangles:** {len(facets)}")
        result.append(f"**Vertices:** {len(vertices)}")
        result.append("")

        if vertices:
            xs = [float(v[0]) for v in vertices]
            ys = [float(v[1]) for v in vertices]
            zs = [float(v[2]) for v in vertices]
            result.append("## Bounding Box")
            result.append(f"**X:** {min(xs):.4f} → {max(xs):.4f}")
            result.append(f"**Y:** {min(ys):.4f} → {max(ys):.4f}")
            result.append(f"**Z:** {min(zs):.4f} → {max(zs):.4f}")

        return "\n".join(result)

    def _parse_binary(self, file_path: str, file_size: int, header: bytes) -> str:
        """Parse binary STL."""
        with open(file_path, 'rb') as f:
            f.seek(80)
            tri_count_bytes = f.read(4)
            if len(tri_count_bytes) < 4:
                return f"Error: STL file too small."
            tri_count = struct.unpack('<I', tri_count_bytes)[0]

        result = [f"# 3D Model (STL Binary): `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(file_size)}")
        result.append(f"**Triangles:** {tri_count}")
        result.append(f"**Header:** `{header[:40].decode('ascii', errors='replace').strip()}`")
        result.append("")

        # Validate: binary STL = 80 (header) + 4 (count) + tri_count * 50 (12+12+12+12+2 bytes per triangle)
        expected_size = 80 + 4 + tri_count * 50
        if abs(expected_size - file_size) > 100:
            result.append(f"**Warning:** Expected size {expected_size}, actual {file_size}")

        return "\n".join(result)
```

- [ ] **Step 2: 测试 import**

```bash
python3 -c "from python_service.httpserver.services.extractors.ebook_science import SrtExtractor, AssVttExtractor, ObjExtractor, StlExtractor; print('OK')"
```

- [ ] **Step 3: 提交**

```bash
git add python_service/httpserver/services/extractors/ebook_science.py
git commit -m "feat(extractors): add SrtExtractor, AssVttExtractor, ObjExtractor, StlExtractor"
```

---

### Task 9: ebook_science.py — EpubExtractor, MobiExtractor

**Files:**
- Modify: `python_service/httpserver/services/extractors/ebook_science.py`

- [ ] **Step 1: 添加 EpubExtractor 和 MobiExtractor**

在 `ebook_science.py` 末尾追加：

```python
@register_extractor
class EpubExtractor(BaseExtractor):
    """Parser for EPUB ebook files (ZIP-based XML format)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import zipfile
            from defusedxml import ElementTree as ET
        except ImportError:
            return "Error: defusedxml library is not installed."

        try:
            if not zipfile.is_zipfile(file_path):
                return "Error: Not a valid EPUB file (not a ZIP archive)."

            result = [f"# EPUB Book: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

            with zipfile.ZipFile(file_path, 'r') as zf:
                names = zf.namelist()
                result.append(f"**Entries:** {len(names)}")
                result.append("")

                # Find container.xml to locate OPF
                opf_path = None
                if 'META-INF/container.xml' in names:
                    try:
                        with zf.open('META-INF/container.xml') as f:
                            container = ET.parse(f)
                        root = container.getroot()
                        for elem in root.iter():
                            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                            if tag == 'rootfile':
                                opf_path = elem.attrib.get('full-path')
                                break
                    except Exception:
                        pass

                if not opf_path:
                    # Try to find OPF by extension
                    opf_files = [n for n in names if n.endswith('.opf')]
                    opf_path = opf_files[0] if opf_files else None

                if opf_path and opf_path in names:
                    try:
                        with zf.open(opf_path) as f:
                            opf_tree = ET.parse(f)
                        opf_root = opf_root = opf_tree.getroot()

                        # Extract metadata
                        ns = {'dc': 'http://purl.org/dc/elements/1.1/',
                              'opf': 'http://www.idpf.org/2007/opf'}

                        metadata = {}
                        for elem in opf_root.iter():
                            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                            if tag in ('title', 'creator', 'publisher', 'language', 'date', 'description', 'identifier'):
                                if elem.text:
                                    metadata[tag] = elem.text.strip()

                        if metadata:
                            result.append("## Book Metadata")
                            for k, v in metadata.items():
                                result.append(f"**{k.title()}:** {v[:200]}")
                            result.append("")

                        # Spine (reading order)
                        spine = []
                        for elem in opf_root.iter():
                            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                            if tag == 'itemref':
                                spine.append(elem.attrib.get('idref', ''))

                        if spine:
                            result.append(f"## Spine ({len(spine)} items)")
                            for i, item in enumerate(spine[:30]):
                                result.append(f"{i+1}. {item}")
                            if len(spine) > 30:
                                result.append(f"\n*(Showing first 30 of {len(spine)} items)*")
                            result.append("")

                        # Manifest
                        manifest = []
                        for elem in opf_root.iter():
                            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                            if tag == 'item':
                                href = elem.attrib.get('href', '')
                                media_type = elem.attrib.get('media-type', '')
                                manifest.append((href, media_type))

                        if manifest:
                            result.append(f"## Manifest ({len(manifest)} items)")
                            result.append("| File | Media Type |")
                            result.append("| --- | --- |")
                            for href, mt in manifest[:30]:
                                result.append(f"| {href[:60]} | {mt} |")
                            if len(manifest) > 30:
                                result.append(f"\n*(Showing first 30 of {len(manifest)} items)*")
                    except Exception as e:
                        result.append(f"*(OPF parse error: {e})*")

                # TOC (toc.ncx)
                toc_path = next((n for n in names if n.endswith('toc.ncx')), None)
                if toc_path:
                    try:
                        with zf.open(toc_path) as f:
                            toc_tree = ET.parse(f)
                        result.append("")
                        result.append("## Table of Contents")
                        for nav in toc_tree.iter():
                            tag = nav.tag.split('}')[-1] if '}' in nav.tag else nav.tag
                            if tag == 'navLabel':
                                text_elem = nav.find('{http://www.daisy.org/z3986/2005/ncx/}text')
                                if text_elem is None:
                                    text_elem = nav.find('text')
                                if text_elem is not None and text_elem.text:
                                    result.append(f"- {text_elem.text[:100]}")
                    except Exception:
                        pass

            return "\n".join(result)
        except zipfile.BadZipFile:
            return "Error: Not a valid EPUB file (corrupt ZIP)."
        except Exception as e:
            return f"Error: Failed to parse EPUB file: {e}"


@register_extractor
class MobiExtractor(BaseExtractor):
    """Parser for MOBI/AZW ebook files (binary format)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            file_size = os.path.getsize(file_path)
            with open(file_path, 'rb') as f:
                data = f.read(min(file_size, 1024 * 1024))  # Read up to 1MB

            # PalmDOC header: 78 bytes
            if len(data) < 78:
                return "Error: File too small to be a valid MOBI file."

            # Check compression type at offset 0
            compression = struct.unpack('>H', data[0:2])[0]

            # MOBI header starts at offset 78 (after PalmDOC header + record 0 header)
            # Actually, MOBI header is at the start of record 0
            # PalmDOC header is 16 bytes, then record entries

            # Try to find MOBI magic
            mobi_magic_pos = data.find(b'MOBI')
            if mobi_magic_pos == -1:
                return self._parse_raw_mobi(file_path, file_size, data)

            # MOBI header starts at mobi_magic_pos
            pos = mobi_magic_pos
            mobi_len = struct.unpack('>I', data[pos+4:pos+8])[0]
            mobi_type = struct.unpack('>I', data[pos+8:pos+12])[0]
            text_encoding = struct.unpack('>I', data[pos+12:pos+16])[0]
            unique_id = struct.unpack('>I', data[pos+16:pos+20])[0]
            file_version = struct.unpack('>I', data[pos+20:pos+24])[0]

            # EXTH header
            exth_flag = struct.unpack('>I', data[pos+28:pos+32])[0]
            has_exth = (exth_flag & 0x40) != 0

            result = [f"# MOBI Book: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(file_size)}")
            result.append(f"**MOBI Type:** {mobi_type}")
            result.append(f"**Text Encoding:** {'UTF-8' if text_encoding == 65001 else f'CP{text_encoding}'}")
            result.append(f"**File Version:** {file_version}")
            result.append("")

            # Parse EXTH records
            if has_exth:
                exth_start = mobi_magic_pos + mobi_len
                if exth_start + 12 <= len(data):
                    exth_magic = data[exth_start:exth_start+4]
                    if exth_magic == b'EXTH':
                        exth_len = struct.unpack('>I', data[exth_start+4:exth_start+8])[0]
                        record_count = struct.unpack('>I', data[exth_start+8:exth_start+12])[0]

                        result.append(f"## EXTH Metadata ({record_count} records)")

                        # EXTH record types
                        EXTH_TYPES = {
                            100: 'Creator', 101: 'Publisher', 103: 'Description',
                            104: 'ISBN', 105: 'Subject', 106: 'Date',
                            108: 'Contributor', 109: 'Rights', 110: 'SubjectCode',
                            112: 'Language', 113: 'Links', 201: 'CoverOffset',
                            202: 'ThumbOffset', 203: 'HasFakeCover',
                            204: 'CreatorSoftware', 205: 'CreatorMajor',
                            401: 'ClippingLimit', 402: 'PublisherLimit',
                            501: 'CDType', 502: 'StartPosition',
                            503: 'EndPosition', 504: 'CheckBase'
                        }

                        pos_exth = exth_start + 12
                        for _ in range(min(record_count, 30)):
                            if pos_exth + 8 > len(data):
                                break
                            rec_type = struct.unpack('>I', data[pos_exth:pos_exth+4])[0]
                            rec_len = struct.unpack('>I', data[pos_exth+4:pos_exth+8])[0]
                            if rec_len < 8 or pos_exth + rec_len > len(data):
                                break
                            rec_data = data[pos_exth+8:pos_exth+rec_len]
                            type_name = EXTH_TYPES.get(rec_type, f'Type_{rec_type}')

                            if rec_type in (100, 101, 103, 104, 105, 106, 108, 109, 112):
                                try:
                                    value = rec_data.decode('utf-8', errors='replace')
                                except Exception:
                                    value = rec_data.hex()
                                result.append(f"**{type_name}:** {value[:200]}")
                            elif rec_type == 201:
                                result.append(f"**Cover Offset:** {struct.unpack('>I', rec_data[:4])[0]}")

                            pos_exth += rec_len

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse MOBI file: {e}"

    def _parse_raw_mobi(self, file_path: str, file_size: int, data: bytes) -> str:
        """Fallback when MOBI magic is not found."""
        result = [f"# MOBI File (raw): `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(file_size)}")
        result.append(f"**Header (hex):** `{data[:32].hex()}`")
        result.append("")
        result.append("*(Could not locate MOBI header — file may be corrupt or in a different format)*")
        return "\n".join(result)
```

- [ ] **Step 2: 测试 import**

```bash
python3 -c "from python_service.httpserver.services.extractors.ebook_science import EpubExtractor, MobiExtractor; print('OK')"
```

- [ ] **Step 3: 提交**

```bash
git add python_service/httpserver/services/extractors/ebook_science.py
git commit -m "feat(extractors): add EpubExtractor, MobiExtractor in ebook_science.py"
```

---

### Task 10: ebook_science.py — Hdf5Extractor, DicomExtractor

**Files:**
- Modify: `python_service/httpserver/services/extractors/ebook_science.py`

- [ ] **Step 1: 添加 Hdf5Extractor 和 DicomExtractor**

在 `ebook_science.py` 末尾追加：

```python
@register_extractor
class Hdf5Extractor(BaseExtractor):
    """Parser for HDF5 scientific data files (.hdf5, .h5, .hdf)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import h5py
        except ImportError:
            return "Error: h5py library is not installed. Install with: `pip install h5py`"

        try:
            result = [f"# HDF5 Data: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

            with h5py.File(file_path, 'r') as f:
                # File-level attributes
                if f.attrs:
                    result.append("")
                    result.append("## File Attributes")
                    result.append("| Key | Value |")
                    result.append("| --- | --- |")
                    for k, v in f.attrs.items():
                        val_str = str(v)[:100]
                        result.append(f"| {k} | {val_str} |")

                # Tree structure
                result.append("")
                result.append("## Structure")
                self._render_group(f, result, depth=0, max_depth=4)

                # Dataset summary
                datasets = []
                f.visititems(lambda name, obj: datasets.append((name, obj)) if isinstance(obj, h5py.Dataset) else None)
                if datasets:
                    result.append("")
                    result.append(f"## Datasets ({len(datasets)})")
                    result.append("| Path | Shape | Dtype |")
                    result.append("| --- | --- | --- |")
                    for name, ds in datasets[:30]:
                        result.append(f"| {name[:60]} | {ds.shape} | {ds.dtype} |")
                    if len(datasets) > 30:
                        result.append(f"\n*(Showing first 30 of {len(datasets)} datasets)*")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse HDF5 file: {e}"

    def _render_group(self, group, result, depth, max_depth):
        if depth > max_depth:
            return
        indent = "  " * depth
        for name, item in group.items():
            if isinstance(item, type(group)):  # Group
                child_count = len(item)
                result.append(f"{indent}- **{name}/** ({child_count} children)")
                self._render_group(item, result, depth + 1, max_depth)
            else:  # Dataset
                result.append(f"{indent}- **{name}** — shape:{item.shape}, dtype:{item.dtype}")


@register_extractor
class DicomExtractor(BaseExtractor):
    """Parser for DICOM medical imaging files (.dcm, .dicom)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import pydicom
        except ImportError:
            return "Error: pydicom library is not installed. Install with: `pip install pydicom`"

        try:
            ds = pydicom.dcmread(file_path, stop_before_pixels=True)

            result = [f"# DICOM Image: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            # Patient Info (with privacy note)
            result.append("## Patient Information")
            patient_id = getattr(ds, 'PatientID', 'N/A')
            patient_name = getattr(ds, 'PatientName', 'N/A')
            result.append(f"**Patient ID:** {patient_id}")
            result.append(f"**Patient Name:** {patient_name}")
            patient_birth = getattr(ds, 'PatientBirthDate', 'N/A')
            patient_sex = getattr(ds, 'PatientSex', 'N/A')
            result.append(f"**Birth Date:** {patient_birth}")
            result.append(f"**Sex:** {patient_sex}")
            result.append("")

            # Study Info
            result.append("## Study Information")
            study_date = getattr(ds, 'StudyDate', 'N/A')
            study_desc = getattr(ds, 'StudyDescription', 'N/A')
            modality = getattr(ds, 'Modality', 'N/A')
            result.append(f"**Study Date:** {study_date}")
            result.append(f"**Modality:** {modality}")
            result.append(f"**Description:** {study_desc}")
            result.append("")

            # Equipment
            result.append("## Equipment")
            manufacturer = getattr(ds, 'Manufacturer', 'N/A')
            model = getattr(ds, 'ManufacturerModelName', 'N/A')
            station = getattr(ds, 'StationName', 'N/A')
            result.append(f"**Manufacturer:** {manufacturer}")
            result.append(f"**Model:** {model}")
            result.append(f"**Station:** {station}")
            result.append("")

            # Image Parameters
            result.append("## Image Parameters")
            rows = getattr(ds, 'Rows', 'N/A')
            cols = getattr(ds, 'Columns', 'N/A')
            bits_stored = getattr(ds, 'BitsStored', 'N/A')
            pixel_spacing = getattr(ds, 'PixelSpacing', 'N/A')
            result.append(f"**Dimensions:** {cols} × {rows}")
            result.append(f"**Bits Stored:** {bits_stored}")
            result.append(f"**Pixel Spacing:** {pixel_spacing}")

            # Additional metadata
            slice_thickness = getattr(ds, 'SliceThickness', None)
            if slice_thickness:
                result.append(f"**Slice Thickness:** {slice_thickness} mm")

            kvp = getattr(ds, 'KVP', None)
            if kvp:
                result.append(f"**KVP:** {kvp} kV")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse DICOM file: {e}"
```

- [ ] **Step 2: 测试 import**

```bash
python3 -c "from python_service.httpserver.services.extractors.ebook_science import Hdf5Extractor, DicomExtractor; print('OK')"
```

- [ ] **Step 3: 提交**

```bash
git add python_service/httpserver/services/extractors/ebook_science.py
git commit -m "feat(extractors): add Hdf5Extractor, DicomExtractor in ebook_science.py"
```

---

### Task 11: 更新 extractor_mapping.json 和 requirements.txt

**Files:**
- Modify: `python_service/config/extractor_mapping.json`
- Modify: `python_service/httpserver/requirements.txt`

- [ ] **Step 1: 更新 extractor_mapping.json**

添加新 extractor 映射，从 MarkitdownExtractor 移除已覆盖的扩展名：

1. 从 `MarkitdownExtractor.extensions` 中移除: `.csv`, `.json`, `.xml`, `.epub`
2. 添加新条目：
   - `CsvExtractor`: [".csv", ".tsv", ".tab"]
   - `JsonDataExtractor`: [".json", ".jsonl", ".ndjson"]
   - `XmlDataExtractor`: [".xml", ".xsl", ".xslt", ".xaml"]
   - `OneNoteExtractor`: [".one", ".onetoc2"]
   - `XpsExtractor`: [".xps", ".oxps"]
   - `PublisherExtractor`: [] (不自动路由，.pub 保持 TextExtractor)
   - `VisioExtractor`: [".vsdx", ".vsdm"]
   - `ProjectExtractor`: [".mpp", ".mpt"]
   - `EtlExtractor`: [".etl"]
   - `MscExtractor`: [".msc"]
   - `UrlExtractor`: [".url"]
   - `PsdExtractor`: [".psd"]
   - `AiExtractor`: [".ai"]
   - `InddExtractor`: [".indd"]
   - `EpubExtractor`: [".epub"]
   - `MobiExtractor`: [".mobi", ".azw", ".azw3"]
   - `SrtExtractor`: [".srt"]
   - `AssVttExtractor`: [".ass", ".ssa", ".vtt"]
   - `ObjExtractor`: [".obj"]
   - `StlExtractor`: [".stl"]
   - `Hdf5Extractor`: [".hdf5", ".h5", ".hdf"]
   - `DicomExtractor`: [".dcm", ".dicom"]

- [ ] **Step 2: 更新 requirements.txt**

添加：
```
h5py>=3.10.0
pydicom>=2.4.0
```

- [ ] **Step 3: 验证 JSON 格式**

```bash
python3 -c "import json; json.load(open('python_service/config/extractor_mapping.json')); print('JSON valid')"
```

- [ ] **Step 4: 提交**

```bash
git add python_service/config/extractor_mapping.json python_service/httpserver/requirements.txt
git commit -m "feat: add routing for 15 new extractors and update requirements"
```

---

### Task 12: 单元测试

**Files:**
- Modify: `python_service/tests/unit/test_forensic_extractors.py`

- [ ] **Step 1: 追加新 extractor 测试**

在测试文件末尾追加：

```python
# --- Data Exchange Extractors ---

class TestCsvExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.data_exchange import CsvExtractor
        import asyncio
        extractor = CsvExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.csv')
        )
        assert 'Error' in result

    def test_basic_csv(self, tmp_path):
        from python_service.httpserver.services.extractors.data_exchange import CsvExtractor
        import asyncio
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\n", encoding='utf-8')
        extractor = CsvExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(csv_file))
        )
        assert 'CSV Data' in result
        assert 'name' in result
        assert 'Alice' in result


class TestJsonDataExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.data_exchange import JsonDataExtractor
        import asyncio
        extractor = JsonDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.json')
        )
        assert 'Error' in result

    def test_basic_json(self, tmp_path):
        from python_service.httpserver.services.extractors.data_exchange import JsonDataExtractor
        import asyncio
        json_file = tmp_path / "test.json"
        json_file.write_text('{"name": "test", "count": 42}', encoding='utf-8')
        extractor = JsonDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(json_file))
        )
        assert 'JSON Data' in result
        assert 'name' in result


class TestXmlDataExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.data_exchange import XmlDataExtractor
        import asyncio
        extractor = XmlDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.xml')
        )
        assert 'Error' in result

    def test_basic_xml(self, tmp_path):
        from python_service.httpserver.services.extractors.data_exchange import XmlDataExtractor
        import asyncio
        xml_file = tmp_path / "test.xml"
        xml_file.write_text('<?xml version="1.0"?><root><item name="a">text</item></root>', encoding='utf-8')
        extractor = XmlDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(xml_file))
        )
        assert 'XML Data' in result
        assert 'root' in result


# --- Microsoft Extended Extractors ---

class TestUrlExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.microsoft_extended import UrlExtractor
        import asyncio
        extractor = UrlExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.url')
        )
        assert 'Error' in result

    def test_basic_url(self, tmp_path):
        from python_service.httpserver.services.extractors.microsoft_extended import UrlExtractor
        import asyncio
        url_file = tmp_path / "test.url"
        url_file.write_text("[InternetShortcut]\nURL=https://example.com\n", encoding='utf-8')
        extractor = UrlExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(url_file))
        )
        assert 'Internet Shortcut' in result
        assert 'https://example.com' in result


class TestMscExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.microsoft_extended import MscExtractor
        import asyncio
        extractor = MscExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.msc')
        )
        assert 'Error' in result


class TestXpsExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.microsoft_extended import XpsExtractor
        import asyncio
        extractor = XpsExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.xps')
        )
        assert 'Error' in result


class TestOneNoteExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.microsoft_extended import OneNoteExtractor
        import asyncio
        extractor = OneNoteExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.one')
        )
        assert 'Error' in result


class TestVisioExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.microsoft_extended import VisioExtractor
        import asyncio
        extractor = VisioExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.vsdx')
        )
        assert 'Error' in result


class TestProjectExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.microsoft_extended import ProjectExtractor
        import asyncio
        extractor = ProjectExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.mpp')
        )
        assert 'Error' in result


class TestEtlExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.microsoft_extended import EtlExtractor
        import asyncio
        extractor = EtlExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.etl')
        )
        assert 'Error' in result


# --- Adobe Format Extractors ---

class TestPsdExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.adobe_formats import PsdExtractor
        import asyncio
        extractor = PsdExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.psd')
        )
        assert 'Error' in result


class TestAiExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.adobe_formats import AiExtractor
        import asyncio
        extractor = AiExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.ai')
        )
        assert 'Error' in result


class TestInddExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.adobe_formats import InddExtractor
        import asyncio
        extractor = InddExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.indd')
        )
        assert 'Error' in result


# --- eBook/Science Extractors ---

class TestSrtExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.ebook_science import SrtExtractor
        import asyncio
        extractor = SrtExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.srt')
        )
        assert 'Error' in result

    def test_basic_srt(self, tmp_path):
        from python_service.httpserver.services.extractors.ebook_science import SrtExtractor
        import asyncio
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(
            "1\n00:00:01,000 --> 00:00:04,000\nHello World\n\n2\n00:00:05,000 --> 00:00:08,000\nTest subtitle\n",
            encoding='utf-8'
        )
        extractor = SrtExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(srt_file))
        )
        assert 'SubRip Subtitles' in result
        assert 'Hello World' in result


class TestAssVttExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.ebook_science import AssVttExtractor
        import asyncio
        extractor = AssVttExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.ass')
        )
        assert 'Error' in result


class TestObjExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.ebook_science import ObjExtractor
        import asyncio
        extractor = ObjExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.obj')
        )
        assert 'Error' in result

    def test_basic_obj(self, tmp_path):
        from python_service.httpserver.services.extractors.ebook_science import ObjExtractor
        import asyncio
        obj_file = tmp_path / "test.obj"
        obj_file.write_text(
            "# Simple cube\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n",
            encoding='utf-8'
        )
        extractor = ObjExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(obj_file))
        )
        assert '3D Model' in result
        assert 'Vertices' in result


class TestStlExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.ebook_science import StlExtractor
        import asyncio
        extractor = StlExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.stl')
        )
        assert 'Error' in result


class TestEpubExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.ebook_science import EpubExtractor
        import asyncio
        extractor = EpubExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.epub')
        )
        assert 'Error' in result


class TestMobiExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.ebook_science import MobiExtractor
        import asyncio
        extractor = MobiExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.mobi')
        )
        assert 'Error' in result


class TestHdf5Extractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.ebook_science import Hdf5Extractor
        import asyncio
        extractor = Hdf5Extractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.h5')
        )
        assert 'Error' in result


class TestDicomExtractor:
    def test_nonexistent_file(self):
        from python_service.httpserver.services.extractors.ebook_science import DicomExtractor
        import asyncio
        extractor = DicomExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.dcm')
        )
        assert 'Error' in result


# --- Registry Tests ---

class TestNewExtractorRegistry:
    def test_all_new_extractors_import(self):
        from python_service.httpserver.services.extractors.data_exchange import CsvExtractor, JsonDataExtractor, XmlDataExtractor
        from python_service.httpserver.services.extractors.microsoft_extended import (
            OneNoteExtractor, XpsExtractor, PublisherExtractor, VisioExtractor,
            ProjectExtractor, EtlExtractor, MscExtractor, UrlExtractor
        )
        from python_service.httpserver.services.extractors.adobe_formats import PsdExtractor, AiExtractor, InddExtractor
        from python_service.httpserver.services.extractors.ebook_science import (
            EpubExtractor, MobiExtractor, SrtExtractor, AssVttExtractor,
            ObjExtractor, StlExtractor, Hdf5Extractor, DicomExtractor
        )
        # All classes should be importable
        assert CsvExtractor is not None
        assert JsonDataExtractor is not None
        assert XmlDataExtractor is not None
        assert OneNoteExtractor is not None
        assert XpsExtractor is not None
        assert PublisherExtractor is not None
        assert VisioExtractor is not None
        assert ProjectExtractor is not None
        assert EtlExtractor is not None
        assert MscExtractor is not None
        assert UrlExtractor is not None
        assert PsdExtractor is not None
        assert AiExtractor is not None
        assert InddExtractor is not None
        assert EpubExtractor is not None
        assert MobiExtractor is not None
        assert SrtExtractor is not None
        assert AssVttExtractor is not None
        assert ObjExtractor is not None
        assert StlExtractor is not None
        assert Hdf5Extractor is not None
        assert DicomExtractor is not None
```

- [ ] **Step 2: 运行测试**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
python3 -m pytest python_service/tests/unit/test_forensic_extractors.py -v -k "TestCsv or TestJsonData or TestXmlData or TestUrl or TestSrt or TestObj or TestNewExtractor" 2>&1 | head -60
```

- [ ] **Step 3: 提交**

```bash
git add python_service/tests/unit/test_forensic_extractors.py
git commit -m "test: add unit tests for 15 new extractors"
```

---

### Task 13: 验证和最终提交

- [ ] **Step 1: 验证所有 extractor 可正确加载**

```bash
python3 -c "
from python_service.httpserver.services.extractors import extractor_registry, load_plugins
print(f'Registry size: {len(extractor_registry)}')
for ext in sorted(extractor_registry.keys()):
    print(f'  {ext} -> {extractor_registry[ext].__class__.__name__}')
"
```

- [ ] **Step 2: 验证新增扩展名在 registry 中**

```bash
python3 -c "
from python_service.httpserver.services.extractors import extractor_registry
new_exts = ['.csv', '.tsv', '.json', '.jsonl', '.xml', '.xps', '.one', '.vsdx', '.mpp', '.etl', '.msc', '.url', '.psd', '.ai', '.indd', '.epub', '.mobi', '.srt', '.ass', '.vtt', '.obj', '.stl', '.hdf5', '.dcm']
for ext in new_exts:
    cls = extractor_registry.get(ext)
    name = cls.__class__.__name__ if cls else 'NOT FOUND'
    print(f'{ext:12} -> {name}')
"
```

- [ ] **Step 3: 运行完整测试套件**

```bash
python3 -m pytest python_service/tests/unit/test_forensic_extractors.py -v 2>&1 | tail -30
```

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "feat: complete Windows common file type extractor expansion (15 extractors, 35+ extensions)"
```
