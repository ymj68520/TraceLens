"""Virtual disk format extractors: VMDK, VHD, QCOW2, DMG."""
import logging
import os
import struct

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024*1024*1024: return f"{size_bytes/1024/1024:.2f} MB"
    else: return f"{size_bytes/1024/1024/1024:.2f} GB"


@register_extractor
class VmdkExtractor(BaseExtractor):
    """Extracts metadata from VMDK (VMware Virtual Disk) files."""
    
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(512)
        except Exception as e:
            return f"Error: Failed to read VMDK file: {e}"
        
        result = [f"# VMDK Virtual Disk: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        
        # Check magic: KDMV (VMDK backwards)
        magic = header[:4]
        if magic == b'KDMV':
            result.append(f"**Format:** VMDK (Sparse)")
            
            # Parse descriptor
            version = struct.unpack('<I', header[4:8])[0]
            result.append(f"**Version:** {version}")
            
            # Read descriptor text
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    descriptor = f.read(4096)
                
                for line in descriptor.split('\n'):
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    if '=' in line:
                        key, _, value = line.partition('=')
                        key = key.strip().lower()
                        value = value.strip().strip('"')
                        if key == 'createtype':
                            result.append(f"**Type:** {value}")
                        elif key == 'ddb.geometry.cylinders':
                            result.append(f"**Cylinders:** {value}")
                        elif key == 'ddb.geometry.heads':
                            result.append(f"**Heads:** {value}")
                        elif key == 'ddb.geometry.sectors':
                            result.append(f"**Sectors:** {value}")
                        elif key == 'ddb.virtualhw.version':
                            result.append(f"**Virtual HW Version:** {value}")
            except: pass
        elif header[0:8] == b'VMDK\x00\x00\x00\x00':
            result.append(f"**Format:** VMDK (Hosted)")
        else:
            result.append(f"**Magic:** {magic.hex()}")
            result.append("")
            result.append("*Could not parse VMDK descriptor.*")
        
        return "\n".join(result)


@register_extractor
class VhdExtractor(BaseExtractor):
    """Extracts metadata from VHD/VHDX (Virtual Hard Disk) files."""
    
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(512)
        except Exception as e:
            return f"Error: Failed to read VHD file: {e}"
        
        ext = os.path.splitext(file_path)[1].lower()
        result = [f"# {'VHDX' if ext == '.vhdx' else 'VHD'} Virtual Disk: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        
        # VHD footer is at the end of the file for VHD
        if ext == '.vhd':
            try:
                with open(file_path, 'rb') as f:
                    f.seek(-512, 2)
                    footer = f.read(512)
                
                if footer[:8] == b'conectix':
                    result.append(f"**Format:** VHD (Fixed/Dynamic)")
                    
                    # Parse footer
                    features = struct.unpack('>I', footer[8:12])[0]
                    version = struct.unpack('>I', footer[12:16])[0]
                    result.append(f"**Version:** {version >> 16}.{version & 0xFFFF}")
                    
                    # Disk type
                    disk_type = struct.unpack('>I', footer[60:64])[0]
                    type_names = {2: 'Fixed', 3: 'Dynamic', 4: 'Differencing', 5: 'Reserved'}
                    result.append(f"**Type:** {type_names.get(disk_type, f'Unknown ({disk_type})')}")
                    
                    # Geometry
                    cylinders = struct.unpack('>H', footer[56:58])[0]
                    heads = footer[58]
                    sectors = footer[59]
                    result.append(f"**Geometry:** {cylinders} C / {heads} H / {sectors} S")
                    
                    # Original size
                    orig_size = struct.unpack('>Q', footer[48:56])[0]
                    result.append(f"**Virtual Size:** {_format_size(orig_size)}")
                else:
                    result.append(f"**Magic:** {footer[:8].hex()}")
            except Exception as e:
                result.append(f"*Error reading VHD footer: {e}*")
        
        elif ext == '.vhdx':
            magic = header[:8]
            if magic == b'vhdxfile':
                result.append(f"**Format:** VHDX")
                result.append("")
                result.append("*VHDX format detected. Full parsing requires specialized VHDX parser.*")
            else:
                result.append(f"**Magic:** {magic.hex()}")
        
        return "\n".join(result)


@register_extractor
class DmgExtractor(BaseExtractor):
    """Extracts metadata from DMG (Apple Disk Image) files."""
    
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(512)
        except Exception as e:
            return f"Error: Failed to read DMG file: {e}"
        
        result = [f"# DMG Disk Image: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** Apple Disk Image (DMG)")
        
        # DMG is typically a UDIF container
        # Check for magic at various offsets
        if header[0:4] == b'\x45\x52\x02\x00' or header[0:4] == b'\x78\x01\x73\x0d':
            result.append(f"**Type:** UDIF (compressed)")
        elif b'koly' in header:
            result.append(f"**Type:** UDIF trailer found")
        else:
            result.append(f"**Type:** Raw DMG")
        
        result.append("")
        result.append("*DMG files are complex Apple-specific disk images. Full content extraction requires macOS tools (`hdiutil`).*")
        
        # Try to find plist metadata
        try:
            with open(file_path, 'rb') as f:
                content = f.read(min(os.path.getsize(file_path), 10*1024*1024))
            
            # Look for XML plist
            plist_start = content.find(b'<?xml')
            if plist_start != -1:
                plist_end = content.find(b'</plist>', plist_start)
                if plist_end != -1:
                    plist_xml = content[plist_start:plist_end+8].decode('utf-8', errors='replace')
                    result.append("## Embedded Plist Metadata")
                    result.append("```xml")
                    result.append(plist_xml[:3000])
                    if len(plist_xml) > 3000:
                        result.append("... (truncated)")
                    result.append("```")
        except: pass
        
        return "\n".join(result)
