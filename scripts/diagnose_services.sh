#!/bin/bash
#
# 快速诊断所有取证分析服务
#

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}取证分析服务诊断${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查端口函数
check_port() {
    local port=$1
    local name=$2

    if lsof -i :$port > /dev/null 2>&1; then
        echo -e "${GREEN}✅${NC} $name (端口 $port) ${GREEN}运行中${NC}"
        lsof -i :$port | tail -1 | awk '{print "   PID: " $2}'
        return 0
    else
        echo -e "${RED}❌${NC} $name (端口 $port) ${RED}未运行${NC}"
        return 1
    fi
}

# 检查二进制文件
check_binary() {
    local binary=$1
    local name=$2

    if [ -f "$binary" ]; then
        echo -e "${GREEN}✅${NC} $name 存在"
        return 0
    else
        echo -e "${RED}❌${NC} $name 未找到: $binary"
        return 1
    fi
}

# 测试 HTTP 端点
test_endpoint() {
    local url=$1
    local name=$2

    local response=$(curl -s -w "\n%{http_code}" "$url" 2>/dev/null)
    local status_code=$(echo "$response" | tail -1)
    local body=$(echo "$response" | head -n -1)

    if [ "$status_code" = "200" ]; then
        echo -e "${GREEN}✅${NC} $name 响应正常"
        return 0
    else
        echo -e "${RED}❌${NC} $name 返回 $status_code"
        if [ -n "$body" ] && [ "$body" != "null" ]; then
            echo "   错误: $(echo "$body" | head -c 100)"
        fi
        return 1
    fi
}

# ============================================
# 1. 检查服务状态
# ============================================
echo -e "${BLUE}[1/5] 服务状态检查${NC}"
echo ""

check_port 8080 "C++ 后端"
check_port 8090 "Python 服务"
check_port ${CS_PORT:-8091} "分布式 C/S 服务"
check_port 3000 "Web 前端" 2>/dev/null || true
check_port 1234 "LM Studio" 2>/dev/null || true

echo ""

# ============================================
# 2. 检查二进制文件
# ============================================
echo -e "${BLUE}[2/5] 二进制文件检查${NC}"
echo ""

check_binary "./build/forensic_analyzer" "C++ 后端"

echo ""

# ============================================
# 3. 测试 API 端点
# ============================================
echo -e "${BLUE}[3/5] API 端点测试${NC}"
echo ""

if check_port 8080 "C++ 后端" >/dev/null 2>&1; then
    test_endpoint "http://localhost:8080/api/health" "C++ 健康检查"
    test_endpoint "http://localhost:8080/api/tasks/list?limit=1" "C++ 任务列表"
fi

if check_port 8090 "Python 服务" >/dev/null 2>&1; then
    test_endpoint "http://localhost:8090/health" "Python 健康检查"
    test_endpoint "http://localhost:8090/docs" "API 文档"
fi

if check_port ${CS_PORT:-8091} "分布式 C/S 服务" >/dev/null 2>&1; then
    test_endpoint "http://localhost:${CS_PORT:-8091}/health" "C/S 健康检查"
fi

echo ""

# ============================================
# 4. 测试 LLM 分析端点
# ============================================
echo -e "${BLUE}[4/5] LLM 分析测试${NC}"
echo ""

if check_port 8090 "Python 服务" >/dev/null 2>&1; then
    echo "测试文本内容分析..."
    test_response=$(curl -s -w "\n%{http_code}" -X POST http://localhost:8090/api/llm/analyze \
        -H "Content-Type: application/json" \
        -d '{"content": "测试文本", "model_type": "text"}' 2>/dev/null)

    status_code=$(echo "$test_response" | tail -1)

    if [ "$status_code" = "200" ]; then
        echo -e "${GREEN}✅${NC} 文本分析端点正常"
    else
        echo -e "${RED}❌${NC} 文本分析端点失败: HTTP $status_code"
        body=$(echo "$test_response" | head -n -1)
        if [ -n "$body" ]; then
            echo "   错误: $(echo "$body" | head -c 200)"
        fi
    fi
else
    echo -e "${YELLOW}⚠️  跳过 LLM 测试（Python 服务未运行）${NC}"
fi

echo ""

# ============================================
# 5. 配置检查
# ============================================
echo -e "${BLUE}[5/5] 配置检查${NC}"
echo ""

if [ -f ".env" ]; then
    echo -e "${GREEN}✅${NC} .env 文件存在"

    echo ""
    echo "关键配置:"
    echo "   PYTHON_HTTP_PORT=$(grep PYTHON_HTTP_PORT .env 2>/dev/null || echo "未设置")"
    echo "   LLM_BASE_URL=$(grep LLM_BASE_URL .env 2>/dev/null || echo "未设置")"
    echo "   LLM_TEXT_MODEL=$(grep LLM_TEXT_MODEL .env 2>/dev/null || echo "未设置")"
else
    echo -e "${YELLOW}⚠️  .env 文件不存在${NC}"
fi

echo ""

# ============================================
# 诊断总结
# ============================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}诊断总结${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 统计问题
cpp_running=false
python_running=false
lm_running=false

if lsof -i :8080 > /dev/null 2>&1; then cpp_running=true; fi
if lsof -i :8090 > /dev/null 2>&1; then python_running=true; fi
if lsof -i :1234 > /dev/null 2>&1; then lm_running=true; fi

if [ "$cpp_running" = true ] && [ "$python_running" = true ] && [ "$lm_running" = true ]; then
    echo -e "${GREEN}✅ 所有服务正常运行！${NC}"
    echo ""
    echo "访问地址:"
    echo "  📊 Web UI:        http://localhost:3000"
    echo "  🔧 C++ API:       http://localhost:8080/docs"
    echo "  🐍 Python API:    http://localhost:8090/docs"
    echo ""
    echo "现在可以正常使用 Files 页面的 AI 分析功能！"
else
    echo -e "${YELLOW}⚠️  部分服务未运行${NC}"
    echo ""

    if [ "$cpp_running" = false ]; then
        echo "启动 C++ 后端:"
        echo "  cd $PROJECT_ROOT"
        echo "  ./build/forensic_analyzer --http-server 8080"
        echo ""
    fi

    if [ "$python_running" = false ]; then
        echo "启动 Python 服务:"
        echo "  cd $PROJECT_ROOT"
        echo "  python -m python_service.httpserver.main"
        echo ""
    fi

    if [ "$lm_running" = false ]; then
        echo "启动 LM Studio:"
        echo "  1. 打开 LM Studio"
        echo "  2. 加载模型"
        echo "  3. 启用服务器（API Server）"
        echo "  4. 确保端口为 1234"
        echo ""
    fi

    echo "快速启动:"
    echo "  ./scripts/start_services.sh"
    echo ""
fi

echo -e "${BLUE}========================================${NC}"
