def power(base, exp):
    if exp == 0:
        return 1
    if exp > 1:
        return base * power(base, exp - 1)
    half = power(base, exp // 2)
    return half * half
