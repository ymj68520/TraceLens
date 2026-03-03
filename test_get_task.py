import asyncio
from python_service.config import get_settings
from python_service.httpserver.services.cpp_backend import CppBackendService

async def main():
    settings = get_settings()
    backend = CppBackendService(settings)
    await backend.initialize()
    task = await backend.get_task("bda3966f-6fb3-42c8-a7ac-c690360c6082")
    print(task)
    await backend.shutdown()

asyncio.run(main())
