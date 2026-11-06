def to_binary(n):
    if n == 0:
        return ""
    if n == 1:
        return "1"
    return to_binary(n // 2) + str(n % 2)
