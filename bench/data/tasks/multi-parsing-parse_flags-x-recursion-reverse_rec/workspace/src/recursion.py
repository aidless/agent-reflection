def reverse_rec(s):
    if len(s) <= 1:
        return s
    return s[0] + reverse_rec(s[1:])
