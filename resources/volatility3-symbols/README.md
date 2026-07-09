# Volatility3 ISF Symbol Files

This directory ships **ISF (Intermediate Symbol File)** JSON files used by
Volatility3 to parse Linux memory dumps. Each file is **kernel-version-specific**
— it encodes the struct layouts/offsets of one exact kernel build.

## Why these exist

vol3 cannot read a Linux LiME/raw dump without a matching ISF; without one,
every plugin fails with `No Linux banners found`. Shipping the ISF for the
project's test image means a fresh clone can analyze that image immediately,
with no ~1.7 GB download.

## Files

| File | Kernel | Source |
|------|--------|--------|
| `linux-6.8.0-110-generic.json.xz` | Ubuntu 6.8.0-110-generic (noble) | generated via `scripts/build-vol3-isf.sh` from `linux-image-unsigned-6.8.0-110-generic-dbgsym_6.8.0-110.110_amd64.ddeb` |

`.xz` files are xz-compressed JSON. `setup.sh` decompresses them into
`~/.cache/volatility3/symbols/` automatically.

## For a different kernel version

ISFs are NOT interchangeable across kernels. To analyze a dump from a different
kernel, generate a matching ISF:

```bash
# Automated (downloads the ddeb, runs dwarf2json, installs):
./scripts/build-vol3-isf.sh <version>      # e.g. 6.8.0-110-generic

# Then analyze:
./build/forensic_analyzer mem.lime --memory-analyze --vol-symbols-dir ~/.cache/volatility3/symbols
```

See the script's header comment for the full flow and manual fallback.

## Regenerating an existing file

```bash
xz -dc linux-6.8.0-110-generic.json.xz | head   # inspect
# To replace:
./scripts/build-vol3-isf.sh 6.8.0-110-generic ./tmp
mv ./tmp/linux-6.8.0-110-generic.json .
xz -9 -k linux-6.8.0-110-generic.json
rm linux-6.8.0-110-generic.json    # keep only the .xz in the repo
```
