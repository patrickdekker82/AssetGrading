"""Wall time, CPU time and peak memory of one job (phase 10: memory and compute on the Synology)."""

import resource
import threading
import time
from pathlib import Path


def rss_mb() -> float | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except OSError:
        return None
    return None


class ResourceMeter:
    """Samples the process memory twice a second while a job runs. CPU time is the whole process (the
    scheduler runs jobs in threads), so it is an upper bound for one job."""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.peak = 0.0
        self._stop = threading.Event()

    def __enter__(self) -> "ResourceMeter":
        self._t0, self._cpu0 = time.monotonic(), self._cpu()
        self.start_mb = rss_mb()
        self.peak = self.start_mb or 0.0
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def _sample(self) -> None:
        while not self._stop.wait(self.interval):
            v = rss_mb()
            if v is not None and v > self.peak:
                self.peak = v

    @staticmethod
    def _cpu() -> float:
        r = resource.getrusage(resource.RUSAGE_SELF)
        return r.ru_utime + r.ru_stime

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        v = rss_mb()
        if v is not None and v > self.peak:
            self.peak = v
        self.result = {"seconds": round(time.monotonic() - self._t0, 1),
                       "cpu_seconds": round(self._cpu() - self._cpu0, 1),
                       "peak_rss_mb": round(self.peak, 1) if self.peak else None,
                       "start_rss_mb": round(self.start_mb, 1) if self.start_mb else None}
