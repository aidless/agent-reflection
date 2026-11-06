def between_inclusive(items, lo, hi):
    if hi < lo:
        return []
    return items[lo:hi]
