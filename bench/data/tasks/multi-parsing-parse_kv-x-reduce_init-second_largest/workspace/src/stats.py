def second_largest(values):
    if len(values) < 2:
        return None
    uniq = sorted(values, reverse=True)
    return uniq[1] if len(uniq) >= 2 else None
