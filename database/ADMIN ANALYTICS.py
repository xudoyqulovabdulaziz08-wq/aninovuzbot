import logging

logger = logging.getLogger("AdminAnalytics")


class AdminAnalytics:

    def __init__(self, orchestrator, metrics):
        self.orchestrator = orchestrator
        self.metrics = metrics

    # ================= SYSTEM HEALTH =================
    def system_health(self):
        return {
            "cache_hit_l1": self.orchestrator.stats["l1_hits"],
            "cache_hit_l2": self.orchestrator.stats["l2_hits"],
            "db_hits": self.orchestrator.stats["db_hits"],
            "miss": self.orchestrator.stats["miss"],
        }

    # ================= FULL REPORT =================
    def full_report(self):
        return {
            "system": self.system_health(),
            "metrics": self.metrics.report(),
        }