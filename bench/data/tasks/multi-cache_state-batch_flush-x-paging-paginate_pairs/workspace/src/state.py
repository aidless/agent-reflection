class BatchStats:
    def __init__(self):
        self.items = []

    def add(self, x):
        self.items.append(x)

    def flush(self):
        vals = list(self.items)
        return sum(vals) / len(vals) if vals else None
