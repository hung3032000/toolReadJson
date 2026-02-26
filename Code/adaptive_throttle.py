import asyncio
import time
from collections import deque


def _percentile(values, pct):
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = max(0, min(len(sorted_vals) - 1, int(round((pct / 100.0) * (len(sorted_vals) - 1)))))
    return float(sorted_vals[k])


class AdaptiveThrottle:
    def __init__(
        self,
        window_sec=10,
        min_concurrency=8,
        max_concurrency=24,
        min_chunk_size=20,
        max_chunk_size=60,
    ):
        self.window_sec = int(window_sec)
        self.min_concurrency = int(min_concurrency)
        self.max_concurrency = int(max_concurrency)
        self.min_chunk_size = int(min_chunk_size)
        self.max_chunk_size = int(max_chunk_size)
        self._events = deque()

    def _prune(self, now_ts):
        cutoff = now_ts - self.window_sec
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def record(self, latency_ms, status_code=None, is_error=False):
        now_ts = time.time()
        self._events.append((now_ts, float(latency_ms), status_code, bool(is_error)))
        self._prune(now_ts)

    def snapshot(self):
        now_ts = time.time()
        self._prune(now_ts)
        total = len(self._events)
        if total == 0:
            return {
                "count": 0,
                "p95_latency_ms": 0.0,
                "error_rate": 0.0,
                "status_5xx_rate": 0.0,
            }

        latencies = [ev[1] for ev in self._events]
        errors = 0
        server_5xx = 0
        for _, _, status, is_err in self._events:
            if is_err:
                errors += 1
            if status is not None and 500 <= int(status) < 600:
                errors += 1
                server_5xx += 1
            if status == 429:
                errors += 1

        return {
            "count": total,
            "p95_latency_ms": _percentile(latencies, 95),
            "error_rate": float(errors) / float(total),
            "status_5xx_rate": float(server_5xx) / float(total),
        }

    def suggest(self, current_concurrency, current_chunk_size):
        current_concurrency = int(current_concurrency)
        current_chunk_size = int(current_chunk_size)
        stats = self.snapshot()
        if stats["count"] == 0:
            return current_concurrency, current_chunk_size, "hold"

        p95 = stats["p95_latency_ms"]
        err = stats["error_rate"]

        if err >= 0.05 or p95 >= 5000.0:
            new_c = max(self.min_concurrency, int(max(self.min_concurrency, current_concurrency * 0.7)))
            new_b = max(self.min_chunk_size, int(max(self.min_chunk_size, current_chunk_size * 0.7)))
            return new_c, new_b, "decrease"

        if err <= 0.02 and p95 <= 2000.0:
            new_c = min(self.max_concurrency, current_concurrency + 2)
            new_b = min(self.max_chunk_size, current_chunk_size + 5)
            return new_c, new_b, "increase"

        return current_concurrency, current_chunk_size, "hold"


class ConcurrencyController:
    def __init__(
        self,
        initial_limit,
        min_limit,
        max_limit,
        initial_chunk_size,
        min_chunk_size,
        max_chunk_size,
    ):
        self.min_limit = int(min_limit)
        self.max_limit = int(max_limit)
        self._limit = max(self.min_limit, min(self.max_limit, int(initial_limit)))
        self._active = 0
        self._condition = asyncio.Condition()

        self.min_chunk_size = int(min_chunk_size)
        self.max_chunk_size = int(max_chunk_size)
        self._chunk_size = max(self.min_chunk_size, min(self.max_chunk_size, int(initial_chunk_size)))

    @property
    def max_workers(self):
        return self.max_limit

    async def acquire(self):
        async with self._condition:
            while self._active >= self._limit:
                await self._condition.wait()
            self._active += 1

    async def release(self):
        async with self._condition:
            if self._active > 0:
                self._active -= 1
            self._condition.notify_all()

    async def set_limit(self, new_limit):
        bounded = max(self.min_limit, min(self.max_limit, int(new_limit)))
        async with self._condition:
            self._limit = bounded
            self._condition.notify_all()

    def get_limit(self):
        return self._limit

    def get_active(self):
        return self._active

    def get_chunk_size(self):
        return self._chunk_size

    def set_chunk_size(self, new_chunk_size):
        self._chunk_size = max(self.min_chunk_size, min(self.max_chunk_size, int(new_chunk_size)))
