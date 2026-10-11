def leaf(a: u4, b: u4) -> u5:
    return a + b

def middle(a: u4, b: u4) -> u6:
    return leaf(a, b) + 1

def top(a: u4, b: u4) -> u7:
    return middle(a, b) + middle(b, a)
