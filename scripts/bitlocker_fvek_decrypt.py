#!/usr/bin/env python3
"""
Standalone BitLocker AES-XTS-128 sector decrypter using a recovered FVEK.

Bypasses dislocker/libbde (which lack AES-XTS support in this environment) by
decrypting the data area directly with the FVEK + tweak key recovered from a
memory dump. Writes a decrypted raw image that TSK can then read as NTFS.

Uses ctypes + OpenSSL EVP for ~180 MB/s throughput.

Usage:
  python3 bitlocker_fvek_decrypt.py <encrypted_partition.raw> <fvek_file(32B)> \
         <output.raw> [--max-sectors N] [--data-start-sector N] [--sector-base N] \
         [--inplace] [--ewf <E01_file> [--partition-offset <sectors>]]

Modes:
  Normal:   reads <encrypted_partition.raw>, writes <output.raw>
  --inplace: decrypts in-place (reads AND writes <encrypted_partition.raw>)
  --ewf:    runs ewfexport internally to extract from E01, then decrypts

The FVEK file is 32 bytes: key1 (FVEK, 16B) || key2 (tweak, 16B), as emitted by
the volatility3 bitlocker_fvek_scan plugin (--dump).

The BitLocker data area begins at a sector whose decrypted content is the NTFS
boot sector (magic "EB 52 90 ... NTFS"). This script auto-detects that sector
(sweeping the first ~16 MB) unless --data-start-sector is given. The tweak key
basis is the ABSOLUTE (physical) sector index within the partition.

If the input file does NOT begin at the partition's physical sector 0 (e.g. it
was extracted starting mid-partition), pass --sector-base N where N is the
physical sector index of the file's first sector. The output file starts at the
NTFS boot sector so TSK sees a plain NTFS volume.
"""
import sys, os, struct, time, ctypes, ctypes.util, subprocess, tempfile

SECTOR = 512
BATCH = 4096  # sectors per progress report

# ── OpenSSL ctypes bindings ──────────────────────────────────────────────
_lib = ctypes.CDLL(ctypes.util.find_library('crypto'))

_lib.EVP_CIPHER_CTX_new.restype = ctypes.c_void_p
_lib.EVP_CIPHER_CTX_free.argtypes = [ctypes.c_void_p]
_lib.EVP_aes_128_xts.restype = ctypes.c_void_p

_lib.EVP_CipherInit_ex.argtypes = [
    ctypes.c_void_p,   # EVP_CIPHER_CTX *
    ctypes.c_void_p,   # const EVP_CIPHER *
    ctypes.c_void_p,   # ENGINE *impl (NULL)
    ctypes.c_char_p,   # const unsigned char *key
    ctypes.c_char_p,   # const unsigned char *iv (tweak)
    ctypes.c_int,      # int enc (0=decrypt, 1=encrypt)
]
_lib.EVP_CipherInit_ex.restype = ctypes.c_int

_lib.EVP_CipherUpdate.argtypes = [
    ctypes.c_void_p,   # EVP_CIPHER_CTX *
    ctypes.c_char_p,   # unsigned char *out
    ctypes.POINTER(ctypes.c_int),  # int *outl
    ctypes.c_char_p,   # const unsigned char *in
    ctypes.c_int,      # int inl
]
_lib.EVP_CipherUpdate.restype = ctypes.c_int


class XTSDecrypter:
    """Batch AES-XTS-128 decrypter via OpenSSL EVP (ctypes)."""

    def __init__(self, key_bytes: bytes):
        assert len(key_bytes) == 32
        self._key = key_bytes
        self._ctx = _lib.EVP_CIPHER_CTX_new()
        if not self._ctx:
            raise RuntimeError("EVP_CIPHER_CTX_new failed")
        self._cipher = _lib.EVP_aes_128_xts()
        self._outbuf = ctypes.create_string_buffer(SECTOR)
        self._outlen = ctypes.c_int(0)

    def decrypt_sector(self, sector_index: int, ct: bytes) -> bytes:
        """Decrypt one 512-byte sector. Returns 512-byte plaintext."""
        tweak = struct.pack('<QQ', sector_index, 0)
        rc = _lib.EVP_CipherInit_ex(
            self._ctx, self._cipher, None,
            self._key, tweak, 0  # 0 = decrypt
        )
        if rc != 1:
            raise RuntimeError(f"EVP_CipherInit_ex failed: {rc}")
        rc = _lib.EVP_CipherUpdate(
            self._ctx, self._outbuf, ctypes.byref(self._outlen),
            ct, SECTOR
        )
        if rc != 1:
            raise RuntimeError(f"EVP_CipherUpdate failed: {rc}")
        return self._outbuf.raw[:SECTOR]

    def close(self):
        if self._ctx:
            _lib.EVP_CIPHER_CTX_free(self._ctx)
            self._ctx = None

    def __del__(self):
        self.close()


# ── Core logic ───────────────────────────────────────────────────────────

def find_data_start(xts: XTSDecrypter, data: bytes, sector_base=0, scan_mb=16):
    """Find the sector whose decrypted content is the NTFS boot sector.

    sector_base: physical sector index of the file's first sector (0 if the file
    begins at the partition's sector 0). The tweak basis is the absolute
    physical sector = sector_base + (file_offset // SECTOR).
    """
    limit = min(len(data), scan_mb * 1048576)
    for off in range(0, limit, SECTOR):
        idx = sector_base + (off // SECTOR)
        pt = xts.decrypt_sector(idx, data[off:off+SECTOR])
        # NTFS VBR: jump (EB 52 90) + OEM "NTFS    "
        if len(pt) >= 11 and pt[0] == 0xEB and pt[2] == 0x90 and pt[3:8] == b'NTFS ':
            return idx
    return None


def extract_partition_from_ewf(ewf_path, part_offset_sectors, part_size_sectors, output_path):
    """Extract a partition from an EWF image using ewfexport."""
    cmd = [
        "ewfexport",
        "-o", str(part_offset_sectors),
        "-B", str(part_size_sectors * SECTOR),
        "-t", output_path,
        ewf_path
    ]
    print(f"Extracting partition: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ewfexport stderr: {result.stderr}")
        raise RuntimeError(f"ewfexport failed with code {result.returncode}")
    # ewfexport appends .raw to a target prefix. Callers must pass a prefix
    # without an extension so the result cannot accidentally become .raw.raw.
    actual = output_path + ".raw"
    print(f"Extracted to: {actual} ({os.path.getsize(actual)/1e9:.2f} GB)")
    return actual


def main():
    if len(sys.argv) < 4:
        print(__doc__); sys.exit(1)
    src, fvek_file, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    max_sectors = None
    data_start = None
    sector_base = 0
    inplace = False
    ewf_path = None
    part_offset = None

    i = 4
    while i < len(sys.argv):
        if sys.argv[i] == "--max-sectors" and i+1 < len(sys.argv):
            max_sectors = int(sys.argv[i+1], 0); i += 2
        elif sys.argv[i] == "--data-start-sector" and i+1 < len(sys.argv):
            data_start = int(sys.argv[i+1], 0); i += 2
        elif sys.argv[i] == "--sector-base" and i+1 < len(sys.argv):
            sector_base = int(sys.argv[i+1], 0); i += 2
        elif sys.argv[i] == "--inplace":
            inplace = True; i += 1
        elif sys.argv[i] == "--ewf" and i+1 < len(sys.argv):
            ewf_path = sys.argv[i+1]; i += 2
        elif sys.argv[i] == "--partition-offset" and i+1 < len(sys.argv):
            part_offset = int(sys.argv[i+1], 0); i += 2
        else:
            i += 1

    with open(fvek_file, "rb") as f:
        keys = f.read()
    if len(keys) != 32:
        print(f"unexpected FVEK file size {len(keys)} (expected exactly 32 bytes)")
        sys.exit(1)
    key1, key2 = keys[:16], keys[16:32]

    xts_key = key1 + key2  # OpenSSL AES-128-XTS key = key1 || key2
    print(f"Loaded 32-byte FVEK; sector_base={sector_base}")

    xts = XTSDecrypter(xts_key)

    # If --ewf mode, extract partition first
    raw_path = src
    cleanup_raw = False
    if ewf_path:
        if part_offset is None:
            print("ERROR: --partition-offset required with --ewf"); sys.exit(1)
        # We need the partition size - derive from src_size or use max_sectors
        # For now, extract the whole remaining image from the offset
        tmp = tempfile.mktemp(prefix="ewf_part_", dir=os.path.dirname(dst) or "/tmp")
        raw_path = extract_partition_from_ewf(ewf_path, part_offset,
                                               max_sectors or 0, tmp)
        cleanup_raw = True

    src_size = os.path.getsize(raw_path)
    with open(raw_path, "r+b" if inplace else "rb") as fi:
        # Locate data area (NTFS boot sector) if not given.
        if data_start is None:
            head = fi.read(16 * 1048576)
            fi.seek(0)
            data_start = find_data_start(xts, head, sector_base=sector_base)
            if data_start is None:
                print("ERROR: could not locate NTFS boot sector in first 16MB - wrong FVEK or sector_base?")
                if cleanup_raw:
                    os.unlink(raw_path)
                sys.exit(2)
        # file offset of the data-start sector
        data_start_fileoff = (data_start - sector_base) * SECTOR
        if data_start_fileoff < 0:
            print(f"ERROR: data_start {data_start} < sector_base {sector_base}"); sys.exit(2)
        print(f"data area starts at sector {data_start} (file offset 0x{data_start_fileoff:x})")
        fi.seek(data_start_fileoff)

        available = src_size - data_start_fileoff
        total_sectors = available // SECTOR
        if max_sectors:
            total_sectors = min(total_sectors, max_sectors)
        mode_str = "in-place" if inplace else f"-> {dst}"
        print(f"decrypting {total_sectors} sectors ({total_sectors*SECTOR/1e6:.1f} MB) {mode_str}")

        t0 = time.time()
        if inplace:
            # In-place: read sector, decrypt, seek back, write
            count = 0
            while count < total_sectors:
                ct = fi.read(SECTOR)
                if len(ct) < SECTOR:
                    break
                pt = xts.decrypt_sector(data_start + count, ct)
                fi.seek(-SECTOR, 1)  # seek back
                fi.write(pt)
                count += 1
                if count % BATCH == 0 or count == total_sectors:
                    elapsed = time.time() - t0
                    rate = count * SECTOR / elapsed / 1e6 if elapsed > 0 else 0
                    pct = count * 100 // total_sectors
                    eta = (total_sectors - count) * elapsed / count if count else 0
                    print(f"  {count}/{total_sectors} sectors ({count*SECTOR//1048576} MB) "
                          f"[{rate:.0f} MB/s] {pct}% ETA {eta:.0f}s")
            fi.flush()
            os.fsync(fi.fileno())
        else:
            with open(dst, "wb") as fo:
                count = 0
                while count < total_sectors:
                    ct = fi.read(SECTOR)
                    if len(ct) < SECTOR:
                        break
                    pt = xts.decrypt_sector(data_start + count, ct)
                    fo.write(pt)
                    count += 1
                    if count % BATCH == 0 or count == total_sectors:
                        elapsed = time.time() - t0
                        rate = count * SECTOR / elapsed / 1e6 if elapsed > 0 else 0
                        pct = count * 100 // total_sectors
                        eta = (total_sectors - count) * elapsed / count if count else 0
                        print(f"  {count}/{total_sectors} sectors ({count*SECTOR//1048576} MB) "
                              f"[{rate:.0f} MB/s] {pct}% ETA {eta:.0f}s")

    elapsed = time.time() - t0
    rate = count * SECTOR / elapsed / 1e6 if elapsed > 0 else 0
    print(f"done: {count} sectors ({count*SECTOR/1e6:.1f} MB) in {elapsed:.1f}s [{rate:.0f} MB/s] -> {dst if not inplace else raw_path}")
    xts.close()

    if cleanup_raw and not inplace:
        # If we extracted from EWF and decrypted to a separate file, clean up raw
        os.unlink(raw_path)

if __name__ == "__main__":
    main()
