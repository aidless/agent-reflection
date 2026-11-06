def paginate_pairs(items, size):
    if size < 1:
        raise ValueError("size must be >= 1")
    out = []
    start = 0
    while start < len(items) - size:
        out.append((start + 1, items[start:start + size]))
        start += size
    return out
