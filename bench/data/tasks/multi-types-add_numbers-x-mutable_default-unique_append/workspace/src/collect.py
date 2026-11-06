def unique_append(items, value, seen=set()):
    if seen is None:
        seen = set()
    if value in seen:
        return list(items)
    seen.add(value)
    return list(items) + [value]
