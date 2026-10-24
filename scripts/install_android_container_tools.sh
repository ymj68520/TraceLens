#!/usr/bin/env bash
# Build the AOSP LP toolchain (liblp / lpmake / lpunpack / lp_inventory) from
# pinned sources.
#
# The build is pinned by source commit, not by distribution package version.
# Distro packaging of the Android host libraries differs per release (Ubuntu
# 24.04 ships android-14 tooling as 1:34.0.4, older releases ship android-10
# r36 as 1:10.0.0+r36-*), so requiring one exact apt version made this script
# fail on every host that was not the original build machine. Only the upstream
# source commits decide the parsing behaviour that matters here.
#
# Host prerequisites are installed automatically when missing; pass --no-install
# to require them up front instead. Installing needs root, so the script
# re-executes itself through sudo once.
#
#   ./scripts/install_android_container_tools.sh              # build, installing deps
#   ./scripts/install_android_container_tools.sh --no-install # never touch apt
#   AOSP_USE_PINNED_LOCAL_SOURCES=1 ./scripts/install_android_container_tools.sh
#
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dependency_root="$project_root/.deps/aosp-android10-r36"
core_root="$dependency_root/core"
extras_root="$dependency_root/extras"
tool_bin="$dependency_root/bin"
core_commit=204bd34e58de124ead5a1e65b852608620077b84
extras_commit=ef17b323e8be065ed9fbcd1ea863d72e63488fc0

install_deps=1
for arg in "$@"; do
    case "$arg" in
        --no-install) install_deps=0 ;;
        --install) install_deps=1 ;;
        -h|--help)
            sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

# Packages needed to compile liblp and the partition tools. Package names are
# the Debian/Ubuntu packaging of the AOSP host libraries and are stable across
# releases even though their versions are not.
required_packages=(
    g++ make pkg-config
    android-libbase-dev
    android-liblog-dev
    android-libsparse-dev
    android-libcutils-dev
    android-libext4-utils-dev
    libssl-dev zlib1g-dev
)

missing_packages=()
for package in "${required_packages[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "install ok installed"; then
        missing_packages+=("$package")
    fi
done

if [ "${#missing_packages[@]}" -gt 0 ]; then
    if [ "$install_deps" != "1" ]; then
        echo "Missing build dependencies: ${missing_packages[*]}" >&2
        echo "Install them (or rerun without --no-install):" >&2
        echo "  sudo apt-get install -y ${missing_packages[*]}" >&2
        exit 1
    fi
    echo "Installing build dependencies: ${missing_packages[*]}"
    if [ "$(id -u)" -eq 0 ]; then
        apt-get update
        apt-get install -y "${missing_packages[@]}"
    elif sudo -n true 2>/dev/null; then
        sudo apt-get update
        sudo apt-get install -y "${missing_packages[@]}"
    elif [ "${TRACELENS_AOSP_SUDO_ATTEMPTED:-0}" != "1" ]; then
        # Re-execute once through sudo so the caller is prompted a single time.
        # The marker stops a second re-exec if sudo did not actually elevate
        # (a wrapper that exits 0 without changing the uid would otherwise
        # recurse forever).
        echo "Root privileges are required to install: ${missing_packages[*]}" >&2
        export TRACELENS_AOSP_SUDO_ATTEMPTED=1
        exec sudo -- bash "${BASH_SOURCE[0]}" --install
    else
        echo "Still not root after sudo; install the packages manually:" >&2
        echo "  sudo apt-get install -y ${missing_packages[*]}" >&2
        exit 1
    fi
fi

# The Android host libraries are versioned per distro release; resolve their
# real location instead of assuming a fixed multiarch path.
multiarch="$(dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || gcc -dumpmachine)"
android_lib_dir="/usr/lib/$multiarch/android"
android_include_dir="/usr/include/android"
if [ ! -d "$android_lib_dir" ]; then
    echo "Android host libraries not found at $android_lib_dir" >&2
    echo "Install android-libbase-dev and friends, then rerun." >&2
    exit 1
fi
if [ ! -d "$android_include_dir" ]; then
    echo "Android host headers not found at $android_include_dir" >&2
    exit 1
fi

mkdir -p "$dependency_root" "$tool_bin"
if [ "${AOSP_USE_PINNED_LOCAL_SOURCES:-0}" = "1" ]; then
    # Explicit offline material prepared from the already accepted source.
    # No clone, fetch or implicit fallback is permitted in this mode.
    (cd "$dependency_root" && sha256sum --check pinned-source.sha256)
else
    if [ ! -d "$core_root/.git" ]; then
        git clone --filter=blob:none --no-checkout --depth 1 --branch android-10.0.0_r36 \
            https://github.com/aosp-mirror/platform_system_core.git "$core_root"
    fi
    git -C "$core_root" sparse-checkout init --cone
    git -C "$core_root" sparse-checkout set fs_mgr/liblp
    git -C "$core_root" checkout --detach "$core_commit"
    test "$(git -C "$core_root" rev-parse HEAD)" = "$core_commit"

    if [ ! -d "$extras_root/.git" ]; then
        git clone --filter=blob:none --no-checkout --depth 1 --branch android-10.0.0_r36 \
            https://android.googlesource.com/platform/system/extras "$extras_root"
    fi
    git -C "$extras_root" sparse-checkout init --cone
    git -C "$extras_root" sparse-checkout set partition_tools
    git -C "$extras_root" checkout --detach "$extras_commit"
    test "$(git -C "$extras_root" rev-parse HEAD)" = "$extras_commit"
fi

lp_src="$core_root/fs_mgr/liblp"
lp_includes=(-I"$lp_src/include" -I"$lp_src" -I"$android_include_dir")
# liblp hashes with OpenSSL's SHA256 (<openssl/sha.h>), so -lcrypto is the
# required dependency. The former -lcrypto_utils entry named an AOSP internal
# library that Debian/Ubuntu do not package at all (there is no
# android-libcrypto-utils-dev on Ubuntu 24.04), which made the original link
# line unsatisfiable on any distro build.
lp_link=(-L"$android_lib_dir" -Wl,-rpath,"$android_lib_dir" -Wl,-rpath,'$ORIGIN'
         -lbase -llog -lsparse -lext4_utils -lcutils -lcrypto -lz)
compiler_flags=(-std=c++17 -O2 -D_FILE_OFFSET_BITS=64 -include cstring -Wno-attributes)

# AOSP r36 relies on transitive <cstring> includes on some Linux toolchains;
# force that standard header without editing the upstream files.
g++ "${compiler_flags[@]}" -fPIC -shared "${lp_includes[@]}" \
    "$lp_src/builder.cpp" "$lp_src/images.cpp" "$lp_src/partition_opener.cpp" \
    "$lp_src/reader.cpp" "$lp_src/utility.cpp" "$lp_src/writer.cpp" \
    "${lp_link[@]}" -Wl,-soname,liblp.so -o "$tool_bin/liblp.so"
for tool in lpmake lpunpack; do
    g++ "${compiler_flags[@]}" "${lp_includes[@]}" \
        "$extras_root/partition_tools/$tool.cc" -L"$tool_bin" -llp \
        "${lp_link[@]}" -o "$tool_bin/$tool"
done
g++ "${compiler_flags[@]}" "${lp_includes[@]}" \
    "$project_root/scripts/aosp_lp_inventory.cpp" -L"$tool_bin" -llp \
    "${lp_link[@]}" -o "$tool_bin/lp_inventory"

# Record the exact sources and binaries that were built. android_lp_image.py
# verifies this manifest's entries before running the tools, so the manifest is
# what makes a locally built bundle acceptable at runtime. Every path is
# relative to the bundle root, which is also where the binaries live
# ("bin/<tool>"), so one manifest covers both and verify_tools() can resolve
# every entry against a single root.
manifest="$dependency_root/pinned-source.sha256"
{
    find "$core_root/fs_mgr/liblp" -type f \( -name '*.cpp' -o -name '*.h' \) \
        ! -name '*_test.cpp' -print
    find "$extras_root/partition_tools" -maxdepth 1 -type f \( -name '*.cc' -o -name '*.h' \) -print
    printf '%s\n' "$project_root/scripts/aosp_lp_inventory.cpp"
} | sort > "$dependency_root/.manifest-sources"
: > "$manifest"
while IFS= read -r absolute; do
    # Paths under the bundle are recorded relative to it; the inventory source
    # lives in the repository and is recorded by its repo-relative name.
    case "$absolute" in
        "$dependency_root"/*) relative="${absolute#"$dependency_root"/}" ;;
        "$project_root"/*)     relative="${absolute#"$project_root"/}" ;;
        *) relative="$absolute" ;;
    esac
    sha256sum "$absolute" | sed "s|  .*|  $relative|" >> "$manifest"
done < "$dependency_root/.manifest-sources"
rm -f "$dependency_root/.manifest-sources"
for tool in liblp.so lpmake lpunpack lp_inventory; do
    sha256sum "$tool_bin/$tool" | sed "s|  .*|  bin/$tool|" >> "$manifest"
done

echo "Installed pinned AOSP liblp/lpmake/lpunpack/lp_inventory at $tool_bin"
echo "AOSP core commit=$core_commit extras commit=$extras_commit"
echo "Source manifest: $manifest"
sha256sum "$tool_bin/liblp.so" "$tool_bin/lpmake" "$tool_bin/lpunpack" "$tool_bin/lp_inventory"
# The runtime pins the source set separately from the binaries, because the
# binary bytes vary with the host toolchain while the sources do not. Print the
# value to put in android_lp_image.PINNED_SOURCE_SET_SHA256 if the audited
# sources ever change.
echo
echo "Source-set digest (android_lp_image.PINNED_SOURCE_SET_SHA256):"
# Matches verify_tools(): the sorted source lines joined by newlines with no
# trailing newline, so the last line is stripped before hashing.
printf '%s' "$(grep -v '  bin/' "$manifest" | sort)" | sha256sum | cut -d' ' -f1
