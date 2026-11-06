def make_counter():
    state = {"n": 0}

    def inc():
        n = state["n"]
        state["n"] += 1
        return n

    return inc
