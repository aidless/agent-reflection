def parse_float_list(text):
    if not text.strip():
        return []
    return [float(x) for x in text.split(",")]
