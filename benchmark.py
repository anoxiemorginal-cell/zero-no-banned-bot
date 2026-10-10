"""Offline rule throughput only; no API calls or production messages."""
import time
from core import Detector

detector = Detector()
count = 100_000
start = time.perf_counter()
flagged = 0
for index in range(count):
    flagged += detector.message(-1001, index % 2000, index, 'campaign message with more than forty characters', 100 + index / 10000) is not None
elapsed = time.perf_counter() - start
print(f'Offline rule check: {count} events in {elapsed:.3f}s = {count / elapsed:,.0f} events/s; flagged={flagged}; windows={len(detector.windows)}')
