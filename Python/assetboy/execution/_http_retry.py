"""HTTP retry helper for R1A runners (Path B v1.12.s66).

Provides `with_429_retry(callable, max_retries, base_delay_s)` — a small
exponential-backoff wrapper that re-raises non-429 errors and retries
HTTP 429 / 503 responses with `1s, 2s, 4s, 8s, ...` delays (capped at
max_retries attempts).

All R1A runners can opt in by wrapping their `urllib.request.urlopen`
call. Default: 3 retries (so 1s + 2s + 4s = 7s max before giving up).

Why a separate module: keeps individual runners under their per-slice
edit cap. One import per runner adds the retry behavior; no per-runner
code duplication.
"""

from __future__ import annotations

import time
import urllib.error
from typing import Callable, TypeVar

T = TypeVar("T")

# HTTP status codes that should trigger a retry.
_RETRYABLE_STATUS_CODES = frozenset({429, 503, 502, 504})


def with_429_retry(
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay_s: float = 1.0,
    cap_delay_s: float = 30.0,
) -> T:
    """Run `fn()` and retry on HTTP 429/503/502/504 with exponential backoff.

    Args:
        fn: zero-arg callable. The wrapped HTTP call; must return on success
            and raise urllib.error.HTTPError on retryable status codes.
        max_retries: max number of additional attempts after the initial call
            (so total calls = 1 + max_retries). Default 3.
        base_delay_s: initial delay; doubles each retry. Default 1.0s.
        cap_delay_s: maximum per-retry delay. Default 30s.

    Returns:
        Whatever `fn()` returns on the first non-retryable success.

    Raises:
        urllib.error.HTTPError: with the LAST attempt's status code if
            all retries are exhausted.
        Anything else `fn()` raises: passed through immediately (no retry).
    """
    attempts = 0
    last_error: urllib.error.HTTPError | None = None
    while attempts <= max_retries:
        try:
            return fn()
        except urllib.error.HTTPError as exc:
            if exc.code not in _RETRYABLE_STATUS_CODES:
                raise
            last_error = exc
            attempts += 1
            if attempts > max_retries:
                break
            delay = min(base_delay_s * (2 ** (attempts - 1)), cap_delay_s)
            time.sleep(delay)
        # Other exceptions (URLError, ValueError) are not retried per spec —
        # caller is expected to handle them.
    # Exhausted; re-raise the last 429/503/etc.
    assert last_error is not None
    raise last_error


__all__ = ["with_429_retry"]
