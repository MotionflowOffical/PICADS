def calculate(addr: u3, value: u5, write: bool) -> u5:
    if write:
        mem_write(addr, value)
    fetched: u5 = mem_read(addr)
    return fetched
