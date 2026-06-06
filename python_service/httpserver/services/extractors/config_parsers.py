"""Enhanced configuration file parsers: INI, TOML, YAML, Markdown deep parsing."""
import logging
import os
import re
from collections import defaultdict

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    else: return f"{size_bytes/1024/1024:.2f} MB"


@register_extractor
class IniExtractor(BaseExtractor):
    """Deep parser for INI/CONF/CFG configuration files."""

    INI_EXTENSIONS = {'.ini', '.conf', '.cfg', '.config', '.properties', '.env'}

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import configparser
        except ImportError:
            return "Error: configparser not available."

        try:
            config = configparser.ConfigParser()
            config.read(file_path, encoding='utf-8')

            result = [f"# Configuration File: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Sections:** {len(config.sections())}")
            result.append("")

            if not config.sections():
                # Try reading as key=value without sections
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()

                result.append("## Key-Value Pairs")
                result.append("| Key | Value |")
                result.append("| --- | --- |")
                count = 0
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#') and not line.startswith(';') and '=' in line:
                        key, _, value = line.partition('=')
                        result.append(f"| {key.strip()} | {value.strip()[:100]} |")
                        count += 1
                        if count >= 100:
                            break
            else:
                for section in config.sections():
                    result.append(f"## [{section}]")
                    result.append("| Key | Value |")
                    result.append("| --- | --- |")
                    for key, value in config.items(section):
                        result.append(f"| {key} | {value[:100]} |")
                    result.append("")

            return "\n".join(result)
        except configparser.Error:
            # Fallback: treat as plain key=value
            return self._parse_kv(file_path)
        except Exception as e:
            return f"Error: Failed to parse config file: {e}"

    def _parse_kv(self, file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            result = [f"# Configuration File: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")
            result.append("## Key-Value Pairs")
            result.append("| Key | Value |")
            result.append("| --- | --- |")

            count = 0
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith(';'):
                    if '=' in line:
                        key, _, value = line.partition('=')
                        result.append(f"| {key.strip()} | {value.strip()[:100]} |")
                        count += 1
                    elif ':' in line:
                        key, _, value = line.partition(':')
                        result.append(f"| {key.strip()} | {value.strip()[:100]} |")
                        count += 1

                    if count >= 200:
                        break

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to read config file: {e}"


@register_extractor
class TomlExtractor(BaseExtractor):
    """Deep parser for TOML configuration files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                return "Error: TOML parser not available (requires Python 3.11+ or tomli)."

        try:
            with open(file_path, 'rb') as f:
                data = tomllib.load(f)

            result = [f"# TOML Configuration: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            self._render_dict(data, result, depth=0)

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse TOML file: {e}"

    def _render_dict(self, data: dict, result: list, depth: int, prefix: str = ""):
        for key, value in sorted(data.items()):
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                result.append(f"{'  ' * depth}### {key}")
                self._render_dict(value, result, depth + 1, full_key)
            elif isinstance(value, list):
                if value and isinstance(value[0], dict):
                    result.append(f"{'  ' * depth}### {key} (array of tables)")
                    for i, item in enumerate(value[:10]):
                        result.append(f"{'  ' * depth}#### [{i}]")
                        self._render_dict(item, result, depth + 1)
                    if len(value) > 10:
                        result.append(f"{'  ' * depth}*... and {len(value) - 10} more items*")
                else:
                    val_str = ', '.join(str(v) for v in value[:10])
                    if len(value) > 10:
                        val_str += f', ... ({len(value)} total)'
                    result.append(f"| {full_key} | `{val_str}` |")
            else:
                result.append(f"| {full_key} | `{str(value)[:100]}` |")


@register_extractor
class YamlExtractor(BaseExtractor):
    """Deep parser for YAML configuration files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import yaml
        except ImportError:
            return "Error: PyYAML library is not installed."

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                data = yaml.safe_load(f)

            result = [f"# YAML Configuration: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            if isinstance(data, dict):
                result.append("## Structure")
                result.append("| Key | Value |")
                result.append("| --- | --- |")
                self._render_yaml_dict(data, result, prefix="")
            elif isinstance(data, list):
                result.append(f"**Root:** List ({len(data)} items)")
                for i, item in enumerate(data[:20]):
                    if isinstance(item, dict):
                        result.append(f"\n### Item {i}")
                        result.append("| Key | Value |")
                        result.append("| --- | --- |")
                        self._render_yaml_dict(item, result, prefix="")
                    else:
                        result.append(f"- `{str(item)[:100]}`")
            else:
                result.append(f"**Value:** `{str(data)[:500]}`")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse YAML file: {e}"

    def _render_yaml_dict(self, data: dict, result: list, prefix: str, max_depth: int = 3):
        if max_depth <= 0:
            return
        for key, value in sorted(data.items()):
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                if len(value) < 20:
                    self._render_yaml_dict(value, result, full_key, max_depth - 1)
                else:
                    result.append(f"| {full_key} | (dict with {len(value)} keys) |")
            elif isinstance(value, list):
                if len(value) <= 5:
                    val_str = ', '.join(str(v)[:30] for v in value)
                    result.append(f"| {full_key} | [{val_str}] |")
                else:
                    result.append(f"| {full_key} | (list with {len(value)} items) |")
            else:
                result.append(f"| {full_key} | `{str(value)[:100]}` |")


@register_extractor
class MarkdownExtractor(BaseExtractor):
    """Enhanced Markdown parser with structure extraction."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception as e:
            return f"Error: Failed to read Markdown file: {e}"

        result = [f"# Markdown Document: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

        # Extract structure
        headings = re.findall(r'^(#{1,6})\s+(.+)$', content, re.MULTILINE)
        code_blocks = re.findall(r'```(\w*)\n', content)
        links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)
        images = re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', content)

        result.append(f"**Headings:** {len(headings)}")
        result.append(f"**Code Blocks:** {len(code_blocks)}")
        result.append(f"**Links:** {len(links)}")
        result.append(f"**Images:** {len(images)}")
        result.append("")

        # Table of contents
        if headings:
            result.append("## Table of Contents")
            for level, title in headings[:50]:
                indent = "  " * (len(level) - 1)
                result.append(f"{indent}- {title}")
            if len(headings) > 50:
                result.append(f"\n*(Showing first 50 of {len(headings)} headings)*")
            result.append("")

        # Links
        if links:
            result.append("## Links")
            result.append("| Text | URL |")
            result.append("| --- | --- |")
            for text, url in links[:30]:
                result.append(f"| {text[:50]} | {url[:80]} |")
            if len(links) > 30:
                result.append(f"\n*(Showing first 30 of {len(links)} links)*")
            result.append("")

        # Code blocks by language
        if code_blocks:
            lang_counts = defaultdict(int)
            for lang in code_blocks:
                lang_counts[lang or 'plain'] += 1
            result.append("## Code Blocks")
            result.append("| Language | Count |")
            result.append("| --- | --- |")
            for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
                result.append(f"| {lang} | {count} |")
            result.append("")

        # Content preview
        result.append("## Content Preview")
        # Strip markdown syntax for preview
        preview = re.sub(r'```[\s\S]*?```', '[CODE BLOCK]', content)
        preview = re.sub(r'!\[.*?\]\(.*?\)', '[IMAGE]', preview)
        if len(preview) > 3000:
            preview = preview[:3000] + "\n\n... (truncated)"
        result.append(preview)

        return "\n".join(result)
