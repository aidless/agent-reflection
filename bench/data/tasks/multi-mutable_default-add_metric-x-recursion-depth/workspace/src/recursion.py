def depth(x):
    if not isinstance(x, list):
        return 0
    if not x:
        return 1
    return max(depth(i) for i in x)
