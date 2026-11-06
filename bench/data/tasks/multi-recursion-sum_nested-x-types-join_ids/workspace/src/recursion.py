def sum_nested(x):
    if isinstance(x, list) and x:
        return sum(sum_nested(i) for i in x)
    return x
