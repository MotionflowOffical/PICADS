def first(a: u5, b: u5) -> u6:
    if a < b:
        v: u6 = a + b
    else:
        v: u6 = a - b
    return v


def second(a: u5, b: u5) -> u6:
    if a < b:
        v: u6 = a - b
    else:
        v: u6 = a + b
    return v
