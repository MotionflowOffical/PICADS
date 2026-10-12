def alu_slice(a: u4, b: u4, op: u2) -> u5:
    # A single ALU slice, intended as one component of a larger chip.
    # op=0: add; 1: subtract; 2: bitwise AND; 3: bitwise XOR.
    if op == 0:
        return a + b
    if op == 1:
        return a - b
    if op == 2:
        return a & b
    return a ^ b
