"""Data exchange format extractors: CSV, JSON, JSON Lines, XML."""
import csv
import json
import logging
import os
import statistics
from collections import Counter

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.2f} MB"


# ---------------------------------------------------------------------------
# CSV Extractor
# ---------------------------------------------------------------------------

@register_extractor
class CsvExtractor(BaseExtractor):
    """Deep parser for CSV/TSV data files with delimiter auto-detection and type inference."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            file_size = os.path.getsize(file_path)
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                sample = f.read(8192)

            # Auto-detect delimiter using csv.Sniffer
            delimiter = ","
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                delimiter = dialect.delimiter
            except csv.Error:
                # Fallback: pick the most frequent candidate delimiter
                counts = {d: sample.count(d) for d in [",", "\t", ";", "|"]}
                delimiter = max(counts, key=counts.get) if any(counts.values()) else ","

            delim_label = {",": "comma", "\t": "tab", ";": "semicolon", "|": "pipe"}.get(
                delimiter, repr(delimiter)
            )

            # Read the full file into rows
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f, delimiter=delimiter)
                all_rows = list(reader)

            if not all_rows:
                return f"Error: CSV file is empty."

            header = all_rows[0]
            data_rows = all_rows[1:]
            num_cols = len(header)
            num_rows = len(data_rows)

            # Infer column types by sampling up to 100 rows
            col_types = self._infer_column_types(data_rows, num_cols)

            result = [
                f"# CSV Data: `{os.path.basename(file_path)}`",
                f"**File Size:** {_format_size(file_size)}",
                f"**Delimiter:** {delim_label}",
                f"**Rows:** {num_rows}",
                f"**Columns:** {num_cols}",
                "",
            ]

            # Column info table
            result.append("## Columns")
            result.append("| # | Name | Inferred Type |")
            result.append("| --- | --- | --- |")
            for i, name in enumerate(header):
                ctype = col_types.get(i, "text")
                result.append(f"| {i + 1} | {name} | {ctype} |")
            result.append("")

            # Numeric column statistics
            numeric_cols = [
                (i, name) for i, name in enumerate(header) if col_types.get(i) in ("integer", "float")
            ]
            if numeric_cols:
                result.append("## Numeric Column Statistics")
                result.append("| Column | Min | Max | Mean |")
                result.append("| --- | --- | --- | --- |")
                for col_idx, col_name in numeric_cols:
                    values = []
                    for row in data_rows:
                        if col_idx < len(row):
                            try:
                                values.append(float(row[col_idx]))
                            except (ValueError, TypeError):
                                pass
                    if values:
                        result.append(
                            f"| {col_name} | {min(values):.4g} | {max(values):.4g} | "
                            f"{statistics.mean(values):.4g} |"
                        )
                result.append("")

            # Data preview: markdown table
            if num_rows > 1000:
                preview_rows = data_rows[:100]
                result.append(f"## Data Preview (first 100 of {num_rows} rows)")
            else:
                preview_rows = data_rows[:200]
                result.append("## Data Preview")

            # Build markdown table
            col_widths = min(num_cols, 12)  # limit displayed columns for readability
            display_header = header[:col_widths]
            result.append("| " + " | ".join(display_header) + " |")
            result.append("| " + " | ".join(["---"] * len(display_header)) + " |")
            for row in preview_rows:
                cells = []
                for j in range(col_widths):
                    val = row[j] if j < len(row) else ""
                    cells.append(val[:80])
                result.append("| " + " | ".join(cells) + " |")

            if num_cols > col_widths:
                result.append(f"\n*Showing first {col_widths} of {num_cols} columns*")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse CSV file: {e}"

    def _infer_column_types(self, data_rows: list, num_cols: int, sample_size: int = 100) -> dict:
        """Infer data types for each column by sampling rows."""
        col_types = {}
        sample = data_rows[:sample_size]

        for col_idx in range(num_cols):
            int_count = 0
            float_count = 0
            total = 0

            for row in sample:
                if col_idx >= len(row) or not row[col_idx].strip():
                    continue
                total += 1
                val = row[col_idx].strip()
                try:
                    int(val)
                    int_count += 1
                    continue
                except ValueError:
                    pass
                try:
                    float(val)
                    float_count += 1
                except ValueError:
                    pass

            if total == 0:
                col_types[col_idx] = "text"
            elif int_count / total > 0.8:
                col_types[col_idx] = "integer"
            elif (int_count + float_count) / total > 0.8:
                col_types[col_idx] = "float"
            else:
                col_types[col_idx] = "text"

        return col_types


# ---------------------------------------------------------------------------
# JSON / JSONL Extractor
# ---------------------------------------------------------------------------

@register_extractor
class JsonDataExtractor(BaseExtractor):
    """Parser for JSON and JSON Lines (.jsonl/.ndjson) data files."""

    JSONL_EXTENSIONS = {".jsonl", ".ndjson"}

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            file_size = os.path.getsize(file_path)
            _, ext = os.path.splitext(file_path)
            ext_lower = ext.lower()

            if ext_lower in self.JSONL_EXTENSIONS:
                return self._parse_jsonl(file_path, file_size)
            else:
                return self._parse_json(file_path, file_size)
        except Exception as e:
            return f"Error: Failed to parse JSON file: {e}"

    def _parse_json(self, file_path: str, file_size: int) -> str:
        """Parse standard JSON file."""
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)

        result = [
            f"# JSON Data: `{os.path.basename(file_path)}`",
            f"**File Size:** {_format_size(file_size)}",
        ]

        if isinstance(data, dict):
            result.append(f"**Type:** Object")
            result.append(f"**Top-level Keys:** {len(data)}")
            depth = self._calc_depth(data)
            result.append(f"**Nesting Depth:** {depth}")
            result.append("")

            if len(data) > 500:
                result.append(f"## Structure Summary (top-level keys: {len(data)})")
            else:
                result.append("## Top-Level Keys")

            result.append("| Key | Type | Preview |")
            result.append("| --- | --- | --- |")
            for key in list(data.keys())[:200]:
                val = data[key]
                val_type = self._type_label(val)
                preview = self._preview_value(val)
                result.append(f"| `{key}` | {val_type} | {preview} |")
            if len(data) > 200:
                result.append(f"\n*Showing first 200 of {len(data)} keys*")

        elif isinstance(data, list):
            result.append(f"**Type:** Array")
            result.append(f"**Length:** {len(data)}")
            depth = self._calc_depth(data)
            result.append(f"**Nesting Depth:** {depth}")
            result.append("")

            if data:
                first_type = type(data[0]).__name__
                result.append(f"**Element Type:** {first_type}")
                result.append("")

                if isinstance(data[0], dict):
                    result.append("## Array Element Schema (first item)")
                    result.append("| Key | Type | Preview |")
                    result.append("| --- | --- | --- |")
                    for key, val in data[0].items():
                        val_type = self._type_label(val)
                        preview = self._preview_value(val)
                        result.append(f"| `{key}` | {val_type} | {preview} |")
                    result.append("")

                    # Field distribution across array
                    if len(data) > 1:
                        field_counts = Counter()
                        for item in data[:1000]:
                            if isinstance(item, dict):
                                field_counts.update(item.keys())
                        if field_counts:
                            result.append("## Field Distribution (across array elements)")
                            result.append("| Field | Occurrences |")
                            result.append("| --- | --- |")
                            for field, count in field_counts.most_common(50):
                                result.append(f"| `{field}` | {count} |")
                            result.append("")

                # Preview first few items
                result.append("## Data Preview")
                for i, item in enumerate(data[:10]):
                    if isinstance(item, dict):
                        preview = json.dumps(item, ensure_ascii=False, default=str)
                    else:
                        preview = str(item)
                    if len(preview) > 200:
                        preview = preview[:200] + "..."
                    result.append(f"**[{i}]** `{preview}`")
                if len(data) > 10:
                    result.append(f"\n*... and {len(data) - 10} more items*")
        else:
            result.append(f"**Type:** {type(data).__name__}")
            result.append(f"**Value:** `{str(data)[:500]}`")

        return "\n".join(result)

    def _parse_jsonl(self, file_path: str, file_size: int) -> str:
        """Parse JSON Lines / NDJSON file line by line."""
        records = []
        field_counts = Counter()
        parse_errors = 0
        line_num = 0

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_num += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    records.append(obj)
                    if isinstance(obj, dict):
                        field_counts.update(obj.keys())
                except json.JSONDecodeError:
                    parse_errors += 1

        result = [
            f"# JSON Lines Data: `{os.path.basename(file_path)}`",
            f"**File Size:** {_format_size(file_size)}",
            f"**Format:** JSON Lines / NDJSON",
            f"**Records:** {len(records)}",
        ]
        if parse_errors:
            result.append(f"**Parse Errors:** {parse_errors}")
        result.append("")

        # Field distribution
        if field_counts:
            result.append("## Field Distribution")
            result.append("| Field | Occurrences |")
            result.append("| --- | --- |")
            for field, count in field_counts.most_common(50):
                pct = (count / len(records) * 100) if records else 0
                result.append(f"| `{field}` | {count} ({pct:.0f}%) |")
            result.append("")

        # Record type summary
        type_counts = Counter(type(r).__name__ for r in records)
        result.append("## Record Type Summary")
        result.append("| Type | Count |")
        result.append("| --- | --- |")
        for tname, tcount in type_counts.most_common():
            result.append(f"| {tname} | {tcount} |")
        result.append("")

        # Preview
        result.append("## Data Preview")
        for i, rec in enumerate(records[:10]):
            if isinstance(rec, dict):
                preview = json.dumps(rec, ensure_ascii=False, default=str)
            else:
                preview = str(rec)
            if len(preview) > 200:
                preview = preview[:200] + "..."
            result.append(f"**[{i}]** `{preview}`")
        if len(records) > 10:
            result.append(f"\n*... and {len(records) - 10} more records*")

        return "\n".join(result)

    @staticmethod
    def _calc_depth(obj, current: int = 0) -> int:
        """Calculate maximum nesting depth of a JSON object/array."""
        if isinstance(obj, dict):
            if not obj:
                return current
            return max(JsonDataExtractor._calc_depth(v, current + 1) for v in obj.values())
        elif isinstance(obj, list):
            if not obj:
                return current
            return max(JsonDataExtractor._calc_depth(v, current + 1) for v in obj[:50])
        return current

    @staticmethod
    def _type_label(val) -> str:
        if isinstance(val, dict):
            return f"object ({len(val)} keys)"
        elif isinstance(val, list):
            return f"array ({len(val)} items)"
        return type(val).__name__

    @staticmethod
    def _preview_value(val, max_len: int = 80) -> str:
        if isinstance(val, (dict, list)):
            s = json.dumps(val, ensure_ascii=False, default=str)
        else:
            s = str(val)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return f"`{s}`"


# ---------------------------------------------------------------------------
# XML Extractor
# ---------------------------------------------------------------------------

@register_extractor
class XmlDataExtractor(BaseExtractor):
    """Secure XML parser using defusedxml (XXE protection)."""

    MAX_DEPTH = 6
    MAX_TEXT_LEN = 200
    MAX_CHILDREN_DISPLAY = 50

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from defusedxml import ElementTree as ET
        except ImportError:
            return "Error: defusedxml library is not installed. Install it with: pip install defusedxml"

        try:
            file_size = os.path.getsize(file_path)
            tree = ET.parse(file_path)
            root = tree.getroot()

            result = [
                f"# XML Document: `{os.path.basename(file_path)}`",
                f"**File Size:** {_format_size(file_size)}",
            ]

            # Root element info
            tag = root.tag
            ns = ""
            if "}" in tag:
                ns_uri, local = tag[1:].split("}", 1)
                ns = ns_uri
                tag = local
            result.append(f"**Root Element:** `{tag}`")
            if ns:
                result.append(f"**Namespace:** `{ns}`")

            # Root attributes
            if root.attrib:
                result.append(f"**Root Attributes:** {len(root.attrib)}")
            result.append("")

            # Attribute list for root
            if root.attrib:
                result.append("## Root Attributes")
                result.append("| Attribute | Value |")
                result.append("| --- | --- |")
                for k, v in root.attrib.items():
                    result.append(f"| `{k}` | `{v[:100]}` |")
                result.append("")

            # Count total elements
            total_elements = sum(1 for _ in root.iter())
            result.append(f"**Total Elements:** {total_elements}")
            result.append("")

            # Element tree structure
            result.append("## Element Tree")
            self._render_tree(root, result, depth=0)
            result.append("")

            # Text content extraction (direct children with text)
            texts = []
            for child in root:
                text = (child.text or "").strip()
                if text:
                    tag_name = child.tag
                    if "}" in tag_name:
                        tag_name = tag_name.split("}", 1)[1]
                    texts.append((tag_name, text))

            if texts:
                result.append("## Text Content")
                result.append("| Element | Text |")
                result.append("| --- | --- |")
                for elem_tag, text in texts[:100]:
                    display = text[: self.MAX_TEXT_LEN]
                    if len(text) > self.MAX_TEXT_LEN:
                        display += "..."
                    result.append(f"| `{elem_tag}` | {display} |")
                if len(texts) > 100:
                    result.append(f"\n*Showing first 100 of {len(texts)} text elements*")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse XML file: {e}"

    def _render_tree(self, element, result: list, depth: int):
        """Recursively render XML element tree with depth limit."""
        if depth > self.MAX_DEPTH:
            return

        indent = "  " * depth
        tag = element.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]

        # Build attribute summary
        attr_str = ""
        if element.attrib:
            attrs = [f'{k}="{v[:30]}"' for k, v in element.attrib.items()]
            attr_str = " " + " ".join(attrs[:3])

        # Child count
        children = list(element)
        child_count = len(children)
        text = (element.text or "").strip()

        if child_count == 0 and not text:
            result.append(f"{indent}- `<{tag}{attr_str} />`")
        elif child_count == 0 and text:
            display_text = text[: self.MAX_TEXT_LEN]
            if len(text) > self.MAX_TEXT_LEN:
                display_text += "..."
            result.append(f'{indent}- `<{tag}{attr_str}>` {display_text}')
        else:
            result.append(f"{indent}- `<{tag}{attr_str}>` ({child_count} children)")

        # Recurse into children (limit display)
        for i, child in enumerate(children):
            if i >= self.MAX_CHILDREN_DISPLAY:
                remaining = child_count - self.MAX_CHILDREN_DISPLAY
                result.append(f"{indent}  - *... and {remaining} more elements*")
                break
            self._render_tree(child, result, depth + 1)
