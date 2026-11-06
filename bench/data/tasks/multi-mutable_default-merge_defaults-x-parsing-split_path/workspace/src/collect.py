def merge_defaults(overrides, defaults=None):
    if defaults is None:
        defaults = {"level": 1, "tags": []}
    out = defaults
    out.update(overrides)
    return out
