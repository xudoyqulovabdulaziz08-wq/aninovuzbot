import time
import logging
from collections import deque
from typing import Dict, Any

logger = logging.getLogger("Metrics")


class Metrics:
    """
    📊 ULTRA HIGH PERFORMANCE METRICS SYSTEM
    🚀 REAL O(1) MOVING AVERAGE WITH FLOATING-POINT CALIBRATION
    """

    def __init__(self, window_size: int = 500):
        self.requests = 0
        self.window_size = window_size
        
        # Slayd oynalari (Moving Windows)
        self.db_latency = deque(maxlen=self.window_size)
        self.cache_latency = deque(maxlen=self.window_size)

        # Matematik yig'indilar (O(1) yangilash uchun)
        self._db_sum = 0.0
        self._cache_sum = 0.0

        # Kalibrlash hisoblagichlari (Floating-point aniqligini saqlash uchun)
        self._db_op_count = 0
        self._cache_op_count = 0
        self._recalibrate_interval = 500  # Har 500 ta operatsiyada qayta hisoblanadi

    # ================= REQUEST =================
    def request(self):
        self.requests += 1

    # ================= DB TRACK =================
    def track_db(self, start: float):
        """
        🚀 Perf counter yordamida aniq va xavfsiz kechikish vaqtini hisoblash
        """
        latency = time.perf_counter() - start  # ✅ FIX 3: Monoton soat (NTP o'zgarishlariga chidamli)
        
        # O'chib ketadigan elementni aniqlash
        # Deque to'lgan holatda append qilinsa, eng birinchi element avtomatik o'chadi
        if len(self.db_latency) == self.window_size:
            oldest = self.db_latency[0]
            self._db_sum -= oldest
        
        self.db_latency.append(latency)
        self._db_sum += latency

        # ✅ FIX 1: FLOATING-POINT PRECISION RECALIBRATION
        self._db_op_count += 1
        if self._db_op_count >= self._recalibrate_interval:
            self._db_sum = sum(self.db_latency)  # Kichik siljishlar butkul tozalanadi
            self._db_op_count = 0

    # ================= CACHE TRACK =================
    def track_cache(self, start: float):
        latency = time.perf_counter() - start
        
        if len(self.cache_latency) == self.window_size:
            oldest = self.cache_latency[0]
            self._cache_sum -= oldest

        self.cache_latency.append(latency)
        self._cache_sum += latency

        # ✅ FIX 1: FLOATING-POINT PRECISION RECALIBRATION
        self._cache_op_count += 1
        if self._cache_op_count >= self._recalibrate_interval:
            self._cache_sum = sum(self.cache_latency)
            self._cache_op_count = 0

    # ================= DINAMIK AVERAGES =================
    @property
    def db_avg(self) -> float:
        count = len(self.db_latency)
        # Manfiy float qoldiqlar (masalan -1.2e-15) yuzaga kelsa, xavfsiz nolga o'giriladi
        if count == 0 or self._db_sum <= 0:
            return 0.0
        return self._db_sum / count

    @property
    def cache_avg(self) -> float:
        count = len(self.cache_latency)
        if count == 0 or self._cache_sum <= 0:
            return 0.0
        return self._cache_sum / count

    # ================= REPORT =================
    def report(self) -> Dict[str, Any]:
        return {
            "requests": self.requests,
            "db_avg_ms": round(self.db_avg * 1000, 2),     # Ko'pincha millisekundda ko'rish qulayroq
            "cache_avg_ms": round(self.cache_avg * 1000, 2)
        }


# Global singleton instansiya
metrics = Metrics()