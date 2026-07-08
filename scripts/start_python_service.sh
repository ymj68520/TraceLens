#!/bin/bash
#
# 启动Python服务（使用虚拟环境）
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}启动 Python HTTP 服务${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 检查虚拟环境
if [ ! -d "python_service/.venv" ]; then
    echo "虚拟环境不存在，正在创建..."
    python3 -m venv python_service/.venv
fi

# 激活虚拟环境并安装依赖
echo "检查依赖..."
python_service/.venv/bin/pip install -q -r python_service/httpserver/requirements.txt

# 检查端口占用
if lsof -i :8090 > /dev/null 2>&1; then
    echo -e "${YELLOW}端口 8090 已被占用，正在关闭旧进程...${NC}"
    lsof -ti :8090 | xargs -r kill -9
    sleep 1
fi

# 启动服务
echo "启动 Python HTTP 服务（端口 8090）..."
python_service/.venv/bin/python -m python_service.httpserver.main

