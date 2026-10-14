# PICADS Python reference is only for selected ALU behavior.
# The CO-selected six-macro physical processor is the Verilog implementation.
# There is currently NO proof of full-CPU sequential equivalence.

def helios16_reference(op: u3, a: u16, b: u16) -> u16:
    if op == 0:
        return (a + b) & 65535
    if op == 1:
        return (a - b) & 65535
    if op == 2:
        return a & b
    if op == 3:
        return a | b
    if op == 4:
        return a ^ b
    return a
