# Apollo 11 / Luminary 099 AGC-inspired standalone PICADS hardware project.
# SOURCE-ONLY MANUAL CHALLENGE: PICADS must generate its own DLS/Verilog/layout.
# Historical basis: Apollo 11 Lunar Module Luminary 099 rev 001, especially
# FRESH_START_AND_RESTART.agc (pages 211-212) and the Block II basic instruction
# set. Original public-domain source: https://github.com/chrislgarry/Apollo-11
#
# THIS IS NOT A TRANSLATION OF THE COMPLETE FLIGHT PROGRAM. In particular:
# - No original 36,864-word fixed rope, 2,048-word erasable memory, banking,
#   DSKY, IMU, counters, interrupt servicing, or interpretive software.
# - A and Q are stored as 15 bits rather than the original wider AGC registers;
#   overflow, editing registers, parity, and timing are not cycle-faithful.
# - The lower 16 words here are a software-loaded executable scratch program,
#   not real fixed-memory rope. Only low 5 address bits select physical slots.
# - AGC-style opcodes are used where supported; the address space is remapped.
# - Selected genuine Luminary fresh-start stores are translated as hardware
#   initialization operations, not as a fully assembled Apollo ROM image.
#
# PICADS COMMAND INTERFACE (transactional CO adds START/READY/DONE/STALL/RESET):
#   command=0  FETCH + EXECUTE one instruction at internal Z (PC).
#   command=1  selected Luminary FRESH START data/state initialization.
#              data = symbolic PRIO12, channel_input = symbolic PRIO30.
#   command=2  PEEK memory[location]; result = selected 15-bit word.
#   command=3  DEPOSIT memory[location] = data; result = written word.
#
# 32-WORD MEMORY MAP (all words are physically implemented as one bank):
#   0..15  software-loaded instructions (can also be read/write data)
#   16     DUMPCNT     17 ERCOUNT       18 FAILREG       19 FAILREG+1
#   20     FAILREG+2   21 REDOCTR      22 DSRUPTSW      23 RCSFLAGS
#   24     A           25 Z/PC         26 Q             27 flags:
#                                               bit0 EXTEND, bit1 RELINT
#   28     output channel latch       29 RESTREG        30 SMODE
#   31     reserved scratch word
#
# Example program (octal AGC instruction notation, decimal for GUI input):
#   DEPOSIT  0, 0o30014 (CA  014 -> RAM[12])
#   DEPOSIT  1, 0o60015 (AD  015 -> RAM[13])
#   DEPOSIT  2, 0o54016 (TS  016 -> RAM[14])
#   DEPOSIT 12, 7
#   DEPOSIT 13, 5
#   FRESH START after loading will reset Z but preserve program/data slots 0..15.
#   EXECUTE three transactions; then PEEK 14 -> 12, PEEK 24 (A) -> 12,
#   PEEK 25 (PC) -> 3.
# Note: these are AGC-like instruction encodings in a REMAPPED 32-word system.


def apollo_luminary_core(command: u2, location: u5, data: u15, channel_input: u15) -> u15:
    # Intentional register-by-register translation of SELECTED LMY99 starts.
    # CAF FOUR / TS RCSFLAGS; CA BIT12 / TS DUMPCNT;
    # CA ZERO / TS ERCOUNT, FAILREG..FAILREG+2, REDOCTR;
    # CS PRIO12 / TS DSRUPTSW; CA PRIO30 / TS RESTREG;
    # CA ZERO / TS SMODE; plus control-register resets for this test model.
    if command == 1:
        mem_write(16, 2048)                     # DUMPCNT = BIT12
        mem_write(17, 0)                        # ERCOUNT
        mem_write(18, 0)                        # FAILREG
        mem_write(19, 0)                        # FAILREG +1
        mem_write(20, 0)                        # FAILREG +2
        mem_write(21, 0)                        # REDOCTR
        mem_write(22, (~data) & 32767)          # DSRUPTSW = CS PRIO12
        mem_write(23, 4)                        # RCSFLAGS = FOUR
        mem_write(24, 0)                        # A
        mem_write(25, 0)                        # Z/PC: start at program slot 0
        mem_write(26, 0)                        # Q
        mem_write(27, 0)                        # EXTEND/RELINT flags
        mem_write(28, 0)                        # output channel latch
        mem_write(29, channel_input)            # RESTREG = PRIO30
        mem_write(30, 0)                        # SMODE
        return 4

    if command == 2:
        return mem_read(location)

    if command == 3:
        mem_write(location, data)
        return data

    # 1. Fetch: instruction comes from the on-chip RAM addressed by Z.
    z: u15 = mem_read(25)
    fetch_address: u5 = z & 15
    instruction: u15 = mem_read(fetch_address)

    # 2. Decode: take opcode groups from authentic 15-bit AGC encodings.
    a: u15 = mem_read(24)
    q: u15 = mem_read(26)
    flags: u15 = mem_read(27)
    field: u5 = instruction & 31
    next_z: u15 = (z + 1) & 15
    extended: u1 = flags & 1

    # Extended I/O prefix and interrupt-enable control state are simplified.
    if extended != 0:
        if (instruction & 28672) == 0:
            if (instruction & 3584) == 0:
                mem_write(24, channel_input)    # READ low channel (simplified)
            if (instruction & 3584) == 512:
                mem_write(28, a)                # WRITE low channel
        mem_write(27, flags & 32766)             # clear EXTEND after one word
    else:
        if (instruction & 28672) == 0:
            if instruction == 6:
                mem_write(27, flags | 1)         # EXTEND
            elif instruction == 3:
                mem_write(27, flags | 2)         # RELINT
            elif instruction == 4:
                mem_write(27, flags & 32765)     # INHINT
            elif instruction >= 8:
                mem_write(26, next_z)            # TC stores return in Q
                next_z = field & 15             # remapped TC destination
        elif (instruction & 28672) == 4096:
            if (instruction & 3072) != 0:
                next_z = field & 15             # limited TCF
        elif (instruction & 28672) == 12288:
            v_ca: u15 = mem_read(field)
            mem_write(24, v_ca)                 # CA: accumulator = memory
        elif (instruction & 28672) == 16384:
            v_cs: u15 = mem_read(field)
            mem_write(24, (~v_cs) & 32767)      # CS: one's complement
        elif (instruction & 28672) == 20480:
            if (instruction & 3072) == 2048:
                mem_write(field, a)             # TS: store accumulator
            elif (instruction & 3072) == 3072:
                v_xch: u15 = mem_read(field)
                mem_write(field, a)             # XCH: exchange A and RAM
                mem_write(24, v_xch)
        elif (instruction & 28672) == 24576:
            v_ad: u15 = mem_read(field)
            s: u16 = a + v_ad
            n: u15 = s & 32767
            if s > 32767:
                n = (n + 1) & 32767             # 1's-complement end-around carry
            mem_write(24, n)
        elif (instruction & 28672) == 28672:
            v_mask: u15 = mem_read(field)
            mem_write(24, a & v_mask)           # MASK

    # 3. Commit one instruction. Clock scheduling may take multiple cycles.
    mem_write(25, next_z)
    return mem_read(24)
