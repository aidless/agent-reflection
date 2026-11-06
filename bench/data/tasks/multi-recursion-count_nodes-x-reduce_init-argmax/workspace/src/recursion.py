def count_nodes(tree):
    if not isinstance(tree, dict):
        return 0
    return sum(count_nodes(v) for v in tree.values())
