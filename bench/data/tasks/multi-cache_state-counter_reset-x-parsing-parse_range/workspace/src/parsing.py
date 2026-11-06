def parse_range(spec):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.append(int(a))
        else:
            out.append(int(part))
    return out
