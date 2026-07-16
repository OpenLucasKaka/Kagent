from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Callable, Dict, Optional


def run_with_timeout(
    call,
    *,
    timeout_seconds: float,
    on_timeout: Optional[Callable[[], None]] = None,
    on_complete: Optional[Callable[[], None]] = None,
) -> Dict:
    executor = ThreadPoolExecutor(max_workers=1)

    def run_and_complete() -> Dict:
        try:
            return call()
        finally:
            if on_complete is not None:
                try:
                    on_complete()
                except Exception:
                    # Lifecycle cleanup must not replace the worker result or error.
                    pass

    future = executor.submit(run_and_complete)
    try:
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError as timeout_error:
            if future.done():
                return future.result()
            if on_timeout is not None:
                on_timeout()
            try:
                future.result(timeout=timeout_seconds)
            except TimeoutError:
                pass
            except Exception:
                pass
            raise timeout_error
    finally:
        if not future.done():
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
