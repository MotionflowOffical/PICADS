def one_cycle_delay(value: u4) -> u4:
    return reg("captured", value, init=0)


def accumulate_view(a: u4, b: u4) -> u5:
    first = one_cycle_delay(a)
    second = one_cycle_delay(b)
    return first + second
