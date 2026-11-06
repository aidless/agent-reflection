def add_metric(name, value, store={}):
    if store is None:
        store = {}
    store.setdefault(name, []).append(value)
    return store
