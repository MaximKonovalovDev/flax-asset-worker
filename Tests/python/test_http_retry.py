"""Tests for execution/_http_retry.py (v1.12.s66)."""

from __future__ import annotations

import unittest
import urllib.error
from unittest.mock import patch


class HttpRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution._http_retry import with_429_retry
        self.fn = with_429_retry

    def _make_http_error(self, code: int) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            url="x", code=code, msg="test",
            hdrs=None, fp=None,  # type: ignore[arg-type]
        )

    def test_success_on_first_try_no_sleep(self) -> None:
        calls = {"n": 0}

        def succeed():
            calls["n"] += 1
            return "ok"

        with patch("assetboy.execution._http_retry.time.sleep") as mock_sleep:
            result = self.fn(succeed)
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 1)
        mock_sleep.assert_not_called()

    def test_429_retried_until_success(self) -> None:
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise self._make_http_error(429)
            return "got_it"

        with patch("assetboy.execution._http_retry.time.sleep") as mock_sleep:
            result = self.fn(flaky, max_retries=3, base_delay_s=0.1)
        self.assertEqual(result, "got_it")
        self.assertEqual(attempts["n"], 3)
        # Two retries -> two sleeps (0.1s, then 0.2s).
        self.assertEqual(mock_sleep.call_count, 2)

    def test_503_also_retried(self) -> None:
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise self._make_http_error(503)
            return "served"

        with patch("assetboy.execution._http_retry.time.sleep"):
            result = self.fn(flaky, base_delay_s=0.1)
        self.assertEqual(result, "served")
        self.assertEqual(attempts["n"], 2)

    def test_404_not_retried(self) -> None:
        attempts = {"n": 0}

        def always_404():
            attempts["n"] += 1
            raise self._make_http_error(404)

        with patch("assetboy.execution._http_retry.time.sleep") as mock_sleep:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.fn(always_404)
        self.assertEqual(ctx.exception.code, 404)
        self.assertEqual(attempts["n"], 1)
        mock_sleep.assert_not_called()

    def test_429_exhausted_reraises_last_error(self) -> None:
        attempts = {"n": 0}

        def always_429():
            attempts["n"] += 1
            raise self._make_http_error(429)

        with patch("assetboy.execution._http_retry.time.sleep"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.fn(always_429, max_retries=2, base_delay_s=0.01)
        self.assertEqual(ctx.exception.code, 429)
        # max_retries=2 means 1 initial + 2 retries = 3 attempts.
        self.assertEqual(attempts["n"], 3)

    def test_url_error_not_retried(self) -> None:
        """urllib.error.URLError (not HTTPError) passes through unchanged."""
        def url_error():
            raise urllib.error.URLError("connection refused")

        with self.assertRaises(urllib.error.URLError):
            self.fn(url_error)

    def test_value_error_not_retried(self) -> None:
        """Any non-HTTPError exception passes through."""
        def boom():
            raise ValueError("bad payload")

        with self.assertRaises(ValueError):
            self.fn(boom)

    def test_delay_capped(self) -> None:
        """cap_delay_s prevents runaway exponential delays."""
        attempts = {"n": 0}
        recorded_delays: list[float] = []

        def always_429():
            attempts["n"] += 1
            raise self._make_http_error(429)

        def capture_sleep(d):
            recorded_delays.append(d)

        with patch("assetboy.execution._http_retry.time.sleep", side_effect=capture_sleep):
            with self.assertRaises(urllib.error.HTTPError):
                self.fn(always_429, max_retries=10, base_delay_s=1.0, cap_delay_s=4.0)
        # base=1 doubling: 1, 2, 4, 8, 16... but capped at 4.
        # 10 retries means 10 sleeps total.
        self.assertEqual(len(recorded_delays), 10)
        self.assertTrue(all(d <= 4.0 for d in recorded_delays))
        # First 3 should be 1, 2, 4. Rest capped at 4.
        self.assertEqual(recorded_delays[0], 1.0)
        self.assertEqual(recorded_delays[1], 2.0)
        self.assertEqual(recorded_delays[2], 4.0)
        self.assertEqual(recorded_delays[3], 4.0)


if __name__ == "__main__":
    unittest.main()
