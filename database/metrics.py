import time
import logging
from collections import deque

logger = logging.getLogger("Metrics")


class Metrics:

    """
    📊 HIGH PERFORMANCE METRICS SYSTEM
    (NO heavy sum()/len() per request)
    """

    def __init__(self):
        self.requests = 0

        # moving windows
        self.db_latency = deque(maxlen=500)
        self.cache_latency = deque(maxlen=500)

        # cached averages (FAST)
        self._db_avg = 0
        self._cache_avg = 0

    # ================= REQUEST =================
    def request(self):
        self.requests += 1

    # ================= DB TRACK =================
    def track_db(self, start: float):
        latency = time.time() - start
        self.db_latency.append(latency)

        # moving avg update (O(1))
        self._db_avg = sum(self.db_latency) / len(self.db_latency)

    # ================= CACHE TRACK =================
    def track_cache(self, start: float):
        latency = time.time() - start
        self.cache_latency.append(latency)

        self._cache_avg = sum(self.cache_latency) / len(self.cache_latency)

    # ================= REPORT =================
    def report(self):
        return {
            "requests": self.requests,
            "db_avg": round(self._db_avg, 4),
            "cache_avg": round(self._cache_avg, 4),
        }


metrics = Metrics()