#!/usr/bin/env bash
# Install the audited, read-only qnxprobe reader outside the tracked source tree.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="$repo_root/.deps/qnxprobe"
commit=fc74ca829c2773879243b326f2262c29f462df3a
if [ ! -d "$target/.git" ]; then
    mkdir -p "$repo_root/.deps"
    git clone https://github.com/abrignoni/qnxprobe.git "$target"
fi
git -C "$target" fetch --depth 1 origin "$commit"
git -C "$target" checkout --detach "$commit"
test "$(git -C "$target" rev-parse HEAD)" = "$commit"
printf '%s  %s\n' \
    ab0f681313bc305f3662d4421199f45da357da3becf90b28696a158fbaae2710 "$target/qnxprobe.py" \
    304616fcdd362339c6890a100eeaba824822f518a09831eb50ed75692f3e52b8 "$target/ewfprobe.py" | sha256sum --check
echo "qnxprobe 1.34 installed and verified at $target"
