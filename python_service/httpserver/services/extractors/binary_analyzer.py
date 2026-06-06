"""Binary file analyzers: PE (EXE/DLL), ELF (SO/LD), Java .class."""
import logging
import os
import struct
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    else: return f"{size_bytes/1024/1024:.2f} MB"


@register_extractor
class PeExtractor(BaseExtractor):
    """Extracts metadata from PE (Portable Executable) files: EXE, DLL, SYS."""
    
    PE_EXTENSIONS = {'.exe', '.dll', '.sys', '.ocx', '.scr', '.cpl', '.drv'}
    
    async def extract_to_markdown(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.PE_EXTENSIONS:
            return f"Error: {ext} is not a recognized PE format."
        
        try:
            import pefile
        except ImportError:
            return "Error: pefile library is not installed. Install with: pip install pefile"
        
        try:
            pe = pefile.PE(file_path, fast_load=False)
            
            result = [f"# PE File Analysis: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Format:** PE ({'64-bit' if pe.FILE_HEADER.Machine == 0x8664 else '32-bit'})")
            result.append(f"**Type:** {'DLL' if pe.is_dll() else 'EXE' if pe.is_exe() else 'Driver'}")
            result.append("")
            
            # Header info
            result.append("## File Header")
            result.append("| Property | Value |")
            result.append("| --- | --- |")
            result.append(f"| Machine | {hex(pe.FILE_HEADER.Machine)} |")
            result.append(f"| Sections | {pe.FILE_HEADER.NumberOfSections} |")
            ts = datetime.fromtimestamp(pe.FILE_HEADER.TimeDateStamp) if pe.FILE_HEADER.TimeDateStamp else None
            result.append(f"| Timestamp | {ts.strftime('%Y-%m-%d %H:%M:%S') if ts else 'N/A'} |")
            result.append(f"| Characteristics | {hex(pe.FILE_HEADER.Characteristics)} |")
            result.append("")
            
            # Sections
            result.append("## Sections")
            result.append("| Name | Virtual Size | Raw Size | Characteristics |")
            result.append("| --- | --- | --- | --- |")
            for section in pe.sections[:20]:
                name = section.Name.decode('utf-8', errors='replace').rstrip('\x00')
                result.append(f"| {name} | {section.Misc_VirtualSize:,} | {section.SizeOfRawData:,} | {hex(section.Characteristics)} |")
            result.append("")
            
            # Imports
            if hasattr(pe, 'DIRECTORY_ENTRY_IMPORT') and pe.DIRECTORY_ENTRY_IMPORT:
                result.append("## Imports")
                for entry in pe.DIRECTORY_ENTRY_IMPORT[:20]:
                    dll_name = entry.dll.decode('utf-8', errors='replace')
                    funcs = [imp.name.decode('utf-8', errors='replace') if imp.name else f'ord_{imp.ordinal}' for imp in entry.imports[:10]]
                    result.append(f"- **{dll_name}**: {', '.join(funcs)}")
                    if len(entry.imports) > 10:
                        result.append(f"  ... and {len(entry.imports) - 10} more")
                result.append("")
            
            # Exports
            if hasattr(pe, 'DIRECTORY_ENTRY_EXPORT') and pe.DIRECTORY_ENTRY_EXPORT:
                result.append("## Exports")
                result.append("| Ordinal | Name | Address |")
                result.append("| --- | --- | --- |")
                for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols[:30]:
                    name = exp.name.decode('utf-8', errors='replace') if exp.name else f'ord_{exp.ordinal}'
                    result.append(f"| {exp.ordinal} | {name} | {hex(exp.address)} |")
                result.append("")
            
            # Version info
            if hasattr(pe, 'VS_FIXEDFILEINFO') and pe.VS_FIXEDFILEINFO:
                vs = pe.VS_FIXEDFILEINFO[0]
                major = vs.FileVersionMS >> 16
                minor = vs.FileVersionMS & 0xFFFF
                build = vs.FileVersionLS >> 16
                rev = vs.FileVersionLS & 0xFFFF
                result.append(f"**Version:** {major}.{minor}.{build}.{rev}")
            
            pe.close()
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse PE file: {e}"


@register_extractor
class ElfExtractor(BaseExtractor):
    """Extracts metadata from ELF (Executable and Linkable Format) files."""
    
    ELF_EXTENSIONS = {'.so', '.o', '.a', '.ko', '.elf'}
    
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from elftools.elf.elffile import ELFFile
        except ImportError:
            return "Error: pyelftools library is not installed. Install with: pip install pyelftools"
        
        try:
            with open(file_path, 'rb') as f:
                elf = ELFFile(f)
                
                result = [f"# ELF File Analysis: `{os.path.basename(file_path)}`"]
                result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
                
                # Basic info
                arch = elf.header.e_machine
                bits = elf.elfclass
                result.append(f"**Architecture:** {arch} ({bits}-bit)")
                result.append(f"**Type:** {elf.header.e_type}")
                result.append(f"**Entry Point:** {hex(elf.header.e_entry)}")
                result.append("")
                
                # Sections
                result.append("## Sections")
                result.append("| Name | Type | Size | Address |")
                result.append("| --- | --- | --- | --- |")
                for section in elf.iter_sections():
                    if section.name:
                        result.append(f"| {section.name} | {section['sh_type']} | {section['sh_size']:,} | {hex(section['sh_addr'])} |")
                result.append("")
                
                # Program headers (segments)
                result.append("## Segments")
                result.append("| Type | Offset | Virtual Addr | Size |")
                result.append("| --- | --- | --- | --- |")
                for segment in elf.iter_segments():
                    result.append(f"| {segment['p_type']} | {hex(segment['p_offset'])} | {hex(segment['p_vaddr'])} | {segment['p_filesz']:,} |")
                result.append("")
                
                # Symbols
                symtab = elf.get_section_by_name('.symtab')
                if symtab:
                    result.append("## Symbols (First 50)")
                    result.append("| Name | Type | Size | Address |")
                    result.append("| --- | --- | --- | --- |")
                    for i, sym in enumerate(symtab.iter_symbols()):
                        if i >= 50:
                            break
                        if sym.name:
                            result.append(f"| {sym.name} | {sym['st_info']['type']} | {sym['st_size']} | {hex(sym['st_value'])} |")
                    if symtab.num_symbols() > 50:
                        result.append(f"\n*(Showing first 50 of {symtab.num_symbols()} symbols)*")
                
                return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse ELF file: {e}"


@register_extractor
class JavaClassExtractor(BaseExtractor):
    """Extracts metadata from Java .class files."""
    
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
        except Exception as e:
            return f"Error: Failed to read file: {e}"
        
        if len(data) < 4:
            return "Error: File too small to be a valid .class file."
        
        # Check magic: 0xCAFEBABE
        magic = struct.unpack('>I', data[:4])[0]
        if magic != 0xCAFEBABE:
            return f"Error: Not a valid Java .class file (magic: {hex(magic)})"
        
        try:
            minor, major = struct.unpack('>HH', data[4:8])
            
            # Java version mapping
            java_versions = {
                45: '1.1', 46: '1.2', 47: '1.3', 48: '1.4', 49: '5.0',
                50: '6', 51: '7', 52: '8', 53: '9', 54: '10', 55: '11',
                56: '12', 57: '13', 58: '14', 59: '15', 60: '16', 61: '17',
                62: '18', 63: '19', 64: '20', 65: '21',
            }
            java_ver = java_versions.get(major, f'Unknown ({major})')
            
            result = [f"# Java Class: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Class File Version:** {major}.{minor}")
            result.append(f"**Java Version:** {java_ver}")
            result.append("")
            
            # Parse constant pool (basic)
            cp_count = struct.unpack('>H', data[8:10])[0]
            result.append(f"**Constant Pool Entries:** {cp_count - 1}")
            
            # Try to extract class name from constant pool
            # This is a simplified parser
            offset = 10
            constant_types = {
                1: 'Utf8', 3: 'Integer', 4: 'Float', 5: 'Long', 6: 'Double',
                7: 'Class', 8: 'String', 9: 'Fieldref', 10: 'Methodref',
                11: 'InterfaceMethodref', 12: 'NameAndType', 15: 'MethodHandle',
                16: 'MethodType', 17: 'Dynamic', 18: 'InvokeDynamic',
                19: 'Module', 20: 'Package',
            }
            
            strings = []
            class_names = []
            
            try:
                for i in range(1, cp_count):
                    if offset >= len(data):
                        break
                    tag = data[offset]
                    offset += 1
                    
                    if tag == 1:  # Utf8
                        length = struct.unpack('>H', data[offset:offset+2])[0]
                        offset += 2
                        s = data[offset:offset+length].decode('utf-8', errors='replace')
                        strings.append(s)
                        offset += length
                    elif tag in (3, 4):  # Integer, Float
                        offset += 4
                    elif tag in (5, 6):  # Long, Double
                        offset += 8
                    elif tag in (7, 8, 16, 19, 20):  # Class, String, MethodType, Module, Package
                        offset += 2
                    elif tag in (9, 10, 11, 12, 17, 18):  # Fieldref, Methodref, etc.
                        offset += 4
                    elif tag == 15:  # MethodHandle
                        offset += 3
                    else:
                        break
            except:
                pass
            
            # Find class names (look for strings that look like class names)
            for s in strings:
                if '/' in s and not s.startswith('('):
                    class_names.append(s.replace('/', '.'))
            
            if class_names:
                result.append("")
                result.append("## Classes Found")
                for cn in class_names[:20]:
                    result.append(f"- `{cn}`")
            
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Java .class file: {e}"
