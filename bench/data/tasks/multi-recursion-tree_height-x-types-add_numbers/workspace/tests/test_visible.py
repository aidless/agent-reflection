
from recursion import Node, tree_height

def test_height_root_only():
    assert tree_height(Node(1)) == 1



def test_height_two_levels():
    root = Node(1, [Node(2), Node(3)])
    assert tree_height(root) == 2
