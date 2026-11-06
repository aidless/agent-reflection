def drop_head(items, n):
    if n <= 0:
        return list(items)
    return items[n - 1:]
