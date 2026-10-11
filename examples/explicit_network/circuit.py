def add(a:u4,b:u4)->u5:
    return a+b

def mul(a:u4,b:u4)->u8:
    return a*b

def choose_result(sum_value:u5,product:u8,choose:bool)->u8:
    return product if choose else sum_value

def calculate(a:u4,b:u4,choose:bool)->u8:
    return a*b if choose else a+b
