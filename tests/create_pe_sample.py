#!/usr/bin/env python3
"""
Create a minimal valid PE file for testing
"""
import struct

def create_minimal_pe(filename):
    """Create a minimal 64-bit PE file"""

    # DOS Header (64 bytes)
    dos_header = bytearray(64)
    # e_magic (MZ)
    struct.pack_into('<H', dos_header, 0, 0x5A4D)
    # e_lfanew (PE header offset = 64)
    struct.pack_into('<I', dos_header, 60, 64)

    # PE Signature (4 bytes)
    pe_sig = b'PE\x00\x00'

    # COFF Header (20 bytes)
    coff_header = bytearray(20)
    # Machine (x64)
    struct.pack_into('<H', coff_header, 0, 0x8664)
    # NumberOfSections
    struct.pack_into('<H', coff_header, 2, 2)
    # TimeDateStamp
    struct.pack_into('<I', coff_header, 4, 0x5F5E100)
    # PointerToSymbolTable
    struct.pack_into('<I', coff_header, 8, 0)
    # NumberOfSymbols
    struct.pack_into('<I', coff_header, 12, 0)
    # SizeOfOptionalHeader
    struct.pack_into('<H', coff_header, 16, 240)
    # Characteristics
    struct.pack_into('<H', coff_header, 18, 0x0022)  # EXECUTABLE_IMAGE | FILE_LARGE_ADDRESS_AWARE

    # Optional Header (PE32+, 240 bytes)
    optional_header = bytearray(240)
    # Magic (PE32+)
    struct.pack_into('<H', optional_header, 0, 0x20B)
    # MajorLinkerVersion, MinorLinkerVersion
    struct.pack_into('<BB', optional_header, 2, 14, 0)
    # SizeOfCode
    struct.pack_into('<I', optional_header, 4, 512)
    # SizeOfInitializedData
    struct.pack_into('<I', optional_header, 8, 0)
    # SizeOfUninitializedData
    struct.pack_into('<I', optional_header, 12, 0)
    # AddressOfEntryPoint
    struct.pack_into('<I', optional_header, 16, 0x1000)
    # BaseOfCode
    struct.pack_into('<I', optional_header, 20, 0x1000)
    # ImageBase (64-bit)
    struct.pack_into('<Q', optional_header, 24, 0x140000000)
    # SectionAlignment
    struct.pack_into('<I', optional_header, 32, 4096)
    # FileAlignment
    struct.pack_into('<I', optional_header, 36, 512)
    # MajorOperatingSystemVersion, MinorOperatingSystemVersion
    struct.pack_into('<HH', optional_header, 40, 6, 0)
    # MajorImageVersion, MinorImageVersion
    struct.pack_into('<HH', optional_header, 44, 0, 0)
    # MajorSubsystemVersion, MinorSubsystemVersion
    struct.pack_into('<HH', optional_header, 48, 6, 0)
    # Win32VersionValue
    struct.pack_into('<I', optional_header, 52, 0)
    # SizeOfImage
    struct.pack_into('<I', optional_header, 56, 8192)
    # SizeOfHeaders
    struct.pack_into('<I', optional_header, 60, 512)
    # CheckSum
    struct.pack_into('<I', optional_header, 64, 0)
    # Subsystem (WINDOWS_GUI)
    struct.pack_into('<H', optional_header, 68, 2)
    # DllCharacteristics
    struct.pack_into('<H', optional_header, 70, 0x0140)  # NX_COMPAT | TERMINAL_SERVER_AWARE
    # SizeOfStackReserve, SizeOfStackCommit
    struct.pack_into('<QQ', optional_header, 72, 0x100000, 0x1000)
    # SizeOfHeapReserve, SizeOfHeapCommit
    struct.pack_into('<QQ', optional_header, 88, 0x100000, 0x1000)
    # LoaderFlags
    struct.pack_into('<I', optional_header, 104, 0)
    # NumberOfRvaAndSizes
    struct.pack_into('<I', optional_header, 108, 9)

    # Data Directories (we only need Security = 0 for unsigned)
    # Export, Import, Resource, Exception, Security (all zeros)
    data_dirs = bytearray(144)

    # Section Table (2 sections, 40 bytes each = 80 bytes)
    section_table = bytearray(80)

    # Section 1: .text (code)
    # Name
    struct.pack_into('<8s', section_table, 0, b'.text\x00\x00\x00')
    # VirtualSize, VirtualAddress
    struct.pack_into('<II', section_table, 8, 512, 0x1000)
    # SizeOfRawData, PointerToRawData
    struct.pack_into('<II', section_table, 16, 512, 512)
    # PointerToRelocations, PointerToLinenumbers
    struct.pack_into('<II', section_table, 20, 0, 0)
    # NumberOfRelocations, NumberOfLinenumbers
    struct.pack_into('<HH', section_table, 24, 0, 0)
    # Characteristics (CODE | EXECUTE | READ)
    struct.pack_into('<I', section_table, 26, 0x60000020)

    # Section 2: .data (data)
    offset = 40
    struct.pack_into('<8s', section_table, offset, b'.data\x00\x00\x00')
    struct.pack_into('<II', section_table, offset + 8, 256, 0x2000)
    struct.pack_into('<II', section_table, offset + 16, 256, 1024)
    struct.pack_into('<II', section_table, offset + 20, 0, 0)
    struct.pack_into('<HH', section_table, offset + 24, 0, 0)
    struct.pack_into('<I', section_table, offset + 26, 0xC0000040)  # INITIALIZED_DATA | READ | WRITE

    # Write file
    with open(filename, 'wb') as f:
        f.write(dos_header)
        f.write(pe_sig)
        f.write(coff_header)
        f.write(optional_header)
        f.write(data_dirs)
        f.write(section_table)
        # Pad to 512 bytes (SizeOfHeaders)
        f.write(b'\x00' * (512 - f.tell()))
        # .text section data (512 bytes)
        f.write(b'\xCC' * 512)  # INT3 breakpoints
        # .data section data (256 bytes)
        f.write(b'\x00' * 256)

    print(f"Created minimal PE file: {filename}")

if __name__ == '__main__':
    create_minimal_pe('/home/ymj68520/projects/Forensics/ForensicsProject/tests/samples/pe/test_minimal.exe')
