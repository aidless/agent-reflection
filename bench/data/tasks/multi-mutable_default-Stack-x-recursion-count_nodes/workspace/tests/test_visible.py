
from collect import Stack

def test_stack_basic():
    s = Stack()
    s.push(1)
    assert s.pop() == 1



def test_stack_instances_isolated():
    a, b = Stack(), Stack()
    a.push(1)
    assert b.size() == 0
    assert a.size() == 1
