class Memo:
    cache = {}

    def __init__(self):
        pass

    def compute(self, x):
        if x not in self.cache:
            self.cache[x] = x * 3
        return self.cache[x]
