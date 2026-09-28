"""Translated reading overlays never change the frozen source snapshot."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from httpserver.services.investigation.initial_analysis_translation import (
    InitialAnalysisTranslationCache,
    TranslationUnavailable,
    needs_chinese_translation,
)
from httpserver.services.investigation.offline_translation import (
    OfflineArgosTranslator,
    OfflineTranslationError,
    _mask_identifiers,
    _restore_identifiers,
)
from httpserver.services.investigation import offline_translation


SOURCE = (
    'SUMMARY: This file is a WYWZ plugin configuration file named "gpass.wyz". '
    "It defines a cleaning rule that targets application data for deletion."
)


@pytest.mark.asyncio
async def test_translation_is_cached_by_task_evidence_and_source_digest(tmp_path):
    translator = Mock(translate=Mock(return_value=(
        "摘要：gpass.wyz 是 WYWZ 插件配置文件，定义清理应用数据的规则。", "test-model",
    )))
    cache = InitialAnalysisTranslationCache(tmp_path / "translations.db", translator)

    first = await cache.translate("task-a", "file:/case/gpass.wyz", SOURCE, evidence_name="gpass.wyz")
    second = await cache.translate("task-a", "file:/case/gpass.wyz", SOURCE, evidence_name="gpass.wyz")

    assert first["translated"] is True and first["cached"] is False
    assert second["cached"] is True and second["text"] == first["text"]
    assert "gpass.wyz" in first["text"]
    translator.translate.assert_called_once_with(SOURCE)
    assert SOURCE.startswith("SUMMARY: This file")  # source object unchanged


@pytest.mark.asyncio
async def test_translation_cache_never_crosses_task_scope(tmp_path):
    translator = Mock(translate=Mock(return_value=("这是 gpass.wyz 的中文描述，专门说明该证据的相关配置。", "m")))
    cache = InitialAnalysisTranslationCache(tmp_path / "translations.db", translator)

    await cache.translate("task-a", "file:/case/gpass.wyz", SOURCE, evidence_name="gpass.wyz")
    await cache.translate("task-b", "file:/case/gpass.wyz", SOURCE, evidence_name="gpass.wyz")

    assert translator.translate.call_count == 2


@pytest.mark.asyncio
async def test_chinese_source_is_returned_without_model_call_or_cache_write(tmp_path):
    translator = Mock(translate=Mock())
    cache = InitialAnalysisTranslationCache(tmp_path / "translations.db", translator)
    result = await cache.translate("task-a", "file:/case/a.txt", "该文件记录了用户登录时间。")
    assert result["translated"] is False
    assert result["text"] == "该文件记录了用户登录时间。"
    assert not cache.db_path.exists()
    translator.translate.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_model_output_cannot_replace_original(tmp_path):
    translator = Mock(translate=Mock(return_value=("The file is an English description only.", "m")))
    cache = InitialAnalysisTranslationCache(tmp_path / "translations.db", translator)
    with pytest.raises(TranslationUnavailable):
        await cache.translate("task-a", "file:/case/gpass.wyz", SOURCE, evidence_name="gpass.wyz")
    assert not cache.db_path.exists()


def test_english_detection_ignores_chinese_with_technical_identifiers():
    assert needs_chinese_translation(SOURCE)
    assert not needs_chinese_translation("这是 Windows 系统的 UsrClass.dat 文件，位于 AppData 目录。")


def test_offline_translation_protects_forensic_identifiers():
    masked, protected = _mask_identifiers(
        "gpass.wyz deletes %USERPROFILE%/GPass and references DelFile."
    )
    assert "gpass.wyz" not in masked
    assert "%USERPROFILE%" not in masked
    restored = _restore_identifiers(masked.lower(), protected)
    assert "gpass.wyz" in restored
    assert "%USERPROFILE%" in restored
    assert "DelFile" in restored
    with pytest.raises(OfflineTranslationError):
        _restore_identifiers("模型漏掉标识符", protected)


def test_offline_translation_lists_identifiers_omitted_by_small_model(monkeypatch):
    class Tokenizer:
        def encode(self, text, out_type=str):
            return text.split()

        def decode(self, tokens):
            return " ".join(tokens)

    class Model:
        def translate_batch(self, pieces, **_kwargs):
            return [Mock(hypotheses=[["这是中文译文"]]) for _ in pieces]

    monkeypatch.setattr(offline_translation, "_load_model", lambda _path: (Tokenizer(), Model()))
    translated, _model = OfflineArgosTranslator(Path("unused")).translate(
        "SUMMARY: This gpass.wyz file uses %USERPROFILE% and WYWZ."
    )
    assert translated.startswith("摘要：这是中文译文")
    assert "原文技术标识" in translated
    assert "gpass.wyz" in translated
    assert "%USERPROFILE%" in translated
    assert "TOKEN" not in translated
