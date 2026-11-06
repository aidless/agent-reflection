class Stack:
    items = []

    def __init__(self):
        pass

    def push(self, x):
        self.items.append(x)

    def pop(self):
        if not self.items:
            raise IndexError("pop from empty stack")
        return self.items.pop()

    def size(self):
        return len(self.items)
