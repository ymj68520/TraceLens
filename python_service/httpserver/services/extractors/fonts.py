"""Font file metadata extractors: TTF, OTF, WOFF."""
import logging
import os

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    else: return f"{size_bytes/1024/1024:.2f} MB"


@register_extractor
class FontExtractor(BaseExtractor):
    """Extracts metadata from font files: TTF, OTF, WOFF, WOFF2."""
    
    FONT_EXTENSIONS = {'.ttf', '.otf', '.woff', '.woff2', '.eot'}
    
    async def extract_to_markdown(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.FONT_EXTENSIONS:
            return f"Error: {ext} is not a recognized font format."
        
        try:
            from fontTools.ttLib import TTFont
        except ImportError:
            return "Error: fonttools library is not installed. Install with: pip install fonttools"
        
        try:
            font = TTFont(file_path)
            
            result = [f"# Font File: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Format:** {ext.upper()[1:]}")
            result.append("")
            
            # Name table
            name_table = font.get('name')
            if name_table:
                result.append("## Font Names")
                result.append("| Name ID | Value |")
                result.append("| --- | --- |")
                
                name_ids = {
                    0: 'Copyright', 1: 'Family', 2: 'Subfamily', 3: 'Unique ID',
                    4: 'Full Name', 5: 'Version', 6: 'PostScript Name',
                    7: 'Trademark', 8: 'Manufacturer', 9: 'Designer',
                    10: 'Description', 11: 'URL Vendor', 12: 'URL Designer',
                    13: 'License', 14: 'URL License',
                }
                
                for record in name_table.names:
                    name_id = record.nameID
                    if name_id in name_ids:
                        try:
                            value = record.toUnicode()
                            if value and len(value) < 200:
                                result.append(f"| {name_ids[name_id]} | {value} |")
                        except: pass
                result.append("")
            
            # OS/2 table
            os2 = font.get('OS/2')
            if os2:
                result.append("## Font Properties")
                result.append("| Property | Value |")
                result.append("| --- | --- |")
                result.append(f"| Weight Class | {os2.usWeightClass} |")
                result.append(f"| Width Class | {os2.usWidthClass} |")
                result.append(f"| Embedding | {os2.fsType} |")
                result.append("")
            
            # Head table
            head = font.get('head')
            if head:
                result.append(f"**Units Per Em:** {head.unitsPerEm}")
            
            # Number of glyphs
            cmap = font.get('cmap')
            if cmap:
                total_glyphs = sum(len(table.cmap) for table in cmap.tables)
                result.append(f"**Total Glyphs:** {total_glyphs:,}")
            
            font.close()
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse font file: {e}"
