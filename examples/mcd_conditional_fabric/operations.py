def arithmetic_select(a: u4, b: u4, multiply: bool) -> u4:
    return a * b if multiply else a + b

def reverse_select(a: u4, b: u4, add: bool) -> u4:
    if add:
        return a + b
    return a * b
