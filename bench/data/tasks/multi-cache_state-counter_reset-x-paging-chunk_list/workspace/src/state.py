class Counter:
    def __init__(self):
        self.total = 0

    def add(self, x=1):
        self.total += x
        return self.total

    def reset(self):
        return self
