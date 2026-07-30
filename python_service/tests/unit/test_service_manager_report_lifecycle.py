from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from httpserver.config import Settings
from httpserver.services.service_manager import ServiceManager


@pytest.mark.asyncio
async def test_report_service_is_recreated_with_the_next_cpp_backend(tmp_path: Path):
    settings = Settings(FORENSIC_REPORT_DIR=str(tmp_path / "reports"))
    manager = ServiceManager(settings)
    first_backend = SimpleNamespace(shutdown=AsyncMock())
    second_backend = SimpleNamespace(shutdown=AsyncMock())
    manager._cpp_backend = first_backend

    first_report_service = manager.forensic_report_service
    assert first_report_service.resolver.cpp_backend is first_backend

    await first_report_service.shutdown()
    manager._cpp_backend = second_backend

    await manager.shutdown()
    assert manager._forensic_report_service is None

    second_report_service = manager.forensic_report_service
    assert second_report_service is not first_report_service
    assert second_report_service.resolver.cpp_backend is second_backend
    assert second_report_service.repository.db_path == first_report_service.repository.db_path
