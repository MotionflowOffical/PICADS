def store(addr: u3, value: u8) -> u8:
    mem_write(addr, value)
    result: u8 = mem_read(addr)
    return result


def load(addr: u3) -> u8:
    result: u8 = mem_read(addr)
    return result
