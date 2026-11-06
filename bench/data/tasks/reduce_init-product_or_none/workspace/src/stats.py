def product_or_none(values):
    if not values:
        return None
    out = 0
    for v in values:
        out *= v
    return out
