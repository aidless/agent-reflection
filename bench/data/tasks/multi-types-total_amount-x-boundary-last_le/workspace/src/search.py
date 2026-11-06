def last_le(arr, x):
    pos = -1
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] <= x:
            pos = mid + 1
            lo = mid + 1
        else:
            hi = mid - 1
    return pos
