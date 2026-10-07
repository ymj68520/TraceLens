# qnxprobe

Read QNX6, QNX4, ETFS, EFS, ext2/3/4, F2FS, FAT32, exFAT, NTFS, HFS+ and APFS filesystems,
the Linux flash filesystems SquashFS, JFFS2, UBI/UBIFS and YAFFS1/YAFFS2, and QNX IFS boot
images, out of raw disk images and flash dumps: identify each by its own on-disk structure
rather than trusting a partition type byte, list, and extract to a zip with a
provenance manifest. No mounting, no admin rights, standard library only.

QNX is what a lot of vehicle infotainment runs on, and it is the reason this tool
exists and keeps its name. When a head unit image lands on your desk, the first
question is what filesystems are in it, and the usual tools do not answer it:
`blkid`, `file` and The Sleuth Kit have no QNX6 support, and the partition table
will happily call a qnx6 volume `0x83 Linux`. This reads the superblock and tells
you what is actually there, then lists and extracts what it found. It reads
ext2/3/4 the same way, so a mixed vehicle landscape (Ford runs QNX, BMW runs
Linux) is one tool rather than two.

It also reads QNX's two flash filesystems, ETFS and EFS, the kind a head unit
keeps its manufacturing and configuration data on. Both are typically imaged bare
with no partition table, so they arrive as the whole image and are read at LBA 0.
ETFS has no superblock at all, so it is rebuilt by replaying the transaction
records in each page's spare area; EFS is found by its `QSSL_F3S` boot record.
Their byte layouts are transcribed from the Kaitai specs in
[NetherlandsForensicInstitute/qnxmount](https://github.com/NetherlandsForensicInstitute/qnxmount)
(Apache-2.0), whose ETFS spec is itself sourced to QNX's `fs/etfs.h` and whose EFS
spec to `fs/f3s_spec.h`, and both readers are validated by round-trip against
qnxmount's own committed test images.

It also reads QNX4, the filesystem of QNX 4 systems, still met on older embedded
and industrial gear. The MBR type bytes `0x4d/0x4e/0x4f` announce a QNX4
partition but never prove one; this reads the actual structure, the `/` root
inode that doubles as the `0x002f` magic, and walks it the way the Linux
kernel's own read-only `fs/qnx4` driver does, inline 64-byte inode entries,
long names resolved through `.inodes` links, and multi-extent files through
their `IamXblk` chains. The reader is validated by round-trip against that
kernel driver on a populated fixture; see
[Where the constants come from](#where-the-constants-come-from).

It also reads QNX IFS boot images, the compressed boot filesystem behind a head
unit's `ifs_*` partitions, holding the kernel, the boot drivers and the startup
scripts. The image filesystem is UCL-compressed, which is not in the standard
library, so a small pure-Python UCL NRV2B decoder is carried in the file rather
than taken as a dependency: the tool still installs nothing. The format and the
decompression are sourced from QNX's own `dumpifs` and `sys/image.h`, and the
decoder is proven byte for byte against the three Ford Sync G4 IFS volumes (each
decompresses to exactly the size its header records and the image checksum
balances). See [What it does not do](#what-it-does-not-do) for the compression
methods it recognises but does not yet read.

It also reads the filesystems embedded Linux keeps on flash: SquashFS, JFFS2, UBI and the
UBIFS inside it, and YAFFS1 and YAFFS2. They are what routers, cameras, drones and Linux
head units tend to carry, often as a chip dump with no partition table and sometimes with
the NAND spare bytes still between the pages. Each is found by its own headers inside such
a dump and read the way the Linux kernel (for YAFFS, Aleph One's own code) reads it. LZO
and LZ4, which the standard library lacks, are carried as small pure-Python decoders. See
[Linux flash filesystems](#linux-flash-filesystems).

One file, Python 3 standard library only. Nothing to install, no admin rights, and
it never writes to the image. A second, optional file, `qnxprobe_gui.py`, puts a
window over it (see [The window](#the-window)); it is standard library too.

## Requirements

Python 3, and nothing else. No packages, no install step.

Reading zstd-compressed SquashFS or UBIFS needs Python 3.14 or later, whose standard
library adds `compression.zstd`. On an older Python those files are named and reported as
not read (see [What it does not do](#what-it-does-not-do)). The
[executables](#executables) carry their own Python 3.14, so they read zstd wherever they
run; those published with v1.31 and v1.32 were built on 3.12 and do not.

Run and self-tested on 3.10, 3.12 and 3.14. It uses no syntax newer than 3.8 and
parses cleanly under 3.8 and 3.9, but it has not been run there.

## Quick start

```
python3 qnxprobe.py mmcblk0.img            # one image
python3 qnxprobe.py *.img *.bin            # several at once
python3 qnxprobe.py partition2.dd          # a partition already carved out
python3 qnxprobe.py --self-test            # prove it reports both ways
python3 qnxprobe.py --help                 # every option, with sourcing
```

## The window

`qnxprobe_gui.py` is a tkinter front end for people who would rather not use a
terminal. It needs the same Python and nothing else; tkinter ships with the
standard Python installers on macOS and Windows and with the `python3-tk` package
on most Linux distributions.

```
python3 qnxprobe_gui.py                 # open the window
python3 qnxprobe_gui.py mmcblk0.img     # open it with an image already added
```

Add one or more images, set the same options the command line takes, and press
**Run report** or **Extract to zip**. Both run `qnxprobe.py` as a subprocess and
stream its output into the Report pane as it is printed, so the report in the
window is byte for byte the report the command line prints. During an extraction
the progress bar is driven by the tool's own `--progress` stream, with exact file
and byte counts per volume. Cancel stops the subprocess; a zip left behind by a
cancelled run is not a complete extraction and the window says so.

The **Contents** pane browses an image without extracting it. It opens the image
read-only, finds each volume with the same partition-table and superblock code
the report uses, and walks it with the same reader classes the extractor uses.
Directories load when you expand them, and a selected file can be saved out on
its own. The Kind column tells regular files from directories, symlinks and
special entries; only regular files can be saved. Created and Accessed are filled
for NTFS, which stores all three times as instants; the other readers carry only
Modified, so those two columns stay blank for them. A FAT32 or exFAT file has no
instant at all: its (UTC) columns stay blank and its readings appear in **Recorded
(as stored)**.

The two halves are kept honest against each other by a check you can run on any
image, with no window:

```
python3 qnxprobe_gui.py --check-discovery mmcblk0.img
```

It runs the report, reads back which volumes it named and what it called each
one, and requires the Contents pane's own discovery to name exactly the same
set. It was run on the 12 synthetic self-test images, qnxmount's four reference
images, a Ford Sync G4 eMMC image (9 volumes) and a BMW MGU image (11 volumes)
before this was published, and all agreed. A qnx6 found only by the brute scan
is reported but has no partition to walk, so it appears in the report and not in
the Contents pane, in the window exactly as on the command line.

## Executables

For a machine with no Python, the repository's GitHub Actions workflow
(`.github/workflows/build-executables.yml`) builds both files into standalone
executables with PyInstaller on Python 3.14, `qnxprobe` for the command line and
`qnxprobe_gui` for the window, on six targets: Windows x64 and arm64, macOS on Apple
silicon and Intel, and Linux x64 and arm64. Each build runs the self-test, the discovery
check, a check that the command line executable extracts every file of the zstd SquashFS
fixture with the bytes it was built from, and a window liveness check on its own runner
before it is packaged with
`SHA256SUMS.txt` and a README. The executables are not code signed; the README
inside each archive says what Windows SmartScreen and macOS Gatekeeper will ask.
They are published on the release for a `v*` tag and are otherwise available as
workflow artifacts.

## What a run looks like

```
==============================================================================
synthetic.img
  7,340,032 bytes (7.0 MiB)
==============================================================================
  MBR      valid, 1 entries
    1  type 0xb1  LBA 2,048           4.0 MiB

  2 magic match(es): 2 CONFIRMED, 0 rejected as coincidence

  CONFIRMED qnx6 filesystem on MBR part 1  [little endian]
      2 superblock copies, 2 generations

      ACTIVE   serial 41   at 0x102000
        sb_ctime   2018-03-19 15:00:25 UTC
        sb_atime   2024-04-04 09:27:48 UTC
        version    4.3   blocksize 4,096   flags 0x00000000
        volume     4.0 MiB  (1,020 blocks, 966 free)   <- 99.6% of the 4.0 MiB partition
        inodes     20,000 total, 15,000 free, 5,000 used

      PREVIOUS serial 40   at 0x102e00   (still on disk)
        sb_ctime   2018-03-19 15:00:25 UTC
        sb_atime   2024-04-04 09:27:46 UTC

      WHAT CHANGED between the two generations
        serial       +1   (one commit)
        sb_atime     +2 s   (forward 2 seconds)
        free_blocks  -1  (1 block allocated)
        free_inodes  -1  (1 inode allocated)

  VERDICT: QNX6 filesystem present.
```

That output is from a synthetic image built by the self-test code, so nothing in it
came off a real device.

## Reading the timestamps

This is the part worth getting right, because it is easy to report the wrong thing.

- **`sb_ctime`** is written once, when the filesystem is created. It does not move.
- **`sb_atime`** moves when the filesystem is **committed**, not when a file is read.
  Do not read it as when the device was last used by a person.
- **`serial`** counts commits. It is the better measure of how much a volume has
  been written.

A qnx6 volume carries four superblock copies, and the tool groups them into
generations. The highest serial is the active one; the one below it is the previous
committed state, still on disk. The `WHAT CHANGED` block diffs the two, so you can
see what a single commit did.

## Deciding what to pull first

A head unit runs to tens of gigabytes and most of it is not evidence.

```
python3 qnxprobe.py --triage mmcblk0.img
```

## What an extraction is named, and how to check it

Every volume extracts under a directory named from the partition table, not from
the filesystem:

```
p2_lba65536                MBR primary 2
p6_lba13168672             second logical volume (logicals number from 5, as OSes do)
p3_lba16384_dps_mfg        GPT partition 3, carrying its name
lba0                       no partition table: a whole-disk filesystem or bare region
```

The LBA is the identity. It is a physical fact about the image that any partition
tool reproduces, and two volumes cannot share one, so names cannot collide. A
label is only ever a suffix. An LBA counts the disk's own logical sectors: 512
bytes on most disks, and 4096 on a disk whose GPT header sits at byte 4096, as on
4Kn drives and UFS LUN images, so `p1_lba300` on such a disk begins at byte
1,228,800.

The zip also carries `volumes.json`: per volume, the LBA and the sector size it
counts in (`sector_bytes`), byte offset, partition size, filesystem type, the recorded volume id or UUID, and what was extracted,
including `short` (files whose blocks reach past the end of the image) and, on a
volume that does, `extends_past_image_by_bytes`. On a split image `image` names the
first segment and `image_segments` lists every segment joined, with its byte count.
For a bare image with no vendor export alongside it, that file is the record
tying every extracted path back to a place on the disk, checkable against
`mmls` or `fdisk` without trusting the directory names.

`--triage` ranks the volumes by how much each has been written, using only what the
probe already read: the qnx6 superblock serial is a commit counter, and ext exposes
mount count and lifetime kilobytes written. It also samples filenames and says so
when they are encrypted, because a volume whose names are encrypted will not yield
to any parser without the keys.

Read the fill percentage alongside the ranking rather than sorting on size. Two
results from real vehicles, both counter-intuitive:

- On a 2024 BMW MGU the busiest volume on the disk was 36% encrypted filenames in a
  sample, so the ranking's top entry was the one least worth extracting.
- On a Ford Sync G4 the 4 MiB manufacturing volume ranked last with 16 commits, and
  it is the one holding the unit's Bluetooth and WiFi addresses, serials and TLS
  keys.

Activity finds the user data. It does not measure value per byte.

## Listing and extracting, without mounting

You do not need to mount anything. macOS ships 18 filesystems and qnx6 is not one of
them, the WSL2 kernel is built with `CONFIG_QNX6FS_FS` unset, and the free FUSE
options are Linux only. So the tool reads the filesystem directly instead.

```
python3 qnxprobe.py --list mmcblk0.img                      # walk and print the tree
python3 qnxprobe.py --list --depth 4 --list-max 3000 img    # deeper, higher cap
python3 qnxprobe.py --extract case.zip mmcblk0.img          # everything, into one zip
python3 qnxprobe.py --extract storage.zip --only storage img   # one volume by name
python3 qnxprobe.py --extract case.zip --exclude ECRYPTFS img  # leave out what will not parse
python3 qnxprobe.py --extract case.zip mmcblk0.img.001        # any segment of a split image; the set is joined
```

`--list` walks qnx6 through the same block resolution the kernel uses in
`qnx6_block_map()`, including multi-level indirect trees and long filenames held out
of line in the Longfile tree, and walks ext through its extent trees, or through the
classic block map of ext2 and ext3 (twelve direct pointers, then single, double and
triple indirect blocks). Both read-only.

A file is read by logical block, so a sparse file comes out at its declared size
with zeros where its holes are, and an extent the kernel wrote as uninitialized
reads as zeros too. That matters on an Android image: SQLite's `-shm` files and
MMKV stores are sparse, and a reader that concatenates the allocated blocks hands
back a shorter file with its pages in the wrong order. The two ext fixtures under
`tests/fixtures/` hold a hole first, a hole in the middle, a trailing hole past the
last block, a file that is nothing but hole and a 3 MiB file with data at both ends,
built with `mke2fs -d` from one tree (`tools/make_ext_fixtures.sh`); the self-test
requires every one to hash to what `sha256sum` recorded over that tree. A file whose
data is inline in its inode is read when it fits the inode's 60 bytes and refused,
by name, when the rest lives in an extended attribute this does not read.

The zip `--extract` produces is what a LEAPP tool ingests, so this replaces the mount
and the manual zip in one step. `--exclude` is repeatable.

## Reading an image from Python

Everything the command line does is reachable by importing the file, and the
entry point is `volumes()`, the callable form of the discovery the report does
while it prints. The window's Contents pane and the LEAPP tools read images
through it, and `qnxprobe_gui.py --check-discovery IMAGE` proves that it names
the same volumes the report does, on any image you give it.

```python
import qnxprobe as q

segments = q.split_segments(path)          # the .001/.002 set beside a segment, or None
image = q.open_image(path, segments)       # a plain file, a joined set, or an .E01
for vol in q.volumes(image):
    print(vol["name"], vol["kind"], vol["label"], vol["missing_past_end"])
    walker = vol.get("walker")            # None when the kind is not one this reads
    if walker is None:
        print("   ", vol["note"])
        continue
    for path, ino, size, mtime in q.collect(walker, walker.root):
        if size is None:                   # a symlink or special file
            continue
        for chunk in walker.read_file(ino, size):
            ...                            # the file's bytes, streamed
image.close()
```

Each dict names the region as the report does (`label`), gives its byte offset and
length (`base`, `size`) and its sector (`lba`, in the disk's logical sectors), the
directory an extraction uses
(`name`, see [What an extraction is named](#what-an-extraction-is-named-and-how-to-check-it)),
the filesystem (`kind`, or `not recognised`, or `extended container` for the MBR
entry that holds logical volumes) and, when the image holds only part of the
volume, `missing_past_end`, the bytes of it that lie past the end of the file. That
last field is how a lone first segment of a split image shows itself. FAT32 and
exFAT walkers hand back readings rather than instants for their times, as
described under [FAT32 and exFAT times](#fat32-and-exfat-times-are-readings-and-are-listed-as-such);
pass a dict as `times` to `collect()` to receive them.

`volumes()` reads only what identification needs. The walk and the reads happen
when you ask for them, so a consumer that wants a few files out of a 250 GiB disk
never touches the rest.

### Listing a whole volume

`collect()` returns the regular files in tree order, which is what an extraction
needs. Something that wants **everything**, directories included, should ask
`walk_all()` instead, because it takes a faster route where one exists.

```python
for path, node, mode, size, mtime, recorded in q.walk_all(walker):
    ...                                    # every file, directory, link and node
```

On NTFS it builds the listing from one sequential pass over `$MFT` rather than
from the directory indexes, and on APFS it reads the file-system tree's leaves
once rather than searching it per lookup. Measured on this Mac:

| | tree walk | `walk_all()` |
| --- | ---: | ---: |
| 7.4 GB Windows E01, 156,894 entries | 6.9 s | 2.0 s |
| 32 GB macOS E01, 625,543 entries | 147.0 s | 8.0 s |

The APFS route trades memory for it, roughly 900 MB on that 625,543-entry
volume, and a volume larger than `APFS_PRIME_MAX_RECORDS` is walked the
ordinary way instead of held.

Since 1.30. `walk_all()` **does not promise an order**, and on NTFS it answers a slightly
different question: it reads what each record says about itself rather than what
each directory says is in it. The two agree on every consistent volume measured
and differ on 4 entries of 313,652 on one acquisition where the volume's own
index and records disagree, and on 3 on another. `NtfsWalker.listing` says which
and what is known about why. `collect()` is unchanged.

## APFS

Every Mac since 2017 is APFS, so `--list` and `--extract` read a container. It is
claimed by the `NXSB` magic in the first block's object header together with a block
size that is a power of two, and only reported once its newest checkpoint and object
map have been read far enough to name the volumes inside it.

A container holds several volumes, and on a Mac the user's data is not the first of
them, so the container is listed as a **directory whose children are its volumes**.
One walk reaches all of them and each file lands under its volume's name.

What it reads: the checkpoint with the highest transaction id whose Fletcher-64
checksum is right, the container and volume object maps, the file-system B-tree,
directory records, inodes and their extended fields, file extents including sparse
ones, symbolic links, and files compressed with the `decmpfs` attribute in its zlib
forms.

What it does not do: an encrypted volume is named and not walked, and a file
compressed with LZVN or LZFSE is listed with its size and refuses to be read. Nothing
here reads a snapshot: what is walked is the volume as the newest checkpoint leaves it.

Validated against The Sleuth Kit's APFS support, an entirely separate implementation.
A 32 MiB container written by macOS itself and populated through its own driver ships
gzipped under `tests/fixtures`; the self-test walks it and requires all 411 files to
match hashes `fls` and `icat` recorded from the same image, and
`tools/make_apfs_fixture.sh` rebuilds it on any Mac as an ordinary user. It carries a
file in 2,046 extents, a sparse file whose hole is a real one, a compressed file, a
symbolic link, two names for one inode, a directory of 400 entries so the tree is
several levels deep, a UTF-16 name and an empty file.

Two defects the comparison found, both in the same place and neither visible by
reading: the object map's own tree points at blocks while the file-system tree points
at virtual ids, so reading the first through the second walks whatever happens to sit
at that offset; and a run of records can begin part way through the leaf before the
first one whose key matches, so starting at the matching leaf lost 13 of 400 children.

## HFS+

A Mac before APFS is an HFS+ volume, and so is an older iOS device, so `--list` and
`--extract` read one. The volume is claimed by the `H+` or `HX` signature 1024 bytes
into the volume together with a geometry that has to make sense.

What it reads: the catalog B-tree in both its index and leaf forms, forks whose
fragments outgrew the eight extent descriptors a catalog record holds and continue in
the extents overflow tree, symbolic links, hard links through the private directory
the volume keeps their indirect nodes in, and files compressed with the `decmpfs`
attribute in its zlib forms, whether the compressed data sits in the attribute or in
the resource fork behind a block table. A `--list` names a resource fork that carries
anything, because that is content the file's own size does not account for. HFSX, the
case-sensitive variant, is read the same way and reported as itself.

What it does not do: a file compressed with LZVN or LZFSE is listed with its recorded
size and refuses to be read, since neither is in the standard library.

Validated against The Sleuth Kit, which reads HFS+ through an entirely separate
implementation. A 24 MiB volume written by macOS itself and populated through its own
driver carries a fragmented file whose extents spilled into the overflow tree, a
compressed file, a symbolic link, two names for one file, a file with a resource fork,
a directory of 400 entries so the catalog is three levels deep, a name that needs
UTF-16 and an empty file. All 412 of its files come back byte for byte against hashes
`fls` and `icat` recorded from the same image, and the fixture ships with the tool so
the self-test compares against it. `tools/make_hfsplus_fixture.sh` rebuilds it on any
Mac, as an ordinary user, and refuses to finish if the image it wrote does not read
back as what it meant to write.

Six deliberate breaks each turn a different case red. The one that mattered was the
B-tree descent: every entry of a directory shares a parent id, so several index entries
carry that id with different names, and taking the last one that is not greater lands
on the last leaf of the run. A 400-entry directory came back with 10 children until the
comparison was strict.

## NTFS

An acquisition of a Windows computer is an NTFS volume, so `--list` and `--extract`
read one directly. The volume is claimed by the `NTFS` name in its boot sector plus a
geometry that has to make sense, and an NTFS boot sector is declined as a partition
table for the same reason a FAT one is: it ends in `0x55AA` and its boot code sits
where partition entries would be.

What it reads: resident and non-resident data, sparse runs, LZNT1 compressed data,
attributes that overflowed into other MFT records through `$ATTRIBUTE_LIST`, and
directory indexes in both the resident `$INDEX_ROOT` and the allocated
`$INDEX_ALLOCATION` form, with the sector fixups put back. Bytes past a file's
initialized size read as zero, which is what the format says and what a database that
preallocates its file depends on. A `--list` also names any alternate data stream it
finds, because a stream is content the file's own size does not account for.

What `--list` does not do: it lists what the directory indexes hold, so an 8.3 name
indexed beside a long one is skipped rather than listed twice, and an encrypted file is
listed with its recorded size and refuses to be read, since the volume holds no key.
Only the unnamed stream is the file's content. `NtfsWalker.stamps(record)` returns
the created, modified and accessed instants a file's `$STANDARD_INFORMATION` holds;
`entry()` carries only the modified one, which is what a listing needs.

Deleted files are recovered separately, from the MFT rather than the directory index.
`NtfsWalker.deleted_files()` yields every record that is marked free but still names a
file: its name, size, dates, and whether the content can still be read. A file whose
data was **resident**, small enough to sit inside the MFT record, is always recoverable
this way, and it is the only route to one, because it never occupied a cluster a carver
could find. A non-resident file is recoverable only while every cluster it used is still
free; once a later file has taken one, `read_deleted()` refuses it rather than hand back
bytes that now belong to something else, so overwritten data is never presented as the
file. `$ATTRIBUTE_LIST` is not followed for a deleted record, because it points at other
records that may since have been reused, so a file whose attributes overflowed its record
is reported as having existed rather than reconstructed from whatever now lives there.

Validated two ways. A 16 MiB volume written by `mkntfs` and populated through `ntfs-3g`
carries a resident file, an empty one, a sparse one, a compressed one, one fragmented
across 333 runs whose attributes had to move into other records, a file grown past what
was written into it, one record with 61 names, a directory of 400 entries so the index
outgrows its record, a name that needs UTF-16, an alternate data stream, and a resident
and a non-resident file that were created and then deleted; every one of its 475 live
files comes back byte for byte against hashes an independent reader recorded from the
same image, the two deleted files are recovered from the MFT and match the bytes written
before they were deleted (which The Sleuth Kit's `icat` confirms from the same records),
and that fixture ships with the tool so the self-test compares against it. On real evidence, a 231.9 GiB Windows volume inside a 232.9 GiB FTK Imager
acquisition: 221,851 live regular files in 9 seconds, the same set The Sleuth Kit's
`fls` reports, each resolving to the same MFT record, and 1,339 of 1,341 sampled files
byte-identical to `icat`. The two that differ are metadata files whose content lives
only in named streams, where the two tools pick different streams.

On a second real image, a small NTFS volume with a screen recording deleted from it,
`deleted_files()` finds the one deleted record `fls -d` reports and recovers its 5.8 MB
byte-identical to `icat`.

`tools/make_ntfs_fixture.sh` rebuilds the fixture on any Linux box with
`ntfsprogs` and `ntfs-3g`, as an ordinary user, and refuses to finish if the image it
wrote does not read back as what it meant to write. It creates the two deleted files
last, so nothing reuses their records or clusters, and records their hashes before
removing them.

That comparison earned its cost twice: it found this reader returning stale bytes past
a file's initialized size, and a second pass found the run list of a heavily fragmented
file counted twice because its own record is named in its attribute list.

### FAT32 and exFAT times are readings, and are listed as such

A FAT32 or exFAT file's times are a wall clock the volume stored with no zone
(exFAT stores a UTC offset beside each one, which is shown and not applied), so a
walker for either gives `entry()` an mtime of 0 and hands the readings out through
`listdir_records()` instead. `--list` prints them that way, `modified 2023-06-01
12:00:00 (as stored, no zone)`, never as an instant and never as `1970-01-01`,
and the window's Contents pane puts them in a **Recorded (as stored)** column with
the three (UTC) columns left blank.

### Deleted files on FAT32 and exFAT

FAT32 and exFAT recover deleted files too, through `Fat32Walker.deleted_files()` and
`ExfatWalker.deleted_files()` with the same `read_deleted()` reader. A FAT32 delete
writes `0xE5` over the first byte of the directory entry and frees its clusters in the
FAT; an exFAT delete clears the in-use bit of the entry's type byte and the file's bits
in the Allocation Bitmap. Either way the name, first cluster, size and recorded dates
survive, so a deleted file comes back with all of them.

What neither keeps is where a fragmented file's later clusters lay: FAT32 zeroes the
chain on delete, and exFAT keeps a chain only for a file it wrote fragmented in the
first place. So a file that occupied one run is recovered exactly, and one whose size
would need clusters that a later file has since taken is reported as having existed
rather than read, because reading it would splice in bytes that now belong to something
else. A recovered file says in `assumed_contiguous` whether its layout was taken on the
one-run assumption or from a chain the volume still held. A deleted directory whose
first cluster is still free and still parses as a directory is walked into, so a folder
of photographs deleted whole comes back file by file.

Validated the same way as NTFS. `tools/make_fat_deleted_fixtures.sh` builds a FAT32 and
an exFAT image, each with a folder of two photographs and one fragmented photograph,
created and then deleted; the self-test recovers them from the directory entries and
matches the hashes taken before deletion, and The Sleuth Kit's `icat` recovers the same
bytes from the same entries. The fragmented file that lands across reused space is
refused by this reader and is the one case `icat` will read on the contiguous
assumption; refusing it is the deliberate choice not to present bytes the entry cannot
vouch for.

## F2FS

F2FS is the filesystem Android uses for `/data` on most phones, so an Android
image or a bare `userdata` partition can carry one where an older device would have
ext4. `--list` and `--extract` read it directly. The volume is claimed by its 4-byte
magic 1024 bytes in, together with the reserved inode numbers the format fixes (node 1,
meta 2, root 3) and a block size and segment size it allows, rather than by the magic
alone.

What it reads: files stored inline in the inode, files addressed by the inode's own
pointer list, and larger files reached through direct, single- and double-indirect node
blocks; directories in both the inline and the multi-block form; and symbolic links.
Timestamps are real UTC instants, so a `--list` shows Modified and, in the window,
Created and Accessed. To find a file the reader resolves each node id through the Node
Address Table, choosing the current copy of each NAT block from the active checkpoint's
bitmap and applying any override in the checkpoint's NAT journal, exactly as the kernel
does.

What it does not do: a file with per-file encryption (the norm on a real Android
`/data`) is listed and its content refused, since the volume holds no key, and its name
is shown as stored; a compressed file (LZ4/LZO/zstd clusters) is listed with its
recorded size and not decompressed. See [What it does not do](#what-it-does-not-do).

Validated against two independent readers. On a fixture `mkfs.f2fs` and `sload.f2fs` wrote
(`tools/make_f2fs_fixture.sh`), every file inside the inode matches what `sha256sum`
recorded over the source tree, and the one file large enough to reach direct and
single-indirect node blocks matches what f2fs-tools' own `dump.f2fs` extracts. On a second
fixture the Linux kernel driver itself wrote by mounting a volume and writing sparse files
(`tools/make_f2fs_hole_fixture.sh`), files full of holes read back the same bytes the
kernel read, holes as zeros. That kernel-written image also carries seven NAT-journal
entries in the compact summary form, every one of them overriding an on-disk NAT entry
that reads unallocated, so the journal path is not just exercised but load-bearing there:
without it no file on that volume resolves. The journal in the normal (non-compact)
summary form is read by the same rules and is not exercised by either fixture. No real
F2FS volume is in the test corpus yet, and the double-indirect path (reached only past
about 8 GiB in one file) is not exercised at all.

A defect in 1.28 is worth knowing about: the bitmap that says which copy of each NAT
block is current was read with bit 0 as the least significant bit of a byte, but F2FS's
own `f2fs_test_bit` puts bit 0 at the most significant end. Every fixture then had that
bitmap all zero, so the two orders agreed and nothing showed it. A third fixture
(`tools/make_f2fs_free_fixture.sh`, root required) has the kernel write the volume in two
mount sessions, which rewrites NAT block 0 and sets the bitmap's first bit. Measured on
it: 1.28 finds no files at all, and the kernel reads 44; 1.29 reads the same 44 byte for
byte. So the failure of the old order is an empty walk that looks like an empty volume.
Fixed in 1.29, where the SIT version bitmap is read the same way, and that fixture's
self-test leg refuses to pass unless the bitmap really does carry a set bit.

The same fixture deletes a 1 MiB file, each of whose 256 blocks names its own index,
before the second checkpoint, on a `nodiscard` mount so the loop device does not zero
what it frees. All 256 blocks are still in the image and all 256 lie inside the runs
`free_extents()` reports, which is the property a carve scoped to free space depends on.
Both kernel-written fixtures also carry six SIT-journal entries that differ from the
on-disk table, so that override is load-bearing for the free-space answer too.

Since 1.29 `F2fsWalker.free_extents()` reports the space the volume says is free, from the
segment information table: one validity bit per block of the main area, 512 per segment,
set by the filesystem's own `f2fs_set_bit` (bit 0 at the top of the byte, the same trap as
above), the current copy of each SIT block chosen by the checkpoint's SIT version bitmap
and any entry in the cold-data summary journal overriding the table. Only the main area is
reported; the superblock, checkpoint, SIT, NAT and SSA areas are the filesystem's own. The
self-test holds it against the checkpoint's own `valid_block_count` and against position:
on both committed images the blocks live files and their nodes occupy equal that count
exactly, none of them lies in a reported run, and the runs plus those blocks tile the main
area. Read least-significant-first, the same map put 14 live blocks of one image inside
"free" runs while the total still matched, which is why the check is positional.

## Linux flash filesystems

Since 1.31. Embedded Linux keeps its filesystems on flash, and four formats cover most
of what turns up: SquashFS for a read-only system image, JFFS2 on NOR flash, UBI with UBIFS on NAND,
and YAFFS on older NAND. `--list` and `--extract` read all four, on their own or inside a
raw flash dump (see [Raw flash dumps and NAND spare bytes](#raw-flash-dumps-and-nand-spare-bytes)).
Each reader follows the kernel code (for YAFFS, Aleph One's own code) that reads the
format, cited line by line in the source and under
[Where the constants come from](#where-the-constants-come-from).

The fixtures come in two kinds. Most were written by the format's own tools
(squashfs-tools 4.7.5, mtd-utils 2.3.0, and Aleph One's yaffs2 built from source) from a
source tree chosen for its shapes, and each reader is held against oracles it never
touches: `sha256sum` over the source tree for the content of every file, and the tree's
own `stat` listing (for SquashFS, `unsquashfs -lln`) for the type, permissions, size and
modification time of every entry. Those tools write an image in one pass, so they leave no
history. The others carry history: the Linux kernel's own JFFS2, UBI and UBIFS drivers
(kernel 7.0.0), and YAFFS's own code, wrote them through a series of overwrites, deletions
and renames, and read them back, and that reading is the oracle. The scripts that build
them all are in `tools/`. None of these readers has yet been run against flash from a
real device; see [What it does not do](#what-it-does-not-do).

### SquashFS

A read-only, compressed filesystem, and the usual root filesystem of a router or a camera.
Version 4.0 is read. The 1.x to 3.x layouts, and their big-endian `sqsh` form, are
recognised and reported but not walked. A volume is claimed only when its superblock
passes the checks the kernel makes before it mounts one (a block size that agrees with its
own log, a compression id the format defines) and its root inode reads back as a
directory.

Every compressor mksquashfs offers is read: gzip, xz (including a BCJ filter), the legacy
lzma format, LZO, LZ4 and, on Python 3.14 or later, zstd. Files split into blocks, files
that end in a shared fragment, and holes are read; symlinks, hard links, device nodes and
FIFOs are listed. Extended attributes are not reported.

Validated on eight images, one per compressor plus an uncompressed one and one with 4 KiB
blocks: 612 of 612 files match `sha256sum` over the source tree, and 621 of 621 entries
agree with `unsquashfs -lln` on every image. The tree includes random bytes that the
4 KiB-block image stores uncompressed because they did not shrink, a file shaped to reach
an LZ decoder's rarer instructions, a directory of 600 entries (more than one directory
header and metadata block) and a 255-byte name.

### JFFS2

A log-structured filesystem with no superblock: the filesystem is whatever nodes the
region holds. It is claimed when the region's first bytes that are not erased flash
(0xFF) open a node whose header CRC holds, and a scan of the region finds inode or
directory nodes. Both byte orders are read.

Every node is scanned and its header CRC checked. A node the filesystem has marked
obsolete is ignored, and so is one whose data fails its own CRC, as the kernel's
`check_node_data` does, so an older copy of that data shows through where one exists; the
report counts the nodes dropped, and a name whose inode is left with no readable node is
not listed, and counted too. For
each name the newest version wins and a newer entry with inode 0 unlinks it; each file
takes its mode, owner and times from its newest inode node and is cut to that node's size.
The none, zero, rtime, zlib and LZO compressors are read; rubin, dynrubin and copy are
reported and not read. Erase block summary nodes are stepped over.

Validated on six images from `mkfs.jffs2` (both byte orders, zlib, LZO, rtime, none, and
one run through `sumtool`): 310 of 310 files and 317 of 317 entries match, and the two
device nodes carry the type and permissions the device table gave them. (`mkfs.jffs2`
stamps device nodes, and so `/dev`, with the time it ran, so their times are not compared.)

`mkfs.jffs2` writes each node once, so those images carry no history. Two more do, written
by the Linux kernel's JFFS2 driver through the history described under
[Kernel-written history](#kernel-written-history) below: one on NOR flash, where the kernel
marks each node it supersedes obsolete (154 on the committed image), and one on NAND
taken with `nanddump --oob`, where it cannot, so older nodes stay valid and only their
version numbers say which is current (24 directory entry nodes for 13 linked names, none
marked). The self-test prints these counts and fails if the history is gone.
Both match what the kernel reads back from them, 10 of 10 files and 13 of 13 entries.

### UBI and UBIFS

UBI is the volume layer raw NAND runs under: each eraseblock carries an erase counter
header, and a mapped one a second header naming the volume and logical block it holds.
The reader finds the eraseblock size from the distance between those headers, rebuilds
each volume from its blocks (of two copies of one block the higher sequence number wins,
unless it is a copy whose data CRC fails), and reads the volume table. A volume holding
UBIFS or SquashFS is listed as a folder named after the volume; any other volume, a kernel
image for example, as a single file holding its bytes. UBI records no time for a volume,
so none is shown for such a file.

UBIFS is read from its committed index, found through the master node, and then the
journal written since the last commit is replayed over it the way the kernel's
`replay.c` does: newer inode and data nodes in sequence order, an inode whose link count
reaches zero removed, a directory entry with inode 0 removing its name, and a truncation
dropping the blocks past the new size. LZO, zlib (raw deflate, as the kernel writes it),
uncompressed data and, on Python 3.14 or later, zstd are read, and a block the index does
not hold is a hole. A bare UBIFS image, as `mkfs.ubifs` writes it before `ubinize` wraps
it, is read too.

Validated on a bare `mkfs.ubifs` image and on five `ubinize` images (NAND with LZO, zlib,
zstd and no compression, and NOR), each with three volumes: the UBIFS volume matches 410 of
410 files and 416 of 416 entries, a static volume holding SquashFS matches 6 of 6 files,
and a static raw volume spanning two eraseblocks matches its hash. `mkfs.ubifs` commits
everything to the index and `ubinize` writes each block once, so in those images the
journal is empty and no block has a second copy.

A third image carries both. The Linux kernel's UBI and UBIFS drivers wrote it on simulated
NAND through the history described below, and it was taken with `nanddump --oob` while
UBIFS was still mounted, so the journal nodes written since the last commit (269 on the
committed image) have to be replayed over the index. Among them are a truncation, deletions, renames and a file created
with no name (`O_TMPFILE`), written, given an extended attribute and then linked in, which
leaves an inode record with no links after the file's data. Its static volume was written
twice, and the first version's two eraseblocks were put back into free eraseblocks from a
dump taken between the writes, the state a power cut during the rewrite leaves, so each of
its blocks has an older copy on the flash. The UBIFS volume matches what the kernel reads
back, 11 of 11 files and 14 of 14 entries, and the static volume the kernel's choice of its
second version. The report names the older copies:

```
        note         2 eraseblock(s): an older copy of a block, not the one read
```

### YAFFS1 and YAFFS2

NAND filesystems with no superblock: every page carries its tags in its spare bytes, and
the filesystem is rebuilt from the tags. The page size, spare size and where in the spare
the tags sit are recorded nowhere, and differ with the NAND controller, so they are found
by trying eleven common page and spare sizes (512+16 to 16384+1280) and, for YAFFS2,
every tag offset in the spare and both byte orders. A layout is accepted only when at least 90% of the used
spares hold plausible tags and at least 90% of the pages those tags call object headers
parse as object headers.

YAFFS2 is read the way its own scan reads it: blocks newest first, the newest object
header and the newest copy of each data page winning, data past a shrink or past the
newest header's size ignored, and a file's size taken from its newest header or from data
written after it, whichever is further. YAFFS1 orders two copies of a page by their 2-bit
serial number and takes a file's size from where its furthest live page ends. `lost+found`
is always listed, as YAFFS lists it; when the flash holds no header for it or for the root,
no time is shown for them, since YAFFS makes them at mount time.

Validated two ways. Aleph One's own image makers wrote four images (YAFFS2 little endian,
YAFFS2 with big-endian headers, YAFFS2 with its tags two bytes into the spare, and YAFFS1):
158 of 158 files and 164 of 164 entries match on each. And YAFFS's own code, run in user
space over a file standing in for NAND (`tools/yaffs_history.c`), wrote three images with
history: overwrites, a shrink and a regrow, holes, deletion, a rename, a hard link whose
first name was removed, enough churn for garbage collection to run, and a file flushed and
never closed, with no unmount at the end. The YAFFS1 images end in power cuts, one of them
leaving two live copies of a page with different bytes that only their serial numbers
order. The oracle for those is YAFFS's own code mounting a copy read-only and reading every
file back: 48 of 48, 49 of 49 and 2 of 2 files match, and every entry agrees.

### Raw flash dumps and NAND spare bytes

A dump read off a flash chip has no partition table (the kernel learns the flash layout
from the device tree or its command line, which the dump does not carry), and usually a
bootloader at offset 0. So when an image has no partition table and nothing is recognised
at its start, qnxprobe looks for SquashFS, UBI and JFFS2 at every 4 KiB boundary of an
image up to 8 GiB, checks each candidate the way identification does, and reports each one
it finds as its own volume, under `FLASH` in the report:

```
  FLASH    no partition table and nothing recognised at offset 0; 2 flash filesystem(s) found by their own headers
    @0x140000 squashfs       36.0 KiB  at byte 1,310,720
    @0x150000 jffs2           2.7 MiB  at byte 1,376,256
```

A SquashFS volume ends where its superblock says; UBI runs over the following eraseblocks
that carry the same image sequence number, or are erased; JFFS2 records no size, so it
runs to the next volume found or the end of the image. YAFFS has no header to search for,
so it is read only when it fills the image or a partition.

A NAND dump taken with its spare bytes (for example by `nanddump --oob`) holds each page's
data followed by its spare. YAFFS needs those bytes. For UBI and JFFS2 they are noise that
does not look like noise: the spare holds error-correction bytes and, on NAND, JFFS2's own
clean markers, and a UBI header in a 512-byte subpage sits inside the first page where the
spare cannot disturb it. So qnxprobe tries the common page and spare sizes, reading the
region with the spare stripped, when a UBI volume table does not read or no JFFS2 node
opens the region, and says so in the report:

```
        NAND         a raw dump: 2048-byte pages each followed by 64 spare bytes, read with the spare stripped
```

Validated two ways. On dumps built from the fixtures: a 4 MiB NOR layout with 1.25 MiB of
bytes no filesystem claims, then the SquashFS and JFFS2 images at 64 KiB boundaries, where
both are found at their offsets and every entry is read, and the UBI and JFFS2 images with
64 spare bytes after every 2 KiB page, where the geometry is found and every file matches.
And on the two kernel-written NAND images, each a `nanddump --oob` of one partition of the
kernel's simulated NAND chip (`nandsim`), where the geometry is found and every file
matches the kernel's reading. The first run on those two images read the files of neither: the UBI
dump mapped through its subpage headers and the JFFS2 dump opened with spare bytes, the
two cases the paragraph above now handles, and neither had shown on the dumps built from
fixtures. An image recognised at offset 0 is never searched further.

### Kernel-written history

`tools/make_kernel_flash_fixtures.sh` (Linux, root) builds the three kernel-written images.
It first writes and deletes more data than the volume holds, so garbage collection runs
and UBIFS commits, then makes the history: data overwritten in the middle and appended, a
shrink followed by data written past the old end, a truncate that grows, a file written
only far from its start, one file rewritten forty times, a deleted file and directory, a
rename across directories, a rename over an existing name, a hard link whose first name is
removed, a symlink, a permission change, and on UBIFS the unnamed file above. Every step
is fsynced, and nothing after the first phase calls `sync()`, which on UBIFS runs a commit.
The kernel then reads each image back: the NOR image through a copy mounted read-only, the
NAND ones after being written back to an erased partition or mounted read-only again, and
a second dump shows the kernel read the bytes that are committed (for UBI, only the two
stale eraseblocks changed, erased by the kernel as older copies).

These images are what make the history rules testable: a deliberate change to any of them
(newest version or name first, journal replay, truncation, name deletion, keeping a
relinked inode, the newest copy of a UBI block) turns the self-test red.

## Split images

FTK Imager and its peers write a raw image as numbered segments (`.001`, `.002`, ...)
unless told to write one file, and the first segment alone is a trap: it carries the
partition table and the boot volumes, so it identifies cleanly and its front volumes
read correctly, while the volume holding the user data ends past the cut, where every
read answers empty. Measured on a Ford Sync G4 image cut at 1,500 MB: every boot
partition extracted in full and the 28.8 GiB storage volume walked to 0 files with
nothing raised.

Since 1.13 the tool joins the set itself. Name any one segment and every segment
beside it (same folder, same stem, same number of digits) is read as one image, in
order, with nothing copied or concatenated on disk:

```
python3 qnxprobe.py --extract case.zip mmcblk0.img.001    # .001 through the last segment beside it
```

The report says what was joined (`20 segments joined, mmcblk0.img.001 ..
mmcblk0.img.020`, with the segment sizes), and in `volumes.json` every volume's
`image` names the first segment while `image_segments` lists each one with its byte
count, so the extraction can be checked back against the set.

A set is joined only when it is whole from its first segment. A hole in the numbering
(`.001` and `.003` with no `.002`), a set whose lowest segment is not `.000` or `.001`,
and segments numbered at two different widths are each refused by name, with exit
status 1, because a set joined around a hole reads every volume past it at the wrong
offset and answers wrong rather than empty. A set that simply ends early cannot be
told from a small disk by its numbering; that case is caught the other way, by the
partition table reaching past the joined size, which draws the
`IMAGE IS SHORTER THAN ITS PARTITION TABLE` warning described under "What it does not
do".

## EnCase/EWF images

An `.E01` acquisition is read directly, so a run on one works exactly like a run
on a raw image:

    python3 qnxprobe.py evidence.E01

The segments of a multi-segment acquisition are joined by the reader from the
format's own records, not from the file names, and an acquisition missing a
segment is refused rather than read short. Point it at the `.E01`; the rest of
the set is found beside it.

This is `ewfprobe.py`, vendored from
[abrignoni/ewfprobe](https://github.com/abrignoni/ewfprobe) and recorded in
`vendored.json`. It is MIT, pure Python and standard library only, so it adds
nothing to build and nothing to install. `tools/check_vendored.py` confirms the
copy still matches what was vendored, and reports a copy it could not check
separately from one that has drifted, because those are different results.

The reader is optional. Without `ewfprobe.py` beside this script everything else
works as before, and an `.E01` is refused with a message saying what is missing.
It is never read as raw bytes: a container read that way holds no filesystem the
walkers can see, so the run would report an empty image instead of saying it
could not read the container.

Measured with 1.27 on a 15-segment FTK Imager acquisition of a 232.9 GiB Windows
disk: the segments join, the GPT and its four partitions are read, the EFI system
partition is identified as FAT32 and the basic data and recovery partitions as
NTFS, all in about a second. Only the 16 MiB Microsoft reserved partition is
reported as not recognised, with its first bytes shown.

## Options

| Option | What it does |
| --- | --- |
| `--list` | Walk each filesystem found and list its contents (qnx6, qnx4, ext2/3/4, F2FS, FAT32, exFAT, NTFS, HFS+, APFS, ETFS, EFS and QNX IFS boot images) |
| `--depth N` | How deep to walk with `--list` (default 2) |
| `--list-max N` | Stop after this many entries per filesystem (default 400) |
| `--extract OUT.zip` | Copy the logical files out of every filesystem into a zip |
| `--only TEXT` | Restrict `--list` and `--extract` to partitions whose name or label contains TEXT |
| `--exclude TEXT` | Skip any path containing TEXT when extracting. Repeatable |
| `--triage` | Rank volumes by how much each has been written, and flag encrypted or bulk ones |
| `--progress` | While extracting, emit one JSON progress object per line on stderr, for a caller driving this as a subprocess. The report on stdout is unchanged |
| `--scan-limit MiB` | How far to brute scan when no superblock sits at the offsets the kernel checks (default 256) |
| `--self-test` | Build throwaway positive and negative images, confirm the detector reports both ways, then delete them |
| `--version` | Print the version |

## The self-test, and why it is not decoration

Run it once before you trust a negative result on real evidence.

```
python3 qnxprobe.py --self-test
```

It builds throwaway images in a temp directory, some that must be detected and one
that must not, across qnx6 (both endians), QNX4, ext4, ext2, F2FS, FAT32, exFAT, NTFS, HFS+, APFS, ETFS, EFS and QNX IFS,
checks them, and removes the directory. For ETFS it also round-trips one file out of
a synthetic image, so a broken structure offset, not just a broken constant, turns
the leg red. For IFS the UCL decoder is run against a fixed synthetic block whose
expected output is written out by hand, and a flipped byte in a synthetic imagefs
must break the image checksum, so a regression in the decompressor or the walk
turns a leg red rather than passing against itself.

The expected values in it are written as literal bytes rather than derived from the
constant they verify. That matters: an earlier version built its fixtures from
`QNX6_MAGIC`, and it passed with the magic deliberately corrupted to `0x68191123`,
which is a build that cannot identify a single real filesystem. A test whose fixture
moves with the bug is not a test. The same discipline covers the ETFS reserved names
and the EFS `QSSL_F3S` signature: break one of those literals and the self-test
exits 1.

## A magic match is not a finding

Across a 256 MiB scan you expect roughly one 4-byte magic hit by chance. Every
candidate is therefore parsed as a superblock and its fields checked for internal
consistency before it is reported CONFIRMED. The run tells you how many matches were
rejected as coincidence.

## Where the constants come from

Nothing here is assumed. Every constant and field offset is read out of the
producer's own source.

QNX6, from the Linux kernel's qnx6 driver:

```
QNX6_SUPER_MAGIC     0x68191122   include/uapi/linux/magic.h:55
QNX6_BOOTBLOCK_SIZE      0x2000   include/linux/qnx6_fs.h:23
QNX6_SUPERBLOCK_SIZE      0x200   include/linux/qnx6_fs.h:21
struct qnx6_super_block               include/linux/qnx6_fs.h:94
```

`fs/qnx6/inode.c` reads the first superblock at `QNX6_BOOTBLOCK_SIZE` and, if the
magic is wrong there, retries at offset 0. It tries little endian first, then big
endian, so both are live in the wild and both are checked.

ext2/3/4:

```
EXT2_SUPER_MAGIC     0xEF53   linux/include/uapi/linux/magic.h:24
EXT4_EXT_MAGIC       0xf30a   linux/fs/ext4/ext4_extents.h
struct ext4_super_block, ext4_group_desc, ext4_inode, ext4_dir_entry_2
                              linux/fs/ext4/ext4.h
```

The ext field offsets were derived from that header and cross-checked against its own
`/*NN*/` offset markers, all fifteen of which agreed, with the struct totalling the
expected 1024 bytes.

F2FS, from the Linux kernel at v7.0 (commit
`028ef9c96e96197026887c0f092424679298aae8`):

```
F2FS_SUPER_MAGIC     0xF2F52010   include/linux/f2fs_fs.h
struct f2fs_super_block, f2fs_checkpoint, f2fs_inode, node_footer,
  f2fs_dir_entry, f2fs_dentry_block, f2fs_nat_entry
                                  include/linux/f2fs_fs.h
current_nat_addr, get_node_path   fs/f2fs/node.{h,c}
validate_checkpoint               fs/f2fs/checkpoint.c
sanity_check_raw_super            fs/f2fs/super.c
read_normal_summaries             fs/f2fs/segment.c   (the NAT journal)
do_read_inode                     fs/f2fs/inode.c
f2fs_fill_dentries                fs/f2fs/dir.c
```

The inode's address count, the direct/indirect node layout and the NAT block
addressing are all parameterised by the superblock's block size, so a 4K-block
and a 16K-block volume are read the same way.

QNX IFS boot images, from QNX's own `dumpifs` and `sys/image.h`:

```
STARTUP_HDR_SIGNATURE  0x00ff7eeb   qnx sys/startup.h:88
STARTUP_HDR_VERSION             1   qnx sys/startup.h:89
struct startup_header               qnx sys/startup.h
flags1 compression, block framing   qnx dumpifs.c  (none/zlib/lzo/ucl)
struct image_header, image_dirent   qnx sys/image.h
UCL NRV2B (_8) decompressor          Oberhumer UCL src/n2b_d.c, src/getbit.h
```

The startup header's field widths sum to 256 bytes, which each image's own
`header_size` field confirms, and the `machine` field is an ELF machine type
(`EM_386` 3, `EM_ARM` 40, `EM_X86_64` 62, `EM_AARCH64` 183 from
`linux/include/uapi/linux/elf-em.h`). `flags1` gives the compression method; a
compressed imagefs is a run of blocks, each a two-byte big-endian length then
that many bytes decompressing to at most 64 KiB, ending at a zero length. Each
UCL block is NRV2B, ported from Oberhumer's UCL into a small pure-Python decoder
so the tool still installs nothing, and `zlib` images are read through the
standard library. The decompressed image is walked from its `image_header` and a
flat table of `image_dirent` records.

This is proven byte for byte against the Ford Sync G4 `ifs_a`, `ifs_b` and
`ifs_recovery` volumes: each decompressed to exactly the `imagefs_size` its own
header records, the 32-bit words from the header through the `image_trailer`
summed to zero against the trailer's checksum, and the extracted files were
valid, including the AArch64 ELF kernel `procnto-smp-instr` whose machine matched
the startup header. That checksum is reported on every run as a decode self-check.

QNX4, from the Linux kernel's read-only qnx4 driver, the same sourcing as qnx6:

```
QNX4_SUPER_MAGIC       0x002f   linux/include/uapi/linux/magic.h:54
struct qnx4_inode_entry         linux/include/uapi/linux/qnx4_fs.h:44
struct qnx4_link_info           linux/include/uapi/linux/qnx4_fs.h:63
struct qnx4_xblk ("IamXblk")    linux/include/uapi/linux/qnx4_fs.h:71
field widths                    linux/include/uapi/linux/qnxtypes.h
directory entry union           linux/fs/qnx4/qnx4.h:75
```

The `0x002f` magic is simply the `/` name of the root directory inode at the
start of the superblock, 512 bytes into the volume. Blocks are 512 bytes and
1-based on disk. A directory's data is a run of 64-byte entries: a name up to
16 bytes is a full inode entry stored inline, a longer name (up to 48) is a
link entry resolving to the real inode by block and index, conventionally
inside the `.inodes` file. A file's extents 2..n live in a chain of `IamXblk`
blocks, followed exactly as `fs/qnx4/inode.c qnx4_block_map()` follows them.
Detection requires what the kernel itself requires to mount: the `/` root
inode with a directory mode and a `.bitmap` entry in the root directory
(`qnx4_checkroot`). A QNX4 boot block can end in `0x55AA`, so the MBR parser
declines a sector whose following sector is a QNX4 root superblock, the same
shared-magic rule as FAT above.

A qnx6 boot block can end in `0x55AA` as well: on qnxmount's qnx6 reference image
sector 0 is x86 boot code, and its bytes at 446 parse as two partitions starting
1.5 and 1.8 TB into a 400 KB file. Taking that table at face value hid the
filesystem entirely, since the qnx6 at offset 0 then had no partition to be listed
or extracted from and its end-of-volume superblock, the active generation, was never
probed. So the MBR parser first checks for a consistent qnx6 superblock at `0x2000`,
the offset the Linux driver reads (`fs/qnx6/inode.c`, `qnx6_fill_super`), and
declines the sector if one is there. As a last resort it also declines any table none
of whose partitions begins inside the image. The boot indicator byte is not used as a
test, because neither util-linux's libfdisk nor The Sleuth Kit rejects a table on it.
The self-test builds an image of this shape and requires both superblock copies to be
found and the volume to be listed.

Since 1.31 the GPT is read as UEFI 2.10 section 5.3 lays it out. The primary header is at LBA 1,
so its byte offset is the logical sector size: 512 on most disks, 4096 on 4Kn drives
and UFS LUN images, and both are tried. A header is used only when it passes the four
checks the spec lists in section 5.3.2: the `EFI PART` signature, HeaderCRC32 over
HeaderSize bytes with that field set to zero, MyLBA naming the block it was read from,
and the CRC32 of the partition entry array, with the offsets from Table 5.5 and the
entry fields from Table 5.6. When the primary fails, the backup header in the last
logical block is read, as that section says to, but only when sector 0 holds a
protective `0xEE` record, because the same section warns that a disk reformatted to a
legacy MBR can keep a stale GPT there. The report names every header it did not use
and why, and says when the backup was the one read. On a 4096-byte disk the MBR's LBAs
are counted in 4096-byte sectors too: Table 5.4 starts the protective record at LBA 1,
"the LBA of the GPT Partition Header". The self-test builds a GPT at each size around
the ext4 fixture and requires the volume at the byte its entry names. Those images read
the same in The Sleuth Kit's `mmls -b 4096` and in util-linux `sfdisk --sector-size
4096`, and a GPT that `sfdisk` wrote with 4096-byte sectors is read as `sfdisk` wrote it.

The QNX4 reader was validated by round-trip against the Linux kernel driver
itself: a fixture populated with nested directories, a multi-extent file, a
long name, a symlink, an empty file and distinct modes, owners and mtimes was
mounted read-only with `fs/qnx4` on kernel 7.0.0, and every path, type,
permission, owner, size, mtime, symlink target and byte of content the kernel
reported matched what this walker reads, 15 of 15 entries. The fixture was
written by a separate generator program (its skeleton follows Peter
Waechtler's Linux-side QNX4 `dinit`, a second independent statement of the
layout), not by this parser, so the two sides are independent.

QNX ETFS and EFS, from [NetherlandsForensicInstitute/qnxmount](https://github.com/NetherlandsForensicInstitute/qnxmount)
(Apache-2.0):

```
etfs_trans, fid scheme, ftable + dir entry   qnxmount/etfs/parser.ksy -> fs/etfs.h
F3S extent, unit, boot, dir entry            qnxmount/efs/parser.ksy  -> fs/f3s_spec.h
```

qnxmount is a peer institute's vehicle-forensics reader. Its ETFS spec cross-references
QNX's own `fs/etfs.h` and its EFS spec `fs/f3s_spec.h`; only the field layouts are
transcribed here, into the same hand-written struct style, so the Kaitai runtime is not
a dependency and the tool stays standard library only. Both readers were validated by
extracting qnxmount's own committed test images and comparing every name, mode, owner,
timestamp, symlink target and byte of content against the tar archive built from the
same live filesystem, which qnxmount produced on QNX independently of this code: ETFS
matched 32 of 32 entries, EFS 31 of 31. ETFS has no magic, so it is claimed only when
the page geometry divides evenly and the `.filetable` carries its fixed reserved names
at their fixed ids; EFS is claimed by its `QSSL_F3S` boot record. Neither fired on the
u-boot, boot_fs or ext partitions of the two vehicle images tested.

SquashFS, JFFS2, UBI and UBIFS, from the Linux kernel at v7.0 (commit
`028ef9c96e96197026887c0f092424679298aae8`):

```
SQUASHFS_MAGIC  0x73717368 ("hsqs")     include/uapi/linux/magic.h:20
struct squashfs_super_block             fs/squashfs/squashfs_fs.h:241
inode, directory, fragment layouts      fs/squashfs/squashfs_fs.h:270-424
metadata block 8 KiB, bit 15 stored     fs/squashfs/squashfs_fs.h:19,106
data block, bit 24 stored               fs/squashfs/squashfs_fs.h:113
JFFS2_MAGIC_BITMASK 0x1985, old 0x1984  include/uapi/linux/jffs2.h:24-25
JFFS2 compressor ids                    include/uapi/linux/jffs2.h:41-48
struct jffs2_unknown_node, raw_dirent,  include/uapi/linux/jffs2.h:102,111,135
  raw_inode
UBI_EC_HDR_MAGIC "UBI#", VID "UBI!"     drivers/mtd/ubi/ubi-media.h:29,31
struct ubi_ec_hdr, ubi_vid_hdr          drivers/mtd/ubi/ubi-media.h:147,268
UBI_CRC32_INIT 0xFFFFFFFF               drivers/mtd/ubi/ubi-media.h:26
layout volume 0x7FFFEFFF                drivers/mtd/ubi/ubi-media.h:294,298
struct ubi_vtbl_record (172 bytes)      drivers/mtd/ubi/ubi-media.h:355
UBIFS_NODE_MAGIC 0x06101831             fs/ubifs/ubifs-media.h:25
superblock, master and log LEBs         fs/ubifs/ubifs-media.h:227-231
key: block or hash bits 29              fs/ubifs/ubifs-media.h:199
```

How each reader chooses among versions and copies is taken from the code that makes the
choice, and cited beside the Python that follows it: `fs/jffs2/readinode.c`
(`check_node_data`, `read_direntry`, `jffs2_do_read_inode_internal`) for JFFS2,
`drivers/mtd/ubi/attach.c` (`ubi_compare_lebs`) for UBI, and `fs/ubifs/replay.c`
(`apply_replay_entry`, `inode_still_linked`, `trun_remove_range`) for the UBIFS journal.

LZO and LZ4 are not in the standard library, so both are carried as pure-Python decoders.
LZO1X is written from the kernel's `Documentation/staging/lzo.rst` and
`lib/lzo/lzo1x_decompress_safe.c` at the same commit, and LZ4 from
`doc/lz4_Block_format.md` in lz4 at v1.10.0 (commit
`ebb370ca83af193212df4dcbadcc5d87bc0de2f0`). Every fixture compressed with them reads back
byte for byte, and each source tree carries a file shaped to reach the decoders' rarer
instructions. LZO-RLE, the second LZO bitstream, which zram writes and none of these
filesystems does, is refused rather than decoded. The kernel does not read SquashFS's
legacy lzma format, so that one follows squashfs-tools' own `lzma_xz_wrapper.c` at commit
`708c59ae80853b0845017c33b42e56061cc546cd`.

YAFFS1 and YAFFS2, from Aleph One's
[yaffs2](https://github.com/Aleph-One-Ltd/yaffs2) at commit
`474b3acb927d27b2305618aaf24456b9d33fe91b`. The object header's field offsets were printed
with `offsetof()` from that tree's own headers rather than counted by hand:

```
object ids: root 1 .. summary 0x10      core/yaffs_guts.h:94-100
sequence numbers 0x1000..0xefffff00     core/yaffs_guts.h:123-124
struct yaffs_spare (YAFFS1 tags)        core/yaffs_guts.h:225
struct yaffs_obj_hdr (512 bytes)        core/yaffs_guts.h:330
YAFFS2 packed tags and their ECC        core/yaffs_packedtags2.c
YAFFS2 scan                             core/yaffs_yaffs2.c yaffs2_scan_chunk
YAFFS1 tags and deletion                core/yaffs_tagscompat.c, core/yaffs_yaffs1.c
root and lost+found modes 0755, 0700    direct/ydirectenv.h:99-100
```

`--help` prints this same sourcing, so it travels with the tool.

## What it does not do

- **It reads raw images and E01 acquisitions only.** A raw image is one file or the
  numbered segments of one, and an E01 is read through `ewfprobe.py` (see
  "EnCase/EWF images" above). AFF4, AD1 and the other evidence containers are not
  decoded; such a file is read as plain raw bytes, so export the raw image from the
  imaging tool first. A segment set is joined only when it is whole from its first
  segment (see "Split images" above). A lone first segment is read as the file it is,
  and since 1.12 a run on it says `IMAGE IS SHORTER THAN ITS PARTITION TABLE`, names
  the partitions that reach past the end, marks each affected volume `INCOMPLETE` in
  the report and in `volumes.json` (`extends_past_image_by_bytes`), and stores a file
  whose blocks lie past the cut under a name ending `.SHORT-<here>-of-<size>-bytes`,
  counted as `short` rather than as extracted.
- **A 4096-byte-sector disk is recognised by its GPT.** A 4Kn disk that carries only
  a legacy MBR states its sector size nowhere, so its LBAs are read as 512-byte
  sectors. Sector sizes other than 512 and 4096 are not probed. A GPT header that fails
  a check is reported and not used, and nothing is ever written back to restore one.
- **Some IFS compression is recognised but not read.** UCL, zlib and uncompressed
  QNX IFS boot images are listed and extracted; `lzo`-compressed images and the Harman
  Becker HBCIFS container are recognised and reported but not decompressed, because no
  sample exists to validate a reader against. A big-endian IFS is declined the same way.
  In each case the header is still reported and the walk is declined out loud.
- **It does not decrypt.** A volume with encrypted filenames is flagged, not opened.
  On F2FS, a real Android `/data` uses per-file encryption: such a file is listed and
  its content refused rather than guessed at.
- **F2FS compression is recognised but not read.** A file compressed with F2FS's LZ4,
  LZO or zstd clusters is listed with its recorded size and not decompressed.
- **F2FS is validated against synthetic fixtures, not yet against a real F2FS volume.**
  Two independent readers are the oracles: f2fs-tools' `dump.f2fs` for inline data,
  directories, the inode's own pointers and direct and single-indirect node blocks, and
  the Linux kernel driver itself for files full of holes. No real F2FS volume is in the
  test corpus, so the NAT-journal override is implemented and sourced but not exercised (a
  cleanly unmounted image has an empty journal), and the double-indirect path (past about
  8 GiB in one file) is not exercised at all.
- **It does not write.** The image is opened read-only. The Linux qnx6 driver has no
  write path at all, so mounting a qnx6 volume on Linux cannot alter these timestamps
  either.
- **QNX4 is validated against a synthetic fixture, not yet against a real QNX4
  volume.** The round-trip oracle is the Linux kernel's own `fs/qnx4` driver, an
  independent implementation, but no confirmed real QNX4 volume exists in the
  test corpus; the one candidate partition (a Ford Sync G4 slot named
  `boot_fs`) turned out to carry a `RAW0` container, not QNX4.
- **ETFS and EFS are validated against qnxmount's synthetic test images, not yet
  against a real vehicle extraction.** No confirmed ETFS or EFS volume was available to
  test on. ETFS in particular keeps its transaction metadata in the NAND spare/out-of-band
  area, so an ETFS volume is only readable if the acquisition captured that spare area;
  an image that dropped it will not divide into pages and will be reported as not
  recognised rather than misread.
- **The Linux flash filesystems are validated against images their own tools and the
  Linux kernel wrote, not yet against flash from a real device.** The NAND images come
  from the kernel's simulated chip (`nandsim`), not from hardware, and the older copies in
  the UBI image were put there from an earlier dump rather than left by a real power cut.
  UBI's fallback to an older copy when a moved block's data CRC fails is implemented and
  sourced but not exercised. YAFFS2's skipping of block summary chunks is exercised (the
  YAFFS2 history image holds 24) but decides nothing there: those chunks reach no listing
  either way.
- **Some flash compression is recognised but not read.** zstd needs Python 3.14 or later
  (`compression.zstd`). On an older Python a zstd SquashFS is identified but cannot be
  listed, since its directory tables are compressed too; since 1.34 `volumes()` carries
  the reason as the volume's note, so the report, the window and a LEAPP run log say why
  it lists nothing. In UBIFS each file whose data
  is zstd-compressed is named and refused. The executables published with v1.31 and v1.32
  were built on Python 3.12 and so do not read zstd; later ones are built on 3.14 and do.
  JFFS2's rubin, dynrubin and copy compressors are reported and not read, and LZO-RLE is
  refused.
- **Older and unusual flash layouts are not walked.** SquashFS 1.x to 3.x (and its
  big-endian `sqsh` form) and JFFS2's original 0x1984 layout are recognised and reported.
  YAFFS2 with inband tags (kept inside the page, on NAND with no usable spare) is not
  recognised at all.
- **Deleted data on flash is not recovered.** Each flash reader returns the filesystem's
  current state, the way the filesystem itself reads it. Older versions still on the flash
  (JFFS2's obsolete nodes, YAFFS's superseded pages, UBI's old copies of a block) are used
  only where the filesystem itself would use them.
- **Encrypted and authenticated UBIFS.** Encryption is not undone: a file fscrypt marks as
  encrypted has its content refused rather than returned, and encrypted names are not
  decrypted. The hashes of an authenticated volume are not checked. Neither case is in the
  fixtures. Extended attributes are not reported on any of the flash filesystems.
- **A raw flash dump is searched only for SquashFS, UBI and JFFS2**, only when it has no
  partition table and nothing is recognised at offset 0, and only up to 8 GiB. Its spare
  bytes are stripped only for UBI and JFFS2, and only for the common page and spare sizes.
  NAND dumps with spare bytes were tested as dumps of one partition each; a filesystem
  that starts further into such a dump has not been tested.

## License

MIT. See [LICENSE](LICENSE).
