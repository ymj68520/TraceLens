# python_service/httpserver/tests/unit/test_concurrent_filter.py
"""
Unit tests for FilterLockManager.
"""

import asyncio
import pytest

from httpserver.services.case_analysis.concurrent_filter import FilterLockManager


@pytest.fixture
def lock_manager():
    """Fresh instance for each test."""
    # Reset singleton for clean test
    FilterLockManager._instance = None
    return FilterLockManager.instance()


class TestFilterLockManager:
    """Test FilterLockManager functionality."""

    @pytest.mark.asyncio
    async def test_singleton_pattern(self, lock_manager):
        """Test that instance returns same object."""
        another = FilterLockManager.instance()
        assert lock_manager is another

    @pytest.mark.asyncio
    async def test_sequential_execution(self, lock_manager):
        """Test sequential execution doesn't block."""

        async def dummy_filter(task_id):
            await asyncio.sleep(0.1)
            return f"result-{task_id}"

        result1 = await lock_manager.filter_with_lock("task-1", dummy_filter, "task-1")
        result2 = await lock_manager.filter_with_lock("task-2", dummy_filter, "task-2")

        assert result1 == "result-task-1"
        assert result2 == "result-task-2"

    @pytest.mark.asyncio
    async def test_concurrent_same_task_waits(self, lock_manager):
        """Test concurrent operations on same task are serialized."""

        execution_order = []

        async def slow_filter(task_id, value):
            execution_order.append(value)
            await asyncio.sleep(0.2)
            return value

        # Start two concurrent operations on same task
        task1 = asyncio.create_task(
            lock_manager.filter_with_lock("same-task", slow_filter, "same-task", "first")
        )
        task2 = asyncio.create_task(
            lock_manager.filter_with_lock("same-task", slow_filter, "same-task", "second")
        )

        await asyncio.gather(task1, task2)

        # Second should wait for first
        assert execution_order == ["first", "second"]

    @pytest.mark.asyncio
    async def test_concurrent_different_tasks_parallel(self, lock_manager):
        """Test concurrent operations on different tasks run in parallel."""

        async def slow_filter(task_id, value):
            await asyncio.sleep(0.2)
            return value

        start_time = asyncio.get_event_loop().time()

        # Run on different tasks - should be parallel
        results = await asyncio.gather(
            lock_manager.filter_with_lock("task-a", slow_filter, "task-a", "a"),
            lock_manager.filter_with_lock("task-b", slow_filter, "task-b", "b"),
        )

        elapsed = asyncio.get_event_loop().time() - start_time

        assert set(results) == {"a", "b"}
        # Parallel execution should be ~0.2s, not ~0.4s
        assert elapsed < 0.35

    @pytest.mark.asyncio
    async def test_timeout_raises_error(self, lock_manager):
        """Test that timeout raises TimeoutError."""

        async def never_releasing_filter():
            # Hold lock forever
            await asyncio.sleep(1000)
            return "never"

        # First call acquires lock
        task1 = asyncio.create_task(
            lock_manager.filter_with_lock("task-timeout", never_releasing_filter)
        )

        # Give it time to acquire lock
        await asyncio.sleep(0.1)

        # Second call should timeout
        with pytest.raises(asyncio.TimeoutError):
            await lock_manager.filter_with_lock(
                "task-timeout",
                never_releasing_filter,
                timeout=0.1
            )

        # Cleanup
        task1.cancel()

    @pytest.mark.asyncio
    async def test_cleanup_task_lock(self, lock_manager):
        """Test lock cleanup removes the lock."""

        # Acquire a lock
        await lock_manager.acquire_task_lock("cleanup-task")
        assert "cleanup-task" in lock_manager._task_locks

        # Clean it up
        lock_manager.cleanup_task_lock("cleanup-task")

        # Wait a bit for async cleanup
        await asyncio.sleep(0.1)
        assert "cleanup-task" not in lock_manager._task_locks
