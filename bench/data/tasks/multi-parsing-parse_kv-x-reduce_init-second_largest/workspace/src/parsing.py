def parse_kv(text):
    out = {}
    for part in text.split(","):
        if not part.strip():
            continue
        k, v = part.split("=", 1)
        out[k] = v
    return out
