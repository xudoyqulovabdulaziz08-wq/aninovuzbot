import time
import logging
from typing import Optional, Dict, Any

from collections import OrderedDict

from database.cache import valkey
from database.repository import UserRepository

logger = logging.getLogger("Orchestrator")


class Orchestrator:

    """
    🧠 FINAL CACHE BRAIN (L1 + L2 + DB)

    FLOW:
    L1 (RAM) → L2 (Redis) → DB
    """

    def __init__(self):
        # ================= L1 CACHE (HOT USERS) =================
        self.l1_cache: OrderedDict[int, Dict[str, Any]] = OrderedDict()
        self.l1_max_size = 5000

        # ================= STATS =================
        self.stats = {
            "l1_hits": 0,
            "l2_hits": 0,
            "db_hits": 0,
        }

    # ================= MAIN FETCH =================
    async def get_user(self, session_pool, tg_user):

        user_id = tg_user.id

        # ================= L1 CACHE =================
        cached = self.l1_cache.get(user_id)
        if cached:
            self.l1_cache.move_to_end(user_id)

            self.stats["l1_hits"] += 1
            return cached

        # ================= L2 CACHE =================
        if valkey.is_alive:
            try:
                cached = await valkey.get("users", user_id)

                if cached:
                    self._set_l1(user_id, cached)

                    self.stats["l2_hits"] += 1
                    return cached

            except Exception as e:
                logger.debug(f"L2 error: {e}")

        # ================= DB FALLBACK =================
        self.stats["db_hits"] += 1

        async with session_pool() as session:
            user = await UserRepository.get_or_create(session, tg_user)
            data = self._to_dict(user)

            await self._sync_cache(user_id, data)

            return data

    # ================= L1 SET =================
    def _set_l1(self, key: int, value: dict):
        self.l1_cache[key] = value
        self.l1_cache.move_to_end(key)

        if len(self.l1_cache) > self.l1_max_size:
            self.l1_cache.popitem(last=False)

    # ================= CACHE SYNC =================
    async def _sync_cache(self, user_id: int, data: dict):
        try:
            self._set_l1(user_id, data)

            if valkey.is_alive:
                await valkey.set("users", user_id, data, ttl=180)

        except Exception as e:
            logger.debug(f"cache sync error: {e}")

    # ================= FORMAT =================
    def _to_dict(self, user):
        return {
            "user_id": user.user_id,
            "username": user.username,
            "status": user.status,
            "points": user.points,
            "referral_count": user.referral_count,
        }