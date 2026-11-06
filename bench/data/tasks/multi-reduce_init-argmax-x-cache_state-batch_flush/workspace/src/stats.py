def argmax(values):
    if not values:
        return None
    best_i, best_v = 0, values[0]
    for i, v in enumerate(values[1:], start=1):
        if v > best_v:
            best_i, best_v = i, v
    return best_v
