# Comprehensive File Type Coverage Design Spec

**Date:** 2026-06-06
**Status:** Draft
**Scope:** Add ~23 new Python extractor classes to cover all common file types

## Problem Statement

The existing extractor system covers forensic-specific formats well, but many everyday file types are still unsupported:
- Office extensions: RTF, ODT, ODS, ODP, iWork (Pages/Numbers/Keynote)
- Image formats: HEIC/HEIF, RAW (CR2/NEF/ARW/DNG), SVG, ICO, AVIF
- Audio/Video: MP4, AVI, MOV, MKV, AAC, OGG, FLAC, WMA, M4A (40+ formats)
- Compression: BZ2, XZ, LZ4, ZST, CAB, ISO, DMG
- Binary: EXE, DLL, SO, ELF, Java .class
- Calendar/Contacts: ICS, VCF
- Fonts: TTF, OTF, WOFF
- Virtual disks: VMDK, VHD, QCOW2

## Goals

1. Add ~23 new extractor classes covering all common file types
2. Follow existing `BaseExtractor` + `extract_to_markdown()` plugin architecture
3. Use pure Python libraries where possible
4. Audio/Video: metadata extraction + content sampling (keyframe screenshots, audio snippets)
5. Binary (PE/ELF): import/export tables, resources, version info
6. Register all in `extractor_mapping.json`

## Architecture

### New Extractor Files

```
python_service/httpserver/services/extractors/
├── office_extended.py      # RtfExtractor, OdtExtractor, OdsExtractor, OdpExtractor, IworkExtractor
├── image_metadata.py       # HeicExtractor, RawImageExtractor, SvgExtractor, IcoExtractor, AvifExtractor
├── media_metadata.py       # VideoExtractor, AudioExtractor
├── archives_extended.py    # Bz2Extractor, XzExtractor, Lz4Extractor, ZstExtractor, IsoExtractor, CabExtractor
├── binary_analyzer.py      # PeExtractor, ElfExtractor, JavaClassExtractor
├── contacts_calendar.py    # IcsExtractor, VcfExtractor
├── fonts.py                # FontExtractor
└── disk_formats.py         # VmdkExtractor, VhdExtractor, DmgExtractor
```

### Dependencies

```python
# Image
pillow-heif>=0.13.0       # HEIC/HEIF
rawpy>=0.19.0             # RAW images

# Audio/Video
mutagen>=1.47.0            # Audio metadata
# ffprobe (from ffmpeg) via subprocess for video

# Binary
pefile>=2023.2.7           # PE files (EXE/DLL)
pyelftools>=0.30           # ELF files (SO/LD)

# Documents
striprtf>=0.0.26           # RTF parsing
odfpy>=1.4.1               # ODF (ODT/ODS/ODP)

# Calendar/Contacts
python-icalendar>=5.0.0    # ICS
vobject>=0.9.6             # VCF

# Fonts
fonttools>=4.40.0          # TTF/OTF/WOFF

# Disk images
pycdlib>=1.14.0            # ISO parsing

# Standard library: zipfile, struct, xml.etree, subprocess, tarfile, json
```

### Routing

All new extractors registered via `extractor_mapping.json` with extension-based routing.

## Implementation Phases

### Phase 1: Documents + Images + Contacts (10 extractors)
- office_extended.py: RtfExtractor, OdtExtractor, OdsExtractor, OdpExtractor, IworkExtractor
- image_metadata.py: HeicExtractor, RawImageExtractor, SvgExtractor
- contacts_calendar.py: IcsExtractor, VcfExtractor

### Phase 2: Audio/Video + Compression (7 extractors)
- media_metadata.py: VideoExtractor, AudioExtractor
- archives_extended.py: Bz2Extractor, XzExtractor, Lz4Extractor, ZstExtractor, IsoExtractor

### Phase 3: Binary + Fonts + Virtual Disks (6 extractors)
- binary_analyzer.py: PeExtractor, ElfExtractor, JavaClassExtractor
- fonts.py: FontExtractor
- disk_formats.py: VmdkExtractor, VhdExtractor, DmgExtractor
