#!/usr/bin/env python3
"""
LLM API 诊断脚本 - 测试 /api/llm/analyze 端点
"""

import sys
import json
import requests
from pathlib import Path

print("="*70)
print("LLM API 诊断")
print("="*70)
print()

# 配置
PYTHON_BASE_URL = "http://localhost:8090"
CPP_BASE_URL = "http://localhost:8080"

# 测试 1: 检查服务是否运行
print("1. 检查服务状态...")
try:
    response = requests.get(f"{PYTHON_BASE_URL}/health", timeout=5)
    if response.status_code == 200:
        print("   ✅ Python 服务运行中")
    else:
        print(f"   ❌ Python 服务状态异常: {response.status_code}")
except Exception as e:
    print(f"   ❌ Python 服务未运行: {e}")
    sys.exit(1)

try:
    response = requests.get(f"{CPP_BASE_URL}/api/health", timeout=5)
    if response.status_code == 200:
        print("   ✅ C++ 后端运行中")
    else:
        print(f"   ⚠️  C++ 后端状态异常: {response.status_code}")
except Exception as e:
    print(f"   ⚠️  C++ 后端未运行: {e}")

print()

# 测试 2: 检查路由是否注册
print("2. 检查 LLM 路由...")
try:
    response = requests.get(f"{PYTHON_BASE_URL}/docs", timeout=5)
    if response.status_code == 200:
        print("   ✅ API 文档可访问")
        # 检查是否包含 /api/llm/analyze 端点
        if "/api/llm/analyze" in response.text:
            print("   ✅ /api/llm/analyze 端点已注册")
        else:
            print("   ❌ /api/llm/analyze 端点未找到")
    else:
        print(f"   ❌ 无法访问 API 文档: {response.status_code}")
except Exception as e:
    print(f"   ❌ 请求失败: {e}")

print()

# 测试 3: 测试文本文件分析（直接内容）
print("3. 测试文本内容分析（不使用文件路径）...")
test_payload_text = {
    "content": "This is a test file content.",
    "model_type": "text",
    "prompt": "Analyze this text",
}

try:
    response = requests.post(
        f"{PYTHON_BASE_URL}/api/llm/analyze",
        json=test_payload_text,
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    print(f"   状态码: {response.status_code}")
    if response.status_code == 200:
        print("   ✅ 文本分析成功")
        result = response.json()
        print(f"   响应: {json.dumps(result, indent=2)[:200]}...")
    elif response.status_code == 404:
        print("   ❌ 404 Not Found - 路由可能未注册")
        print(f"   响应: {response.text[:200]}")
    elif response.status_code == 400:
        print("   ❌ 400 Bad Request - 请求参数错误")
        print(f"   响应: {response.text[:200]}")
    else:
        print(f"   ❌ 其他错误: {response.status_code}")
        print(f"   响应: {response.text[:200]}")
except Exception as e:
    print(f"   ❌ 请求异常: {e}")

print()

# 测试 4: 测试文件路径分析
print("4. 测试文件路径分析...")
test_file_path = "/tmp/test_llm_file.txt"
Path(test_file_path).write_text("Test content for LLM analysis")

test_payload_file = {
    "file_path": test_file_path,
    "model_type": "text",
}

try:
    response = requests.post(
        f"{PYTHON_BASE_URL}/api/llm/analyze",
        json=test_payload_file,
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    print(f"   状态码: {response.status_code}")
    if response.status_code == 200:
        print("   ✅ 文件路径分析成功")
    elif response.status_code == 404:
        print("   ❌ 404 - 文件未找到或路由问题")
        print(f"   响应: {response.text[:300]}")
    elif response.status_code == 400:
        print("   ❌ 400 - 请求错误")
        print(f"   响应: {response.text[:300]}")
    else:
        print(f"   ❌ 其他错误: {response.status_code}")
        print(f"   响应: {response.text[:300]}")
except Exception as e:
    print(f"   ❌ 请求异常: {e}")

# 清理
Path(test_file_path).unlink(missing_ok=True)

print()

# 测试 5: 检查前端请求格式
print("5. 模拟前端请求格式...")
frontend_payload = {
    "filePath": "/tmp/test.txt",
    "dbFilePath": "/path/in/db/file.txt",
    "modelType": "text",
    "filesDbPath": "/tmp/test_files.db",
}

# 转换为后端期望格式
backend_payload = {
    "file_path": frontend_payload["filePath"],
    "db_file_path": frontend_payload["dbFilePath"],
    "model_type": frontend_payload["modelType"],
    "files_db_path": frontend_payload["filesDbPath"],
}

print(f"   前端格式: {json.dumps(frontend_payload, indent=2)}")
print(f"   后端格式: {json.dumps(backend_payload, indent=2)}")
print("   ✅ 格式转换正确")

print()
print("="*70)
print("诊断完成")
print("="*70)
