#!/usr/bin/env bash
#
# build-vol3-isf.sh — Obtain and install a Volatility3 ISF symbol file for a
# given Linux kernel version, so MemoryAnalyzer can parse that kernel's LiME/
# raw memory dump.
#
# Why this exists: vol3 cannot parse a Linux memory dump without an ISF
# (Intermediate Symbol File) matching the dump's exact kernel version. This
# script fetches one with three strategies, tried in order (fastest first):
#
#   L1  Community symbol repo (Abyss-W4tcher/volatility3-symbols) via jsDelivr
#       CDN — seconds, no build step. Covers hundreds of Ubuntu/Debian/Kali
#       kernels.  <-- the elegant, preferred path
#   L2  dwarf2json from a dbgsym ddeb — minutes; a fallback for kernels NOT in
#       the community repo. Uses the bundled dwarf2json (resources/).
#   L3  Friendly failure with manual instructions.
#
# Usage:
#   ./scripts/build-vol3-isf.sh <kernel-version> [install-dir] [--from-ddeb]
#
#   kernel-version   e.g. 6.8.0-110-generic  (uname -r of the dump's kernel)
#                    For non-generic flavors: 6.8.0-110-lowlatency, etc.
#   install-dir      where to copy the .json (default: ~/.cache/volatility3/symbols)
#                    NOTE: vol3 2.x scans ~/.cache/volatility3/symbols, not ~/.config
#   --from-ddeb      skip L1 (community repo); go straight to dwarf2json.
#
# Examples:
#   ./scripts/build-vol3-isf.sh 6.8.0-110-generic
#   ./scripts/build-vol3-isf.sh 5.4.0-100-generic ./my-symbols
#   ./scripts/build-vol3-isf.sh 6.8.0-110-generic --from-ddeb   # force L2
#
# Re-running for the same version is idempotent (overwrites the ISF).
#
set -euo pipefail

# ---------- helpers ----------
RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; BLU=$'\033[34m'; RST=$'\033[0m'
info()  { echo "${GRN}[+]${RST} $*"; }
step()  { echo "${BLU}[>]${RST} $*"; }
warn()  { echo "${YLW}[!]${RST} $*"; }
die()   { echo "${RED}[x]${RST} $*" >&2; exit 1; }

# ---------- args ----------
FORCE_DDEB=0
POSITIONAL=()
for a in "$@"; do
    case "$a" in
        --from-ddeb) FORCE_DDEB=1 ;;
        -h|--help)
            sed -n '2,40p' "$0"; exit 0 ;;
        *) POSITIONAL+=("$a") ;;
    esac
done
VERSION="${POSITIONAL[0]:-}"
INSTALL_DIR="${POSITIONAL[1]:-$HOME/.cache/volatility3/symbols}"

[ -z "$VERSION" ] && die "usage: $0 <kernel-version> [install-dir] [--from-ddeb]
e.g. $0 6.8.0-110-generic"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

info "Kernel version: $VERSION"
info "Install dir:    $INSTALL_DIR"

mkdir -p "$INSTALL_DIR"

# Parse version: 6.8.0-110-generic -> kver=6.8.0, abi=110, flavor=generic
BASE="${VERSION%-*}"      # 6.8.0-110
KVER="${BASE%-*}"         # 6.8.0
ABI="${BASE##*-}"         # 110
FLAVOR="${VERSION##*-}"   # generic

# ====================================================================
# L1: Community symbol repo via jsDelivr CDN (preferred)
# Path pattern: <Distro>/<arch>/<kver>/<abi>/<flavor>/Ubuntu_<full>_amd64.json.xz
# The community filename embeds a build number that we can't derive, so we list
# the directory via the GitHub API and pick the best match.
# ====================================================================
try_community_repo() {
    [ "$FORCE_DDEB" -eq 1 ] && { warn "--from-ddeb set, skipping community repo."; return 1; }

    step "L1: searching community symbol repo (Abyss-W4tcher/volatility3-symbols)..."
    local dir_url="https://api.github.com/repos/Abyss-W4tcher/volatility3-symbols/contents/Ubuntu/amd64/${KVER}/${ABI}/${FLAVOR}"

    local listing
    if ! listing="$(curl -fsSL --connect-timeout 20 --max-time 40 "$dir_url" 2>/dev/null)"; then
        warn "Community repo: directory not found for Ubuntu/amd64/${KVER}/${ABI}/${FLAVOR}"
        return 1
    fi

    # Extract .json.xz filenames from the JSON listing.
    local files
    files="$(printf '%s' "$listing" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('ERR'); sys.exit()
if isinstance(d, dict) and d.get('message'):  # API error response
    print('ERR'); sys.exit()
for x in d:
    n = x.get('name','')
    if n.endswith('.json.xz'):
        print(n)
" 2>/dev/null)"
    [ "$files" = "ERR" ] && { warn "Community repo: unexpected API response."; return 1; }
    [ -z "$files" ] && { warn "Community repo: no .json.xz in that directory."; return 1; }

    # Prefer a file whose name contains the full version; avoid ~22.04 backport
    # variants unless that's all there is.
    local chosen
    chosen="$(printf '%s\n' "$files" | grep -v '~' | head -1)"
    [ -z "$chosen" ] && chosen="$(printf '%s\n' "$files" | head -1)"
    info "Community repo: found $chosen"

    local raw_url="https://cdn.jsdelivr.net/gh/Abyss-W4tcher/volatility3-symbols@master/Ubuntu/amd64/${KVER}/${ABI}/${FLAVOR}/${chosen}"
    local tmp_xz
    tmp_xz="$(mktemp)"
    if curl -fSL --connect-timeout 20 --max-time 120 -o "$tmp_xz" "$raw_url"; then
        local out="$INSTALL_DIR/linux-${VERSION}.json"
        if xz -dc "$tmp_xz" > "$out" && python3 -c "import json;json.load(open('$out'))" 2>/dev/null; then
            info "Downloaded + validated ISF ($(du -h "$out" | cut -f1))"
            rm -f "$tmp_xz"
            ok_done
            return 0
        fi
        warn "Community repo: downloaded file failed validation (corrupt?)."
    else
        warn "Community repo: download failed."
    fi
    rm -f "$tmp_xz"
    return 1
}

# ====================================================================
# L2: dwarf2json from a dbgsym ddeb (fallback)
# ====================================================================
try_dwarf2json() {
    step "L2: generating ISF with dwarf2json from a dbgsym ddeb..."

    local DWARF2JSON="$REPO_ROOT/resources/volatility3-tools/dwarf2json-linux-amd64"
    if [ ! -x "$DWARF2JSON" ]; then
        if command -v dwarf2json >/dev/null 2>&1; then
            DWARF2JSON="$(command -v dwarf2json)"
        else
            warn "dwarf2json not found at $DWARF2JSON and not on PATH."
            return 1
        fi
    fi
    info "dwarf2json: $DWARF2JSON"

    local WORK
    WORK="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '$WORK'" RETURN

    # Locate the ddeb. The ABI number usually equals the build suffix
    # (6.8.0-110 -> 6.8.0-110.110), but this is a heuristic.
    local PKG_VER="${BASE}.${ABI}"   # 6.8.0-110.110
    local DDEB_NAME="linux-image-unsigned-${VERSION}-dbgsym_${PKG_VER}_amd64.ddeb"
    local DDEB="$WORK/kernel-dbgsym.ddeb"
    local url="https://launchpad.net/ubuntu/+archive/primary/+files/${DDEB_NAME}"

    info "Downloading ddeb (~1.7GB): $url"
    if ! curl -fL --retry 3 --connect-timeout 30 -o "$DDEB" "$url"; then
        warn "ddeb auto-download failed (URL may differ for this kernel)."
        return 1
    fi
    ar t "$DDEB" >/dev/null 2>&1 || { warn "ddeb is not a valid ar archive."; return 1; }

    info "Extracting vmlinux..."
    mkdir -p "$WORK/extract"
    dpkg-deb -x "$DDEB" "$WORK/extract"
    local VMLINUX
    VMLINUX="$(find "$WORK/extract/usr/lib/debug/boot" -name "vmlinux-${VERSION}*" 2>/dev/null | head -1)"
    [ -z "$VMLINUX" ] && VMLINUX="$(find "$WORK/extract" -name 'vmlinux*' 2>/dev/null | head -1)"
    [ -z "$VMLINUX" ] && { warn "no vmlinux inside the ddeb."; return 1; }

    local out="$INSTALL_DIR/linux-${VERSION}.json"
    info "Running dwarf2json (~1-2 min)..."
    if "$DWARF2JSON" linux --elf "$VMLINUX" > "$out" && [ -s "$out" ]; then
        info "Generated ISF ($(du -h "$out" | cut -f1))"
        ok_done
        return 0
    fi
    warn "dwarf2json failed."
    return 1
}

# ====================================================================
ok_done() {
    echo
    info "${GRN}Done.${RST} ISF for kernel $VERSION installed to $INSTALL_DIR."
    info "Now analyze:"
    echo "    ./build/forensic_analyzer mem.lime --memory-analyze --vol-symbols-dir \"$INSTALL_DIR\""
    echo "    (or omit --vol-symbols-dir if $INSTALL_DIR is vol3's default scan path)"
}

# ---------- run the cascade ----------
if try_community_repo; then exit 0; fi
echo
if try_dwarf2json; then exit 0; fi

# ====================================================================
# L3: friendly failure
# ====================================================================
echo
die "${RED}Could not obtain an ISF for kernel $VERSION automatically.${RST}

Manual options:
  A) Community repo — browse https://github.com/Abyss-W4tcher/volatility3-symbols
     (Ubuntu/amd64/${KVER}/${ABI}/${FLAVOR}/), download the .json.xz, decompress,
     and copy to $INSTALL_DIR.
  B) Ubuntu debug-symbol apt source:
       echo 'deb http://ddebs.ubuntu.com \$(lsb_release -cs) main' | sudo tee /etc/apt/sources.list.d/ddebs.list
       sudo apt install ubuntu-dbgsym-keyring && sudo apt update
       sudo apt install linux-image-unsigned-${VERSION}-dbgsym
     then run: $0 $VERSION --from-ddeb   (with the ddeb now in apt cache)
  C) Any source of vmlinux for this kernel + dwarf2json (see resources/volatility3-tools/)."
