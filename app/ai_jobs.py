"""Общий пул фоновых запросов к модели: проверка фото и тьютор."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any, Callable

from .config import Config

_lock = Lock()
_executor: ThreadPoolExecutor | None = None


def worker_count() -> int:
    return int(Config.AI_CHECK_CONCURRENCY)


def submit(fn: Callable[..., Any], *args: Any, **kwargs: Any):
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=worker_count(),
                thread_name_prefix="ai-job",
            )
        pool = _executor
    return pool.submit(fn, *args, **kwargs)
