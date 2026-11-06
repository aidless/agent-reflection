def page_items(items, page, size):
    if page < 1 or size < 1:
        raise ValueError("page and size must be >= 1")
    start = page * size
    return items[start:start + size]
