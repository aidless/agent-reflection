def last_page(total, size):
    if size < 1:
        raise ValueError("size must be >= 1")
    return total // size
