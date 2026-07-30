"""Tests for at_common.fetch_parallel, the bounded-concurrency fetcher.

These pin the three properties the board sources actually rely on, each of which
was a real bug risk when the sources moved off "serial loop + time.sleep":

  1. Order is preserved. Both callers dedupe with `setdefault`, so if results
     came back in completion order the winning duplicate would be chosen by
     network timing rather than by the caller's search ordering.
  2. Concurrency is genuinely bounded. A pool that ignored `workers` would point
     60 simultaneous requests at karriere.at, which is the behaviour that got
     StepStone's WAF to IP-block this machine.
  3. Work actually overlaps. A "parallel" helper that silently ran serially
     would still pass 1 and 2 while leaving the 8-minute scan unfixed.
"""

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from sources.at_common import fetch_parallel


def test_preserves_input_order_regardless_of_completion_order():
    """Item 0 finishes last; it must still come back first."""
    def worker(n: int) -> int:
        time.sleep(0.05 if n == 0 else 0.0)
        return n

    assert fetch_parallel(range(6), worker, workers=6) == [0, 1, 2, 3, 4, 5]


def test_never_exceeds_the_worker_ceiling():
    lock = threading.Lock()
    live = 0
    peak = 0

    def worker(_):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.02)
        with lock:
            live -= 1

    fetch_parallel(range(24), worker, workers=4)
    assert peak <= 4, f"ran {peak} concurrent workers, ceiling was 4"


def test_actually_runs_concurrently():
    """8 items x 0.1s must take well under the 0.8s a serial run would."""
    started = time.monotonic()
    fetch_parallel(range(8), lambda _: time.sleep(0.1), workers=8)
    elapsed = time.monotonic() - started
    assert elapsed < 0.4, f"took {elapsed:.2f}s — looks serial, not parallel"


def test_pace_throttles_each_worker():
    """With one worker, `pace` is a floor on the time between items."""
    started = time.monotonic()
    fetch_parallel(range(3), lambda n: n, workers=1, pace=0.05)
    elapsed = time.monotonic() - started
    assert elapsed >= 0.15, f"pace ignored: 3 items in {elapsed:.3f}s"


def test_empty_input_makes_no_calls():
    calls = []
    assert fetch_parallel([], calls.append) == []
    assert calls == []


def test_single_worker_falls_back_to_a_plain_loop():
    """workers=1 must still return every result, in order."""
    assert fetch_parallel(range(5), lambda n: n * 2, workers=1) == [0, 2, 4, 6, 8]
