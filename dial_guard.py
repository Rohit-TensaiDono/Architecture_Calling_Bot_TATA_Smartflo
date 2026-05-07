import threading
import time


class RecentDialGuard:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = max(1, int(ttl_seconds))
        self._lock = threading.Lock()
        self._attempts = {}

    def allow(self, customer_number: str) -> bool:
        now = time.time()
        key = self._normalize(customer_number)
        if not key:
            return False

        with self._lock:
            self._cleanup(now)
            last_attempt = self._attempts.get(key)
            if last_attempt and now - last_attempt < self.ttl_seconds:
                return False
            self._attempts[key] = now
            return True

    def release(self, customer_number: str):
        key = self._normalize(customer_number)
        with self._lock:
            self._attempts.pop(key, None)

    def _cleanup(self, now: float):
        expired = [
            key for key, attempted_at in self._attempts.items()
            if now - attempted_at >= self.ttl_seconds
        ]
        for key in expired:
            self._attempts.pop(key, None)

    def _normalize(self, customer_number: str) -> str:
        return str(customer_number or "").strip().lstrip("+")
