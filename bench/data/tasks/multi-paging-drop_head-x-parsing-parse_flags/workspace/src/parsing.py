def parse_flags(argv):
    out = {}
    for token in argv:
        if not token.startswith("--"):
            continue
        body = token[2:]
        if "=" in body:
            k, v = body.split("=", 1)
            out[k] = v
        else:
            out[body] = "true"
    return out
