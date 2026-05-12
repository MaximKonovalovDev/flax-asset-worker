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

import os
import threading
import time
import urllib.error
from typing import Callable, TypeVar

T = TypeVar("T")

# HTTP status codes that should trigger a retry.
_RETRYABLE_STATUS_CODES = frozenset({429, 503, 502, 504})


# v1.13.s99 — global retry budget per process.
# FAW_HTTP_RETRY_BUDGET env var sets the max number of retry SLEEPS this
# process will do in total before subsequent retryable errors short-circuit
# to re-raise. 0 or unset = unlimited (preserves v1.12.s66 behavior).
_BUDGET_LOCK = threading.Lock()
_BUDGET_USED = 0


def _budget_max() -> int:
    raw = os.environ.get("FAW_HTTP_RETRY_BUDGET", "").strip()
    if not raw:
        return 0  # 0 == unlimited
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def get_retry_budget_used() -> int:
    """Diagnostic: how many retry sleeps the process has consumed this run."""
    with _BUDGET_LOCK:
        return _BUDGET_USED


def reset_retry_budget() -> None:
    """Reset the counter (test helper)."""
    global _BUDGET_USED
    with _BUDGET_LOCK:
        _BUDGET_USED = 0


def _budget_consume_one() -> bool:
    """Try to consume one retry slot. Returns True if granted, False if exhausted."""
    global _BUDGET_USED
    cap = _budget_max()
    if cap <= 0:
        # Unlimited mode: still count for diagnostics but always grant.
        with _BUDGET_LOCK:
            _BUDGET_USED += 1
        return True
    with _BUDGET_LOCK:
        if _BUDGET_USED >= cap:
            return False
        _BUDGET_USED += 1
        return True


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

    v1.13.s99: honors FAW_HTTP_RETRY_BUDGET env var (int). When that many
    retry sleeps have been consumed process-wide, subsequent retryable
    errors short-circuit to re-raise immediately. 0 / unset = unlimited.

    Returns:
        Whatever `fn()` returns on the first non-retryable success.

    Raises:
        urllib.error.HTTPError: with the LAST attempt's status code if
            all retries are exhausted OR the global budget is exhausted.
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
            # v1.13.s99 — check global budget before sleeping.
            if not _budget_consume_one():
                # Budget exhausted: don't sleep, don't retry; re-raise now.
                break
            delay = min(base_delay_s * (2 ** (attempts - 1)), cap_delay_s)
            time.sleep(delay)
        # Other exceptions (URLError, ValueError) are not retried per spec —
        # caller is expected to handle them.
    # Exhausted; re-raise the last 429/503/etc.
    assert last_error is not None
    raise last_error


# v1.15.s110 — global polite-sleep override.
# Each runner has a default polite_sleep_s argument. When this env var is
# set, get_polite_sleep_s(default) returns the env override instead, letting
# the operator tune all R1A runners at once.

def get_polite_sleep_s(default: float) -> float:
    """Return FAW_POLITE_SLEEP_S env override (if set, parseable, non-negative)
    or the supplied default.

    Use in runners:
        time.sleep(get_polite_sleep_s(polite_sleep_s))
    """
    raw = os.environ.get("FAW_POLITE_SLEEP_S", "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
        return max(0.0, v)
    except ValueError:
        return default


__all__ = [
    "with_429_retry",
    "get_retry_budget_used",
    "reset_retry_budget",
    "get_polite_sleep_s",
]
