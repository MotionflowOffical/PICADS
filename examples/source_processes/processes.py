def choose(a: u4, b: u4, multiply: bool) -> u8:
    if multiply:
        result: u8 = a * b
    else:
        result: u8 = a + b
    return result

def accumulate(a: u4, b: u4) -> u8:
    total: u8 = a + b
    total = total + a
    return total
