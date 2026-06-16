"""
Extractor for GRUB 2 bootloader module files (.mod).

GRUB 2 modules are relocatable ELF objects found under ``grub/<platform>/``
(e.g. ``grub/i386-pc/normal.mod``). Each module dynamically extends the
bootloader with filesystem drivers, network protocols, commands, etc.

These files are genuine ELF relocatable objects, so pyelftools (already a
project dependency) can parse them. The extractor surfaces:
  - ELF metadata (architecture, type, sections, key symbols)
  - GRUB-specific intelligence: module name, dependency chain, registered
    commands, and a short functional description inferred from the name

This turns 276+ otherwise-opaque binary blobs into actionable forensic
context (e.g. "network boot enabled", "ZFS support loaded", "crypto active").
"""

import logging
import os

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Human-readable descriptions for well-known GRUB modules.
# Mapped from the module basename (without .mod) so the LLM gets context.
# ---------------------------------------------------------------------------
_KNOWN_MODULES: dict[str, str] = {
    "normal": "Interactive command line interpreter and boot menu engine",
    "net": "Network stack: boot via TFTP/HTTP, DHCP, PXE",
    "tftp": "TFTP file transfer for network boot",
    "http": "HTTP client for network boot",
    "zfs": "ZFS filesystem driver",
    "btrfs": "Btrfs filesystem driver",
    "ext2": "Ext2/3/4 filesystem driver",
    "xfs": "XFS filesystem driver",
    "ntfs": "NTFS filesystem driver",
    "fat": "FAT12/16/32 filesystem driver",
    "exfat": "exFAT filesystem driver",
    "hfsplus": "HFS+ filesystem driver",
    "iso9660": "ISO 9660 optical media filesystem driver",
    "luks": "LUKS disk encryption support",
    "cryptodisk": "Generic encrypted disk framework",
    "gcry_sha256": "SHA-256 hash algorithm",
    "gcry_sha512": "SHA-512 hash algorithm",
    "gcry_rijndael": "AES (Rijndael) cipher",
    "gcry_rsa": "RSA public-key algorithm",
    "password_pbkdf2": "PBKDF2 password derivation for GRUB passwords",
    "password": "Basic password authentication",
    "legacy_password_test": "Legacy password compatibility",
    "part_gpt": "GPT partition table support",
    "part_msdos": "MBR/DOS partition table support",
    "part_apple": "Apple partition map support",
    "chain": "Chain-loading of other bootloaders / NTLDR / bootmgr",
    "linux": "Linux kernel image loader",
    "linux16": "16-bit Linux kernel loader (BIOS real mode)",
    "multiboot": "Multiboot specification kernel loader",
    "reboot": "System reboot command",
    "halt": "System halt command",
    "help": "In-shell help system",
    "ls": "List files and devices",
    "search": "Search for devices by UUID/label/filesystem",
    "configfile": "Load and execute a GRUB configuration file",
    "serial": "Serial console support",
    "terminal": "Terminal output selection (console/serial)",
    "gfxterm": "Graphical terminal output",
    "png": "PNG image decoder (for GRUB themes/splash)",
    "jpeg": "JPEG image decoder",
    "font": "Font rendering for graphical menu",
    "test": "Conditional expression evaluation",
    "true": "Always-succeed test",
    "false": "Always-fail test",
    "setpci": "Direct PCI configuration space access",
    "ata": "ATA/IDE disk driver",
    "ahci": "AHCI SATA disk driver",
    "usb": "USB host controller driver",
    "uhci": "UHCI USB host controller (USB 1.1)",
    "ehci": "EHCI USB host controller (USB 2.0)",
    "xhci": "XHCI USB host controller (USB 3.0)",
    "pcidump": "Dump PCI device information",
    "lsdev": "List known devices",
    "lspci": "List PCI devices",
    "play": "PC speaker beep tunes",
    "echo": "Print text to terminal",
    "cat": "Display file contents",
    "sleep": "Pause for a number of seconds",
    "date": "Display or set the date/time",
    "keystatus": "Check shift/ctrl/alt key status at boot",
    "loadenv": "Load/save GRUB environment block",
    "saveenv": "Save environment variables to disk",
    "md5sum": "Compute MD5 checksum of data",
    "sha256sum": "Compute SHA-256 checksum",
    "probe": "Probe device for filesystem/type/UUID",
    "regexp": "Regular expression support",
    "all_video": "Video mode aggregation module",
    "videoinfo": "List available video modes",
    "videotest": "Test video mode with a pattern",
    "file": "File type detection by magic bytes",
    "tr": "Translate/delete characters",
    "cmosdump": "Dump CMOS/RTC contents",
    "cmostest": "Test CMOS/RTC bits",
    "gptsync": "Create hybrid MBR for GPT disks",
    "boot": "Boot the loaded OS or kernel",
    "exit": "Exit from current GRUB script or instance",
    "loopback": "Create a virtual disk from a file (loop mount)",
    "hashsum": "Generic hash computation command",
    "memrw": "Read/write physical memory",
    "rdmsr": "Read CPU model-specific register",
    "wrmsr": "Write CPU model-specific register",
    "cbfs": "Coreboot File System support",
    "lsefisummary": "List UEFI variable summary",
    "lsefimmap": "List UEFI memory map",
    "efivarfs": "UEFI variable filesystem support",
    "lsefi": "List UEFI devices",
    "fixVideo": "Fix video mode for problematic BIOSes",
    "915resolution": "Intel 915 video BIOS resolution hack",
    "layout": "Keyboard layout switching",
    "keylayouts": "Keyboard layout file loader",
    "biosmem": "BIOS memory map interrogation",
    "paging": "CPU paging support",
    "minicmd": "Minimal rescue-mode command set",
    "atest": "ATA disk test",
    "hdparm": "Query/set hard disk parameters",
    "macbless": "HFS+ blessing for Mac boot",
    "loadbios": "Load BIOS from a file (for Macs)",
    "fix_service": "Service record fixup",
    "sendkey": "Emulate keystrokes at boot",
}


def _format_size(n: int) -> str:
    """Human-readable byte size."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


@register_extractor
class GrubModuleExtractor(BaseExtractor):
    """Extracts metadata and GRUB-specific intelligence from .mod files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from elftools.elf.elffile import ELFFile
            from elftools.common.exceptions import ELFError
        except ImportError:
            return "Error: pyelftools library is not installed. Install with: pip install pyelftools"

        basename = os.path.basename(file_path)
        module_name = basename.removesuffix(".mod")
        file_size = os.path.getsize(file_path)

        result: list[str] = [f"# GRUB Module: `{basename}`"]
        result.append(f"**Module Name:** `{module_name}`")
        result.append(f"**File Size:** {_format_size(file_size)}")
        result.append("")

        # Functional description from the known-modules table.
        description = _KNOWN_MODULES.get(module_name)
        if description:
            result.append(f"**Function:** {description}")
        else:
            # Heuristic: infer category from the module name prefix.
            category = _infer_category(module_name)
            if category:
                result.append(f"**Function:** GRUB module — {category}")
        result.append("")

        try:
            with open(file_path, "rb") as f:
                try:
                    elf = ELFFile(f)
                except ELFError:
                    # Some GRUB modules use a non-standard container that
                    # pyelftools cannot parse. Fall back to string extraction.
                    result.append("*Note: File is not standard ELF; showing extracted strings.*")
                    result.append("")
                    _append_strings(f, file_size, result)
                    return "\n".join(result)

                result.append(f"**Architecture:** {elf.header.e_machine} ({elf.elfclass}-bit)")
                result.append(f"**ELF Type:** {elf.header.e_type}")
                result.append("")

                # Collect section names for display and symbol extraction.
                section_names = []
                symtab_section = None
                moddeps_section = None
                for section in elf.iter_sections():
                    if section.name:
                        section_names.append(section.name)
                    if section.name == ".symtab":
                        symtab_section = section
                    elif section.name == ".moddeps":
                        moddeps_section = section

                if section_names:
                    result.append("## Sections")
                    result.append("| Name | Type | Size |")
                    result.append("| --- | --- | --- |")
                    for section in elf.iter_sections():
                        if section.name:
                            result.append(
                                f"| {section.name} | {section['sh_type']} | {section['sh_size']:,} |"
                            )
                    result.append("")

                # GRUB commands registered by this module (symbols starting
                # with grub_cmd_ followed by the command name).
                commands: list[str] = []
                symbols: list[str] = []
                if symtab_section:
                    for sym in symtab_section.iter_symbols():
                        if not sym.name:
                            continue
                        symbols.append(sym.name)
                        if sym.name.startswith("grub_cmd_"):
                            cmd = sym.name[len("grub_cmd_"):]
                            commands.append(cmd)

                # Module dependencies — stored as null-terminated module-name
                # strings in the .moddeps section.
                dependencies: list[str] = []
                if moddeps_section and moddeps_section.data():
                    raw = moddeps_section.data()
                    dependencies = [
                        dep for dep in raw.decode("utf-8", errors="replace").split("\x00") if dep
                    ]

                # Symbols (capped for readability)
                if symbols:
                    result.append("## Key Symbols")
                    result.append(f"Total symbols: {len(symbols)} (showing first 30)")
                    result.append("| Symbol |")
                    result.append("| --- |")
                    for sym_name in symbols[:30]:
                        result.append(f"| `{sym_name}` |")
                    result.append("")

                if commands:
                    result.append("## Registered Commands")
                    result.append("This module provides the following GRUB shell commands:")
                    result.append("")
                    for cmd in sorted(set(commands)):
                        result.append(f"- `{cmd}`")
                    result.append("")

                if dependencies:
                    result.append("## Module Dependencies")
                    result.append("This module depends on (must be loaded first):")
                    result.append("")
                    for dep in dependencies:
                        result.append(f"- `{dep}.mod`")
                    result.append("")

                # Forensic assessment
                result.append("## Forensic Assessment")
                assessment = _forensic_assessment(module_name, description or "", commands, dependencies)
                result.append(assessment)

        except Exception as e:
            logger.error("Failed to parse GRUB module %s: %s", file_path, e)
            return f"Error: Failed to parse GRUB module: {e}"

        return "\n".join(result)


def _infer_category(name: str) -> str:
    """Infer a functional category from a GRUB module name prefix."""
    prefixes = {
        "gcry_": "cryptographic algorithm",
        "part_": "partition table support",
        "usb": "USB subsystem",
        "video": "video subsystem",
        "ls": "listing / enumeration",
        "part": "partition support",
        "search_": "search filter",
    }
    for prefix, category in prefixes.items():
        if name.startswith(prefix):
            return category
    return ""


def _append_strings(f, file_size: int, result: list[str]) -> None:
    """Extract printable ASCII strings (fallback for non-ELF modules)."""
    f.seek(0)
    data = f.read(min(file_size, 65536))  # cap at 64 KB
    strings: list[str] = []
    current = []
    for byte in data:
        if 32 <= byte < 127:
            current.append(chr(byte))
        else:
            if len(current) >= 4:
                strings.append("".join(current))
            current = []
    if len(current) >= 4:
        strings.append("".join(current))

    result.append("## Extracted Strings (first 100)")
    result.append("| String |")
    result.append("| --- |")
    for s in strings[:100]:
        result.append(f"| `{s}` |")


def _forensic_assessment(
    module_name: str,
    description: str,
    commands: list[str],
    dependencies: list[str],
) -> str:
    """Generate a short forensic significance note for the LLM."""
    notes: list[str] = []

    security_modules = {"luks", "cryptodisk", "password_pbkdf2", "password",
                        "gcry_rsa", "gcry_rijndael", "legacy_password_test"}
    if module_name in security_modules:
        notes.append("This module is **security-relevant** — it enables encryption or authentication.")

    net_modules = {"net", "tftp", "http", "efinet", "arp", "dhcp", "dns",
                   "http", "tftp", "ofnet", "pxe"}
    if module_name in net_modules:
        notes.append("This module enables **network boot** (PXE/TFTP/HTTP) — the system can boot over the network.")

    if "chain" in commands or module_name == "chain":
        notes.append("Chain-loading is available — this system can boot Windows or other bootloaders via GRUB.")

    if module_name in {"linux", "linux16", "multiboot"}:
        notes.append("This module is responsible for loading the Linux kernel.")

    if module_name in {"configfile", "normal"}:
        notes.append("This module processes GRUB configuration — relevant for understanding boot menu customization.")

    if not notes:
        notes.append("This is a standard GRUB support module with no special forensic significance beyond confirming it is present.")

    return "\n".join(f"- {n}" for n in notes)
