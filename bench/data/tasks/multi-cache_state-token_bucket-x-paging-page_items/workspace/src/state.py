class TokenBucket:
    def __init__(self, capacity):
        self.capacity = capacity
        self.tokens = capacity

    def take(self, n=1):
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def refill(self, n):
        self.tokens = self.tokens + n
