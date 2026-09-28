#!/usr/bin/env bash
# Build AOSP Android 10 r36 LP tools from pinned source; no downloaded binaries.
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dependency_root="$project_root/.deps/aosp-android10-r36"
core_root="$dependency_root/core"
extras_root="$dependency_root/extras"
tool_bin="$dependency_root/bin"
core_commit=204bd34e58de124ead5a1e65b852608620077b84
extras_commit=ef17b323e8be065ed9fbcd1ea863d72e63488fc0
package_version='1:10.0.0+r36-9'

for package in android-sdk-libsparse-utils android-libbase-dev android-liblog-dev \
               android-libsparse-dev android-libcutils-dev \
               android-libcrypto-utils-dev; do
    installed="$(dpkg-query -W -f='${Version}' "$package" 2>/dev/null || true)"
    if [ "$installed" != "$package_version" ]; then
        echo "Required AOSP-packaged dependency $package=$package_version (found: $installed)" >&2
        echo "Install with apt, then rerun this script; no unknown binary will be downloaded." >&2
        exit 1
    fi
done
ext4_version="$(dpkg-query -W -f='${Version}' android-libext4-utils-dev 2>/dev/null || true)"
if [ "$ext4_version" != '10.0.0+r36+ds-2' ]; then
    echo "Required android-libext4-utils-dev=10.0.0+r36+ds-2 (found: $ext4_version)" >&2
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

android_lib_dir="/usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)/android"
lp_src="$core_root/fs_mgr/liblp"
lp_includes=(-I"$lp_src/include" -I"$lp_src" -I/usr/include/android)
lp_link=(-L"$android_lib_dir" -Wl,-rpath,"$android_lib_dir" -Wl,-rpath,'$ORIGIN'
         -lbase -llog -lcrypto_utils -lsparse -lext4_utils -lcutils -lcrypto -lz)
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
echo "Installed pinned AOSP liblp/lpmake/lpunpack at $tool_bin"
echo "AOSP core commit=$core_commit extras commit=$extras_commit"
sha256sum "$tool_bin/liblp.so" "$tool_bin/lpmake" "$tool_bin/lpunpack" "$tool_bin/lp_inventory"
