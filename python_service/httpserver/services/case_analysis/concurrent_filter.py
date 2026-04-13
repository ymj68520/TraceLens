# python_service/httpserver/services/case_analysis/concurrent_filter.py
"""
Concurrent filter control - prevent race conditions in parallel filtering.
"""

import asyncio
import logging
import threading
from typing import Awaitable, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


class FilterLockManager:
    """
    Singleton manager for task-level async locks.
    Prevents concurrent filtering operations on the same task.
    """

    _instance: Optional['FilterLockManager'] = None
    _lock = threading.Lock()

    def __init__(self):
        if FilterLockManager._instance is not None:
            raise RuntimeError("Use instance() method to get singleton")
        self._task_locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        logger.info("FilterLockManager initialized")

    @classmethod
    def instance(cls) -> 'FilterLockManager':
        """Get the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def acquire_task_lock(self, task_id: str) -> asyncio.Lock:
        """
        Get or create a lock for the specific task.

        Args:
            task_id: Task identifier

        Returns:
            Async lock for the task
        """
        async with self._global_lock:
            if task_id not in self._task_locks:
                self._task_locks[task_id] = asyncio.Lock()
                logger.debug(f"Created new lock for task: {task_id}")
            return self._task_locks[task_id]

    async def filter_with_lock(
        self,
        task_id: str,
        filter_func: Callable[..., Awaitable[T]],
        *args,
        timeout: Optional[int] = None,
        **kwargs
    ) -> T:
        """
        Execute filter function with task-level locking.

        Args:
            task_id: Task identifier
            filter_func: Async function to execute
            *args: Positional arguments for filter_func
            timeout: Lock acquisition timeout in seconds (default: 300)
            **kwargs: Keyword arguments for filter_func

        Returns:
            Result from filter_func

        Raises:
            asyncio.TimeoutError: If lock cannot be acquired within timeout
        """
        lock = await self.acquire_task_lock(task_id)
        timeout = timeout or 300

        try:
            # Acquire lock with timeout
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            logger.info(f"Acquired lock for task: {task_id}")

            try:
                result = await filter_func(*args, **kwargs)
                return result
            finally:
                lock.release()
                logger.info(f"Released lock for task: {task_id}")

        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for lock on task: {task_id}")
            raise

    def cleanup_task_lock(self, task_id: str) -> None:
        """
        Remove lock for a completed task (optional cleanup).

        Args:
            task_id: Task identifier
        """
        # Note: This needs to be async but the spec says sync
        # For now, we'll make it async internally
        async def _cleanup():
            async with self._global_lock:
                if task_id in self._task_locks:
                    del self._task_locks[task_id]
                    logger.debug(f"Cleaned up lock for task: {task_id}")

        # Create event loop if needed and run
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, create a task
                asyncio.create_task(_cleanup())
            else:
                # If loop is not running, run until complete
                loop.run_until_complete(_cleanup())
        except RuntimeError:
            # No event loop, create a new one
            asyncio.run(_cleanup())
