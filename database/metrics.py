import time
import logging
from collections import deque

logger = logging.getLogger("Metrics")


class Metrics:
    """
    📊 ULTRA HIGH PERFORMANCE METRICS SYSTEM
    🚀 REAL O(1) MOVING AVERAGE WITH NO SUM() LOOPS
    """

    def __init__(self):
        self.requests = 0

        # Oyna hajmi (so'nggi 500 ta so'rov)
        self.window_size = 500
        
        # Slayd oynalari (Moving Windows)
        self.db_latency = deque(maxlen=self.window_size)
        self.cache_latency = deque(maxlen=self.window_size)

        # Matematik yig'indilar (O(1) yangilash uchun)
        self._db_sum = 0.0
        self._cache_sum = 0.0

    # ================= REQUEST =================
    def request(self):
        self.requests += 1

    # ================= DB TRACK =================
    def track_db(self, start: float):
        latency = time.time() - start

        # Agar deque to'lgan bo'lsa, chapdan chiqib ketadigan elementni aniqlaymiz
        if len(self.db_latency) == self.window_size:
            oldest = self.db_latency[0]  # O(1) tezlikda eng birinchi elementni olish
            self._db_sum -= oldest       # Eskisini yig'indidan ayiramiz

        # Yangi qiymatni qo'shamiz
        self.db_latency.append(latency)
        self._db_sum += latency          # Yangisini yig'indiga qo'shamiz

    # ================= CACHE TRACK =================
    def track_cache(self, start: float):
        latency = time.time() - start

        if len(self.cache_latency) == self.window_size:
            oldest = self.cache_latency[0]
            self._cache_sum -= oldest

        self.cache_latency.append(latency)
        self._cache_sum += latency

    # ================= DINAMIK AVERAGES =================
    # Property yordamida o'rtacha qiymat faqat so'ralgandagina va O(1) da hisoblanadi
    @property
    def db_avg(self) -> float:
        count = len(self.db_latency)
        return self._db_sum / count if count > 0 else 0.0

    @property
    def cache_avg(self) -> float:
        count = len(self.cache_latency)
        return self._cache_sum / count if count > 0 else 0.0

    # ================= REPORT =================
    def report(self):
        return {
            "requests": self.requests,
            "db_avg": round(self.db_avg, 4),
            "cache_avg": round(self.cache_avg, 4),
        }


# Global singletone instansiya
metrics = Metrics()