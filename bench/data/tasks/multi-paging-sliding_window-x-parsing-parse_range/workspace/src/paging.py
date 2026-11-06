def sliding_window(items, k):
    if k < 1:
        raise ValueError("k must be >= 1")
    return [items[i:i + k] for i in range(len(items) - k)]
