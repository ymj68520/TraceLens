#!/usr/bin/env bash
# Build the verified native Prefetch parser without exporting its bundled helpers.
set -euo pipefail
version=20260527
sha256=ed4d07cffbd598d6b7b33fbb0f7835aed480667b9019c4fba3562a4bd52c6b76
url=https://files.pythonhosted.org/packages/c7/9f/f5a438cb4d46412711d4ce816e29c5a51628d0d437dc06f1529b359d96b1/libscca_python-20260527.tar.gz
prefix=${1:-"${XDG_CACHE_HOME:-$HOME/.cache}/tracelens/libscca/$version"}
mkdir -p "$prefix"
prefix=$(cd "$prefix" && pwd)
work=$(mktemp -d)
# Only the freshly created private build directory is removed on exit.
trap 'rm -rf -- "$work"' EXIT
curl --fail --location --retry 2 "$url" --output "$work/source.tar.gz"
printf '%s  %s\n' "$sha256" "$work/source.tar.gz" | sha256sum --check --status
tar -xzf "$work/source.tar.gz" -C "$work"
cat > "$work/exports.map" <<'EOF'
{ global: libscca_*; local: *; };
EOF
cd "$work/libscca_python-$version"
# Distro libbfio can have an older ABI. Bundle it privately; expose only libscca.
LDFLAGS="-Wl,--version-script=$work/exports.map -Wl,-Bsymbolic-functions" \
  ./configure --prefix="$prefix" --disable-python --with-libbfio=no
make -j"${JOBS:-2}"
make install
printf '\n已安装原生 Prefetch 解析库：%s\n' "$prefix"
printf '编译项目时设置 PKG_CONFIG_PATH=%s/lib/pkgconfig\n' "$prefix"
