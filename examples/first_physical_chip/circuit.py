def first_chip(data: u4, enable: bool, reset: bool) -> u4:
    return reg("captured", data, init=0, enable=enable, reset=reset)
