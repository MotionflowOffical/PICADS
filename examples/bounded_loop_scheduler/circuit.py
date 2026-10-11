def accumulate(a: u4, b: u4) -> u8:
    total: u8 = 0
    for i in range(3):
        total: u8 = total + a
    return total + b
