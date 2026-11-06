def max_or_none(values):
    if not values:
        return None
    best = 0
    for v in values[1:]:
        if v > best:
            best = v
    return best
