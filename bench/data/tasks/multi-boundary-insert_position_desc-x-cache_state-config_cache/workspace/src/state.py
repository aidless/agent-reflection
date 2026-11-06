class Config:
    def __init__(self):
        self._cache = {}
        self._values = {}

    def set(self, k, v):
        self._values[k] = v

    def get(self, k, default=None):
        if k not in self._cache:
            self._cache[k] = self._values.get(k, default)
        return self._cache[k]
