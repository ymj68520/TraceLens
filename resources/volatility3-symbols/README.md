# Volatility3 ISF Symbol Files

This directory is a **drop location** for ISF (Intermediate Symbol File) JSON
files used by Volatility3 to parse Linux memory dumps. Each file is
**kernel-version-specific** — it encodes the struct layouts/offsets of one exact
kernel build.

> **No ISFs are shipped here by default.** They are fetched on demand (see
> `scripts/build-vol3-isf.sh`) to keep the repo small and avoid pinning one
> kernel. Drop your own here if you want a manual cache.

## How ISFs are obtained (run time)

vol3 cannot read a Linux LiME/raw dump without a matching ISF; without one,
every plugin fails with `No Linux banners found`. Get one with:

```bash
./scripts/build-vol3-isf.sh <version>      # e.g. 6.8.0-110-generic
```

The script tries three sources in order (fastest first):

1. **Community repo** `Abyss-W4tcher/volatility3-symbols` via jsDelivr CDN —
   *seconds*, covers hundreds of Ubuntu/Debian/Kali kernels. (Preferred path.)
2. **dwarf2json** from a dbgsym ddeb — *minutes*; uses the bundled tool in
   `resources/volatility3-tools/`. A fallback for kernels not in the community
   repo. Use `--from-ddeb` to force this path.
3. Friendly failure with manual instructions.

ISFs install into vol3's default scan dir (`~/.cache/volatility3/symbols`), so
the analyzer needs no `--vol-symbols-dir` after install.

## Manual placement

If you already have an ISF (e.g. from another machine), copy it here or to
`~/.cache/volatility3/symbols/`:

```bash
cp linux-6.8.0-110-generic.json ~/.cache/volatility3/symbols/
```
