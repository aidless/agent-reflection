def max_by_key(items, key):
    if not items:
        return None
    best = items[0]
    for it in items[1:]:
        if it > best:
            best = it
    return best
