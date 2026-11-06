def min_or_none(values):
    if not values:
        return float("inf")
    best = values[0]
    for v in values[1:]:
        if v < best:
            best = v
    return best
