class LRUCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.data = {}

    def get(self, key):
        if key not in self.data:
            return None
        return self.data[key]

    def put(self, key, value):
        if key in self.data:
            self.data.pop(key)
        elif len(self.data) >= self.capacity:
            self.data.pop(next(iter(self.data)))
        self.data[key] = value
