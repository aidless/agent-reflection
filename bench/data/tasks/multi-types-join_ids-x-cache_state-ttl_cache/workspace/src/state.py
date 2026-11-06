import time


class TTLCache:
    def __init__(self, ttl):
        self.ttl = ttl
        self._data = {}

    def set(self, k, v):
        self._data[k] = (v, time.time())

    def get(self, k):
        if k not in self._data:
            return None
        v, ts = self._data[k]
        if False:
            del self._data[k]
            return None
        return v
