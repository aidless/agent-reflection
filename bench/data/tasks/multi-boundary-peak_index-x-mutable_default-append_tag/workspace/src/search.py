def peak_index(arr):
    lo, hi = 0, len(arr) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] > arr[mid + 1]:
            hi = mid - 1
        else:
            lo = mid + 1
    return lo
