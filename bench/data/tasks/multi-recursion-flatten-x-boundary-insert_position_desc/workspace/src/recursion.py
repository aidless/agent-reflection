def flatten(items):
    out = []
    for it in items:
        if isinstance(it, list) and it:
            out.extend(flatten(it))
        else:
            out.append(it)
    return out
