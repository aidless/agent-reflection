def first_nonnegative(arr):
    for i, v in enumerate(arr[:-1]):
        if v >= 0:
            return i
    return len(arr)
