# Tiny8: deliberately small 8-bit stored-program processor for PICADS.
# CO transactional scheduling adds the physical start/ready/done/fault/stall/reset interface.
# Each EXECUTE transaction fetches and executes exactly one instruction.
# The host can load 8-bit instructions/data over the DEPOSIT command port.
# No Python interpreter is present on the chip.
#
# 16 x 8-bit register-memory word map:
#   0..7    instructions,   8..11  writable data
#   12      output latch,  13      zero status (0/1)
#   14      accumulator,   15      PC (only low 3 bits used)
# Instruction: [7:4] opcode / [3:0] operand
#   0 NOP, 1 LDI, 2 LDA, 3 ADD, 4 SUB, 5 AND,
#   6 XOR, 7 STA, 8 JMP, 9 JZ, A OUT, B OR.
#   Arithmetic results wrap to 8 bits; addresses select one of 16 RAM words.
#   Branch destinations wrap to 3 bits (program slots 0..7).
# Interface command: 0 EXECUTE, 1 DEPOSIT, 2 PEEK, 3 STATUS(ACC)


def tiny8_cpu(command: u2, location: u4, data: u8) -> u8:
    if command == 1:
        mem_write(location, data)
        return data

    if command == 2:
        return mem_read(location)

    if command == 3:
        return mem_read(14)

    pc: u8 = mem_read(15)
    fetch: u4 = pc & 7
    instruction: u8 = mem_read(fetch)
    opcode: u8 = instruction & 240
    address: u4 = instruction & 15
    acc: u8 = mem_read(14)
    next_pc: u8 = (pc + 1) & 7

    if opcode == 16:                    # LDI #imm4
        mem_write(14, instruction & 15)
    elif opcode == 32:                  # LDA [address]
        loaded: u8 = mem_read(address)
        mem_write(14, loaded)
    elif opcode == 48:                  # ADD [address]
        rhs_add: u8 = mem_read(address)
        mem_write(14, (acc + rhs_add) & 255)
    elif opcode == 64:                  # SUB [address]
        rhs_sub: u8 = mem_read(address)
        mem_write(14, (acc - rhs_sub) & 255)
    elif opcode == 80:                  # AND [address]
        rhs_and: u8 = mem_read(address)
        mem_write(14, acc & rhs_and)
    elif opcode == 96:                  # XOR [address]
        rhs_xor: u8 = mem_read(address)
        mem_write(14, acc ^ rhs_xor)
    elif opcode == 112:                 # STA [address]
        mem_write(address, acc)
    elif opcode == 128:                 # JMP target
        next_pc = address & 7
    elif opcode == 144:                 # JZ target
        if acc == 0:
            next_pc = address & 7
    elif opcode == 160:                 # OUT: output latch = accumulator
        mem_write(12, acc)
    elif opcode == 176:                 # OR [address]
        rhs_or: u8 = mem_read(address)
        mem_write(14, acc | rhs_or)

    # Maintain a readable zero flag for diagnostics / future branch extensions.
    new_acc: u8 = mem_read(14)
    mem_write(13, 1 if new_acc == 0 else 0)
    mem_write(15, next_pc)
    return new_acc
