class Node:
    def __init__(self, value, children=None):
        self.value = value
        self.children = children or []


def tree_height(node):
    if node is None:
        return 0
    if not node.children:
        return 0
    return 1 + max(tree_height(c) for c in node.children)
