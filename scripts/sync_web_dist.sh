#!/usr/bin/env bash
# 构建前端并镜像同步到 build/web/dist。
# 用 rsync --delete 清掉历史构建残留的旧版本 chunk（assets 里只保留当前 index.html
# 引用的哈希文件），避免 dist 无限膨胀后误判"改了没生效"。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT/web"
npm run build

rsync -a --delete "$ROOT/web/dist/" "$ROOT/build/web/dist/"
echo "synced web/dist -> build/web/dist"
