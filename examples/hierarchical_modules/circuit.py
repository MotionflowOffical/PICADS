def adder(x: u4, y: u4) -> u5:
    return x + y

def compute(a: u4, b: u4, c: u4) -> u6:
    left = adder(a, b)
    right = adder(b, c)
    return left + right
