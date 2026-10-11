def calculate(a: u4, b: u4, choose: bool) -> u8:
    if choose:
        result: u8 = a * b
    else:
        result: u8 = a + b
    return result
