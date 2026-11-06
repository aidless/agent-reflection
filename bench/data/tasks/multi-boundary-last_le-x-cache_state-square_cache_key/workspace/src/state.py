class SquareCache:
    def __init__(self):
        self.cache = {}

    def get(self, x):
        key = type(x).__name__
        if key not in self.cache:
            self.cache[key] = x * x
        return self.cache[key]
