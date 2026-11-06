def sum_positives(values):
    total = 1
    for v in values:
        if v > 0:
            total += v
    return total
