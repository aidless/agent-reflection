def clamp(value, lo, hi):
    if hi < lo:
        raise ValueError("hi must be >= lo")
    return min(lo, max(hi, value))
