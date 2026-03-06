#!/usr/bin/env python3
"""
验证 generate_file_descriptions 是否真的调用 LLM 分析

这个测试验证数据流完整性：提取文件后，LLM 分析是否真的被调用。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Add python_service to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python_service"))


async def test_llm_analyze_called_for_text():
    """验证文本文件的 LLM analyze() 被调用"""
    print("测试 1: 验证文本文件的 LLM analyze() 被调用...")

    # Import here to avoid module import issues
    from httpserver.services.case_analysis_service import CaseAnalysisService
    from httpserver.config import Settings

    # 创建 mock 服务
    settings = Settings(
        cpp_backend_url="http://localhost:8080",
        llm_base_url="http://localhost:1234",
        llm_text_model="test-model",
        llm_vision_model="test-vision-model",
    )

    case_service = CaseAnalysisService(settings)

    # 创建 mock LLM service
    class MockLLMService:
        def __init__(self):
            self.analyze = AsyncMock(return_value={
                "analysis": {
                    "description": "Test analysis",
                    "summary": "Test summary",
                    "keywords": ["test"]
                },
                "model": "test-model",
                "tokens_used": 100,
            })
            self.read_file_content = AsyncMock(return_value="test file content")
            self.persist_to_files_db = MagicMock(return_value=True)

    mock_llm = MockLLMService()
    case_service._llm_service = mock_llm

    # 创建测试文件
    test_file = Path("/tmp/test_llm_file.txt")
    test_file.write_text("test content")

    try:
        # 调用 generate_file_descriptions
        results = await case_service.generate_file_descriptions(
            files_db_path="/tmp/test_files.db",
            file_paths=[str(test_file)],
            case_description="测试案情",
            extraction_dir="/tmp"
        )

        # 验证 analyze() 被调用
        assert mock_llm.analyze.called, "❌ analyze() 未被调用!"
        assert mock_llm.analyze.call_count == 1, f"❌ analyze() 调用次数错误: {mock_llm.analyze.call_count}"

        # 验证参数正确
        call_kwargs = mock_llm.analyze.call_args.kwargs
        assert call_kwargs.get('content') == "test file content", f"❌ 内容参数错误: {call_kwargs.get('content')}"
        assert call_kwargs.get('model_type') == "text", f"❌ 模型类型错误: {call_kwargs.get('model_type')}"

        # 验证 read_file_content 被调用
        assert mock_llm.read_file_content.called, "❌ read_file_content() 未被调用!"

        print("✅ 测试 1 通过: LLM analyze() 确实被调用")
        print(f"   - analyze() 调用次数: {mock_llm.analyze.call_count}")
        print(f"   - 传入内容: '{call_kwargs.get('content')[:50]}...'")
        print(f"   - 模型类型: {call_kwargs.get('model_type')}")
        return True

    except AssertionError as e:
        print(f"❌ 测试 1 失败: {e}")
        return False
    finally:
        # 清理测试文件
        if test_file.exists():
            test_file.unlink()


async def test_llm_analyze_image_called():
    """验证图片文件调用 analyze_image()"""
    print("\n测试 2: 验证图片文件的 LLM analyze_image() 被调用...")

    from httpserver.services.case_analysis_service import CaseAnalysisService
    from httpserver.config import Settings

    settings = Settings(
        cpp_backend_url="http://localhost:8080",
        llm_base_url="http://localhost:1234",
        llm_text_model="test-model",
        llm_vision_model="test-vision-model",
    )

    case_service = CaseAnalysisService(settings)

    # 创建 mock LLM service
    class MockLLMService:
        def __init__(self):
            self.analyze_image = AsyncMock(return_value={
                "analysis": {
                    "description": "Image shows test content",
                    "summary": "Test image",
                    "keywords": ["image", "test"]
                },
                "model": "test-vision-model",
                "tokens_used": 200,
            })
            self.persist_to_files_db = MagicMock(return_value=True)

    mock_llm = MockLLMService()
    case_service._llm_service = mock_llm

    # 创建测试图片（最小化的有效JPEG）
    test_image = Path("/tmp/test_llm_image.jpg")

    # 创建一个最小的1x1像素JPEG文件
    import struct
    jpeg_header = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
    jpeg_footer = b'\xff\xd9'
    minimal_jpeg = jpeg_header + struct.pack('>H', 0) + jpeg_footer

    test_image.write_bytes(minimal_jpeg)

    try:
        # 调用 generate_file_descriptions
        results = await case_service.generate_file_descriptions(
            files_db_path="/tmp/test_files.db",
            file_paths=[str(test_image)],
            case_description="测试案情",
            extraction_dir="/tmp"
        )

        # 验证 analyze_image() 被调用
        assert mock_llm.analyze_image.called, "❌ analyze_image() 未被调用!"
        assert mock_llm.analyze_image.call_count == 1, f"❌ analyze_image() 调用次数错误: {mock_llm.analyze_image.call_count}"

        # 验证参数正确
        call_kwargs = mock_llm.analyze_image.call_args.kwargs
        assert 'image_data' in call_kwargs, "❌ 缺少 image_data 参数"
        assert len(call_kwargs['image_data']) > 0, "❌ image_data 为空"

        print("✅ 测试 2 通过: LLM analyze_image() 确实被调用")
        print(f"   - analyze_image() 调用次数: {mock_llm.analyze_image.call_count}")
        print(f"   - 图像数据大小: {len(call_kwargs['image_data'])} bytes")
        return True

    except AssertionError as e:
        print(f"❌ 测试 2 失败: {e}")
        return False
    finally:
        # 清理测试文件
        if test_image.exists():
            test_image.unlink()


async def test_file_not_found_handling():
    """测试文件不存在时的处理"""
    print("\n测试 3: 验证文件不存在时的错误处理...")

    from httpserver.services.case_analysis_service import CaseAnalysisService
    from httpserver.config import Settings

    settings = Settings(
        cpp_backend_url="http://localhost:8080",
        llm_base_url="http://localhost:1234",
        llm_text_model="test-model",
        llm_vision_model="test-vision-model",
    )

    case_service = CaseAnalysisService(settings)

    # 创建 mock LLM service（不应该被调用）
    class MockLLMService:
        def __init__(self):
            self.analyze = AsyncMock()
            self.analyze_image = AsyncMock()

    mock_llm = MockLLMService()
    case_service._llm_service = mock_llm

    # 使用不存在的文件路径
    nonexistent_file = "/tmp/nonexistent_file_12345.txt"

    try:
        # 调用 generate_file_descriptions
        results = await case_service.generate_file_descriptions(
            files_db_path="/tmp/test_files.db",
            file_paths=[nonexistent_file],
            case_description="测试案情",
            extraction_dir="/tmp"
        )

        # 验证 analyze() 没有被调用
        assert not mock_llm.analyze.called, "❌ analyze() 不应该被调用!"

        # 验证结果中包含错误
        assert len(results) == 1, "❌ 应该返回1个结果"
        assert results[0]['success'] == False, "❌ 应该标记为失败"
        assert 'File not found' in results[0]['error'], "❌ 应该包含文件未找到错误"

        print("✅ 测试 3 通过: 文件不存在时正确处理")
        print(f"   - 错误消息: {results[0]['error']}")
        return True

    except AssertionError as e:
        print(f"❌ 测试 3 失败: {e}")
        return False


async def main():
    """运行所有验证测试"""
    print("="*70)
    print("数据流和 LLM 调用验证测试")
    print("="*70)
    print()

    results = []

    # 运行所有测试
    results.append(await test_llm_analyze_called_for_text())
    results.append(await test_llm_analyze_image_called())
    results.append(await test_file_not_found_handling())

    # 总结
    print("\n" + "="*70)
    if all(results):
        print("✅ 所有验证测试通过!")
        print("="*70)
        print("\n结论:")
        print("1. ✅ generate_file_descriptions() 确实调用 LLM 分析")
        print("2. ✅ 文本文件调用 analyze() 方法")
        print("3. ✅ 图片文件调用 analyze_image() 方法")
        print("4. ✅ 文件内容被读取并传递给 LLM")
        print("5. ✅ 文件不存在时正确处理并返回错误")
        print("\n🎉 数据流完整性验证通过！")
        print("\n说明:")
        print("- extract_filtered_files() 提取文件")
        print("- generate_file_descriptions() 接收提取目录")
        print("- 对每个文件调用相应的 LLM 分析方法")
        print("- 分析结果会被持久化到数据库")
        return 0
    else:
        print("❌ 部分测试失败")
        print("="*70)
        print(f"通过: {sum(results)}/{len(results)}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
