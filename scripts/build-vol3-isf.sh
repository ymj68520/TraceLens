#!/usr/bin/env bash
#
# build-vol3-isf.sh — Generate and install a Volatility3 ISF symbol file for a
# given Linux kernel version, so MemoryAnalyzer can parse that kernel's LiME/
# raw memory dump.
#
# Why this exists: vol3 cannot parse a Linux memory dump without an ISF
# (Intermediate Symbol File) matching the dump's exact kernel version. This
# script automates the otherwise-manual flow:
#     ddeb (dbgsym package) -> extract vmlinux -> dwarf2json -> ISF -> install
#
# Usage:
#   ./scripts/build-vol3-isf.sh <kernel-version> [install-dir]
#
#   kernel-version   e.g. 6.8.0-110-generic  (the uname -r of the dump's kernel)
#   install-dir      where to copy the .json (default: ~/.cache/volatility3/symbols)
#                    NOTE: vol3 2.x scans ~/.cache/volatility3/symbols, not ~/.config
#
# Examples:
#   ./scripts/build-vol3-isf.sh 6.8.0-110-generic
#   ./scripts/build-vol3-isf.sh 6.8.0-110-generic ./my-symbols
#
# Notes:
#   - Downloads the dbgsym ddeb from launchpadlibrarian (~1.7GB). Some mirrors
#     don't support Range/resume; a fast link is recommended.
#   - The bundled dwarf2json (resources/volatility3-tools/) is used; falls back
#     to PATH if absent.
#   - Re-running for the same version is idempotent (overwrites the ISF).
#
set -euo pipefail

# ---------- helpers ----------
RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; RST=$'\033[0m'
info()  { echo "${GRN}[+]${RST} $*"; }
warn()  { echo "${YLW}[!]${RST} $*"; }
die()   { echo "${RED}[x]${RST} $*" >&2; exit 1; }

# ---------- args ----------
VERSION="${1:-}"
[ -z "$VERSION" ] && die "usage: $0 <kernel-version> [install-dir]
e.g. $0 6.8.0-110-generic"

INSTALL_DIR="${2:-$HOME/.cache/volatility3/symbols}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# strip "-generic" suffix for the build number lookup
BASE_VER="${VERSION%-generic}"
DWARF2JSON="$REPO_ROOT/resources/volatility3-tools/dwarf2json-linux-amd64"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

info "Kernel version: $VERSION"
info "Install dir:    $INSTALL_DIR"
info "Work dir:       $WORK"

# ---------- locate dwarf2json ----------
if [ ! -x "$DWARF2JSON" ]; then
    if command -v dwarf2json >/dev/null 2>&1; then
        DWARF2JSON="$(command -v dwarf2json)"
    else
        die "dwarf2json not found at $DWARF2JSON and not on PATH.
Hint: it is bundled in resources/volatility3-tools/. Run setup.sh to install it,
or download from https://github.com/volatilityfoundation/dwarf2json/releases"
    fi
fi
info "dwarf2json: $DWARF2JSON"

# ---------- locate the dbgsym ddeb ----------
# Ubuntu publishes dbgsym .ddebs. The launchpadlibrarian URL needs the full
# build number (e.g. 6.8.0-110.110). We probe launchpad for it.
info "Locating dbgsym ddeb for $VERSION..."

# Try common build-number patterns. The ABI number usually equals the -N in the
# kernel version (6.8.0-110 -> build 110).
ABI="${BASE_VER##*-}"   # e.g. 110
PKG_VER="${BASE_VER}.${ABI}"   # e.g. 6.8.0-110.110
DDEB_NAME="linux-image-unsigned-${VERSION}-dbgsym_${PKG_VER}_amd64.ddeb"

# Candidate download URLs (tried in order).
LP_URL="https://launchpad.net/ubuntu/+archive/primary/+files/${DDEB_NAME}"
DDEB_URLS=( "$LP_URL" )

DDEB="$WORK/kernel-dbgsym.ddeb"
downloaded=0
for url in "${DDEB_URLS[@]}"; do
    info "Trying: $url"
    if curl -fL --retry 3 --connect-timeout 30 -o "$DDEB" "$url"; then
        downloaded=1
        info "Downloaded ddeb ($(du -h "$DDEB" | cut -f1))"
        break
    fi
done

if [ "$downloaded" -eq 0 ]; then
    warn "Auto-download failed. Manual fallback:"
    echo "  1. Enable the Ubuntu debug-symbol apt source:"
    echo "     echo 'deb http://ddebs.ubuntu.com noble main restricted universe multiverse' | sudo tee /etc/apt/sources.list.d/ddebs.list"
    echo "     sudo apt install ubuntu-dbgsym-keyring && sudo apt update"
    echo "     sudo apt install linux-image-unsigned-${VERSION}-dbgsym"
    echo "  2. Then re-run: $0 $VERSION \$INSTALL_DIR  (place the extracted vmlinux at /tmp/vmlinux-debug and edit this script, OR install via apt and skip download)"
    die "Could not download $DDEB_NAME"
fi

# ---------- validate ddeb ----------
ar t "$DDEB" >/dev/null 2>&1 || die "$DDEB is not a valid ar archive (corrupt download?)"

# ---------- extract vmlinux ----------
info "Extracting vmlinux from ddeb..."
mkdir -p "$WORK/extract"
dpkg-deb -x "$DDEB" "$WORK/extract"
VMLINUX="$(find "$WORK/extract/usr/lib/debug/boot" -name "vmlinux-${VERSION}*" 2>/dev/null | head -1)"
if [ -z "$VMLINUX" ]; then
    # fallback: any vmlinux
    VMLINUX="$(find "$WORK/extract" -name 'vmlinux*' 2>/dev/null | head -1)"
fi
[ -z "$VMLINUX" ] && die "No vmlinux found inside the ddeb"
info "Found vmlinux: $VMLINUX ($(du -h "$VMLINUX" | cut -f1))"

# ---------- generate ISF ----------
ISF="$WORK/linux-${VERSION}.json"
info "Generating ISF with dwarf2json (~1-2 min)..."
"$DWARF2JSON" linux --elf "$VMLINUX" > "$ISF"
[ -s "$ISF" ] || die "dwarf2json produced an empty ISF"
info "ISF generated: $(du -h "$ISF" | cut -f1)"

# validate it's plausibly valid JSON (has the expected top-level keys)
python3 - "$ISF" <<'PY' || die "ISF does not look like a valid vol3 symbol file"
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
assert isinstance(d.get("symbols"), dict) and len(d["symbols"]) > 1000, \
    "missing/large symbols map"
print(f"  symbols={len(d['symbols'])}")
PY

# ---------- install ----------
mkdir -p "$INSTALL_DIR"
cp "$ISF" "$INSTALL_DIR/linux-${VERSION}.json"
info "Installed: $INSTALL_DIR/linux-${VERSION}.json"
echo
info "${GRN}Done.${RST} vol3 will now find symbols for kernel $VERSION."
info "Re-run the analyzer:"
echo "    ./build/forensic_analyzer mem.lime --memory-analyze --vol-symbols-dir \"$INSTALL_DIR\""
